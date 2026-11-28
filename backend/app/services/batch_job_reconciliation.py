# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded inspection of stale or otherwise unresolved batch-job journals.

A stale heartbeat is an inspection trigger, never termination proof. The scan
reuses the monitor's read-only observation and only finalizes an outcome when
the daemon supplies exact identity and exit evidence. It never issues a create
or a start after a persisted start checkpoint.

``inspect()`` is the read-only decision classifier behind the admin reconcile
endpoint: it reports whether the evidence supports one terminal transition but
never persists an adopted container, refreshes a heartbeat, or finalizes a row.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

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
from app.services.batch_job_runtime import (
    JobStateSnapshot,
    classify_exit,
    container_status,
)

logger = get_logger(__name__)

SCAN_STATE_KEY = "batch_jobs_recovery_scan_state"
_RECOVERY_STATES = ("starting", "running", "cancelling", "recovery_required")
_TERMINAL_STATES = frozenset(TERMINAL_JOB_STATES)
_ACTIVE_STATES = frozenset(_RECOVERY_STATES)
_CLEANUP_BATCH_LIMIT = 10
_SAFE_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,99}\Z")

JobReconcileTerminalState = Literal["succeeded", "failed", "cancelled", "timed_out"]
JobReconcileRuntimeState = Literal["present", "absent", "ambiguous"]
JobReconcileLiveness = Literal["alive", "stopped", "ambiguous"]


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


@dataclass(frozen=True, slots=True)
class BatchJobReconcileDecision:
    """One bounded, read-only conclusion about a job's runtime evidence."""

    job_id: uuid.UUID
    state: str
    terminal_state: JobReconcileTerminalState | None
    reason_code: str
    proof_source: str
    exit_code: int | None
    runtime_state: JobReconcileRuntimeState
    liveness: JobReconcileLiveness
    observed_started_at: datetime | None = None
    observed_finished_at: datetime | None = None

    def __post_init__(self) -> None:
        for value in (self.state, self.reason_code, self.proof_source):
            if not _SAFE_CODE_RE.fullmatch(value):
                raise ValueError("Invalid batch job reconciliation code")
        if self.terminal_state not in (None, "succeeded", "failed", "cancelled", "timed_out"):
            raise ValueError("Invalid batch job terminal state")
        if self.runtime_state not in ("present", "absent", "ambiguous"):
            raise ValueError("Invalid batch job runtime state")
        if self.liveness not in ("alive", "stopped", "ambiguous"):
            raise ValueError("Invalid batch job liveness")


def _safe_code(value: object) -> str:
    return value if isinstance(value, str) and _SAFE_CODE_RE.fullmatch(value) else "unknown"


def _checkpoint_recorded(snapshot: JobStateSnapshot) -> bool:
    """A create/start checkpoint proves a runtime may have been requested."""
    return bool(
        snapshot.container_id or snapshot.create_requested_at or snapshot.start_requested_at
    )


def _exit_code(info: dict) -> int | None:
    state = info.get("State")
    value = state.get("ExitCode") if isinstance(state, dict) else None
    return value if type(value) is int else None


def _fresh(value: datetime | None, *, now: datetime, stale_seconds: int) -> bool:
    if not isinstance(value, datetime):
        return False
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return now - value < timedelta(seconds=stale_seconds)


def _job_decision(
    job_id: uuid.UUID,
    *,
    state: str,
    reason_code: str,
    terminal_state: JobReconcileTerminalState | None = None,
    proof_source: str = "none",
    exit_code: int | None = None,
    runtime_state: JobReconcileRuntimeState = "ambiguous",
    liveness: JobReconcileLiveness = "ambiguous",
    observed_started_at: datetime | None = None,
    observed_finished_at: datetime | None = None,
) -> BatchJobReconcileDecision:
    return BatchJobReconcileDecision(
        job_id=job_id,
        state=state,
        terminal_state=terminal_state,
        reason_code=reason_code,
        proof_source=proof_source,
        exit_code=exit_code,
        runtime_state=runtime_state,
        liveness=liveness,
        observed_started_at=observed_started_at,
        observed_finished_at=observed_finished_at,
    )


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

    async def inspect(self, job_id: uuid.UUID) -> BatchJobReconcileDecision:
        """Classify one job's evidence without changing any row or runtime."""
        await self._clean_session()
        snapshot = await self.runtime.load(job_id)
        if snapshot is None:
            return _job_decision(job_id, state="unknown", reason_code="job_not_found")
        state = _safe_code(snapshot.state)
        if state in _TERMINAL_STATES:
            return _job_decision(job_id, state=state, reason_code="job_terminal")
        if not snapshot.reservation_active or state not in _ACTIVE_STATES:
            return _job_decision(job_id, state=state, reason_code="job_not_reconcilable")

        liveness = await self._executor_liveness(snapshot)
        lookup = await self.runtime.lookup_container(snapshot)
        if lookup.status in ("unavailable", "mismatch"):
            return _job_decision(
                job_id,
                state=state,
                reason_code="runtime_unverifiable",
                liveness=liveness,
            )
        if lookup.status == "missing":
            if not _checkpoint_recorded(snapshot):
                return _job_decision(
                    job_id,
                    state=state,
                    reason_code="runtime_unverifiable",
                    runtime_state="absent",
                    liveness=liveness,
                )
            if liveness == "alive":
                return _job_decision(
                    job_id,
                    state=state,
                    reason_code="executor_live",
                    runtime_state="absent",
                    liveness=liveness,
                )
            return _job_decision(
                job_id,
                state=state,
                terminal_state="failed",
                reason_code="runtime_absent",
                proof_source="runtime_inspection",
                runtime_state="absent",
                liveness=liveness,
                observed_started_at=snapshot.started_at,
                # Absence has no exit timestamp. Bound the billable interval to
                # the last fenced observation instead of charging until the
                # operator happens to reconcile.
                observed_finished_at=snapshot.heartbeat_at or snapshot.state_changed_at,
            )
        if lookup.info is None or lookup.container_id is None:
            return _job_decision(
                job_id,
                state=state,
                reason_code="runtime_unverifiable",
                liveness=liveness,
            )
        if snapshot.container_id is None or lookup.container_id != snapshot.container_id:
            # Inspection may find a deterministic-name collision, but adopting a
            # different runtime identity is a mutation the classifier must not make.
            return _job_decision(
                job_id,
                state=state,
                reason_code="runtime_unverifiable",
                runtime_state="present",
                liveness=liveness,
            )

        status = container_status(lookup.info)
        if status == "running":
            return _job_decision(
                job_id,
                state=state,
                reason_code="runtime_running",
                proof_source="runtime_inspection",
                runtime_state="present",
                liveness=liveness,
            )
        if status == "exited":
            exit_code = _exit_code(lookup.info)
            if exit_code is None:
                return _job_decision(
                    job_id,
                    state=state,
                    reason_code="runtime_unverifiable",
                    runtime_state="present",
                    liveness=liveness,
                )
            forced = (
                "cancel"
                if state == "cancelling" or snapshot.stop_requested_at is not None
                else None
            )
            terminal, _outcome, reason, observed_exit, observed_started, observed_finished = (
                classify_exit(snapshot, lookup.info, forced=forced)
            )
            if terminal not in ("succeeded", "failed", "cancelled", "timed_out"):
                return _job_decision(
                    job_id,
                    state=state,
                    reason_code="runtime_unverifiable",
                    runtime_state="present",
                    liveness=liveness,
                )
            return _job_decision(
                job_id,
                state=state,
                terminal_state=terminal,
                reason_code=reason or "exit_zero",
                proof_source="runtime_inspection",
                exit_code=observed_exit,
                runtime_state="present",
                liveness=liveness,
                observed_started_at=observed_started,
                observed_finished_at=observed_finished,
            )
        if status == "created":
            return _job_decision(
                job_id,
                state=state,
                reason_code="runtime_not_started",
                runtime_state="present",
                liveness=liveness,
            )
        return _job_decision(
            job_id,
            state=state,
            reason_code="runtime_unverifiable",
            runtime_state="present",
            liveness=liveness,
        )

    async def _executor_liveness(self, snapshot: JobStateSnapshot) -> JobReconcileLiveness:
        """Judge the job's fenced executor claim from its heartbeat age.

        The per-job ``heartbeat_at`` is the executor claim. A live process that
        is no longer refreshing this job does not hold the claim, so the process
        registry must not block an otherwise proof-backed absent runtime.
        """
        now = utc_now()
        stale_seconds = int(settings.batch_jobs_heartbeat_stale_seconds)
        if _fresh(snapshot.heartbeat_at, now=now, stale_seconds=stale_seconds):
            return "alive"
        return "stopped"

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
    "BatchJobReconcileDecision",
    "BatchJobReconciliationService",
    "SCAN_STATE_KEY",
]
