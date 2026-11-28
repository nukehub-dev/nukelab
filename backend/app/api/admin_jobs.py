# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Sanitized cross-owner batch job visibility and proof-only reconciliation.

Rows are deliberately sanitized: command arguments, retained logs, environment
values, image references, runtime identity, volume paths, fencing tokens and
raw daemon payloads stay in the owner surface. Reconciliation is proof-only:
the read-only classifier must support one terminal transition before the
existing fenced finalizer runs. There is no admin cancel, retry, force or manual
reservation-release path.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_operations import (
    _heartbeat_age,
    _safe_code,
    _safe_display_name,
    require_operations_manage,
    require_operations_read,
)
from app.container.driver import ContainerDriver
from app.container.factory import get_driver
from app.core.permissions import Permission
from app.core.security import has_all_permissions
from app.core.time_utils import utc_now
from app.db.session import get_db
from app.dependencies import no_store_cache
from app.models.batch_job import ACTIVE_JOB_STATES, TERMINAL_JOB_STATES, BatchJob
from app.models.user import User
from app.models.volume_operation import VolumeOperation
from app.schemas.admin_jobs import (
    AdminJobEntry,
    AdminJobListState,
    AdminJobPage,
    AdminJobPagination,
    AdminJobReconcileRequest,
    AdminJobReconcileResult,
    AdminJobSummary,
)
from app.services.activity_service import ActivityService
from app.services.batch_job_finalizer import BatchJobFinalizer
from app.services.batch_job_reconciliation import (
    BatchJobReconcileDecision,
    BatchJobReconciliationService,
)
from app.services.volume_operation_service import ACTIVE_STATES as ACTIVE_VOLUME_STATES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs")

Database = Annotated[AsyncSession, Depends(get_db)]

_MAX_OFFSET = 1000
_MAX_AGE_SECONDS = 365 * 24 * 60 * 60
_MAX_CLEANUP_ATTEMPTS = 2**31 - 1
_ACTIVE_STATES = frozenset(ACTIVE_JOB_STATES)
_HISTORY_STATES = frozenset(TERMINAL_JOB_STATES)
_JOB_STATES = (*ACTIVE_JOB_STATES, *TERMINAL_JOB_STATES)
_MANAGE_PERMISSIONS = (Permission.ADMIN_ACCESS, Permission.OPERATIONS_MANAGE_ALL)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "job_not_found"},
    )


def _snapshot_text(snapshot: object, key: str) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    return _safe_display_name(snapshot.get(key))


def _age_cutoff(age_min_seconds: int | None):
    if age_min_seconds is None:
        return None
    return utc_now() - timedelta(seconds=age_min_seconds)


def _filters(
    *,
    state_filter: AdminJobListState,
    cutoff,
) -> list:
    conditions = []
    if state_filter == "active":
        conditions.append(BatchJob.state.in_(_ACTIVE_STATES))
    elif state_filter == "history":
        conditions.append(BatchJob.state.in_(_HISTORY_STATES))
    if cutoff is not None:
        conditions.append(BatchJob.created_at <= cutoff)
    return conditions


def _guard_key(job: BatchJob) -> tuple[UUID, UUID] | None:
    if job.volume_id is None:
        return None
    return (job.volume_operation_id or job.id, job.volume_id)


async def _owner_names(db: AsyncSession, jobs: list[BatchJob]) -> dict[UUID, tuple]:
    owner_ids = {job.user_id for job in jobs}
    if not owner_ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.username, User.first_name, User.last_name).where(
                User.id.in_(owner_ids)
            )
        )
    ).all()
    return {row.id: row for row in rows}


async def _active_guards(db: AsyncSession, jobs: list[BatchJob]) -> set[tuple[UUID, UUID]]:
    wanted = {key for job in jobs if (key := _guard_key(job)) is not None}
    if not wanted:
        return set()
    operation_ids = {operation_id for operation_id, _ in wanted}
    volume_ids = {volume_id for _, volume_id in wanted}
    rows = (
        await db.execute(
            select(VolumeOperation.operation_id, VolumeOperation.volume_id).where(
                VolumeOperation.operation_id.in_(operation_ids),
                VolumeOperation.volume_id.in_(volume_ids),
                VolumeOperation.state.in_(ACTIVE_VOLUME_STATES),
            )
        )
    ).all()
    return {(operation_id, volume_id) for operation_id, volume_id in rows} & wanted


def _entry(
    job: BatchJob,
    *,
    owner: object | None,
    guard_active: bool,
    can_manage: bool,
) -> AdminJobEntry:
    revision_snapshot = job.revision_snapshot if isinstance(job.revision_snapshot, dict) else {}
    plan_snapshot = job.plan_snapshot if isinstance(job.plan_snapshot, dict) else {}
    volume_snapshot = job.volume_snapshot if isinstance(job.volume_snapshot, dict) else {}
    username = _safe_display_name(getattr(owner, "username", None))
    first_name = _safe_display_name(getattr(owner, "first_name", None))
    last_name = _safe_display_name(getattr(owner, "last_name", None))
    display_name = " ".join(part for part in (first_name, last_name) if part) or username
    state = _safe_code(job.state, fallback="unknown") or "unknown"
    return AdminJobEntry(
        id=job.id,
        state=state,
        reason_code=_safe_code(job.reason_code),
        owner_id=job.user_id,
        owner_username=username,
        owner_display_name=display_name,
        environment_name=_snapshot_text(revision_snapshot, "environment_name"),
        environment_display_label=_snapshot_text(revision_snapshot, "display_label"),
        plan_name=_snapshot_text(plan_snapshot, "name"),
        volume_display_name=_snapshot_text(volume_snapshot, "display_name"),
        created_at=job.created_at,
        updated_at=job.updated_at,
        finished_at=job.finished_at,
        reservation_active=bool(job.reservation_active),
        guard_active=guard_active,
        heartbeat_age_seconds=_heartbeat_age(job),
        log_state=_safe_code(job.log_state, fallback="unknown") or "unknown",
        cleanup_state=_safe_code(job.cleanup_state, fallback="unknown") or "unknown",
        cleanup_attempts=min(max(int(job.cleanup_attempts or 0), 0), _MAX_CLEANUP_ATTEMPTS),
        can_reconcile=can_manage and state == "recovery_required",
    )


async def _entry_for_job(db: AsyncSession, job: BatchJob, *, can_manage: bool) -> AdminJobEntry:
    """Build the sanitized entry plus its owner and live volume-guard state."""
    owners = await _owner_names(db, [job])
    guards = await _active_guards(db, [job])
    return _entry(
        job,
        owner=owners.get(job.user_id),
        guard_active=_guard_key(job) in guards,
        can_manage=can_manage,
    )


def _can_manage(current_user: User) -> bool:
    return has_all_permissions(current_user, list(_MANAGE_PERMISSIONS))


async def _summary(db: AsyncSession, *, cutoff) -> AdminJobSummary:
    conditions = [BatchJob.created_at <= cutoff] if cutoff is not None else []
    rows = (
        await db.execute(
            select(BatchJob.state, func.count())
            .select_from(BatchJob)
            .where(*conditions)
            .group_by(BatchJob.state)
        )
    ).all()
    counts = dict.fromkeys(_JOB_STATES, 0)
    total = 0
    for state, count in rows:
        value = int(count or 0)
        total += value
        safe_state = _safe_code(state)
        if safe_state in counts:
            counts[safe_state] += value
    return AdminJobSummary(total=total, **counts)


@router.get("", response_model=AdminJobPage)
async def list_jobs(
    response: Response,
    db: Database,
    current_user: User = Depends(require_operations_read),
    state: AdminJobListState = Query("all"),
    age_min_seconds: int | None = Query(None, ge=0, le=_MAX_AGE_SECONDS),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=_MAX_OFFSET),
):
    """List batch jobs across owners in stable newest-first order.

    ``age_min_seconds`` keeps rows created at least that many seconds ago.
    The summary honors the age filter but ignores the active/history/all chip,
    matching the read-only admin queue summary convention.
    """
    no_store_cache(response)
    cutoff = _age_cutoff(age_min_seconds)
    conditions = _filters(state_filter=state, cutoff=cutoff)
    total = int(await db.scalar(select(func.count()).select_from(BatchJob).where(*conditions)) or 0)
    jobs = (
        await db.scalars(
            select(BatchJob)
            .where(*conditions)
            .order_by(BatchJob.created_at.desc().nulls_last(), BatchJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    owners = await _owner_names(db, list(jobs))
    guards = await _active_guards(db, list(jobs))
    can_manage = _can_manage(current_user)
    items = [
        _entry(
            job,
            owner=owners.get(job.user_id),
            guard_active=_guard_key(job) in guards,
            can_manage=can_manage,
        )
        for job in jobs
    ]
    return AdminJobPage(
        items=items,
        pagination=AdminJobPagination(
            limit=limit,
            offset=offset,
            total=total,
            has_more=offset + len(items) < total,
        ),
        summary=await _summary(db, cutoff=cutoff),
    )


@router.get("/{job_id}", response_model=AdminJobEntry)
async def get_job(
    job_id: UUID,
    response: Response,
    db: Database,
    current_user: User = Depends(require_operations_read),
):
    """Return one sanitized job row.

    Foreign and unknown ids are deliberately indistinguishable: a row is only
    returned when it exists, and the response never includes owner payloads.
    """
    no_store_cache(response)
    job = await db.get(BatchJob, job_id, populate_existing=True)
    if job is None:
        raise _not_found()
    return await _entry_for_job(db, job, can_manage=_can_manage(current_user))


def _reconciliation_service(
    db: AsyncSession, driver: ContainerDriver
) -> BatchJobReconciliationService:
    """Build the read-only classifier; the test seam supplies fake runtimes."""
    return BatchJobReconciliationService(db, driver)


async def _record_audit(
    db: AsyncSession,
    *,
    actor_id: str,
    job_id: UUID,
    reason: str,
    outcome: str,
    applied: bool = False,
    decision: BatchJobReconcileDecision | None = None,
    previous_state: str | None = None,
    current_state: str | None = None,
) -> None:
    """Write bounded reconcile audit details; never include job payloads."""
    details: dict[str, object] = {
        "reason": reason,
        "outcome": outcome,
        "applied": applied,
        "previous_state": previous_state,
        "new_state": current_state,
    }
    if decision is not None:
        details.update(
            {
                "terminal_state": decision.terminal_state,
                "proof_source": decision.proof_source,
                "runtime_state": decision.runtime_state,
                "liveness": decision.liveness,
                "reason_code": decision.reason_code,
            }
        )
    try:
        await ActivityService(db).log(
            action="jobs.reconcile_applied" if applied else "jobs.reconcile",
            target_type="batch_job",
            target_id=str(job_id),
            actor_id=actor_id,
            details=details,
        )
    except Exception as exc:
        logger.warning(
            "Batch job reconciliation audit failed",
            extra={"job_id": str(job_id), "error_class": type(exc).__name__},
        )
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "audit_unavailable"},
        ) from None


@router.post(
    "/{job_id}/reconcile",
    response_model=AdminJobReconcileResult,
    responses={409: {"description": "Proof is insufficient or the row is not reconcilable."}},
)
async def reconcile_job(
    job_id: UUID,
    body: AdminJobReconcileRequest,
    response: Response,
    db: Database,
    current_user: User = Depends(require_operations_manage),
):
    """Apply one proof-backed terminal result through the existing finalizer."""
    no_store_cache(response)
    actor_id = str(current_user.id)
    can_manage = _can_manage(current_user)
    job = await db.get(BatchJob, job_id, populate_existing=True)
    if job is None:
        await _record_audit(
            db,
            actor_id=actor_id,
            job_id=job_id,
            reason=body.reason,
            outcome="job_not_found",
        )
        raise _not_found()

    previous_state = _safe_code(job.state, fallback="unknown") or "unknown"
    if previous_state in _HISTORY_STATES:
        entry = await _entry_for_job(db, job, can_manage=can_manage)
        await _record_audit(
            db,
            actor_id=actor_id,
            job_id=job_id,
            reason=body.reason,
            outcome="already_terminal",
            previous_state=previous_state,
            current_state=previous_state,
        )
        return AdminJobReconcileResult(
            job=entry,
            applied=False,
            already_terminal=True,
            outcome="already_terminal",
            terminal_state=None,
            proof_source=None,
            reason_code=None,
        )

    if previous_state != "recovery_required":
        await _record_audit(
            db,
            actor_id=actor_id,
            job_id=job_id,
            reason=body.reason,
            outcome="job_not_reconcilable",
            previous_state=previous_state,
            current_state=previous_state,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "job_not_reconcilable"},
        )

    expected_fence = job.fencing_token
    started_at = job.started_at
    try:
        driver = await get_driver()
        decision = await _reconciliation_service(db, driver).inspect(job_id)
    except Exception as exc:
        logger.warning(
            "Batch job reconciliation inspection unavailable",
            extra={"job_id": str(job_id), "error_class": type(exc).__name__},
        )
        await _record_audit(
            db,
            actor_id=actor_id,
            job_id=job_id,
            reason=body.reason,
            outcome="inspection_unavailable",
            previous_state=previous_state,
            current_state=previous_state,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "inspection_unavailable"},
        ) from None

    if decision.reason_code == "job_not_found":
        await _record_audit(
            db,
            actor_id=actor_id,
            job_id=job_id,
            reason=body.reason,
            outcome="job_not_found",
            previous_state=previous_state,
            current_state=previous_state,
        )
        raise _not_found()

    if decision.terminal_state is None:
        await _record_audit(
            db,
            actor_id=actor_id,
            job_id=job_id,
            reason=body.reason,
            outcome="proof_insufficient",
            decision=decision,
            previous_state=previous_state,
            current_state=previous_state,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "proof_insufficient"},
        )

    # Audit before mutation so an unavailable audit trail cannot release anything.
    await _record_audit(
        db,
        actor_id=actor_id,
        job_id=job_id,
        reason=body.reason,
        outcome="applied",
        applied=True,
        decision=decision,
        previous_state=previous_state,
        current_state=decision.terminal_state,
    )
    try:
        result = await BatchJobFinalizer(db, driver).finalize(
            job_id,
            fencing_token=expected_fence,
            state=decision.terminal_state,
            outcome_code=decision.terminal_state,
            reason_code=decision.reason_code,
            proof_class="runtime",
            exit_code=decision.exit_code,
            executor_terminated=True,
            started_at=decision.observed_started_at or started_at,
            finished_at=decision.observed_finished_at or utc_now(),
        )
    except Exception as exc:
        logger.warning(
            "Batch job reconciliation finalization failed",
            extra={"job_id": str(job_id), "error_class": type(exc).__name__},
        )
        await _record_audit(
            db,
            actor_id=actor_id,
            job_id=job_id,
            reason=body.reason,
            outcome="no_change",
            decision=decision,
            previous_state=previous_state,
            current_state=previous_state,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "reconciliation_failed"},
        ) from None

    current = await db.get(BatchJob, job_id, populate_existing=True)
    if current is None:
        raise _not_found()
    current_state = _safe_code(current.state, fallback="unknown") or "unknown"
    applied = bool(result.applied) and result.error is None
    already_terminal = bool(result.already_terminal) and not applied
    if result.error is not None:
        outcome = "no_change"
    elif applied:
        outcome = "applied"
    elif already_terminal:
        outcome = "already_terminal"
    else:
        outcome = "no_change"
    if outcome != "applied":
        # The proof was current when inspected but another owner of the fenced
        # row settled it first. Record the truthful non-applied result.
        await _record_audit(
            db,
            actor_id=actor_id,
            job_id=job_id,
            reason=body.reason,
            outcome=outcome,
            decision=decision,
            previous_state=previous_state,
            current_state=current_state,
        )
    entry = await _entry_for_job(db, current, can_manage=can_manage)
    return AdminJobReconcileResult(
        job=entry,
        applied=applied,
        already_terminal=already_terminal,
        outcome=outcome,
        terminal_state=decision.terminal_state,
        proof_source=decision.proof_source,
        reason_code=decision.reason_code,
    )
