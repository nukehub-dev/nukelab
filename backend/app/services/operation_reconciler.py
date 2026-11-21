# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded, idempotent reconciliation over active recovery journal rows.

The scanner is a scheduling and selection boundary only: the read-only
``ReconciliationService`` decides what the evidence supports, and the
``OperationFinalizer`` applies a terminal decision under its own admission
lock and fencing check. No admission or row lock is held across runtime or
artifact inspection, and no container, helper, or artifact is mutated here.

Rows are inspected in bounded, deterministic order. Each kind contributes at
most one row per round-robin pass so that a large launch backlog cannot starve
backup or restore work. A row that is still young enough to be claimed, has a
live executor, or has no proof-backed terminal outcome is deferred.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver
from app.core.time_utils import utc_now
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.services.operation_finalizer import OperationFinalizer, VolumeFinalizationHooks
from app.services.operation_reconciliation import (
    PROOF_RUNTIME_INSPECTION,
    Liveness,
    OperationKind,
    ReconcileDecision,
    ReconciliationService,
    RecoveryArtifactInspector,
    RuntimeState,
    TerminalState,
)

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_LAUNCH_ACTIVE_STATES = ("prepared", "executing", "uncertain")
_VOLUME_ACTIVE_STATES = ("pending", "in_progress", "recovery_required")
_SUCCESSOR_ACTIONS = frozenset({"create", "start", "restart", "update"})
_PREPARED_PROOF = "prepared_unclaimed"
_PREPARED_REASON = "prepared_unclaimed"
_PREPARED_RUNTIME_PRESENT = "prepared_runtime_present"

# A pending volume row is a committed reservation window. Absence of a helper
# or artifact is not evidence that the claim will never arrive, so these
# observations keep the row claimable for the durable dispatcher.
_PENDING_VOLUME_DEFER_REASONS = frozenset(
    {
        "helper_absent",
        "helper_failed",
        "runtime_inspection_unavailable",
        "artifact_inspection_unavailable",
        "operation_identity_missing",
    }
)

_DEFERRED = "deferred"
_FINALIZED = "finalized"
_RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    """Bounded outcome summary for one reconciliation pass."""

    scanned: int = 0
    finalized: int = 0
    deferred: int = 0
    recovery_required: int = 0
    errors: int = 0
    duration_seconds: float = 0.0

    def as_dict(self) -> dict[str, int | float]:
        """Return only bounded counters and timing; never row payloads."""
        return {
            "scanned": self.scanned,
            "finalized": self.finalized,
            "deferred": self.deferred,
            "recovery_required": self.recovery_required,
            "errors": self.errors,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    kind: OperationKind
    operation_id: uuid.UUID
    state: str
    fencing_token: uuid.UUID | None
    created_at: datetime | None
    heartbeat_at: datetime | None
    executor_id: uuid.UUID | None = None
    action: str | None = None


class OperationReconciler:
    """Inspect and, only with proof, finalize active launch/backup/restore rows."""

    def __init__(
        self,
        session_factory: SessionFactory,
        driver: ContainerDriver,
        *,
        artifact_inspector: RecoveryArtifactInspector | None = None,
        volume_hooks: VolumeFinalizationHooks | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._driver = driver
        self._artifact_inspector = artifact_inspector
        self._volume_hooks = volume_hooks
        self._clock = clock

    async def scan(self, limit: int | None = None) -> ReconcileReport:
        """Run one bounded pass and never let a single row abort the batch."""
        started = time.perf_counter()
        bound = self._bound(limit)
        if bound < 1:
            return ReconcileReport(duration_seconds=round(time.perf_counter() - started, 3))

        try:
            candidates = await self._select(bound)
        except Exception as exc:
            logger.warning(
                "Operation reconciliation selection failed",
                extra={"error_class": type(exc).__name__},
            )
            return ReconcileReport(
                errors=1, duration_seconds=round(time.perf_counter() - started, 3)
            )

        now = self._clock()
        counters = {_FINALIZED: 0, _DEFERRED: 0, _RECOVERY_REQUIRED: 0, "errors": 0}
        for candidate in candidates:
            try:
                outcome = await self._reconcile(candidate, now)
            except Exception as exc:
                counters["errors"] += 1
                logger.warning(
                    "Operation reconciliation row failed",
                    extra={
                        "kind": candidate.kind.value,
                        "operation_id": str(candidate.operation_id),
                        "error_class": type(exc).__name__,
                    },
                )
                continue
            counters[outcome] += 1

        report = ReconcileReport(
            scanned=len(candidates),
            finalized=counters[_FINALIZED],
            deferred=counters[_DEFERRED],
            recovery_required=counters[_RECOVERY_REQUIRED],
            errors=counters["errors"],
            duration_seconds=round(time.perf_counter() - started, 3),
        )
        logger.info("Operation reconciliation scan complete", extra=report.as_dict())
        return report

    @staticmethod
    def _bound(limit: int | None) -> int:
        maximum = int(settings.recovery_scan_batch_size)
        if limit is None:
            return maximum
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit < 0:
            raise ValueError("limit cannot be negative")
        return min(limit, maximum)

    async def _select(self, bound: int) -> list[_Candidate]:
        async with self._session_factory() as db:
            groups = [
                await self._candidates(db, OperationKind.LAUNCH, bound),
                await self._candidates(db, OperationKind.BACKUP, bound),
                await self._candidates(db, OperationKind.RESTORE, bound),
            ]
        return _interleave(groups, bound)

    async def _candidates(
        self, db: AsyncSession, kind: OperationKind, bound: int
    ) -> list[_Candidate]:
        if kind is OperationKind.LAUNCH:
            model = ServerLaunchOperation
            state_column = model.state
            states = _LAUNCH_ACTIVE_STATES
            order = func.coalesce(model.heartbeat_at, model.created_at)
            statement = select(
                model.id,
                state_column,
                model.fencing_token,
                model.created_at,
                model.heartbeat_at,
                model.executor_id,
                model.action,
            )
        else:
            model = VolumeBackup if kind is OperationKind.BACKUP else VolumeRestore
            state_column = model.status
            states = _VOLUME_ACTIVE_STATES
            order = func.coalesce(model.heartbeat_at, model.created_at)
            statement = select(
                model.id,
                state_column,
                model.fencing_token,
                model.created_at,
                model.heartbeat_at,
                model.executor_id,
            )

        rows = (
            await db.execute(
                statement.where(state_column.in_(states))
                .order_by(order.asc(), model.id.asc())
                .limit(bound)
            )
        ).all()
        return [
            _Candidate(
                kind=kind,
                operation_id=row[0],
                state=row[1],
                fencing_token=row[2],
                created_at=row[3],
                heartbeat_at=row[4],
                executor_id=row[5],
                action=row[6] if kind is OperationKind.LAUNCH else None,
            )
            for row in rows
        ]

    async def _reconcile(self, candidate: _Candidate, now: datetime) -> str:
        row_started = time.perf_counter()
        if (
            candidate.kind is OperationKind.LAUNCH
            and candidate.state == "prepared"
            and not self._prepared_grace_elapsed(candidate, now)
        ):
            logger.debug(
                "Prepared operation is still within its claim grace",
                extra={
                    "kind": candidate.kind.value,
                    "operation_id": str(candidate.operation_id),
                },
            )
            return _DEFERRED

        decision = self._shape_prepared(candidate, await self._inspect(candidate))
        if decision.liveness is Liveness.ALIVE:
            self._warn_if_stalled(candidate, now)
        if decision.terminal_state is None:
            return _DEFERRED

        if decision.liveness is Liveness.ALIVE and decision.terminal_state is not (
            TerminalState.SUCCEEDED
        ):
            return _DEFERRED

        if self._defers_pending_volume(candidate, decision):
            return _DEFERRED

        applied = await self._finalize(decision, candidate.fencing_token)
        if decision.terminal_state is TerminalState.RECOVERY_REQUIRED:
            if applied:
                self._log_transition(candidate, decision, row_started)
            return _RECOVERY_REQUIRED

        if applied:
            self._log_transition(candidate, decision, row_started)
            return _FINALIZED
        return _DEFERRED

    async def _inspect(self, candidate: _Candidate) -> ReconcileDecision:
        """Inspect through a fresh short-lived session; no lock spans I/O."""
        async with self._session_factory() as db:
            service = ReconciliationService(
                db,
                self._driver,
                artifact_inspector=self._artifact_inspector,
                clock=self._clock,
            )
            return await service.inspect(candidate.kind, candidate.operation_id)

    async def _finalize(
        self, decision: ReconcileDecision, expected_fence: uuid.UUID | None
    ) -> bool:
        """Apply the decision through a fresh session owned by the finalizer."""
        async with self._session_factory() as db:
            finalizer = OperationFinalizer(
                db,
                self._driver,
                volume_hooks=self._volume_hooks,
            )
            return await finalizer.finalize(decision, expected_fence=expected_fence)

    def _prepared_grace_elapsed(self, candidate: _Candidate, now: datetime) -> bool:
        if candidate.created_at is None:
            return False
        return now - candidate.created_at >= timedelta(
            seconds=settings.recovery_prepared_grace_seconds
        )

    @staticmethod
    def _shape_prepared(candidate: _Candidate, decision: ReconcileDecision) -> ReconcileDecision:
        """Limit prepared rows to outcomes their durable state can support.

        A prepared row has no executor claim. An old, unclaimed successor row
        with no runtime side effect is failed with a bounded proof. A present
        runtime is never adopted for a prepared row, and a live/ambiguous
        executor is never failed.
        """
        if candidate.kind is not OperationKind.LAUNCH or candidate.state != "prepared":
            return decision
        if decision.terminal_state is TerminalState.SUCCEEDED:
            return replace(
                decision,
                terminal_state=TerminalState.RECOVERY_REQUIRED,
                reason_code=_PREPARED_RUNTIME_PRESENT,
                proof_source=PROOF_RUNTIME_INSPECTION,
            )
        if (
            decision.terminal_state is TerminalState.RECOVERY_REQUIRED
            and candidate.executor_id is None
            and candidate.action in _SUCCESSOR_ACTIONS
            and candidate.fencing_token is not None
            and decision.liveness is Liveness.AMBIGUOUS
            and decision.runtime_state is RuntimeState.ABSENT
            and decision.reason_code == "runtime_absent"
        ):
            return ReconcileDecision(
                kind=decision.kind,
                operation_id=decision.operation_id,
                liveness=Liveness.STOPPED,
                proof_source=_PREPARED_PROOF,
                runtime_state=RuntimeState.ABSENT,
                terminal_state=TerminalState.FAILED,
                reason_code=_PREPARED_REASON,
                detail={"row_state": candidate.state, "action": candidate.action or ""},
            )
        return decision

    @staticmethod
    def _defers_pending_volume(candidate: _Candidate, decision: ReconcileDecision) -> bool:
        if candidate.kind is OperationKind.LAUNCH or candidate.state != "pending":
            return False
        if decision.terminal_state is TerminalState.SUCCEEDED:
            return False
        return decision.reason_code in _PENDING_VOLUME_DEFER_REASONS

    @staticmethod
    def _warn_if_stalled(candidate: _Candidate, now: datetime) -> None:
        if candidate.heartbeat_at is None:
            return
        age_seconds = max(0.0, (now - candidate.heartbeat_at).total_seconds())
        if age_seconds < settings.recovery_stall_warning_seconds:
            return
        logger.warning(
            "Operation heartbeat is stale while its executor is alive",
            extra={
                "kind": candidate.kind.value,
                "operation_id": str(candidate.operation_id),
                "heartbeat_age_seconds": int(age_seconds),
            },
        )

    @staticmethod
    def _log_transition(
        candidate: _Candidate,
        decision: ReconcileDecision,
        row_started: float,
    ) -> None:
        logger.info(
            "Operation reconciliation applied",
            extra={
                "kind": decision.kind.value,
                "operation_id": str(decision.operation_id),
                "previous_state": candidate.state,
                "new_state": _applied_state(candidate, decision),
                "proof_source": decision.proof_source,
                "liveness": decision.liveness.value,
                "runtime_state": decision.runtime_state.value,
                "reason_code": decision.reason_code,
                "duration_ms": round((time.perf_counter() - row_started) * 1000, 1),
            },
        )


def _applied_state(candidate: _Candidate, decision: ReconcileDecision) -> str | None:
    """Map a terminal decision to the state the journal row actually takes."""
    terminal = decision.terminal_state
    if terminal is None:
        return None
    if candidate.kind is OperationKind.LAUNCH:
        if terminal is TerminalState.RECOVERY_REQUIRED:
            return "uncertain"
        return terminal.value
    if terminal is TerminalState.SUCCEEDED:
        return "completed"
    return terminal.value


def _interleave(groups: list[list[_Candidate]], limit: int) -> list[_Candidate]:
    """Round-robin one row per kind while preserving each kind's own order."""
    selected: list[_Candidate] = []
    longest = max((len(group) for group in groups), default=0)
    for index in range(longest):
        for group in groups:
            if index >= len(group):
                continue
            selected.append(group[index])
            if len(selected) == limit:
                return selected
    return selected
