# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded inspection of stale or otherwise unresolved batch-job journals.

A stale heartbeat is an inspection trigger, never termination proof. The scan
reuses the monitor's read-only observation and only finalizes an outcome when
the daemon supplies exact identity and exit evidence. It never issues a create
or a start after a persisted start checkpoint.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.batch_job import TERMINAL_JOB_STATES, BatchJob
from app.models.system_setting import SystemSetting
from app.services.batch_job_finalizer import BatchJobFinalizer
from app.services.batch_job_monitor import BatchJobMonitorService

logger = get_logger(__name__)

SCAN_STATE_KEY = "batch_jobs_recovery_scan_state"
_RECOVERY_STATES = ("starting", "running", "cancelling", "recovery_required")
_TERMINAL_STATES = frozenset(TERMINAL_JOB_STATES)
_CLEANUP_BATCH_LIMIT = 10


@dataclass
class BatchJobRecoveryReport:
    scanned: int = 0
    observed: int = 0
    started: int = 0
    finalized: int = 0
    recovery_required: int = 0
    retained: int = 0
    cleanup_retried: int = 0
    cleanup_completed: int = 0
    cleanup_pending: int = 0
    errors: int = 0
    duration_seconds: float = 0.0

    def as_dict(self) -> dict[str, int | float]:
        return {
            "scanned": self.scanned,
            "observed": self.observed,
            "started": self.started,
            "finalized": self.finalized,
            "recovery_required": self.recovery_required,
            "retained": self.retained,
            "cleanup_retried": self.cleanup_retried,
            "cleanup_completed": self.cleanup_completed,
            "cleanup_pending": self.cleanup_pending,
            "errors": self.errors,
            "duration_seconds": round(self.duration_seconds, 3),
        }


class BatchJobReconciliationService:
    """Retry proof for stale jobs and bounded cleanup after terminal results."""

    def __init__(
        self,
        db: AsyncSession,
        driver: ContainerDriver,
        *,
        monitor: BatchJobMonitorService | None = None,
        finalizer: BatchJobFinalizer | None = None,
    ):
        self.db = db
        self.driver = driver
        self.monitor = monitor or BatchJobMonitorService(db, driver)
        self.finalizer = finalizer or self.monitor.finalizer
        self.runtime = self.monitor.runtime

    async def _clean_session(self) -> None:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Batch job reconciliation requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def _stale_candidates(self, limit: int) -> list[uuid.UUID]:
        now = utc_now()
        heartbeat_cutoff = now - timedelta(seconds=settings.batch_jobs_heartbeat_stale_seconds)
        start_cutoff = now - timedelta(seconds=settings.server_launch_timeout_seconds)
        rows = (
            await self.db.scalars(
                select(BatchJob.id)
                .where(
                    BatchJob.state.in_(_RECOVERY_STATES),
                    or_(
                        BatchJob.heartbeat_at.is_(None),
                        BatchJob.heartbeat_at < heartbeat_cutoff,
                        and_(
                            BatchJob.state == "starting",
                            func.coalesce(
                                BatchJob.create_requested_at,
                                BatchJob.reserved_at,
                                BatchJob.state_changed_at,
                            )
                            < start_cutoff,
                        ),
                    ),
                )
                .order_by(
                    BatchJob.heartbeat_at.asc().nulls_first(),
                    BatchJob.created_at.asc(),
                    BatchJob.id.asc(),
                )
                .limit(limit)
            )
        ).all()
        return list(rows)

    async def _cleanup_candidates(self, limit: int) -> list[uuid.UUID]:
        rows = (
            await self.db.scalars(
                select(BatchJob.id)
                .where(
                    BatchJob.state.in_(_TERMINAL_STATES),
                    BatchJob.cleanup_state != "complete",
                )
                .order_by(
                    BatchJob.last_cleanup_at.asc().nulls_first(),
                    BatchJob.id.asc(),
                )
                .limit(min(limit, _CLEANUP_BATCH_LIMIT))
            )
        ).all()
        return list(rows)

    async def scan(self, limit: int | None = None) -> BatchJobRecoveryReport:
        if limit is None:
            limit = settings.batch_jobs_recovery_batch_size
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Batch job recovery limit must be between 1 and 500")
        await self._clean_session()
        started = time.monotonic()
        report = BatchJobRecoveryReport()
        async with self.db.begin():
            candidates = await self._stale_candidates(limit)
            cleanup = await self._cleanup_candidates(limit)
        for job_id in candidates:
            report.scanned += 1
            try:
                observation = await self.monitor.observe_job(job_id, allow_recovery=True)
            except Exception as exc:
                report.errors += 1
                logger.warning(
                    "Batch job recovery observation deferred",
                    extra={"job_id": str(job_id), "error_class": type(exc).__name__},
                )
                continue
            report.observed += 1
            if observation.action == "running":
                report.started += 1
            elif observation.action in ("succeeded", "failed", "cancelled", "timed_out"):
                report.finalized += 1
            elif observation.action == "recovery_required":
                report.recovery_required += 1
            elif observation.action in ("retained", "noop", "deferred"):
                report.retained += 1
        for job_id in cleanup:
            report.cleanup_retried += 1
            try:
                result = await self.finalizer.cleanup(job_id)
            except Exception as exc:
                report.errors += 1
                logger.warning(
                    "Batch job cleanup retry deferred",
                    extra={"job_id": str(job_id), "error_class": type(exc).__name__},
                )
                continue
            if result.state == "complete":
                report.cleanup_completed += 1
            else:
                report.cleanup_pending += 1
        report.duration_seconds = time.monotonic() - started
        await self._persist_scan_state(report)
        return report

    async def _persist_scan_state(self, report: BatchJobRecoveryReport) -> None:
        """Keep a bounded, identifier-free freshness record for operators."""
        payload = json.dumps(
            {
                "last_scan_at": utc_now().isoformat(),
                "report": report.as_dict(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            await self._clean_session()
            async with self.db.begin():
                row = await self.db.get(SystemSetting, SCAN_STATE_KEY)
                if row is None:
                    self.db.add(SystemSetting(key=SCAN_STATE_KEY, value=payload))
                else:
                    row.value = payload
        except Exception as exc:
            await self.db.rollback()
            logger.warning(
                "Batch job recovery scan state deferred",
                extra={"error_class": type(exc).__name__},
            )


__all__ = [
    "BatchJobRecoveryReport",
    "BatchJobReconciliationService",
    "SCAN_STATE_KEY",
]
