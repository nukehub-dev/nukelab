# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded first-fit dispatch through the shared reservation/launch boundary.

The caller owns loop-local operation resources. No runtime provisioning occurs
inside the scan transaction; waiting requests are neither charged nor allocated.
"""

import asyncio
import copy
import logging
import uuid
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.container.driver import ContainerDriver
from app.core.time_utils import utc_now
from app.models.server_queue import ServerQueue
from app.schemas.server_launch import NormalizedLaunchRequest
from app.schemas.server_queue import QueuedServerResponse
from app.services.environment_revision_service import ConfigurationChanged, RevisionUnavailable
from app.services.server_launch_service import LaunchError, LaunchReservation, ServerLaunchService
from app.services.server_launch_validation import LaunchValidationError
from app.services.server_queue_service import QueueError, ServerQueueService
from app.services.volume_operation_service import VolumeOperationError

logger = logging.getLogger(__name__)


@dataclass
class QueueDispatchResult:
    scanned: int = 0
    started: int = 0
    waiting: int = 0
    failed: int = 0
    cancelled: int = 0
    expired: int = 0
    skipped: int = 0
    recovery_required: int = 0


@dataclass(frozen=True)
class _Candidate:
    id: uuid.UUID
    owner_id: uuid.UUID
    payload: dict | None
    version: int | None
    revision_id: uuid.UUID | None


_FAILURE_CODES = {
    "permission_revoked",
    "configuration_changed",
    "revision_unavailable",
    "request_already_exists",
    "quota_exceeded",
    "insufficient_credits",
    "gpu_unavailable",
    "artifact_missing",
    "volume_unavailable",
    "volume_capacity_exceeded",
}


class ServerQueueDispatchService:
    def __init__(self, db: AsyncSession, driver: ContainerDriver):
        self.db = db
        self.launch = ServerLaunchService(db, driver)

    async def _clean_session(self):
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Queue dispatcher requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def _pending_transition(self, queue_id, *, state, reason):
        """Conditional status update cannot fail/cancel an already claimed runtime."""
        await self._clean_session()
        async with self.db.begin():
            values = {"status": state, "reason_code": reason, "updated_at": utc_now()}
            if state == "failed":
                values["failed_at"] = utc_now()
            result = await self.db.execute(
                update(ServerQueue)
                .where(ServerQueue.id == queue_id, ServerQueue.status == "pending")
                .values(**values)
            )
            return bool(result.rowcount)

    async def _uncertain(self, reservation: LaunchReservation):
        # Provision's own recovery normally records this. This additional fencing
        # also covers cancellation before its Exception handler can run.
        await self.db.rollback()
        async with self.db.begin():
            await self.db.execute(
                update(ServerQueue)
                .where(
                    ServerQueue.id == reservation.queue_id,
                    ServerQueue.status == "starting",
                    ServerQueue.claim_token == reservation.claim_token,
                )
                .values(reason_code="recovery_required", updated_at=utc_now())
            )

    async def dispatch(self, *, batch_size: int = 20) -> QueueDispatchResult:
        if type(batch_size) is not int or not 1 <= batch_size <= 100:
            raise ValueError("Queue scan size must be between 1 and 100")
        await self._clean_session()
        result = QueueDispatchResult()
        async with self.db.begin():
            result.expired = await ServerQueueService(self.db).expire_pending()
            rows = (
                await self.db.scalars(
                    select(ServerQueue)
                    .where(ServerQueue.status == "pending")
                    .order_by(
                        ServerQueue.priority.desc(),
                        ServerQueue.requested_at.asc(),
                        ServerQueue.id.asc(),
                    )
                    .limit(batch_size)
                    .execution_options(populate_existing=True)
                )
            ).all()
            candidates = [
                _Candidate(
                    row.id,
                    row.user_id,
                    copy.deepcopy(row.request_payload),
                    row.request_version,
                    row.revision_id,
                )
                for row in rows
            ]
        for candidate in candidates:
            result.scanned += 1
            if not candidate.payload or candidate.version != 1 or candidate.revision_id is None:
                changed = await self._pending_transition(
                    candidate.id, state="cancelled", reason="configuration_changed"
                )
                result.cancelled += int(changed)
                result.skipped += int(not changed)
                continue
            try:
                request = NormalizedLaunchRequest.model_validate(candidate.payload)
                revision_id = uuid.UUID(str(candidate.revision_id))
            except (ValidationError, TypeError, ValueError):
                changed = await self._pending_transition(
                    candidate.id, state="failed", reason="configuration_changed"
                )
                result.failed += int(changed)
                result.skipped += int(not changed)
                continue
            try:
                reservation = await self.launch.reserve(
                    candidate.owner_id, request, revision_id, queue_id=candidate.id
                )
            except (
                LaunchError,
                LaunchValidationError,
                QueueError,
                VolumeOperationError,
                RevisionUnavailable,
                ConfigurationChanged,
            ) as exc:
                await self.db.rollback()
                if isinstance(exc, RevisionUnavailable):
                    code = "revision_unavailable"
                elif isinstance(exc, ConfigurationChanged):
                    code = "configuration_changed"
                else:
                    code = exc.code
                if code in _FAILURE_CODES:
                    changed = await self._pending_transition(
                        candidate.id, state="failed", reason=code
                    )
                    result.failed += int(changed)
                    result.skipped += int(not changed)
                elif code in ("capacity_wait", "gpu_wait", "volume_busy"):
                    changed = await self._pending_transition(
                        candidate.id, state="pending", reason=code
                    )
                    result.waiting += int(changed)
                    result.skipped += int(not changed)
                else:
                    result.skipped += 1
                continue
            except asyncio.CancelledError:
                # reserve has no external effects and rolls its transaction back.
                raise
            except Exception:
                await self.db.rollback()
                # Unknown infrastructure failures remain pending; never manufacture
                # a definitive policy rejection from a DB/driver/programming error.
                logger.exception("Queue admission failed", extra={"queue_id": str(candidate.id)})
                result.skipped += 1
                continue
            if reservation is None or isinstance(reservation, QueuedServerResponse):
                result.waiting += 1
                continue
            try:
                await self.launch.provision(reservation)
            except asyncio.CancelledError:
                try:
                    await self._uncertain(reservation)
                except Exception:
                    logger.exception("Queue cancellation requires reconciliation")
                raise
            except Exception:
                try:
                    await self._uncertain(reservation)
                except Exception:
                    logger.exception("Queue launch requires reconciliation")
                result.recovery_required += 1
                continue
            result.started += 1
        return result


def run_queue_dispatch(*, timeout_seconds: float, batch_size: int = 20) -> QueueDispatchResult:
    """Synchronous worker boundary with one owned event loop, driver and DB session.

    Schedulers must explicitly select this dispatcher after draining legacy queue
    workers. A deadline never authorizes discarding starting reservations.
    """
    from app.services.operation_runner import operation_resources, run_operation

    async def execute():
        async with operation_resources() as resources:
            return await ServerQueueDispatchService(resources.db, resources.driver).dispatch(
                batch_size=batch_size
            )

    return run_operation(execute, timeout_seconds=timeout_seconds)
