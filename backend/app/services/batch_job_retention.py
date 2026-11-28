# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded physical removal of expired batch-job log payloads.

The terminal result, timestamps, billing fields, reservation state and cleanup
journal stay untouched. Only the byte-bounded ``batch_job_logs`` payload is
deleted, and only after its own ``expires_at`` has passed for a terminal job.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.batch_job import TERMINAL_JOB_STATES, BatchJob, BatchJobLog

logger = get_logger(__name__)

_TERMINAL_STATES = frozenset(TERMINAL_JOB_STATES)
LOG_STATE_EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class LogPurgeReport:
    """Bounded counters for one purge run; never row payloads."""

    scanned: int = 0
    deleted: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "deleted": self.deleted,
            "errors": self.errors,
        }


def _naive_utc(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _batch_limit(limit: int | None) -> int:
    if limit is None:
        return int(settings.batch_jobs_log_purge_batch_size)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return 0
    return limit


async def _clean_session(db: AsyncSession) -> None:
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("Batch job log purge requires a clean session")
    if db.in_transaction():
        await db.rollback()


async def _expired_candidates(db: AsyncSession, *, now: datetime, limit: int) -> list[uuid.UUID]:
    if limit < 1:
        return []
    rows = await db.execute(
        select(BatchJobLog.job_id)
        .join(BatchJob, BatchJob.id == BatchJobLog.job_id)
        .where(
            BatchJobLog.expires_at.is_not(None),
            BatchJobLog.expires_at <= now,
            BatchJob.state.in_(_TERMINAL_STATES),
        )
        .order_by(BatchJobLog.expires_at.asc(), BatchJobLog.job_id.asc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def _purge_one(db: AsyncSession, job_id: uuid.UUID, *, now: datetime) -> bool:
    """Delete one expired payload under row locks; return whether one was removed."""
    job = await db.scalar(
        select(BatchJob)
        .where(BatchJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        # The job may have been removed between selection and locking. Its log
        # row is then an orphan payload; remove it without inventing job state.
        payload = await db.get(
            BatchJobLog,
            job_id,
            with_for_update=True,
            populate_existing=True,
        )
        if payload is None or payload.expires_at is None or payload.expires_at > now:
            return False
        await db.delete(payload)
        return True

    if job.state not in _TERMINAL_STATES:
        # An active job's log payload is never eligible, even if it carries an
        # old expiry from an earlier observation.
        return False

    payload = await db.get(
        BatchJobLog,
        job_id,
        with_for_update=True,
        populate_existing=True,
    )
    if payload is None or payload.expires_at is None or payload.expires_at > now:
        return False
    await db.delete(payload)
    job.log_state = LOG_STATE_EXPIRED
    job.updated_at = now
    return True


async def purge_expired_logs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> LogPurgeReport:
    """Delete a bounded batch of expired log payload rows.

    The selection is bounded by ``limit`` (or the configured purge batch size)
    and each row is rechecked under a job/log row lock before deletion. Repeated
    runs are idempotent: an already-purged job has no log row to select.
    """
    await _clean_session(db)
    current = _naive_utc(now)
    cap = _batch_limit(limit)
    candidates = await _expired_candidates(db, now=current, limit=cap)
    await db.rollback()

    scanned = len(candidates)
    deleted = 0
    errors = 0
    for job_id in candidates:
        try:
            await _clean_session(db)
            async with db.begin():
                if await _purge_one(db, job_id, now=current):
                    deleted += 1
        except Exception as exc:
            await _safe_rollback(db)
            errors += 1
            logger.warning(
                "Batch job log purge row deferred",
                extra={
                    "job_id": str(job_id),
                    "error_class": type(exc).__name__,
                },
            )

    report = LogPurgeReport(scanned=scanned, deleted=deleted, errors=errors)
    if scanned:
        logger.info("Batch job log purge complete", extra=report.as_dict())
    return report


async def _safe_rollback(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


__all__ = [
    "LOG_STATE_EXPIRED",
    "LogPurgeReport",
    "purge_expired_logs",
]
