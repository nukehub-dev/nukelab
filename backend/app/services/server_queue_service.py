# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Transaction-owned queue state transitions.

Callers commit before external work and retain starting reservations until runtime
cleanup is confirmed. Claiming alone does not authorize provisioning: the caller
must revalidate policy and reserve the stable server in the same transaction.
"""

import copy
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utc_now
from app.models.server import Server
from app.models.server_queue import ServerQueue
from app.schemas.server_queue import (
    QueueEntryResponse,
    QueuePageResponse,
    QueueRequestSummary,
    QueueResources,
)
from app.services.resource_pool_service import ResourcePoolService

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
        """
        from app.services.admission_service import acquire_admission_lock

        await acquire_admission_lock(self.db)
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
