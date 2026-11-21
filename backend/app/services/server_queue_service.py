# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Transaction-owned queue state transitions.

Callers commit before external work and retain starting reservations until runtime
cleanup is confirmed. Claiming alone does not authorize provisioning: the caller
must revalidate policy and reserve the stable server in the same transaction.
"""

import asyncio
import copy
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.container.driver import ContainerDriver, ContainerDriverError
from app.core.time_utils import utc_now
from app.models.server import Server
from app.models.server_launch_intent import ServerLaunchIntent
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_queue import ServerQueue
from app.schemas.server_queue import (
    QueueEntryResponse,
    QueuePageResponse,
    QueueRequestSummary,
    QueueResources,
)
from app.services.resource_pool_service import ResourcePoolService

logger = logging.getLogger(__name__)

_ACTIVE_LAUNCH_STATES = ("prepared", "executing", "uncertain")
_SAFE_REASON_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


@dataclass
class QueueReconcileResult:
    """Bounded summary of one starting-request recovery pass."""

    scanned: int = 0
    started: int = 0
    failed: int = 0
    cancelled: int = 0
    recovery_required: int = 0
    deferred: int = 0


@dataclass(frozen=True)
class _StartingCandidate:
    id: uuid.UUID
    claim_token: uuid.UUID | None
    server_id: uuid.UUID | None


@dataclass(frozen=True)
class _StartingObservation:
    claim_token: uuid.UUID | None
    server_id: uuid.UUID | None
    operation_id: uuid.UUID | None
    operation_state: str | None
    operation_reason: str | None
    server_status: str | None
    server_started_at: datetime | None
    server_container_id: str | None
    ambiguous: bool


def _safe_reason(value: str | None) -> str:
    if isinstance(value, str) and _SAFE_REASON_RE.fullmatch(value):
        return value
    return "configuration_changed"


_MESSAGES = {
    "capacity_wait": "Waiting for available capacity.",
    "gpu_wait": "Waiting for an available GPU.",
    "request_cancelled": "Request cancelled.",
    "queue_expired": "Request expired. Submit a new request to try again.",
    "configuration_changed": "Configuration changed. Submit a new request.",
    "permission_revoked": "This request is no longer permitted.",
    "revision_unavailable": "The selected environment revision is unavailable.",
    "recovery_required": "Launch outcome requires operator verification.",
}


class QueueError(Exception):
    def __init__(self, code: str, status_code: int, queue_id: uuid.UUID | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.queue_id = queue_id


class ServerQueueService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_owned(self, queue_id: uuid.UUID, owner_id: uuid.UUID) -> ServerQueue:
        entry = await self.db.scalar(
            select(ServerQueue).where(ServerQueue.id == queue_id, ServerQueue.user_id == owner_id)
        )
        if entry is None:
            raise QueueError("request_not_found", 404)
        return entry

    async def describe(self, entry: ServerQueue) -> QueueEntryResponse:
        position = None
        if entry.status == "pending":
            position = await ResourcePoolService(self.db).get_queue_position(str(entry.id))
        return QueueEntryResponse(
            id=entry.id,
            request=QueueRequestSummary(
                name=entry.server_name,
                plan_id=entry.plan_id,
                environment_id=entry.environment_id,
                resources=QueueResources(
                    cpu=entry.requested_cpu or 0,
                    memory_mib=ResourcePoolService._parse_memory(entry.requested_memory),
                    disk_mib=ResourcePoolService._parse_memory(entry.requested_disk),
                    gpu_count=entry.requested_gpu or 0,
                ),
            ),
            status=entry.status,
            position=position,
            reason_code=entry.reason_code,
            message=_MESSAGES.get(
                entry.reason_code,
                {
                    "pending": "Waiting for available capacity.",
                    "starting": "Launch in progress.",
                    "started": "Server started.",
                    "failed": "Launch failed. Submit a new request to try again.",
                    "cancelled": "Request cancelled.",
                }.get(entry.status, "Request scheduled."),
            ),
            requested_at=entry.requested_at,
            expires_at=entry.expires_at,
            started_at=entry.started_at,
            server_id=entry.server_id,
            can_cancel=entry.status == "pending",
        )

    async def list_owned(
        self,
        owner_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 25,
        statuses: list[str] | None = None,
    ) -> QueuePageResponse:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("Invalid queue pagination")
        conditions = [ServerQueue.user_id == owner_id]
        if statuses:
            conditions.append(ServerQueue.status.in_(statuses))
        total = await self.db.scalar(
            select(func.count()).select_from(ServerQueue).where(*conditions)
        )
        entries = (
            await self.db.scalars(
                select(ServerQueue)
                .where(*conditions)
                .order_by(ServerQueue.requested_at.desc(), ServerQueue.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return QueuePageResponse(
            items=[await self.describe(entry) for entry in entries],
            total=total or 0,
            page=page,
            page_size=page_size,
        )

    async def cancel(self, queue_id: uuid.UUID, owner_id: uuid.UUID) -> ServerQueue:
        entry = await self.db.scalar(
            update(ServerQueue)
            .where(
                ServerQueue.id == queue_id,
                ServerQueue.user_id == owner_id,
                ServerQueue.status == "pending",
            )
            .values(status="cancelled", reason_code="request_cancelled", updated_at=utc_now())
            .returning(ServerQueue)
            .execution_options(populate_existing=True)
        )
        if entry is None:
            entry = await self.get_owned(queue_id, owner_id)
            if entry.status != "cancelled":
                raise QueueError("launch_in_progress", 409)
        await self.db.flush()
        return entry

    async def enqueue(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        plan_id: uuid.UUID,
        environment_id: uuid.UUID,
        request_payload: dict,
        plan_snapshot: dict,
        revision_id: uuid.UUID,
        reason_code: str = "capacity_wait",
        priority: int = 0,
        timeout_seconds: int = 3600,
        max_per_owner: int = 5,
        max_total: int = 500,
    ) -> ServerQueue:
        """Store already validated normalized intent without allocating volumes/credits.

        The caller supplies authorized revision/plan selections and holds admission
        serialization through commit. This helper never provisions or commits.
        """
        from app.services.admission_service import acquire_admission_lock

        if reason_code not in {"capacity_wait", "gpu_wait"}:
            raise ValueError("Invalid queue waiting reason")
        if min(timeout_seconds, max_per_owner, max_total) <= 0:
            raise ValueError("Queue limits must be positive")
        await acquire_admission_lock(self.db)
        existing = await self.db.scalar(
            select(ServerQueue).where(
                ServerQueue.user_id == owner_id,
                ServerQueue.server_name == name,
                ServerQueue.status.in_(["pending", "starting"]),
            )
        )
        if existing is not None:
            raise QueueError("request_already_exists", 409, existing.id)
        server = await self.db.scalar(
            select(Server.id).where(
                Server.user_id == owner_id,
                Server.name == name,
            )
        )
        if server is not None:
            raise QueueError("request_already_exists", 409)
        total = await self.db.scalar(
            select(func.count())
            .select_from(ServerQueue)
            .where(
                ServerQueue.status == "pending",
            )
        )
        owned = await self.db.scalar(
            select(func.count())
            .select_from(ServerQueue)
            .where(
                ServerQueue.status == "pending",
                ServerQueue.user_id == owner_id,
            )
        )
        if (total or 0) >= max_total or (owned or 0) >= max_per_owner:
            raise QueueError("queue_limit_exceeded", 429)
        now = utc_now()
        entry = ServerQueue(
            user_id=owner_id,
            server_name=name,
            plan_id=plan_id,
            environment_id=environment_id,
            status="pending",
            priority=priority,
            request_payload=copy.deepcopy(request_payload),
            request_version=1,
            plan_snapshot=copy.deepcopy(plan_snapshot),
            revision_id=revision_id,
            requested_cpu=plan_snapshot["cpu"],
            requested_memory=plan_snapshot["memory"],
            requested_disk=plan_snapshot["disk"],
            requested_gpu=plan_snapshot["gpu_count"],
            requested_at=now,
            expires_at=now + timedelta(seconds=timeout_seconds),
            reason_code=reason_code,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def claim(
        self,
        queue_id: uuid.UUID,
        *,
        server_id: uuid.UUID,
        claim_token: uuid.UUID,
    ) -> ServerQueue | None:
        """Atomic pending claim, inside the caller's capacity reservation transaction.

        The server identity must be persisted in this transaction before calling.
        Expired or legacy payloads cannot be claimed. A lost race returns None.
        A request that already owns a launch operation is never claimed again:
        a lost worker/broker leaves the durable row for reconciliation instead.
        """
        from app.services.admission_service import acquire_admission_lock

        await acquire_admission_lock(self.db)
        queue = await self.db.scalar(
            select(ServerQueue)
            .where(ServerQueue.id == queue_id)
            .execution_options(populate_existing=True)
        )
        if queue is not None:
            operation, ambiguous, linked_server_id = await self._resolve_launch_operation(queue)
            if ambiguous or operation is not None or linked_server_id is not None:
                raise QueueError("launch_in_progress", 409, queue_id)
        now = utc_now()
        entry = await self.db.scalar(
            update(ServerQueue)
            .where(
                ServerQueue.id == queue_id,
                ServerQueue.status == "pending",
                ServerQueue.request_version == 1,
                ServerQueue.request_payload.is_not(None),
                ServerQueue.expires_at > now,
            )
            .values(
                status="starting",
                server_id=server_id,
                claim_token=claim_token,
                claimed_at=now,
                reason_code=None,
                updated_at=now,
            )
            .returning(ServerQueue)
            .execution_options(populate_existing=True)
        )
        await self.db.flush()
        return entry

    async def _clean(self) -> None:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Queue recovery requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def _resolve_launch_operation(
        self, queue: ServerQueue
    ) -> tuple[ServerLaunchOperation | None, bool, uuid.UUID | None]:
        """Resolve the create operation linked to a queue request.

        The immutable launch intent is the primary link. A committed claim also
        records the server identity on the queue row, so a missing intent can
        still be resolved to the one create operation for that server. Anything
        ambiguous is reported instead of guessed; callers keep the request
        operator-visible rather than creating new runtime work.
        """
        intents = (
            await self.db.scalars(
                select(ServerLaunchIntent)
                .where(ServerLaunchIntent.queue_id == queue.id)
                .limit(2)
                .execution_options(populate_existing=True)
            )
        ).all()
        if len(intents) > 1:
            return None, True, queue.server_id
        if intents:
            intent = intents[0]
            if queue.server_id is not None and queue.server_id != intent.server_id:
                return None, True, queue.server_id
            operation = await self.db.get(
                ServerLaunchOperation, intent.server_id, populate_existing=True
            )
            if operation is None:
                operation = await self.db.scalar(
                    select(ServerLaunchOperation)
                    .where(
                        ServerLaunchOperation.server_id == intent.server_id,
                        ServerLaunchOperation.action == "create",
                    )
                    .order_by(ServerLaunchOperation.created_at.desc())
                    .limit(1)
                    .execution_options(populate_existing=True)
                )
            if (
                intent.claim_token is not None
                and queue.claim_token is not None
                and intent.claim_token != queue.claim_token
            ):
                return operation, True, intent.server_id
            return operation, False, intent.server_id
        if queue.server_id is None:
            return None, False, None
        starting_rows = (
            await self.db.scalars(
                select(ServerQueue.id)
                .where(
                    ServerQueue.server_id == queue.server_id,
                    ServerQueue.status == "starting",
                )
                .limit(2)
            )
        ).all()
        if len(starting_rows) > 1:
            return None, True, queue.server_id
        operation = await self.db.get(
            ServerLaunchOperation, queue.server_id, populate_existing=True
        )
        if operation is None or operation.action != "create":
            rows = (
                await self.db.scalars(
                    select(ServerLaunchOperation)
                    .where(
                        ServerLaunchOperation.server_id == queue.server_id,
                        ServerLaunchOperation.action == "create",
                    )
                    .order_by(ServerLaunchOperation.created_at.desc())
                    .limit(2)
                    .execution_options(populate_existing=True)
                )
            ).all()
            if len(rows) > 1:
                return None, True, queue.server_id
            operation = rows[0] if rows else None
        return operation, False, queue.server_id

    async def _observe_starting(self, queue_id: uuid.UUID) -> _StartingObservation | None:
        await self._clean()
        async with self.db.begin():
            queue = await self.db.get(ServerQueue, queue_id, populate_existing=True)
            if queue is None or queue.status != "starting":
                return None
            operation, ambiguous, server_id = await self._resolve_launch_operation(queue)
            server = (
                await self.db.get(Server, server_id, populate_existing=True)
                if server_id is not None
                else None
            )
            if operation is None and server_id is not None:
                active_other = await self.db.scalar(
                    select(ServerLaunchOperation.id)
                    .where(
                        ServerLaunchOperation.server_id == server_id,
                        ServerLaunchOperation.state.in_(_ACTIVE_LAUNCH_STATES),
                    )
                    .limit(1)
                )
                ambiguous = ambiguous or active_other is not None
            return _StartingObservation(
                claim_token=queue.claim_token,
                server_id=server_id,
                operation_id=operation.id if operation is not None else None,
                operation_state=operation.state if operation is not None else None,
                operation_reason=operation.reason_code if operation is not None else None,
                server_status=server.status if server is not None else None,
                server_started_at=server.started_at if server is not None else None,
                server_container_id=server.container_id if server is not None else None,
                ambiguous=ambiguous,
            )

    async def _runtime_presence(
        self, driver: ContainerDriver, observation: _StartingObservation
    ) -> str:
        """Prove runtime absence without trusting a stale server status alone."""
        if observation.server_id is None:
            # No server identity means no label/name to inspect; never guess.
            return "unknown"
        if observation.server_status in ("running", "stopping"):
            # The database claims an active runtime; absence is not proof.
            return "unknown"
        try:
            if observation.server_container_id:
                try:
                    info = await driver.get_container_info(observation.server_container_id)
                except ContainerDriverError as exc:
                    if exc.status != 404:
                        return "unknown"
                except Exception:
                    return "unknown"
                else:
                    if not isinstance(info, dict):
                        return "unknown"
                    if info.get("Id") not in (None, observation.server_container_id):
                        return "unknown"
                    return "present"
            listed = await driver.list_containers(
                filters={"label": [f"nukelab.server.id={observation.server_id}"]},
                all=True,
            )
            if not isinstance(listed, list):
                return "unknown"
            for item in listed:
                if not isinstance(item, dict):
                    return "unknown"
                config = item.get("Config")
                labels = config.get("Labels") if isinstance(config, dict) else None
                if not isinstance(labels, dict):
                    return "unknown"
                if labels.get("nukelab.server.id") == str(observation.server_id):
                    return "present"
            named = await driver.get_container_by_name(f"nukelab-launch-{observation.server_id}")
            if named is not None:
                return "present"
            return "absent"
        except Exception:
            return "unknown"

    async def reconcile_starting(
        self, driver: ContainerDriver, *, limit: int = 20
    ) -> QueueReconcileResult:
        """Resolve ``starting`` requests against their durable launch operation.

        The launch operation is authoritative:

        - succeeded with a running server -> ``started`` using the server's start
          time;
        - failed with a safe reason -> ``failed``;
        - uncertain/ambiguous -> stay ``starting`` with ``recovery_required``.

        A ``starting`` row without an operation is corrupt or legacy. It is
        never requeued or cancelled blindly. Cancellation requires proof that no
        operation is linked and that no runtime container carries the server
        identity (label, deterministic launch name, or recorded container id).
        Missing identity or an unavailable runtime inspection keeps the row
        ``starting`` with ``recovery_required`` for an operator.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Queue recovery batch size must be between 1 and 100")
        await self._clean()
        result = QueueReconcileResult()
        async with self.db.begin():
            rows = (
                await self.db.scalars(
                    select(ServerQueue)
                    .where(ServerQueue.status == "starting")
                    .order_by(
                        ServerQueue.requested_at.asc().nulls_last(),
                        ServerQueue.id.asc(),
                    )
                    .limit(limit)
                    .execution_options(populate_existing=True)
                )
            ).all()
            candidates = [
                _StartingCandidate(row.id, row.claim_token, row.server_id) for row in rows
            ]
        for candidate in candidates:
            result.scanned += 1
            try:
                outcome = await self._recover_candidate(driver, candidate)
            except asyncio.CancelledError:
                raise
            except Exception:
                await self.db.rollback()
                logger.warning(
                    "Queue starting-request recovery row deferred",
                    extra={
                        "queue_id": str(candidate.id),
                    },
                )
                result.deferred += 1
                continue
            if outcome == "started":
                result.started += 1
            elif outcome == "failed":
                result.failed += 1
            elif outcome == "cancelled":
                result.cancelled += 1
            elif outcome == "recovery_required":
                result.recovery_required += 1
            else:
                result.deferred += 1
        return result

    async def _recover_candidate(
        self, driver: ContainerDriver, candidate: _StartingCandidate
    ) -> str:
        observation = await self._observe_starting(candidate.id)
        if observation is None:
            return "deferred"
        if observation.operation_id is not None:
            return await self._apply_operation_outcome(candidate, observation)
        if observation.ambiguous or observation.server_id is None:
            return await self._apply_recovery(candidate, observation)
        presence = await self._runtime_presence(driver, observation)
        return await self._apply_orphan_outcome(candidate, observation, presence=presence)

    @staticmethod
    def _same_starting_queue(queue: ServerQueue | None, candidate: _StartingCandidate) -> bool:
        return (
            queue is not None
            and queue.status == "starting"
            and queue.claim_token == candidate.claim_token
            and queue.server_id == candidate.server_id
        )

    @staticmethod
    def _set_recovery(queue: ServerQueue, *, server_id: uuid.UUID | None = None) -> None:
        if server_id is not None and queue.server_id is None:
            queue.server_id = server_id
        if queue.reason_code != "recovery_required":
            queue.reason_code = "recovery_required"
            queue.updated_at = utc_now()

    async def _apply_operation_outcome(
        self, candidate: _StartingCandidate, observation: _StartingObservation
    ) -> str:
        if observation.operation_state not in ("succeeded", "failed", "uncertain") and not (
            observation.ambiguous
        ):
            return "deferred"
        await self._clean()
        async with self.db.begin():
            await self._lock_starting()
            queue = await self.db.get(
                ServerQueue,
                candidate.id,
                with_for_update=True,
                populate_existing=True,
            )
            if queue is None or not self._same_starting_queue(queue, candidate):
                return "deferred"
            operation = await self.db.get(
                ServerLaunchOperation,
                observation.operation_id,
                with_for_update=True,
                populate_existing=True,
            )
            if (
                operation is None
                or operation.action != "create"
                or operation.state != observation.operation_state
                or (queue.server_id is not None and queue.server_id != operation.server_id)
            ):
                return "deferred"
            if observation.ambiguous or operation.state == "uncertain":
                self._set_recovery(queue, server_id=operation.server_id)
                return "recovery_required"
            if operation.state == "succeeded":
                server = await self.db.get(
                    Server,
                    operation.server_id,
                    with_for_update=True,
                    populate_existing=True,
                )
                if server is None or server.status != "running" or server.started_at is None:
                    self._set_recovery(queue, server_id=operation.server_id)
                    return "recovery_required"
                queue.status = "started"
                queue.server_id = operation.server_id
                queue.started_at = server.started_at
                queue.reason_code = None
                queue.updated_at = utc_now()
                return "started"
            if operation.state != "failed":
                return "deferred"
            queue.status = "failed"
            queue.server_id = operation.server_id
            queue.reason_code = _safe_reason(operation.reason_code)
            queue.failed_at = utc_now()
            queue.updated_at = utc_now()
            return "failed"

    async def _apply_recovery(
        self, candidate: _StartingCandidate, observation: _StartingObservation
    ) -> str:
        await self._clean()
        async with self.db.begin():
            await self._lock_starting()
            queue = await self.db.get(
                ServerQueue,
                candidate.id,
                with_for_update=True,
                populate_existing=True,
            )
            if queue is None or not self._same_starting_queue(queue, candidate):
                return "deferred"
            if observation.operation_id is not None:
                operation = await self.db.get(
                    ServerLaunchOperation,
                    observation.operation_id,
                    populate_existing=True,
                )
                if operation is None or operation.state not in _ACTIVE_LAUNCH_STATES:
                    return "deferred"
                self._set_recovery(queue, server_id=operation.server_id)
            else:
                self._set_recovery(queue, server_id=observation.server_id)
            return "recovery_required"

    async def _apply_orphan_outcome(
        self,
        candidate: _StartingCandidate,
        observation: _StartingObservation,
        *,
        presence: str,
    ) -> str:
        await self._clean()
        async with self.db.begin():
            await self._lock_starting()
            queue = await self.db.get(
                ServerQueue,
                candidate.id,
                with_for_update=True,
                populate_existing=True,
            )
            if queue is None or not self._same_starting_queue(queue, candidate):
                return "deferred"
            operation, ambiguous, server_id = await self._resolve_launch_operation(queue)
            if operation is not None or ambiguous:
                return "deferred"
            if server_id is not None:
                active = await self.db.scalar(
                    select(ServerLaunchOperation.id)
                    .where(
                        ServerLaunchOperation.server_id == server_id,
                        ServerLaunchOperation.state.in_(_ACTIVE_LAUNCH_STATES),
                    )
                    .limit(1)
                )
                if active is not None:
                    return "deferred"
            if presence != "absent":
                self._set_recovery(queue, server_id=server_id)
                return "recovery_required"
            if server_id is not None:
                server = await self.db.get(
                    Server, server_id, with_for_update=True, populate_existing=True
                )
                if server is not None and server.status in ("running", "stopping"):
                    self._set_recovery(queue, server_id=server_id)
                    return "recovery_required"
            queue.status = "cancelled"
            queue.reason_code = "configuration_changed"
            queue.updated_at = utc_now()
            return "cancelled"

    async def _lock_starting(self) -> None:
        """Take admission before any fresh transition accounting/lock."""
        from app.services.admission_service import acquire_admission_lock

        await acquire_admission_lock(self.db)

    async def expire_pending(self) -> int:
        """Expire pending only; a live or uncertain launch keeps its protection."""
        result = await self.db.execute(
            update(ServerQueue)
            .where(
                ServerQueue.status == "pending",
                ServerQueue.expires_at <= utc_now(),
            )
            .values(status="cancelled", reason_code="queue_expired", updated_at=utc_now())
        )
        await self.db.flush()
        return result.rowcount
