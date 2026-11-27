# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded batch-job dispatch through the shared admission lock.

Selection is advisory. Admission re-reads the queued row under the platform
lock, and only a committed starting reservation is handed to a broker hint.
The durable queued row remains authoritative when a hint is lost.
"""

from __future__ import annotations

import inspect
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.batch_job import TERMINAL_JOB_STATES, BatchJob
from app.models.system_setting import SystemSetting
from app.services.admission_service import acquire_admission_lock
from app.services.batch_job_admission_service import (
    BatchJobAdmissionService,
    JobAdmission,
)
from app.services.worker_heartbeat import current_executor_id

logger = get_logger(__name__)

_DISPATCH_CURSOR_KEY = "batch_jobs_dispatch_cursor"
_TERMINAL_STATES = frozenset(TERMINAL_JOB_STATES)
_ENQUEUE_ERROR = "enqueue_failed"


@dataclass
class BatchJobDispatchReport:
    selected: int = 0
    admitted: int = 0
    enqueued: int = 0
    waiting: int = 0
    failed: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "selected": self.selected,
            "admitted": self.admitted,
            "enqueued": self.enqueued,
            "waiting": self.waiting,
            "failed": self.failed,
            "errors": self.errors,
        }


def _default_enqueue(job_id: str) -> None:
    from app.tasks import run_batch_job

    run_batch_job.delay(job_id)


def _decode_cursor(raw: object) -> tuple[datetime, uuid.UUID] | None:
    if not isinstance(raw, str) or len(raw) > 512:
        return None
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"version", "created_at", "id"}:
            return None
        if type(value["version"]) is not int or value["version"] != 1:
            return None
        created_at = datetime.fromisoformat(value["created_at"])
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(UTC).replace(tzinfo=None)
        return created_at, uuid.UUID(value["id"])
    except (ValueError, TypeError, AttributeError, RecursionError):
        return None


class BatchJobDispatchService:
    """Claim queued jobs once, then deliver an opaque job-id hint."""

    def __init__(
        self,
        db: AsyncSession,
        driver: ContainerDriver,
        *,
        admission: BatchJobAdmissionService | None = None,
        enqueue: Callable[[str], object] | None = None,
    ):
        self.db = db
        self.driver = driver
        self.admission = admission or BatchJobAdmissionService(db, driver)
        self.enqueue = enqueue or _default_enqueue

    async def _clean_session(self) -> None:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Batch job dispatch requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def _scan_batch(self, limit: int) -> list[uuid.UUID]:
        await acquire_admission_lock(self.db)
        setting = await self.db.scalar(
            select(SystemSetting)
            .where(SystemSetting.key == _DISPATCH_CURSOR_KEY)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        cursor = _decode_cursor(setting.value if setting is not None else None)
        base = (
            select(BatchJob.id)
            .where(BatchJob.state == "queued")
            .order_by(BatchJob.created_at.asc(), BatchJob.id.asc())
            .limit(limit)
        )
        query = base
        if cursor is not None:
            created_at, job_id = cursor
            query = query.where(
                or_(
                    BatchJob.created_at > created_at,
                    and_(BatchJob.created_at == created_at, BatchJob.id > job_id),
                )
            )
        rows = list((await self.db.scalars(query)).all())
        if not rows and cursor is not None:
            rows = list((await self.db.scalars(base)).all())
        if rows:
            last = await self.db.scalar(
                select(BatchJob)
                .where(BatchJob.id == rows[-1])
                .execution_options(populate_existing=True)
            )
            value = json.dumps(
                {
                    "version": 1,
                    "created_at": last.created_at.isoformat() if last else utc_now().isoformat(),
                    "id": str(rows[-1]),
                },
                sort_keys=True,
            )
        else:
            value = "null"
        if setting is None:
            if rows:
                self.db.add(
                    SystemSetting(
                        key=_DISPATCH_CURSOR_KEY,
                        value=value,
                        updated_at=utc_now(),
                    )
                )
        else:
            setting.value = value
            setting.updated_at = utc_now()
        await self.db.flush()
        return rows

    async def _outcome(self, job_id: uuid.UUID) -> str:
        try:
            row = (
                await self.db.execute(
                    select(BatchJob.state, BatchJob.reason_code).where(BatchJob.id == job_id)
                )
            ).one_or_none()
        finally:
            if self.db.in_transaction():
                await self.db.rollback()
        if row is None:
            return "missing"
        if row.state in _TERMINAL_STATES:
            return "failed"
        if row.state == "queued":
            return "waiting"
        return "waiting"

    async def dispatch(self, limit: int | None = None) -> BatchJobDispatchReport:
        if limit is None:
            limit = settings.batch_jobs_dispatch_batch_size
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("Batch job dispatch limit must be between 1 and 100")
        await self._clean_session()
        report = BatchJobDispatchReport()
        async with self.db.begin():
            candidate_ids = await self._scan_batch(limit)
        executor_id = current_executor_id()
        for job_id in candidate_ids:
            report.selected += 1
            try:
                admission = await self.admission.admit(job_id, executor_id=executor_id)
            except Exception as exc:
                await self.db.rollback()
                report.errors += 1
                logger.warning(
                    "Batch job admission deferred",
                    extra={"job_id": str(job_id), "error_class": type(exc).__name__},
                )
                continue
            if not isinstance(admission, JobAdmission):
                outcome = await self._outcome(job_id)
                if outcome == "failed":
                    report.failed += 1
                elif outcome == "waiting":
                    report.waiting += 1
                else:
                    report.waiting += 1
                continue
            report.admitted += 1
            try:
                delivered = self.enqueue(str(admission.job_id))
                if inspect.isawaitable(delivered):
                    await delivered
            except Exception as exc:
                # The committed starting reservation is authoritative. A later
                # monitor/recovery pass observes it without creating twice.
                report.errors += 1
                logger.warning(
                    "Batch job broker hint deferred",
                    extra={
                        "job_id": str(job_id),
                        "error_class": type(exc).__name__,
                        "code": _ENQUEUE_ERROR,
                    },
                )
                continue
            report.enqueued += 1
        return report


def run_batch_job_dispatch(*, timeout_seconds: float, limit: int | None = None):
    """Synchronous worker boundary with loop-owned DB and driver resources."""
    from app.services.operation_runner import operation_resources, run_operation

    async def execute():
        async with operation_resources() as resources:
            return await BatchJobDispatchService(resources.db, resources.driver).dispatch(
                limit=limit
            )

    return run_operation(execute, timeout_seconds=timeout_seconds)


__all__ = [
    "BatchJobDispatchReport",
    "BatchJobDispatchService",
    "run_batch_job_dispatch",
]
