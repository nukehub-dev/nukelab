# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Apply one proof-backed recovery decision exactly once.

The read-only inspector decides which terminal outcome the evidence can
support. This module is the only mutation boundary: it re-reads the journal
row under admission and a row lock, verifies identity/fencing/active state,
and applies the decision without retrying external I/O.

Safety rules:

- terminal rows are immutable; a repeated call is a no-op;
- a live executor is never failed from runtime health alone;
- failure requires ``liveness=stopped`` and proven runtime absence;
- recovery-required decisions retain every reservation;
- no container, volume archive, or completed artifact is deleted here;
- restore completion metadata that cannot be proven stays recovery-required.

Volume success/failure still belongs to the recovery service. Supply
``volume_hooks`` backed by ``VolumeBackupService._finish_backup`` and
``VolumeBackupService._finish_restore`` (the same primitives called by
``execute_backup`` / ``execute_restore``). The hook call sites are
``finish_backup(backup_id, fencing_token, metadata=...) ->
service._finish_backup(...)`` and ``finish_restore(restore_id,
fencing_token, metadata=...) -> service._finish_restore(...)``; the hook must
re-read completion metadata itself. Hooks own their transaction and must
re-read the row with admission/``FOR UPDATE`` before mutating. The finalizer
calls them only after a proof-backed decision and never deletes an artifact or
activates a restore destination itself. Without hooks the finalizer applies
only conservative failure/recovery-required transitions.
"""

from __future__ import annotations

import copy
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver
from app.core.time_utils import utc_now
from app.models.credit_transaction import CreditTransaction
from app.models.environment_revision import EnvironmentRevision
from app.models.server import Server
from app.models.server_launch_intent import ServerLaunchIntent
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_queue import ServerQueue
from app.models.volume import Volume
from app.models.volume_backup import VolumeBackup
from app.models.volume_operation import VolumeOperation
from app.models.volume_restore import VolumeRestore
from app.schemas.environment_manifest import ImageIdentity
from app.schemas.server_launch import NormalizedLaunchRequest
from app.services.admission_service import acquire_admission_lock
from app.services.environment_revision_service import EnvironmentRevisionService
from app.services.gpu_allocator import GpuAllocatorService
from app.services.operation_reconciliation import (
    PROOF_LAUNCH_RUNTIME,
    PROOF_RECOVERY_ARTIFACT,
    Liveness,
    OperationKind,
    ReconcileDecision,
    RuntimeState,
    TerminalState,
)
from app.services.quota_service import QuotaService
from app.services.registry_client import parse_reference
from app.services.server_launch_service import (
    LaunchError,
    LaunchSuccessOutcome,
    finalize_launch_success,
)
from app.services.server_operation_service import ACTIVE_STATES as ACTIVE_LAUNCH_STATES
from app.services.server_operation_service import finish_operation
from app.services.volume_operation_service import ACTIVE_STATES as ACTIVE_VOLUME_STATES
from app.services.volume_operation_service import transition_volume_operation

logger = logging.getLogger(__name__)

_SUCCESSOR_ACTIONS = frozenset({"create", "start", "restart", "update"})
_ACTIVE_VOLUME_ROW_STATES = frozenset({"pending", "in_progress", "recovery_required"})
_TERMINATION_ACTIONS = frozenset({"stop", "delete"})
_QUEUE_REASON_MAX = 64
_VOLUME_REASON_MAX = 50


class VolumeFinalizationHooks(Protocol):
    """Volume-service callbacks for proof-backed terminal transitions.

    Implementations must own their transaction, re-read the row under
    admission and a row lock, compare ``fencing_token``, and use the existing
    ``_finish_backup`` / ``_finish_restore`` primitives. Returning ``False``
    means the transition did not apply and the row remains protected.
    """

    async def finish_backup(
        self,
        *,
        backup_id: uuid.UUID,
        fencing_token: uuid.UUID,
        decision: ReconcileDecision,
    ) -> bool: ...

    async def finish_restore(
        self,
        *,
        restore_id: uuid.UUID,
        fencing_token: uuid.UUID,
        decision: ReconcileDecision,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class _LaunchSnapshot:
    id: uuid.UUID
    server_id: uuid.UUID
    owner_id: uuid.UUID
    action: str
    state: str
    fencing_token: uuid.UUID | None
    revision_id: uuid.UUID | None
    generation: int | None
    request_payload: Mapping | None
    mounts: list[dict]
    resources: dict
    environment_slug: str | None
    username: str
    previous_container_id: str | None
    previous_status: str | None
    queue_id: uuid.UUID | None
    claim_token: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class _VolumeSnapshot:
    kind: OperationKind
    id: uuid.UUID
    status: str
    fencing_token: uuid.UUID | None
    reserved_bytes: int
    source_volume_id: uuid.UUID | None
    destination_volume_id: uuid.UUID | None
    backup_id: uuid.UUID | None


async def _allow_recovery_template(_template) -> None:
    """Recovery finalization is not a new launch authorization decision."""


def _recovery_revisions(db: AsyncSession) -> EnvironmentRevisionService:
    return EnvironmentRevisionService(db, _allow_recovery_template)


def _bounded_reason(value: str, *, maximum: int) -> str:
    if isinstance(value, str) and 0 < len(value) <= maximum:
        return value
    return "recovery_required"


def _matches_approved(approved: ImageIdentity, observed: ImageIdentity) -> bool:
    if (
        observed.local_id != approved.local_id
        or observed.os.casefold() != approved.os.casefold()
        or observed.architecture.casefold() != approved.architecture.casefold()
    ):
        return False
    if not approved.registry_verified:
        return True
    if not (approved.verified_reference and approved.manifest_digest):
        return False
    try:
        canonical = parse_reference(approved.verified_reference)
        if not canonical.is_digest or canonical.reference != approved.manifest_digest:
            return False
        for value in observed.repository_digests:
            candidate = parse_reference(value)
            if (
                candidate.is_digest
                and candidate.reference == approved.manifest_digest
                and candidate.registry == canonical.registry
                and candidate.repository == canonical.repository
            ):
                return True
    except Exception:
        return False
    return False


def _generation_matches(action: str, generation: int | None, maximum: int) -> bool:
    if generation is None or generation < 1:
        return False
    if action == "create":
        return maximum == 0 and generation == 1
    if maximum == 0:
        return generation == 1
    return generation == maximum + 1


class OperationFinalizer:
    """Apply a bounded ``ReconcileDecision`` under fenced database locks."""

    def __init__(
        self,
        db: AsyncSession,
        driver: ContainerDriver,
        *,
        volume_hooks: VolumeFinalizationHooks | None = None,
    ) -> None:
        self.db = db
        self.driver = driver
        self.volume_hooks = volume_hooks

    async def finalize(
        self,
        decision: ReconcileDecision,
        *,
        expected_fence: uuid.UUID | None = None,
    ) -> bool:
        """Apply ``decision`` once, returning whether a transition was applied.

        ``expected_fence`` is the fencing token observed with the decision. When
        supplied and the active row has moved to another token, nothing changes.
        """
        try:
            if not isinstance(decision, ReconcileDecision):
                return False
            if not isinstance(decision.operation_id, uuid.UUID):
                return False
            if decision.terminal_state is None:
                return False
            # A live executor is never failed from unhealthy/ambiguous runtime
            # evidence. Only an explicit success proof may mutate a live row.
            if (
                decision.liveness is Liveness.ALIVE
                and decision.terminal_state is not TerminalState.SUCCEEDED
            ):
                return False
            if decision.terminal_state is TerminalState.FAILED:
                if decision.liveness is not Liveness.STOPPED:
                    return False
                if decision.runtime_state is not RuntimeState.ABSENT:
                    return False
            if decision.kind is OperationKind.LAUNCH:
                return await self._finalize_launch(decision, expected_fence)
            return await self._finalize_volume(decision, expected_fence)
        except Exception:
            await self._safe_rollback()
            logger.warning(
                "Operation finalization deferred",
                extra={
                    "kind": str(getattr(decision, "kind", "unknown")),
                    "operation_id": str(getattr(decision, "operation_id", "unknown")),
                },
            )
            # A release that cannot be proven is never partially applied. Keep
            # the row protected and operator-visible instead of terminal.
            try:
                await self._degrade_to_recovery_required(decision, expected_fence)
            except Exception:
                await self._safe_rollback()
            return False

    async def _degrade_to_recovery_required(
        self, decision: ReconcileDecision, expected_fence: uuid.UUID | None
    ) -> None:
        fallback = replace(
            decision,
            terminal_state=TerminalState.RECOVERY_REQUIRED,
            reason_code="recovery_required",
        )
        if decision.kind is OperationKind.LAUNCH:
            snapshot = await self._load_launch(decision.operation_id)
            if snapshot is not None:
                await self._finalize_launch_recovery(snapshot, fallback, expected_fence)
            return
        snapshot = await self._load_volume(decision.kind, decision.operation_id)
        if snapshot is not None:
            await self._apply_volume_transition(
                snapshot,
                TerminalState.RECOVERY_REQUIRED,
                fallback,
                expected_fence,
            )

    async def _clean(self) -> None:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Operation finalization requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def _safe_rollback(self) -> None:
        try:
            await self.db.rollback()
        except Exception:
            pass

    async def _load_launch(self, operation_id: uuid.UUID) -> _LaunchSnapshot | None:
        await self._clean()
        async with self.db.begin():
            operation = await self.db.get(
                ServerLaunchOperation, operation_id, populate_existing=True
            )
            if operation is None:
                return None
            intent = await self.db.get(
                ServerLaunchIntent, operation.server_id, populate_existing=True
            )
            return _LaunchSnapshot(
                id=operation.id,
                server_id=operation.server_id,
                owner_id=operation.owner_id,
                action=operation.action,
                state=operation.state,
                fencing_token=operation.fencing_token,
                revision_id=operation.revision_id,
                generation=operation.generation,
                request_payload=copy.deepcopy(operation.request_payload),
                mounts=copy.deepcopy(operation.mounts or []),
                resources=copy.deepcopy(operation.resources or {}),
                environment_slug=operation.environment_slug,
                username=operation.username,
                previous_container_id=operation.previous_container_id,
                previous_status=operation.previous_status,
                queue_id=intent.queue_id if intent is not None else None,
                claim_token=intent.claim_token if intent is not None else None,
            )

    async def _load_volume(
        self, kind: OperationKind, operation_id: uuid.UUID
    ) -> _VolumeSnapshot | None:
        await self._clean()
        async with self.db.begin():
            if kind is OperationKind.BACKUP:
                row = await self.db.get(VolumeBackup, operation_id, populate_existing=True)
                if row is None:
                    return None
                return _VolumeSnapshot(
                    kind=kind,
                    id=row.id,
                    status=row.status,
                    fencing_token=row.fencing_token,
                    reserved_bytes=row.reserved_bytes or 0,
                    source_volume_id=row.source_volume_id,
                    destination_volume_id=None,
                    backup_id=row.id,
                )
            row = await self.db.get(VolumeRestore, operation_id, populate_existing=True)
            if row is None:
                return None
            return _VolumeSnapshot(
                kind=kind,
                id=row.id,
                status=row.status,
                fencing_token=row.fencing_token,
                reserved_bytes=row.reserved_bytes or 0,
                source_volume_id=None,
                destination_volume_id=row.destination_volume_id,
                backup_id=row.backup_id,
            )

    async def _finalize_launch(
        self, decision: ReconcileDecision, expected_fence: uuid.UUID | None
    ) -> bool:
        snapshot = await self._load_launch(decision.operation_id)
        if snapshot is None or snapshot.state not in ACTIVE_LAUNCH_STATES:
            return False
        if snapshot.fencing_token is None:
            return False
        if expected_fence is not None and snapshot.fencing_token != expected_fence:
            return False

        if decision.terminal_state is TerminalState.SUCCEEDED:
            if snapshot.action in _TERMINATION_ACTIONS:
                return await self._finalize_termination_success(snapshot, decision, expected_fence)
            return await self._finalize_launch_success(snapshot, decision, expected_fence)
        if decision.terminal_state is TerminalState.FAILED:
            if snapshot.action not in _SUCCESSOR_ACTIONS:
                return False
            return await self._finalize_launch_failure(snapshot, decision, expected_fence)
        if decision.terminal_state is TerminalState.RECOVERY_REQUIRED:
            return await self._finalize_launch_recovery(snapshot, decision, expected_fence)
        return False

    async def _launch_proof(
        self, snapshot: _LaunchSnapshot, decision: ReconcileDecision
    ) -> LaunchSuccessOutcome | None:
        if decision.runtime_state is not RuntimeState.PRESENT:
            return None
        if decision.proof_source != PROOF_LAUNCH_RUNTIME:
            return None
        if snapshot.revision_id is None or snapshot.generation is None:
            return None
        if not snapshot.request_payload or not snapshot.mounts:
            return None
        container_id = decision.detail.get("container_id")
        if not isinstance(container_id, str) or not container_id:
            return None
        try:
            request = NormalizedLaunchRequest.model_validate(
                copy.deepcopy(snapshot.request_payload)
            )
        except ValueError:
            return None

        await self._clean()
        async with self.db.begin():
            revision = await self.db.get(
                EnvironmentRevision, snapshot.revision_id, populate_existing=True
            )
            if revision is None:
                return None
            try:
                approved_runtime = ImageIdentity.model_validate(revision.runtime_identity)
                approved_toolchain = (
                    ImageIdentity.model_validate(revision.toolchain_identity)
                    if revision.toolchain_identity
                    else None
                )
            except ValueError:
                return None
            maximum = (
                await self.db.scalar(
                    select(func.max(ServerLaunchRecord.generation)).where(
                        ServerLaunchRecord.server_id == snapshot.server_id
                    )
                )
                or 0
            )
        if not _generation_matches(snapshot.action, snapshot.generation, maximum):
            return None

        try:
            info = await self.driver.get_container_info(container_id)
        except Exception:
            return None
        if not isinstance(info, dict) or info.get("Id") != container_id:
            return None
        config = info.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if not isinstance(labels, dict):
            return None
        if labels.get("nukelab.launch.id") != str(snapshot.id):
            return None
        if labels.get("nukelab.server.id") != str(snapshot.server_id):
            return None
        user_label = labels.get("nukelab.user.id")
        if user_label is not None and user_label != str(snapshot.owner_id):
            return None
        state = info.get("State")
        if not isinstance(state, dict) or state.get("Running") is not True:
            return None
        health = state.get("Health")
        health_status = health.get("Status") if isinstance(health, dict) else None
        if health_status != "healthy":
            return None
        if not await self._runtime_readiness(snapshot, request, container_id):
            return None
        observed_image = info.get("Image")
        if not isinstance(observed_image, str) or not observed_image:
            return None
        try:
            actual_runtime = ImageIdentity.model_validate(
                await self.driver.resolve_image(observed_image)
            )
        except Exception:
            return None
        if not _matches_approved(approved_runtime, actual_runtime):
            return None
        actual_toolchain = None
        if approved_toolchain is not None:
            try:
                actual_toolchain = ImageIdentity.model_validate(
                    await self.driver.resolve_image(approved_toolchain.local_id)
                )
            except Exception:
                return None
            if not _matches_approved(approved_toolchain, actual_toolchain):
                return None

        external_url = f"{settings.public_url.rstrip('/')}/user/{snapshot.username}/{request.name}"
        return LaunchSuccessOutcome(
            server_id=snapshot.server_id,
            owner_id=snapshot.owner_id,
            operation_id=snapshot.id,
            revision_id=snapshot.revision_id,
            generation=snapshot.generation,
            request=request,
            mounts=snapshot.mounts,
            environment_slug=snapshot.environment_slug or "",
            actual_runtime=actual_runtime,
            actual_toolchain=actual_toolchain,
            container_id=container_id,
            image=actual_runtime.local_id,
            external_url=external_url,
            health_status="healthy",
            resources=snapshot.resources,
            queue_id=snapshot.queue_id if snapshot.action == "create" else None,
            claim_token=snapshot.claim_token if snapshot.action == "create" else None,
            fencing_token=snapshot.fencing_token,
        )

    async def _runtime_readiness(
        self,
        snapshot: _LaunchSnapshot,
        request: NormalizedLaunchRequest,
        container_id: str,
    ) -> bool:
        """Run the same container and Traefik readiness probes as a live launch."""
        alias = f"srv-{str(snapshot.server_id)[:8]}"
        try:
            if not await self.driver.wait_for_container_ready(
                alias,
                f"http://{alias}:8080/health",
            ):
                return False
            if settings.traefik_internal_url:
                route_prefix = f"/user/{snapshot.username}/{request.name}"
                if not await self.driver.wait_for_container_ready(
                    container_id,
                    f"{settings.traefik_internal_url.rstrip('/')}{route_prefix}/health",
                    body_contains="healthy",
                ):
                    return False
        except Exception:
            return False
        return True

    async def _finalize_launch_success(
        self,
        snapshot: _LaunchSnapshot,
        decision: ReconcileDecision,
        expected_fence: uuid.UUID | None,
    ) -> bool:
        outcome = await self._launch_proof(snapshot, decision)
        if outcome is None:
            return False
        await self._clean()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            operation = await self.db.get(
                ServerLaunchOperation,
                snapshot.id,
                with_for_update=True,
                populate_existing=True,
            )
            if (
                operation is None
                or operation.state != "executing"
                or operation.fencing_token != snapshot.fencing_token
            ):
                return False
            if expected_fence is not None and operation.fencing_token != expected_fence:
                return False
            return bool(
                await finalize_launch_success(
                    self.db,
                    outcome,
                    revisions=_recovery_revisions(self.db),
                )
            )

    async def _finalize_launch_failure(
        self,
        snapshot: _LaunchSnapshot,
        decision: ReconcileDecision,
        expected_fence: uuid.UUID | None,
    ) -> bool:
        reason = _bounded_reason(decision.reason_code, maximum=_QUEUE_REASON_MAX)
        await self._clean()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            operation = await self.db.get(
                ServerLaunchOperation,
                snapshot.id,
                with_for_update=True,
                populate_existing=True,
            )
            if (
                operation is None
                or operation.state not in ACTIVE_LAUNCH_STATES
                or operation.fencing_token != snapshot.fencing_token
            ):
                return False
            if expected_fence is not None and operation.fencing_token != expected_fence:
                return False
            if decision.proof_source == "prepared_unclaimed" and (
                operation.state != "prepared" or operation.executor_id is not None
            ):
                # A late claim after the scan must win; never fail an executor
                # that acquired the row before finalization.
                return False
            server = await self.db.get(
                Server,
                snapshot.server_id,
                with_for_update=True,
                populate_existing=True,
            )
            if server is None:
                return False
            if server.status not in ("starting", "running", "error", "stopped"):
                return False
            was_active = server.status in ("starting", "running")
            server.status = "error"
            server.status_reason = reason
            server.container_id = None
            server.health_status = "unknown"
            server.expires_at = None
            if was_active:
                server.stopped_at = utc_now()
            await GpuAllocatorService(self.db).release(str(server.id), commit=False)
            await self._release_all_mounts(server.id)
            await self._fail_create_queue(operation, reason)
            finished = await finish_operation(
                self.db,
                operation.id,
                operation.fencing_token,
                "failed",
                reason_code=reason,
                executor_terminated=True,
            )
            if finished is None:
                raise LaunchError("launch_in_progress")
            await QuotaService(self.db).recalculate_usage(str(operation.owner_id), commit=False)
            return True

    async def _finalize_launch_recovery(
        self,
        snapshot: _LaunchSnapshot,
        decision: ReconcileDecision,
        expected_fence: uuid.UUID | None,
    ) -> bool:
        reason = _bounded_reason(decision.reason_code, maximum=_QUEUE_REASON_MAX)
        await self._clean()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            operation = await self.db.get(
                ServerLaunchOperation,
                snapshot.id,
                with_for_update=True,
                populate_existing=True,
            )
            if (
                operation is None
                or operation.state not in ACTIVE_LAUNCH_STATES
                or operation.fencing_token != snapshot.fencing_token
            ):
                return False
            if expected_fence is not None and operation.fencing_token != expected_fence:
                return False
            if operation.state == "uncertain":
                return False
            server = await self.db.get(
                Server,
                snapshot.server_id,
                with_for_update=True,
                populate_existing=True,
            )
            if server is not None and server.status in ("starting", "stopping"):
                server.status_reason = "recovery_required"
            if snapshot.action == "create" and snapshot.queue_id is not None:
                queue = await self.db.get(
                    ServerQueue,
                    snapshot.queue_id,
                    with_for_update=True,
                    populate_existing=True,
                )
                if (
                    queue is not None
                    and queue.status == "starting"
                    and queue.claim_token == snapshot.claim_token
                ):
                    queue.reason_code = "recovery_required"
            finished = await finish_operation(
                self.db,
                operation.id,
                operation.fencing_token,
                "uncertain",
                reason_code=reason,
            )
            if finished is None:
                raise LaunchError("launch_in_progress")
            return True

    async def _finalize_termination_success(
        self,
        snapshot: _LaunchSnapshot,
        decision: ReconcileDecision,
        expected_fence: uuid.UUID | None,
    ) -> bool:
        if decision.runtime_state is not RuntimeState.ABSENT:
            return False
        await self._clean()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            operation = await self.db.get(
                ServerLaunchOperation,
                snapshot.id,
                with_for_update=True,
                populate_existing=True,
            )
            if (
                operation is None
                or operation.state not in ACTIVE_LAUNCH_STATES
                or operation.fencing_token != snapshot.fencing_token
            ):
                return False
            if expected_fence is not None and operation.fencing_token != expected_fence:
                return False
            server = await self.db.get(
                Server,
                snapshot.server_id,
                with_for_update=True,
                populate_existing=True,
            )
            if server is None or server.status != "stopping":
                return False
            if server.container_id != operation.previous_container_id:
                return False
            server.status = "stopped"
            server.container_id = None
            server.status_reason = None
            server.expires_at = None
            if operation.previous_status != "stopped":
                server.stopped_at = utc_now()
            await GpuAllocatorService(self.db).release(str(server.id), commit=False)
            await self._release_all_mounts(server.id)
            if (
                await finish_operation(
                    self.db,
                    operation.id,
                    operation.fencing_token,
                    "succeeded",
                    runtime_verified=True,
                )
                is None
            ):
                raise LaunchError("launch_in_progress")
            if operation.action == "delete":
                await self.db.execute(
                    delete(CreditTransaction).where(CreditTransaction.server_id == server.id)
                )
                await self.db.delete(server)
                await self.db.flush()
            await QuotaService(self.db).recalculate_usage(str(operation.owner_id), commit=False)
            return True

    async def _release_all_mounts(self, server_id: uuid.UUID) -> None:
        operation_ids = set(
            (
                await self.db.scalars(
                    select(ServerLaunchOperation.id).where(
                        ServerLaunchOperation.server_id == server_id
                    )
                )
            ).all()
        ) | {server_id}
        guards = (
            await self.db.scalars(
                select(VolumeOperation)
                .where(
                    VolumeOperation.operation_id.in_(operation_ids),
                    VolumeOperation.kind == "mount",
                    VolumeOperation.state.in_(ACTIVE_VOLUME_STATES),
                )
                .order_by(VolumeOperation.volume_id, VolumeOperation.operation_id)
                .execution_options(populate_existing=True)
            )
        ).all()
        for guard in guards:
            await transition_volume_operation(
                self.db,
                operation_id=guard.operation_id,
                volume_id=guard.volume_id,
                fencing_token=guard.fencing_token,
                state="succeeded",
                executor_terminated=True,
            )

    async def _fail_create_queue(self, operation: ServerLaunchOperation, reason: str) -> None:
        if operation.action != "create":
            return
        intent = await self.db.get(ServerLaunchIntent, operation.server_id, populate_existing=True)
        if intent is None or intent.queue_id is None:
            return
        queue = await self.db.get(
            ServerQueue,
            intent.queue_id,
            with_for_update=True,
            populate_existing=True,
        )
        if (
            queue is not None
            and queue.status == "starting"
            and queue.claim_token == intent.claim_token
        ):
            queue.status = "failed"
            queue.reason_code = reason
            queue.failed_at = utc_now()

    async def _finalize_volume(
        self, decision: ReconcileDecision, expected_fence: uuid.UUID | None
    ) -> bool:
        snapshot = await self._load_volume(decision.kind, decision.operation_id)
        if snapshot is None or snapshot.status not in _ACTIVE_VOLUME_ROW_STATES:
            return False
        if snapshot.fencing_token is None:
            return False
        if expected_fence is not None and snapshot.fencing_token != expected_fence:
            return False

        effective = self._effective_volume_state(decision, snapshot)
        if effective is None:
            return False

        if self.volume_hooks is not None:
            proof = decision
            if effective is not decision.terminal_state:
                proof = replace(decision, terminal_state=effective)
            if snapshot.kind is OperationKind.BACKUP:
                applied = (
                    await self.volume_hooks.finish_backup(
                        backup_id=snapshot.id,
                        fencing_token=snapshot.fencing_token,
                        decision=proof,
                    )
                    is True
                )
            else:
                applied = (
                    await self.volume_hooks.finish_restore(
                        restore_id=snapshot.id,
                        fencing_token=snapshot.fencing_token,
                        decision=proof,
                    )
                    is True
                )
            if applied:
                return True
            if effective is not TerminalState.RECOVERY_REQUIRED:
                return False
            # A missing restore artifact must remain operator-visible even when
            # the service hook could not apply the observation itself.

        if effective is TerminalState.SUCCEEDED:
            # Without the volume service's completion primitive there is no safe
            # way to write checksum/size metadata or activate a destination.
            return False
        return await self._apply_volume_transition(snapshot, effective, decision, expected_fence)

    @staticmethod
    def _effective_volume_state(
        decision: ReconcileDecision, snapshot: _VolumeSnapshot
    ) -> TerminalState | None:
        if decision.terminal_state is TerminalState.SUCCEEDED:
            if decision.runtime_state is not RuntimeState.PRESENT:
                return None
            if decision.proof_source != PROOF_RECOVERY_ARTIFACT:
                return None
            return TerminalState.SUCCEEDED
        if decision.terminal_state is TerminalState.FAILED:
            if decision.runtime_state is not RuntimeState.ABSENT:
                return None
            # A restore helper can complete and disappear before its metadata is
            # read. The destination is never failed from a missing artifact.
            if snapshot.kind is OperationKind.RESTORE:
                return TerminalState.RECOVERY_REQUIRED
            return TerminalState.FAILED
        if decision.terminal_state is TerminalState.RECOVERY_REQUIRED:
            return TerminalState.RECOVERY_REQUIRED
        return None

    async def _apply_volume_transition(
        self,
        snapshot: _VolumeSnapshot,
        effective: TerminalState,
        decision: ReconcileDecision,
        expected_fence: uuid.UUID | None,
    ) -> bool:
        reason = _bounded_reason(decision.reason_code, maximum=_VOLUME_REASON_MAX)
        model = VolumeBackup if snapshot.kind is OperationKind.BACKUP else VolumeRestore
        await self._clean()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            row = await self.db.get(
                model,
                snapshot.id,
                with_for_update=True,
                populate_existing=True,
            )
            if (
                row is None
                or row.status not in _ACTIVE_VOLUME_ROW_STATES
                or row.fencing_token != snapshot.fencing_token
            ):
                return False
            if expected_fence is not None and row.fencing_token != expected_fence:
                return False

            if snapshot.kind is OperationKind.RESTORE:
                volume = (
                    await self.db.get(
                        Volume,
                        row.destination_volume_id,
                        with_for_update=True,
                        populate_existing=True,
                    )
                    if row.destination_volume_id is not None
                    else None
                )
                if effective is TerminalState.FAILED and volume is not None:
                    if volume.status == "active":
                        # A completed destination is never downgraded by a late
                        # missing-artifact observation.
                        effective = TerminalState.RECOVERY_REQUIRED
                    elif volume.status == "restoring":
                        volume.status = "restore_failed"

            if effective is TerminalState.RECOVERY_REQUIRED:
                if row.status == "recovery_required":
                    return False
                row.status = "recovery_required"
                row.reason_code = reason
                guard_state = "recovery_required"
                terminated = False
            else:
                row.status = "failed"
                row.reason_code = reason
                row.completed_at = utc_now()
                row.reserved_bytes = 0
                guard_state = "failed"
                terminated = True

            volume_id = (
                row.source_volume_id
                if snapshot.kind is OperationKind.BACKUP
                else row.destination_volume_id
            )
            if volume_id is not None:
                guard = await self.db.scalar(
                    select(VolumeOperation)
                    .where(
                        VolumeOperation.operation_id == row.id,
                        VolumeOperation.volume_id == volume_id,
                        VolumeOperation.state.in_(ACTIVE_VOLUME_STATES),
                    )
                    .execution_options(populate_existing=True)
                )
                if guard is not None:
                    await transition_volume_operation(
                        self.db,
                        operation_id=guard.operation_id,
                        volume_id=guard.volume_id,
                        fencing_token=guard.fencing_token,
                        state=guard_state,
                        executor_terminated=terminated,
                    )
            return True
