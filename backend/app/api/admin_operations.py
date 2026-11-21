# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin-only operation visibility and proof-only reconciliation.

Reads return sanitized durable metadata. Reconciliation reruns the read-only
evidence inspector and asks the fenced finalizer to apply only a proof-backed
terminal outcome. There is no force/override path: an operator reason never
releases a reservation or changes a row on its own. Volume completion still
requires the recovery service's artifact/completion primitive, so a
proof-backed volume success stays protected when that primitive is absent.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_jwt_auth
from app.container.driver import ContainerDriver
from app.container.factory import get_driver
from app.core.permissions import Permission
from app.core.time_utils import utc_now
from app.db.session import get_db
from app.dependencies import PermissionChecker, get_current_active_user, no_store_cache
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.user import User
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.schemas.admin_operations import (
    AdminOperation,
    AdminOperationPage,
    AdminOperationPagination,
    AdminOperationReconcileRequest,
    AdminOperationReconcileResult,
)
from app.services.activity_service import ActivityService
from app.services.operation_finalizer import OperationFinalizer
from app.services.operation_reconciliation import (
    Liveness,
    OperationKind,
    ReconcileDecision,
    ReconciliationService,
    RuntimeState,
    TerminalState,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/operations")

Database = Annotated[AsyncSession, Depends(get_db)]

_LAUNCH_ACTIVE_STATES = frozenset({"prepared", "executing", "uncertain"})
_VOLUME_ACTIVE_STATES = frozenset({"pending", "in_progress", "recovery_required"})
_MAX_OFFSET = 1000
_DIAGNOSTIC_VALUE_MAX = 64
_SAFE_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,99}\Z")
_SAFE_DIAGNOSTIC_KEYS = (
    "row_state",
    "action",
    "container_count",
    "health_status",
    "destination_status",
    "executor_alive",
    "helper",
    "liveness_proof",
)
_KIND_MODELS = {
    OperationKind.LAUNCH: ServerLaunchOperation,
    OperationKind.BACKUP: VolumeBackup,
    OperationKind.RESTORE: VolumeRestore,
}


async def require_operations_read(
    current_user: User = Depends(get_current_active_user),
    _jwt=Depends(require_jwt_auth()),
) -> User:
    """Require admin access, the operations read grant, and a JWT session."""
    PermissionChecker(current_user).require_all(
        [Permission.ADMIN_ACCESS, Permission.OPERATIONS_READ_ALL]
    )
    return current_user


async def require_operations_manage(
    current_user: User = Depends(get_current_active_user),
    _jwt=Depends(require_jwt_auth()),
) -> User:
    """Require admin access, the operations manage grant, and a JWT session."""
    PermissionChecker(current_user).require_all(
        [Permission.ADMIN_ACCESS, Permission.OPERATIONS_MANAGE_ALL]
    )
    return current_user


def _reconciliation_service(db: AsyncSession, driver: ContainerDriver) -> ReconciliationService:
    """Build the read-only inspector; the test seam supplies fake artifacts."""
    return ReconciliationService(db, driver)


def _model(kind: OperationKind):
    return _KIND_MODELS[kind]


def _state_column(kind: OperationKind):
    if kind is OperationKind.LAUNCH:
        return ServerLaunchOperation.state
    return _model(kind).status


def _owner_column(kind: OperationKind):
    if kind is OperationKind.LAUNCH:
        return ServerLaunchOperation.owner_id
    return _model(kind).user_id


def _row_state(kind: OperationKind, row) -> str:
    value = row.state if kind is OperationKind.LAUNCH else row.status
    return _safe_code(value, fallback="unknown") or "unknown"


def _is_active(kind: OperationKind, state: str) -> bool:
    if kind is OperationKind.LAUNCH:
        return state in _LAUNCH_ACTIVE_STATES
    return state in _VOLUME_ACTIVE_STATES


def _is_recovery_required(kind: OperationKind, state: str) -> bool:
    return state == ("uncertain" if kind is OperationKind.LAUNCH else "recovery_required")


def _applied_row_state(kind: OperationKind, terminal_state: TerminalState) -> str:
    if kind is OperationKind.LAUNCH:
        return (
            "uncertain"
            if terminal_state is TerminalState.RECOVERY_REQUIRED
            else terminal_state.value
        )
    return "completed" if terminal_state is TerminalState.SUCCEEDED else terminal_state.value


def _safe_code(value, *, fallback: str | None = None) -> str | None:
    if isinstance(value, str) and _SAFE_CODE_RE.fullmatch(value):
        return value
    return fallback


def _heartbeat_age(row) -> int | None:
    heartbeat_at = getattr(row, "heartbeat_at", None)
    if not isinstance(heartbeat_at, datetime):
        return None
    if heartbeat_at.tzinfo is not None:
        heartbeat_at = heartbeat_at.astimezone(UTC).replace(tzinfo=None)
    age = int((utc_now() - heartbeat_at).total_seconds())
    return min(max(age, 0), 2**31 - 1)


def _summary(kind: OperationKind, row) -> AdminOperation:
    if kind is OperationKind.LAUNCH:
        state = _safe_code(row.state, fallback="unknown")
        action = _safe_code(row.action)
        owner_id = row.owner_id
        updated_at = row.updated_at
        finished_at = row.finished_at
    else:
        state = _safe_code(row.status, fallback="unknown")
        action = kind.value
        owner_id = row.user_id
        updated_at = row.completed_at
        finished_at = row.completed_at
    return AdminOperation(
        kind=kind.value,
        id=row.id,
        state=state,
        action=action,
        owner_id=owner_id,
        created_at=row.created_at,
        updated_at=updated_at,
        finished_at=finished_at,
        reason_code=_safe_code(row.reason_code),
        recovery_required=_is_recovery_required(kind, state),
        heartbeat_age_seconds=_heartbeat_age(row),
    )


def _safe_diagnostics(decision: ReconcileDecision) -> dict[str, str]:
    diagnostics: dict[str, str] = {}
    for key in _SAFE_DIAGNOSTIC_KEYS:
        value = decision.detail.get(key)
        if value is None:
            continue
        text = str(value)[:_DIAGNOSTIC_VALUE_MAX]
        if text:
            diagnostics[key] = text
    return diagnostics


def _safe_counters(decision: ReconcileDecision) -> dict[str, int]:
    value = decision.detail.get("container_count")
    if value is None:
        return {}
    try:
        return {"container_count": max(0, int(value))}
    except (TypeError, ValueError):
        return {}


def _apply_decision(item: AdminOperation, decision: ReconcileDecision) -> None:
    item.evidence_reason_code = decision.reason_code
    item.liveness = decision.liveness.value
    item.proof_source = decision.proof_source
    item.runtime_state = decision.runtime_state.value
    item.diagnostics = _safe_diagnostics(decision)
    item.counters = _safe_counters(decision)


def _cutoff(age_days: int | None, older_than: datetime | None) -> datetime | None:
    cutoffs: list[datetime] = []
    if age_days is not None:
        cutoffs.append(utc_now() - timedelta(days=age_days))
    if older_than is not None:
        value = older_than
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        cutoffs.append(value)
    return min(cutoffs) if cutoffs else None


def _conditions(
    kind: OperationKind,
    *,
    state: str | None,
    owner_id: UUID | None,
    created_before: datetime | None,
    recovery_required: bool | None,
) -> list:
    model = _model(kind)
    state_column = _state_column(kind)
    conditions = []
    if state is not None:
        conditions.append(state_column == state)
    if owner_id is not None:
        conditions.append(_owner_column(kind) == owner_id)
    if created_before is not None:
        conditions.append(model.created_at <= created_before)
    if recovery_required is True:
        conditions.append(
            state_column == ("uncertain" if kind is OperationKind.LAUNCH else "recovery_required")
        )
    elif recovery_required is False:
        conditions.append(
            state_column != ("uncertain" if kind is OperationKind.LAUNCH else "recovery_required")
        )
    return conditions


async def _load(db: AsyncSession, kind: OperationKind, operation_id: UUID):
    return await db.get(_model(kind), operation_id, populate_existing=True)


async def _inspect(
    db: AsyncSession, driver: ContainerDriver, kind: OperationKind, operation_id: UUID
) -> ReconcileDecision:
    return await _reconciliation_service(db, driver).inspect(kind, operation_id)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "operation_not_found"},
    )


async def _record_audit(
    db: AsyncSession,
    *,
    actor_id: str,
    kind: OperationKind,
    operation_id: UUID,
    reason: str,
    outcome: str,
    decision: ReconcileDecision | None = None,
    previous_state: str | None = None,
    current_state: str | None = None,
    applied: bool = False,
) -> None:
    details: dict[str, object] = {
        "kind": kind.value,
        "reason": reason,
        "outcome": outcome,
        "applied": applied,
        "previous_state": previous_state,
        "new_state": current_state,
    }
    if decision is not None:
        details.update(
            {
                "terminal_state": (
                    decision.terminal_state.value if decision.terminal_state is not None else None
                ),
                "liveness": decision.liveness.value,
                "proof_source": decision.proof_source,
                "runtime_state": decision.runtime_state.value,
                "evidence_reason_code": decision.reason_code,
            }
        )
    try:
        await ActivityService(db).log(
            action="operations.reconcile_applied" if applied else "operations.reconcile",
            target_type="operation",
            target_id=str(operation_id),
            actor_id=actor_id,
            details=details,
        )
    except Exception as exc:
        logger.warning(
            "Operation reconciliation audit failed",
            extra={
                "kind": kind.value,
                "operation_id": str(operation_id),
                "error_class": type(exc).__name__,
            },
        )
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "audit_unavailable"},
        ) from None


@router.get("", response_model=AdminOperationPage)
async def list_operations(
    response: Response,
    db: Database,
    _current_user: User = Depends(require_operations_read),
    kind: OperationKind | None = Query(None),
    state: str | None = Query(None, min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$"),
    owner_id: UUID | None = Query(None),
    age_days: int | None = Query(None, ge=0, le=3650),
    older_than: datetime | None = Query(None),
    recovery_required: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=_MAX_OFFSET),
):
    """List active and historical operations in bounded, stable order.

    ``age_days`` keeps rows created at least that many days ago;
    ``older_than`` accepts an explicit UTC cutoff. ``recovery_required``
    matches launch ``uncertain`` and volume ``recovery_required`` rows.
    """
    no_store_cache(response)
    selected = [kind] if kind is not None else list(OperationKind)
    created_before = _cutoff(age_days, older_than)
    bound = offset + limit
    total = 0
    items: list[AdminOperation] = []
    for current_kind in selected:
        model = _model(current_kind)
        conditions = _conditions(
            current_kind,
            state=state,
            owner_id=owner_id,
            created_before=created_before,
            recovery_required=recovery_required,
        )
        total += int(
            await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
        )
        rows = (
            await db.execute(
                select(model)
                .where(*conditions)
                .order_by(model.created_at.desc().nulls_last(), model.id.asc())
                .limit(bound)
            )
        ).scalars()
        items.extend(_summary(current_kind, row) for row in rows)
    items.sort(key=lambda item: (item.created_at or datetime.min, str(item.id)), reverse=True)
    page = items[offset : offset + limit]
    return AdminOperationPage(
        items=page,
        pagination=AdminOperationPagination(
            limit=limit,
            offset=offset,
            total=total,
            has_more=offset + len(page) < total,
        ),
    )


@router.get("/{kind}/{operation_id}", response_model=AdminOperation)
async def get_operation(
    kind: OperationKind,
    operation_id: UUID,
    response: Response,
    db: Database,
    _current_user: User = Depends(require_operations_read),
):
    """Return one sanitized operation with current read-only evidence."""
    no_store_cache(response)
    row = await _load(db, kind, operation_id)
    if row is None:
        raise _not_found()
    item = _summary(kind, row)
    if not _is_active(kind, item.state):
        return item
    try:
        driver = await get_driver()
        decision = await _inspect(db, driver, kind, operation_id)
    except Exception as exc:
        logger.warning(
            "Operation detail inspection unavailable",
            extra={
                "kind": kind.value,
                "operation_id": str(operation_id),
                "error_class": type(exc).__name__,
            },
        )
        item.evidence_reason_code = "inspection_unavailable"
        item.liveness = Liveness.AMBIGUOUS.value
        item.proof_source = "none"
        item.runtime_state = RuntimeState.AMBIGUOUS.value
        return item
    if decision.reason_code == "operation_not_found":
        raise _not_found()
    _apply_decision(item, decision)
    return item


@router.post(
    "/{kind}/{operation_id}/reconcile",
    response_model=AdminOperationReconcileResult,
    responses={409: {"description": "Proof is ambiguous; no mutation was applied."}},
)
async def reconcile_operation(
    kind: OperationKind,
    operation_id: UUID,
    body: AdminOperationReconcileRequest,
    response: Response,
    db: Database,
    current_user: User = Depends(require_operations_manage),
):
    """Rerun evidence inspection and apply only a proof-backed terminal outcome."""
    no_store_cache(response)
    actor_id = str(current_user.id)
    row = await _load(db, kind, operation_id)
    if row is None:
        await _record_audit(
            db,
            actor_id=actor_id,
            kind=kind,
            operation_id=operation_id,
            reason=body.reason,
            outcome="not_found",
        )
        raise _not_found()
    previous_state = _row_state(kind, row)
    expected_fence = row.fencing_token
    base_item = _summary(kind, row)
    try:
        driver = await get_driver()
        decision = await _inspect(db, driver, kind, operation_id)
    except Exception as exc:
        logger.warning(
            "Operation reconciliation inspection unavailable",
            extra={
                "kind": kind.value,
                "operation_id": str(operation_id),
                "error_class": type(exc).__name__,
            },
        )
        await _record_audit(
            db,
            actor_id=actor_id,
            kind=kind,
            operation_id=operation_id,
            reason=body.reason,
            outcome="inspection_unavailable",
            previous_state=previous_state,
            current_state=previous_state,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "inspection_unavailable"},
        ) from None
    if decision.reason_code == "operation_not_found":
        await _record_audit(
            db,
            actor_id=actor_id,
            kind=kind,
            operation_id=operation_id,
            reason=body.reason,
            outcome="not_found",
            previous_state=previous_state,
            current_state=previous_state,
        )
        raise _not_found()

    if decision.terminal_state is TerminalState.RECOVERY_REQUIRED:
        diagnostics = _safe_diagnostics(decision)
        await _record_audit(
            db,
            actor_id=actor_id,
            kind=kind,
            operation_id=operation_id,
            reason=body.reason,
            outcome="recovery_required",
            decision=decision,
            previous_state=previous_state,
            current_state=previous_state,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "recovery_required",
                "recovery_required": True,
                "applied": False,
                "kind": kind.value,
                "id": str(operation_id),
                "state": previous_state,
                "liveness": decision.liveness.value,
                "proof_source": decision.proof_source,
                "runtime_state": decision.runtime_state.value,
                "reason_code": decision.reason_code,
                "diagnostics": diagnostics,
            },
        )

    applied = False
    if decision.terminal_state in (TerminalState.SUCCEEDED, TerminalState.FAILED):
        applied = await OperationFinalizer(db, driver).finalize(
            decision, expected_fence=expected_fence
        )

    current = await _load(db, kind, operation_id)
    if current is not None:
        current_state = _row_state(kind, current)
    elif applied and decision.terminal_state is not None:
        current_state = _applied_row_state(kind, decision.terminal_state)
    else:
        current_state = previous_state
    if not applied and current_state != previous_state:
        applied = True
    if decision.terminal_state is None:
        outcome = "terminal" if decision.reason_code == "operation_terminal" else "deferred"
    elif applied:
        outcome = "applied"
    else:
        outcome = "noop"
    result = _summary(kind, current) if current is not None else base_item
    result.state = current_state
    _apply_decision(result, decision)
    await _record_audit(
        db,
        actor_id=actor_id,
        kind=kind,
        operation_id=operation_id,
        reason=body.reason,
        outcome=outcome,
        decision=decision,
        previous_state=previous_state,
        current_state=current_state,
        applied=applied,
    )
    return AdminOperationReconcileResult(
        **result.model_dump(),
        previous_state=previous_state,
        applied=applied,
        terminal_state=(
            decision.terminal_state.value if decision.terminal_state is not None else None
        ),
    )
