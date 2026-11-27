# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded observation of active batch jobs by recorded or deterministic runtime.

Monitoring runs daemon inspection outside any transaction or admission lock.
A missing or unverifiable runtime is never reconstructed blindly; only a
container with no start checkpoint may be started by the runtime lane.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob
from app.services.batch_job_admission_service import BatchJobAdmissionService
from app.services.batch_job_finalizer import BatchJobFinalizer
from app.services.batch_job_runtime import (
    ACTIVE_RUNTIME_STATES,
    BatchJobRuntimeService,
    JobStateSnapshot,
    RuntimeStartResult,
    container_status,
)
from app.services.worker_heartbeat import current_executor_id

logger = get_logger(__name__)

_ACTIVE_RUNTIME_STATES = frozenset(ACTIVE_RUNTIME_STATES)
_OBSERVABLE_STATES = frozenset((*ACTIVE_RUNTIME_STATES, "recovery_required"))
_SCAN_STATES = ("starting", "running", "cancelling")


@dataclass(frozen=True, slots=True)
class JobObservation:
    job_id: uuid.UUID
    action: str
    container_id: str | None = None
    detail: str | None = None


@dataclass
class MonitorReport:
    scanned: int = 0
    observed: int = 0
    started: int = 0
    finalized: int = 0
    recovery_required: int = 0
    retained: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "observed": self.observed,
            "started": self.started,
            "finalized": self.finalized,
            "recovery_required": self.recovery_required,
            "retained": self.retained,
            "errors": self.errors,
        }


class BatchJobMonitorService:
    """Observe active jobs and apply only proof-backed terminal outcomes."""

    def __init__(
        self,
        db: AsyncSession,
        driver: ContainerDriver,
        *,
        admission: BatchJobAdmissionService | None = None,
        finalizer: BatchJobFinalizer | None = None,
        runtime: BatchJobRuntimeService | None = None,
    ):
        self.db = db
        self.driver = driver
        self.admission = admission or BatchJobAdmissionService(db, driver)
        self.finalizer = finalizer or BatchJobFinalizer(db, driver, admission=self.admission)
        self.runtime = runtime or BatchJobRuntimeService(
            db,
            driver,
            admission=self.admission,
            finalizer=self.finalizer,
        )

    async def _scan(self, limit: int) -> list[uuid.UUID]:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Batch job monitor requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()
        async with self.db.begin():
            rows = (
                await self.db.scalars(
                    select(BatchJob.id)
                    .where(BatchJob.state.in_(_SCAN_STATES))
                    .order_by(
                        BatchJob.heartbeat_at.asc().nulls_first(),
                        BatchJob.created_at.asc(),
                        BatchJob.id.asc(),
                    )
                    .limit(limit)
                )
            ).all()
        return list(rows)

    async def monitor(self, limit: int | None = None) -> MonitorReport:
        if limit is None:
            limit = settings.batch_jobs_monitor_batch_size
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Batch job monitor limit must be between 1 and 500")
        report = MonitorReport()
        for job_id in await self._scan(limit):
            report.scanned += 1
            try:
                observation = await self.observe_job(job_id)
            except Exception as exc:
                report.errors += 1
                logger.warning(
                    "Batch job observation deferred",
                    extra={"job_id": str(job_id), "error_class": type(exc).__name__},
                )
                continue
            _count_observation(report, observation)
        return report

    async def observe_job(
        self, job_id: uuid.UUID, *, allow_recovery: bool = False
    ) -> JobObservation:
        """Inspect one job; never issue a second create or start."""
        snapshot = await self.runtime.load(job_id)
        if snapshot is None:
            return JobObservation(job_id=job_id, action="noop", detail="job_not_found")
        if not snapshot.reservation_active or snapshot.state not in _OBSERVABLE_STATES:
            return JobObservation(job_id=job_id, action="noop", detail="not_active")
        if snapshot.state == "recovery_required" and not allow_recovery:
            return JobObservation(job_id=job_id, action="retained", detail="recovery_required")

        lookup = await self.runtime.lookup_container(snapshot)
        if lookup.status == "unavailable":
            return await self._recovery(snapshot, "runtime_unverifiable")
        if lookup.status == "mismatch":
            return await self._recovery(snapshot, "runtime_unverifiable")
        if lookup.status == "missing":
            return await self._missing(snapshot)
        if lookup.info is None or lookup.container_id is None:
            return await self._recovery(snapshot, "runtime_unverifiable")
        if snapshot.container_id != lookup.container_id:
            adopted = await self.runtime.persist_container_id(
                snapshot,
                lookup.container_id,
                touch_heartbeat=False,
                replace_existing=True,
            )
            if adopted is not None:
                snapshot = adopted

        status = container_status(lookup.info)
        if status == "created":
            return await self._created(snapshot, lookup.container_id)
        if status == "running":
            return await self._running(snapshot, lookup.info)
        if status == "exited":
            return await self._exited(snapshot, lookup.info)
        return await self._recovery(snapshot, "runtime_unverifiable")

    async def _missing(self, snapshot: JobStateSnapshot) -> JobObservation:
        if snapshot.state == "recovery_required":
            return JobObservation(
                job_id=snapshot.job_id,
                action="retained",
                detail="runtime_missing",
            )
        if snapshot.state == "starting" and snapshot.create_requested_at is None:
            result = await self.runtime.start(snapshot.job_id)
            return _from_runtime(snapshot, result)
        return await self._recovery(snapshot, "runtime_unverifiable")

    async def _created(self, snapshot: JobStateSnapshot, container_id: str) -> JobObservation:
        if snapshot.state == "recovery_required":
            return JobObservation(
                job_id=snapshot.job_id,
                action="retained",
                container_id=container_id,
                detail="created_unstarted",
            )
        if (
            snapshot.state == "starting"
            and snapshot.start_requested_at is None
            and snapshot.stop_requested_at is None
        ):
            result = await self.runtime.start_created(snapshot.job_id, container_id)
            return _from_runtime(snapshot, result)
        return await self._recovery(snapshot, "runtime_unverifiable")

    async def _running(self, snapshot: JobStateSnapshot, info: dict) -> JobObservation:
        if snapshot.state == "recovery_required":
            if snapshot.stop_requested_at is not None:
                if snapshot.container_id is None:
                    return await self._recovery(snapshot, "runtime_unverifiable")
                result = await self.runtime.stop_and_finalize(
                    snapshot, snapshot.container_id, forced="cancel"
                )
                return _from_runtime(snapshot, result)
            if _deadline_passed(snapshot):
                if snapshot.container_id is None:
                    return await self._recovery(snapshot, "runtime_unverifiable")
                result = await self.runtime.stop_and_finalize(
                    snapshot, snapshot.container_id, forced="deadline"
                )
                return _from_runtime(snapshot, result)
            return JobObservation(
                job_id=snapshot.job_id,
                action="retained",
                container_id=snapshot.container_id,
                detail="recovery_required",
            )

        result = await self.runtime.persist_running(snapshot, info)
        if result.action != "running":
            return _from_runtime(snapshot, result)
        updated = await self.runtime.load(snapshot.job_id)
        if updated is None:
            return JobObservation(job_id=snapshot.job_id, action="noop")
        if _deadline_passed(updated):
            if updated.container_id is None:
                return await self._recovery(updated, "runtime_unverifiable")
            stopped = await self.runtime.stop_and_finalize(
                updated, updated.container_id, forced="deadline"
            )
            return _from_runtime(updated, stopped)
        return JobObservation(
            job_id=snapshot.job_id,
            action="running",
            container_id=updated.container_id,
        )

    async def _exited(self, snapshot: JobStateSnapshot, info: dict) -> JobObservation:
        forced = None
        if snapshot.state == "cancelling":
            forced = "cancel"
        result = await self.runtime.finalize_exit(snapshot, info, forced=forced)
        return _from_runtime(snapshot, result)

    async def _recovery(self, snapshot: JobStateSnapshot, reason: str) -> JobObservation:
        if snapshot.state == "recovery_required":
            return JobObservation(
                job_id=snapshot.job_id,
                action="retained",
                container_id=snapshot.container_id,
                detail=reason,
            )
        if _owned_claim_active(snapshot):
            # The same registered executor still owns the durable prep/create
            # claim and is refreshing its heartbeat. Observe without preparing,
            # creating, or escalating until that heartbeat goes stale.
            return JobObservation(
                job_id=snapshot.job_id,
                action="deferred",
                container_id=snapshot.container_id,
                detail=reason,
            )
        result = await self.runtime.mark_recovery(snapshot, reason=reason)
        return _from_runtime(snapshot, result)


def _owned_claim_active(snapshot: JobStateSnapshot) -> bool:
    if snapshot.state != "starting" or not snapshot.reservation_active:
        return False
    executor_id = current_executor_id()
    if executor_id is None or snapshot.executor_id != executor_id:
        return False
    if snapshot.heartbeat_at is None:
        return False
    age = utc_now() - snapshot.heartbeat_at
    return age < timedelta(seconds=settings.batch_jobs_heartbeat_stale_seconds)


def _deadline_passed(snapshot: JobStateSnapshot) -> bool:
    deadline: datetime | None = snapshot.deadline_at
    if deadline is None and snapshot.started_at is not None:
        deadline = snapshot.started_at + timedelta(seconds=int(snapshot.max_runtime_seconds))
    return deadline is not None and utc_now() >= deadline


def _from_runtime(snapshot: JobStateSnapshot, result: RuntimeStartResult) -> JobObservation:
    return JobObservation(
        job_id=snapshot.job_id,
        action=result.action,
        container_id=result.container_id
        if result.container_id is not None
        else snapshot.container_id,
        detail=result.detail,
    )


def _count_observation(report: MonitorReport, observation: JobObservation) -> None:
    report.observed += 1
    if observation.action == "running":
        report.started += 1
    elif observation.action in ("succeeded", "failed", "cancelled", "timed_out"):
        report.finalized += 1
    elif observation.action == "recovery_required":
        report.recovery_required += 1
    elif observation.action in ("retained", "noop", "deferred"):
        report.retained += 1


__all__ = ["BatchJobMonitorService", "JobObservation", "MonitorReport"]
