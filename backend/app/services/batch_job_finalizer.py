# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""One terminal batch-job result plus separately idempotent runtime cleanup.

The admission service owns the terminal transaction and the volume-guard
release. This module only adds the durable cleanup state after that commit and
never turns a cleanup failure into a different execution result.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container.driver import ContainerDriver, ContainerDriverError
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.batch_job import TERMINAL_JOB_STATES, BatchJob
from app.services.admission_service import acquire_admission_lock
from app.services.batch_job_admission_service import (
    BatchJobAdmissionService,
    JobAdmissionError,
)
from app.services.worker_heartbeat import current_executor_id

logger = get_logger(__name__)

CLEANUP_PENDING = "pending"
CLEANUP_COMPLETE = "complete"
_TERMINAL_STATES = frozenset(TERMINAL_JOB_STATES)


@dataclass(frozen=True, slots=True)
class CleanupResult:
    job_id: uuid.UUID
    state: str
    attempts: int
    retained: bool = False


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    job_id: uuid.UUID
    applied: bool
    already_terminal: bool
    executor_unconfirmed: bool
    cleanup: CleanupResult | None = None
    error: str | None = None


def _status(error: BaseException) -> int | None:
    value = getattr(error, "status", None)
    return value if isinstance(value, int) else None


def _safe_labels(info: dict) -> dict:
    config = info.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    return labels if isinstance(labels, dict) else {}


@dataclass(frozen=True, slots=True)
class _CleanupOutcome:
    complete: bool
    retained: bool = False
    error_class: str | None = None


class BatchJobFinalizer:
    """Apply exactly one terminal result, then retry container removal."""

    def __init__(
        self,
        db: AsyncSession,
        driver: ContainerDriver,
        *,
        admission: BatchJobAdmissionService | None = None,
    ):
        self.db = db
        self.driver = driver
        self.admission = admission or BatchJobAdmissionService(db, driver)

    async def _clean_session(self) -> None:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Batch job finalization requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def finalize(
        self,
        job_id: uuid.UUID,
        *,
        fencing_token: uuid.UUID,
        state: str,
        outcome_code: str,
        reason_code: str | None = None,
        proof_class: str | None = None,
        exit_code: int | None = None,
        executor_terminated: bool = True,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        log_state: str | None = None,
        log_text: str | None = None,
        log_truncated: bool = False,
        log_size_bytes: int | None = None,
        log_expires_at: datetime | None = None,
        observed_runtime_identity: dict | None = None,
    ) -> FinalizeResult:
        """Commit one terminal result and then attempt bounded cleanup."""
        was_terminal = await self._is_terminal(job_id)
        try:
            job = await self.admission.release_terminal(
                job_id,
                fencing_token=fencing_token,
                state=state,
                outcome_code=outcome_code,
                reason_code=reason_code,
                proof_class=proof_class,
                exit_code=exit_code,
                executor_terminated=executor_terminated,
                started_at=started_at,
                finished_at=finished_at,
                log_state=log_state,
                log_text=log_text,
                log_truncated=log_truncated,
                log_size_bytes=log_size_bytes,
                log_expires_at=log_expires_at,
                observed_runtime_identity=observed_runtime_identity,
            )
        except JobAdmissionError as exc:
            if exc.code == "executor_unconfirmed":
                try:
                    await self.admission.mark_recovery_required(
                        job_id,
                        fencing_token=fencing_token,
                        executor_id=current_executor_id(),
                        reason_code="runtime_unverifiable",
                    )
                except Exception as recovery_exc:
                    logger.warning(
                        "Batch job executor-unconfirmed handoff deferred",
                        extra={
                            "job_id": str(job_id),
                            "error_class": type(recovery_exc).__name__,
                        },
                    )
                return FinalizeResult(
                    job_id=job_id,
                    applied=False,
                    already_terminal=False,
                    executor_unconfirmed=True,
                    error=exc.code,
                )
            if exc.code in ("job_not_active", "operation_conflict"):
                return FinalizeResult(
                    job_id=job_id,
                    applied=False,
                    already_terminal=False,
                    executor_unconfirmed=False,
                    error=exc.code,
                )
            raise

        if job is None:
            return FinalizeResult(
                job_id=job_id,
                applied=False,
                already_terminal=False,
                executor_unconfirmed=False,
                error="job_not_found",
            )

        already_terminal = job.result_recorded_at is not None and was_terminal
        cleanup = None
        if job.state in _TERMINAL_STATES:
            try:
                cleanup = await self.cleanup(job_id)
            except Exception as exc:
                # The terminal result is already durable. Cleanup is a separate
                # idempotent concern and must never reopen the result.
                logger.warning(
                    "Batch job cleanup deferred",
                    extra={
                        "job_id": str(job_id),
                        "error_class": type(exc).__name__,
                    },
                )
        return FinalizeResult(
            job_id=job_id,
            applied=not already_terminal,
            already_terminal=already_terminal,
            executor_unconfirmed=False,
            cleanup=cleanup,
        )

    async def _is_terminal(self, job_id: uuid.UUID) -> bool:
        await self._clean_session()
        async with self.db.begin():
            job = await self.db.scalar(
                select(BatchJob)
                .where(BatchJob.id == job_id)
                .execution_options(populate_existing=True)
            )
            return bool(job is not None and job.state in _TERMINAL_STATES)

    async def cleanup(self, job_id: uuid.UUID) -> CleanupResult:
        """Remove one terminal job's container without changing its result."""
        await self._clean_session()
        async with self.db.begin():
            job = await self.db.scalar(
                select(BatchJob)
                .where(BatchJob.id == job_id)
                .execution_options(populate_existing=True)
            )
            if job is None:
                return CleanupResult(job_id=job_id, state="missing", attempts=0)
            if job.state not in _TERMINAL_STATES:
                return CleanupResult(
                    job_id=job_id,
                    state=CLEANUP_PENDING,
                    attempts=int(job.cleanup_attempts or 0),
                )
            if job.cleanup_state == CLEANUP_COMPLETE:
                return CleanupResult(
                    job_id=job_id,
                    state=CLEANUP_COMPLETE,
                    attempts=int(job.cleanup_attempts or 0),
                )
            container_id = job.container_id
            container_name = job.container_name
            fencing_token = job.fencing_token
            attempts = int(job.cleanup_attempts or 0)

        outcome = await self._remove_runtime(
            job_id=job_id,
            fencing_token=fencing_token,
            container_id=container_id,
            container_name=container_name,
        )
        now = utc_now()
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self.db.scalar(
                select(BatchJob)
                .where(BatchJob.id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if job is None or job.state not in _TERMINAL_STATES:
                return CleanupResult(
                    job_id=job_id,
                    state=CLEANUP_PENDING,
                    attempts=attempts,
                    retained=outcome.retained,
                )
            if job.container_id != container_id:
                # A later verified observation recorded a different runtime.
                return CleanupResult(
                    job_id=job_id,
                    state=CLEANUP_PENDING,
                    attempts=attempts,
                    retained=True,
                )
            job.cleanup_attempts = int(job.cleanup_attempts or 0) + 1
            job.last_cleanup_at = now
            if outcome.complete:
                job.cleanup_state = CLEANUP_COMPLETE
            job.updated_at = now
            if not outcome.complete:
                logger.warning(
                    "Batch job container retained for cleanup retry",
                    extra={
                        "job_id": str(job_id),
                        "error_class": outcome.error_class,
                    },
                )
            return CleanupResult(
                job_id=job_id,
                state=CLEANUP_COMPLETE if outcome.complete else CLEANUP_PENDING,
                attempts=job.cleanup_attempts,
                retained=outcome.retained or not outcome.complete,
            )

    async def _remove_runtime(
        self,
        *,
        job_id: uuid.UUID,
        fencing_token: uuid.UUID,
        container_id: str | None,
        container_name: str | None,
    ) -> _CleanupOutcome:
        resolved_id = container_id
        if resolved_id is None and container_name:
            try:
                resolved_id = await self.driver.get_container_by_name(container_name)
            except Exception as exc:
                return _CleanupOutcome(
                    complete=False,
                    retained=True,
                    error_class=type(exc).__name__,
                )
            if resolved_id is None:
                try:
                    info = await self.driver.get_container_info(container_name)
                except ContainerDriverError as exc:
                    if _status(exc) == 404:
                        return _CleanupOutcome(complete=True)
                    return _CleanupOutcome(
                        complete=False,
                        retained=True,
                        error_class=type(exc).__name__,
                    )
                except Exception as exc:
                    return _CleanupOutcome(
                        complete=False,
                        retained=True,
                        error_class=type(exc).__name__,
                    )
                identifier = info.get("Id")
                if isinstance(identifier, str) and identifier:
                    resolved_id = identifier
                else:
                    return _CleanupOutcome(
                        complete=False,
                        retained=True,
                        error_class="unresolved_container",
                    )
            try:
                info = await self.driver.get_container_info(resolved_id)
            except Exception as exc:
                return _CleanupOutcome(
                    complete=False,
                    retained=True,
                    error_class=type(exc).__name__,
                )
            labels = _safe_labels(info)
            if (
                labels.get("nukelab.job.id") != str(job_id)
                or labels.get("nukelab.job.fence") != str(fencing_token)
                or labels.get("nukelab.workload") != "job"
            ):
                # A colliding deterministic name is never ours to remove.
                return _CleanupOutcome(
                    complete=False,
                    retained=True,
                    error_class="identity_mismatch",
                )
        if resolved_id is None:
            return _CleanupOutcome(complete=True)
        try:
            await self.driver.delete_container(resolved_id, force=False)
        except ContainerDriverError as exc:
            if _status(exc) == 404:
                return _CleanupOutcome(complete=True)
            return _CleanupOutcome(
                complete=False,
                retained=True,
                error_class=type(exc).__name__,
            )
        except Exception as exc:
            return _CleanupOutcome(
                complete=False,
                retained=True,
                error_class=type(exc).__name__,
            )
        return _CleanupOutcome(complete=True)


__all__ = [
    "BatchJobFinalizer",
    "CLEANUP_COMPLETE",
    "CLEANUP_PENDING",
    "CleanupResult",
    "FinalizeResult",
]
