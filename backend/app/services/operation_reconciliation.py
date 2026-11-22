# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Read-only liveness and runtime/artifact evidence for recovery decisions.

The inspector never mutates a journal row, releases a reservation, deletes an
artifact, or calls a mutating driver/helper method. Callers receive a bounded
decision that names the only terminal transition the evidence can support.
Instance/container state, the process heartbeat registry, and recovery helper
labels are the authorities; Celery inspection and Redis are not consulted.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import stat
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver, ContainerDriverError
from app.core.time_utils import utc_now
from app.models.environment_revision import EnvironmentRevision
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.volume import Volume
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.models.worker_heartbeat import WorkerHeartbeat
from app.schemas.environment_manifest import ImageIdentity
from app.services.registry_client import parse_reference
from app.services.volume_recovery_runtime import VolumeRecoveryRuntime

_PROOF_SOURCE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_REASON_RE = re.compile(r"[a-z][a-z0-9_]{0,99}\Z")
_DETAIL_MAX_KEYS = 20
_DETAIL_VALUE_MAX = 160
_TRUSTED_ARTIFACT_UID = 65532

_LAUNCH_ACTIVE_STATES = frozenset({"prepared", "executing", "uncertain"})
_VOLUME_ACTIVE_STATES = frozenset({"pending", "in_progress", "recovery_required"})
_SUCCESSOR_ACTIONS = frozenset({"create", "start", "restart", "update"})
_TERMINATION_ACTIONS = frozenset({"stop", "delete"})
_LAUNCH_PROOF_ACTIONS = _SUCCESSOR_ACTIONS | _TERMINATION_ACTIONS

PROOF_LEGACY_DRAIN = "legacy_drain"
PROOF_GRACEFUL_MARKER = "graceful_marker"
PROOF_WORKER_HEARTBEAT = "worker_heartbeat"
PROOF_CONTAINER_INCARNATION = "container_incarnation"
PROOF_EXECUTOR_REPLACED = "executor_replaced"
PROOF_RUNTIME_INSPECTION = "runtime_inspection"
PROOF_LAUNCH_RUNTIME = "launch_runtime"
PROOF_RECOVERY_ARTIFACT = "recovery_artifact"
PROOF_NONE = "none"


class OperationKind(StrEnum):
    LAUNCH = "launch"
    BACKUP = "backup"
    RESTORE = "restore"


class Liveness(StrEnum):
    ALIVE = "alive"
    STOPPED = "stopped"
    AMBIGUOUS = "ambiguous"


class RuntimeState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"


class TerminalState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"


class ArtifactInspectionUnavailable(RuntimeError):
    """The read-only artifact path could not prove presence or absence."""


def _bounded_detail(values: Mapping[str, Any]) -> Mapping[str, str]:
    bounded: dict[str, str] = {}
    for key, value in values.items():
        if len(bounded) >= _DETAIL_MAX_KEYS:
            break
        text = "" if value is None else str(value)
        bounded[str(key)[:32]] = text[:_DETAIL_VALUE_MAX]
    return MappingProxyType(bounded)


@dataclass(frozen=True, slots=True)
class ReconcileDecision:
    """One bounded, read-only conclusion about an operation's evidence."""

    kind: OperationKind
    operation_id: uuid.UUID
    liveness: Liveness
    proof_source: str
    runtime_state: RuntimeState
    terminal_state: TerminalState | None
    reason_code: str
    detail: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _PROOF_SOURCE_RE.fullmatch(self.proof_source):
            raise ValueError("Invalid proof source")
        if not _REASON_RE.fullmatch(self.reason_code):
            raise ValueError("Invalid reconciliation reason code")
        object.__setattr__(self, "detail", _bounded_detail(self.detail))


@dataclass(frozen=True, slots=True)
class _LivenessObservation:
    liveness: Liveness
    proof_source: str
    detail: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _Evidence:
    runtime_state: RuntimeState
    terminal_state: TerminalState | None
    reason_code: str
    proof_source: str | None = None
    detail: Mapping[str, str] = field(default_factory=dict)


class RecoveryArtifactInspector(Protocol):
    """Read-only completion/artifact validation used by backup and restore."""

    def read_completion(
        self,
        *,
        kind: OperationKind,
        operation_id: uuid.UUID,
        backup_id: uuid.UUID,
        fencing_token: uuid.UUID,
        maximum: int,
    ) -> Mapping[str, Any] | None: ...

    def backup_archive_matches(
        self, *, backup_id: uuid.UUID, metadata: Mapping[str, Any]
    ) -> bool: ...


class _RuntimeArtifactInspector:
    """Delegate completion parsing to the recovery runtime's read-only path."""

    def __init__(self, driver: ContainerDriver) -> None:
        self._driver = driver

    def read_completion(
        self,
        *,
        kind: OperationKind,
        operation_id: uuid.UUID,
        backup_id: uuid.UUID,
        fencing_token: uuid.UUID,
        maximum: int,
    ) -> Mapping[str, Any] | None:
        runtime, storage = self._trusted_storage()
        work = storage / "backups" / str(backup_id)
        if kind is OperationKind.RESTORE:
            work = work / "operations" / str(operation_id)
        try:
            limits = runtime._limits(maximum)
        except ValueError:
            raise ArtifactInspectionUnavailable("Invalid artifact bounds") from None
        try:
            return runtime._metadata(
                work,
                str(operation_id),
                str(fencing_token),
                str(backup_id),
                "capture" if kind is OperationKind.BACKUP else "restore",
                limits,
            )
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            raise ArtifactInspectionUnavailable("Completion metadata is unreadable") from None

    def backup_archive_matches(self, *, backup_id: uuid.UUID, metadata: Mapping[str, Any]) -> bool:
        _, storage = self._trusted_storage()
        path = storage / "backups" / str(backup_id) / "archive.tar.gz"
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as archive:
                info = os.fstat(archive.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != _TRUSTED_ARTIFACT_UID
                    or info.st_size != metadata.get("compressed_bytes")
                ):
                    return False
                digest = hashlib.sha256()
                for chunk in iter(lambda: archive.read(65536), b""):
                    digest.update(chunk)
        except FileNotFoundError:
            return False
        except OSError:
            raise ArtifactInspectionUnavailable("Backup archive is unreadable") from None
        return digest.hexdigest() == metadata.get("sha256")

    def _trusted_storage(self) -> tuple[VolumeRecoveryRuntime, Path]:
        storage = settings.volume_backup_storage_path
        if not storage:
            raise ArtifactInspectionUnavailable("Recovery storage is not configured")
        runtime = VolumeRecoveryRuntime(self._driver, storage_root=storage)
        try:
            return runtime, runtime._storage()
        except Exception:
            raise ArtifactInspectionUnavailable("Recovery storage is unavailable") from None


class ReconciliationService:
    """Classify an operation as alive, stopped, or ambiguous without mutation."""

    def __init__(
        self,
        db: AsyncSession,
        driver: ContainerDriver,
        *,
        artifact_inspector: RecoveryArtifactInspector | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.driver = driver
        self._artifacts = artifact_inspector or _RuntimeArtifactInspector(driver)
        self._clock = clock

    async def inspect(
        self, kind: str | OperationKind, operation_id: uuid.UUID | str
    ) -> ReconcileDecision:
        """Return the proof-eligible outcome without changing any row."""
        operation_kind = _operation_kind(kind)
        operation_uuid = _operation_uuid(operation_id)

        with self.db.no_autoflush:
            row = await self._load(operation_kind, operation_uuid)
            if row is None:
                return ReconcileDecision(
                    kind=operation_kind,
                    operation_id=operation_uuid,
                    liveness=Liveness.AMBIGUOUS,
                    proof_source=PROOF_NONE,
                    runtime_state=RuntimeState.AMBIGUOUS,
                    terminal_state=None,
                    reason_code="operation_not_found",
                    detail={"kind": operation_kind.value},
                )

            liveness = await self._observe_liveness(row)
            if not _is_active(operation_kind, row):
                return ReconcileDecision(
                    kind=operation_kind,
                    operation_id=operation_uuid,
                    liveness=liveness.liveness,
                    proof_source=liveness.proof_source,
                    runtime_state=RuntimeState.AMBIGUOUS,
                    terminal_state=None,
                    reason_code="operation_terminal",
                    detail={**dict(liveness.detail), "row_state": _row_state(operation_kind, row)},
                )

            if operation_kind is OperationKind.LAUNCH:
                evidence = await self._launch_evidence(row, liveness)
            else:
                evidence = await self._volume_evidence(row, operation_kind, liveness)

        detail = {
            **dict(liveness.detail),
            "liveness_proof": liveness.proof_source,
            **dict(evidence.detail),
        }
        return ReconcileDecision(
            kind=operation_kind,
            operation_id=operation_uuid,
            liveness=liveness.liveness,
            proof_source=evidence.proof_source or liveness.proof_source,
            runtime_state=evidence.runtime_state,
            terminal_state=evidence.terminal_state,
            reason_code=evidence.reason_code,
            detail=detail,
        )

    async def _load(
        self, kind: OperationKind, operation_id: uuid.UUID
    ) -> ServerLaunchOperation | VolumeBackup | VolumeRestore | None:
        model = {
            OperationKind.LAUNCH: ServerLaunchOperation,
            OperationKind.BACKUP: VolumeBackup,
            OperationKind.RESTORE: VolumeRestore,
        }[kind]
        return await self.db.get(model, operation_id, populate_existing=True)

    async def _observe_liveness(
        self, row: ServerLaunchOperation | VolumeBackup | VolumeRestore
    ) -> _LivenessObservation:
        executor_id = row.executor_id
        now = self._clock()
        detail: dict[str, Any] = {
            "executor_id": executor_id,
            "operation_heartbeat_at": row.heartbeat_at,
        }
        if executor_id is None:
            if settings.recovery_legacy_drain_confirmed:
                return _LivenessObservation(
                    Liveness.STOPPED, PROOF_LEGACY_DRAIN, _bounded_detail(detail)
                )
            return _LivenessObservation(
                Liveness.AMBIGUOUS, "legacy_executor", _bounded_detail(detail)
            )

        heartbeat = await self.db.get(WorkerHeartbeat, executor_id, populate_existing=True)
        if heartbeat is None:
            return _LivenessObservation(
                Liveness.AMBIGUOUS, "worker_heartbeat_missing", _bounded_detail(detail)
            )

        detail.update(
            {
                "worker_state": heartbeat.state,
                "worker_heartbeat_at": heartbeat.heartbeat_at,
                "container_id": heartbeat.container_id,
                "container_started_at": heartbeat.container_started_at,
                "single_process_container": heartbeat.single_process_container,
            }
        )
        if heartbeat.state == "stopped":
            return _LivenessObservation(
                Liveness.STOPPED, PROOF_GRACEFUL_MARKER, _bounded_detail(detail)
            )

        if _is_fresh(heartbeat.heartbeat_at, now):
            return _LivenessObservation(
                Liveness.ALIVE, PROOF_WORKER_HEARTBEAT, _bounded_detail(detail)
            )

        if not heartbeat.container_id or not heartbeat.container_started_at:
            return _LivenessObservation(
                Liveness.AMBIGUOUS, "container_identity_missing", _bounded_detail(detail)
            )

        info, status = await self._container_info(heartbeat.container_id)
        if status == "absent":
            return _LivenessObservation(
                Liveness.STOPPED, PROOF_CONTAINER_INCARNATION, _bounded_detail(detail)
            )
        if status == "unavailable" or not isinstance(info, dict):
            return _LivenessObservation(
                Liveness.AMBIGUOUS, PROOF_RUNTIME_INSPECTION, _bounded_detail(detail)
            )

        container_id = info.get("Id")
        if not isinstance(container_id, str) or container_id != heartbeat.container_id:
            return _LivenessObservation(
                Liveness.STOPPED, PROOF_CONTAINER_INCARNATION, _bounded_detail(detail)
            )

        state = info.get("State")
        running = state.get("Running") if isinstance(state, dict) else None
        detail["container_running"] = running
        if type(running) is not bool:
            return _LivenessObservation(
                Liveness.AMBIGUOUS, PROOF_RUNTIME_INSPECTION, _bounded_detail(detail)
            )
        if running is False:
            return _LivenessObservation(
                Liveness.STOPPED, PROOF_CONTAINER_INCARNATION, _bounded_detail(detail)
            )

        started_at = state.get("StartedAt")
        detail["observed_started_at"] = started_at
        if not isinstance(started_at, str) or started_at != heartbeat.container_started_at:
            return _LivenessObservation(
                Liveness.STOPPED, PROOF_CONTAINER_INCARNATION, _bounded_detail(detail)
            )

        if not heartbeat.single_process_container:
            return _LivenessObservation(
                Liveness.AMBIGUOUS, "api_executor_ambiguous", _bounded_detail(detail)
            )

        replacement = await self._fresh_replacement_executor(heartbeat, now)
        if replacement is not None:
            detail["replacement_executor_id"] = replacement
            return _LivenessObservation(
                Liveness.STOPPED, PROOF_EXECUTOR_REPLACED, _bounded_detail(detail)
            )

        return _LivenessObservation(
            Liveness.AMBIGUOUS, "worker_heartbeat_stale", _bounded_detail(detail)
        )

    async def _fresh_replacement_executor(
        self, heartbeat: WorkerHeartbeat, now: datetime
    ) -> uuid.UUID | None:
        cutoff = now - timedelta(seconds=settings.worker_heartbeat_stale_seconds)
        statement = (
            select(WorkerHeartbeat.executor_id)
            .where(
                WorkerHeartbeat.container_id == heartbeat.container_id,
                WorkerHeartbeat.container_started_at == heartbeat.container_started_at,
                WorkerHeartbeat.executor_id != heartbeat.executor_id,
                WorkerHeartbeat.state == "running",
                WorkerHeartbeat.heartbeat_at >= cutoff,
            )
            .limit(1)
        )
        return await self.db.scalar(statement)

    async def _container_info(self, identifier: str) -> tuple[dict | None, str]:
        try:
            info = await self.driver.get_container_info(identifier)
        except ContainerDriverError as error:
            return (None, "absent") if error.status == 404 else (None, "unavailable")
        except Exception:
            return None, "unavailable"
        if info is None:
            return None, "absent"
        if not isinstance(info, dict):
            return None, "unavailable"
        return info, "present"

    async def _launch_evidence(
        self,
        operation: ServerLaunchOperation,
        liveness: _LivenessObservation,
    ) -> _Evidence:
        if operation.action not in _LAUNCH_PROOF_ACTIONS:
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "runtime_identity_unknown",
                PROOF_RUNTIME_INSPECTION,
                {"action": operation.action},
            )

        containers = await self._launch_containers(operation.id)
        if containers is None:
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "runtime_inspection_unavailable",
                PROOF_RUNTIME_INSPECTION,
            )
        if len(containers) > 1:
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "multiple_runtime_containers",
                PROOF_RUNTIME_INSPECTION,
                {"container_count": len(containers)},
            )

        if operation.action in _TERMINATION_ACTIONS:
            return await self._termination_evidence(operation, liveness, containers)

        if not containers:
            predecessor = await self._predecessor_observation(operation)
            if predecessor == "running":
                return _Evidence(
                    RuntimeState.PRESENT,
                    TerminalState.RECOVERY_REQUIRED,
                    "predecessor_running",
                    PROOF_RUNTIME_INSPECTION,
                    {"previous_container_id": operation.previous_container_id},
                )
            if predecessor == "ambiguous":
                return _Evidence(
                    RuntimeState.AMBIGUOUS,
                    TerminalState.RECOVERY_REQUIRED,
                    "predecessor_unverified",
                    PROOF_RUNTIME_INSPECTION,
                    {"previous_container_id": operation.previous_container_id},
                )
            return _missing_runtime_evidence(liveness)

        container_id = containers[0].get("Id")
        if not isinstance(container_id, str):
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "runtime_inspection_unavailable",
                PROOF_RUNTIME_INSPECTION,
            )
        info, status = await self._container_info(container_id)
        if status != "present" or not isinstance(info, dict):
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "runtime_inspection_unavailable",
                PROOF_RUNTIME_INSPECTION,
            )

        identity_reason = self._verify_launch_labels(operation, info)
        if identity_reason is not None:
            return _invalid_runtime(identity_reason)

        previous_id = operation.previous_container_id
        if previous_id and info.get("Id") == previous_id:
            return _Evidence(
                RuntimeState.PRESENT,
                TerminalState.RECOVERY_REQUIRED,
                "predecessor_running",
                PROOF_RUNTIME_INSPECTION,
            )
        predecessor = await self._predecessor_observation(
            operation, exclude_container_id=info.get("Id")
        )
        if predecessor == "running":
            return _Evidence(
                RuntimeState.PRESENT,
                TerminalState.RECOVERY_REQUIRED,
                "predecessor_running",
                PROOF_RUNTIME_INSPECTION,
                {"previous_container_id": previous_id},
            )
        if predecessor == "ambiguous":
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "predecessor_unverified",
                PROOF_RUNTIME_INSPECTION,
                {"previous_container_id": previous_id},
            )

        state = info.get("State")
        running = state.get("Running") if isinstance(state, dict) else None
        if type(running) is not bool:
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "runtime_inspection_unavailable",
                PROOF_RUNTIME_INSPECTION,
            )
        if running is False:
            return _invalid_runtime("runtime_not_running")

        image_reason = await self._verify_runtime_image(operation, info)
        if image_reason is not None:
            return _invalid_runtime(image_reason)

        generation_reason = await self._verify_generation(operation)
        if generation_reason is not None:
            return _invalid_runtime(generation_reason)

        health = state.get("Health") if isinstance(state, dict) else None
        health_status = health.get("Status") if isinstance(health, dict) else None
        if health_status != "healthy":
            return _invalid_runtime("runtime_unhealthy", {"health_status": health_status})

        return _Evidence(
            RuntimeState.PRESENT,
            TerminalState.SUCCEEDED,
            "runtime_verified",
            PROOF_LAUNCH_RUNTIME,
            {"container_id": info.get("Id"), "action": operation.action},
        )

    async def _termination_evidence(
        self,
        operation: ServerLaunchOperation,
        liveness: _LivenessObservation,
        containers: list[dict],
    ) -> _Evidence:
        if containers:
            return _Evidence(
                RuntimeState.PRESENT,
                TerminalState.RECOVERY_REQUIRED,
                "runtime_unexpected",
                PROOF_RUNTIME_INSPECTION,
                {"container_count": len(containers)},
            )
        predecessor = await self._predecessor_observation(operation)
        if predecessor == "running":
            return _Evidence(
                RuntimeState.PRESENT,
                TerminalState.RECOVERY_REQUIRED,
                "predecessor_running",
                PROOF_RUNTIME_INSPECTION,
                {"previous_container_id": operation.previous_container_id},
            )
        if predecessor == "ambiguous":
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "predecessor_unverified",
                PROOF_RUNTIME_INSPECTION,
                {"previous_container_id": operation.previous_container_id},
            )
        if liveness.liveness is Liveness.STOPPED:
            return _Evidence(
                RuntimeState.ABSENT,
                TerminalState.SUCCEEDED,
                "runtime_absent",
                liveness.proof_source,
            )
        return _missing_runtime_evidence(liveness)

    async def _launch_containers(self, operation_id: uuid.UUID) -> list[dict] | None:
        try:
            listed = await self.driver.list_containers(
                filters={"label": [f"nukelab.launch.id={operation_id}"]}, all=True
            )
        except Exception:
            return None
        if not isinstance(listed, list):
            return None
        matches: list[dict] = []
        expected = str(operation_id)
        for item in listed:
            if not isinstance(item, dict) or not isinstance(item.get("Id"), str):
                return None
            config = item.get("Config")
            labels = config.get("Labels") if isinstance(config, dict) else None
            if not isinstance(labels, dict):
                return None
            launch_id = labels.get("nukelab.launch.id")
            if launch_id is None:
                continue
            if launch_id != expected:
                continue
            matches.append(item)
        return matches

    def _verify_launch_labels(
        self, operation: ServerLaunchOperation, info: Mapping[str, Any]
    ) -> str | None:
        config = info.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if not isinstance(labels, dict):
            return "runtime_inspection_unavailable"
        if labels.get("nukelab.launch.id") != str(operation.id):
            return "runtime_launch_mismatch"
        if labels.get("nukelab.server.id") != str(operation.server_id):
            return "runtime_server_mismatch"
        return None

    async def _predecessor_observation(
        self, operation: ServerLaunchOperation, *, exclude_container_id: str | None = None
    ) -> str:
        container_id = operation.previous_container_id
        if not container_id:
            server = await self.db.get(Server, operation.server_id, populate_existing=True)
            container_id = server.container_id if server is not None else None
        if not container_id or container_id == exclude_container_id:
            return "absent"
        info, status = await self._container_info(container_id)
        if status == "absent":
            return "absent"
        if status != "present" or not isinstance(info, dict):
            return "ambiguous"
        if info.get("Id") != container_id:
            return "ambiguous"
        config = info.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if not isinstance(labels, dict):
            return "ambiguous"
        if labels.get("nukelab.server.id") != str(operation.server_id):
            return "ambiguous"
        state = info.get("State")
        running = state.get("Running") if isinstance(state, dict) else None
        if running is True:
            return "running"
        if running is False:
            return "stopped"
        return "ambiguous"

    async def _verify_runtime_image(
        self, operation: ServerLaunchOperation, info: Mapping[str, Any]
    ) -> str | None:
        if operation.revision_id is None:
            return "revision_missing"
        revision = await self.db.get(
            EnvironmentRevision, operation.revision_id, populate_existing=True
        )
        if revision is None:
            return "revision_missing"
        try:
            approved = ImageIdentity.model_validate(revision.runtime_identity)
        except ValueError:
            return "revision_invalid"

        observed_image = info.get("Image")
        if not isinstance(observed_image, str) or not observed_image:
            return "runtime_image_unresolved"
        try:
            local = await self.driver.resolve_image(observed_image)
        except Exception:
            return "runtime_image_unresolved"
        if not isinstance(local, dict):
            return "runtime_image_unresolved"
        if local.get("local_id") != approved.local_id:
            return "runtime_image_mismatch"
        if (
            not isinstance(local.get("os"), str)
            or local["os"].casefold() != approved.os.casefold()
            or not isinstance(local.get("architecture"), str)
            or local["architecture"].casefold() != approved.architecture.casefold()
        ):
            return "runtime_platform_mismatch"
        if approved.registry_verified and not _verified_digest_is_local(approved, local):
            return "runtime_image_unverified"
        return None

    async def _verify_generation(self, operation: ServerLaunchOperation) -> str | None:
        if operation.action not in _SUCCESSOR_ACTIONS:
            return None
        maximum = (
            await self.db.scalar(
                select(func.max(ServerLaunchRecord.generation)).where(
                    ServerLaunchRecord.server_id == operation.server_id
                )
            )
            or 0
        )
        generation = operation.generation
        if generation is None or generation < 1:
            return "generation_missing"
        if operation.action == "create":
            if maximum != 0 or generation != 1:
                return "generation_mismatch"
            return None
        if maximum == 0:
            return None if generation == 1 else "generation_mismatch"
        if generation != maximum + 1:
            return "generation_mismatch"
        return None

    async def _volume_evidence(
        self,
        row: VolumeBackup | VolumeRestore,
        kind: OperationKind,
        liveness: _LivenessObservation,
    ) -> _Evidence:
        if row.fencing_token is None:
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "operation_identity_missing",
                PROOF_RUNTIME_INSPECTION,
            )
        backup_id = row.id if kind is OperationKind.BACKUP else row.backup_id
        helper = await self._helper_observation(row, kind, backup_id)
        if helper == "unavailable":
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "runtime_inspection_unavailable",
                PROOF_RUNTIME_INSPECTION,
            )
        if helper == "running":
            return _Evidence(
                RuntimeState.PRESENT,
                None,
                "helper_running",
                "recovery_helper",
                {"helper": "running"},
            )
        if helper == "identity_mismatch":
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "helper_identity_mismatch",
                PROOF_RUNTIME_INSPECTION,
            )

        maximum = _artifact_maximum(row, kind)
        if maximum is None:
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "artifact_inspection_unavailable",
                PROOF_RUNTIME_INSPECTION,
            )
        try:
            metadata = await asyncio.to_thread(
                self._artifacts.read_completion,
                kind=kind,
                operation_id=row.id,
                backup_id=backup_id,
                fencing_token=row.fencing_token,
                maximum=maximum,
            )
        except ArtifactInspectionUnavailable:
            return _Evidence(
                RuntimeState.AMBIGUOUS,
                TerminalState.RECOVERY_REQUIRED,
                "artifact_inspection_unavailable",
                PROOF_RUNTIME_INSPECTION,
            )
        if metadata is None:
            reason = "helper_failed" if helper == "failed" else "helper_absent"
            return _deferred_or_required(
                liveness,
                RuntimeState.ABSENT,
                reason,
                proof_source=PROOF_RUNTIME_INSPECTION,
            )
        if helper == "failed":
            return _Evidence(
                RuntimeState.ABSENT,
                TerminalState.RECOVERY_REQUIRED,
                "helper_failed",
                PROOF_RUNTIME_INSPECTION,
            )

        if kind is OperationKind.BACKUP:
            try:
                archive_matches = await asyncio.to_thread(
                    self._artifacts.backup_archive_matches,
                    backup_id=backup_id,
                    metadata=metadata,
                )
            except ArtifactInspectionUnavailable:
                return _Evidence(
                    RuntimeState.AMBIGUOUS,
                    TerminalState.RECOVERY_REQUIRED,
                    "artifact_inspection_unavailable",
                    PROOF_RUNTIME_INSPECTION,
                )
            if not archive_matches:
                return _Evidence(
                    RuntimeState.PRESENT,
                    TerminalState.RECOVERY_REQUIRED,
                    "artifact_invalid",
                    PROOF_RUNTIME_INSPECTION,
                )
            return _Evidence(
                RuntimeState.PRESENT,
                TerminalState.SUCCEEDED,
                "artifact_verified",
                PROOF_RECOVERY_ARTIFACT,
            )

        return await self._restore_destination_evidence(row, metadata, liveness)

    async def _restore_destination_evidence(
        self,
        row: VolumeRestore,
        metadata: Mapping[str, Any],
        liveness: _LivenessObservation,
    ) -> _Evidence:
        backup = await self.db.get(VolumeBackup, row.backup_id, populate_existing=True)
        if (
            backup is None
            or not isinstance(backup.sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", backup.sha256)
        ):
            return _invalid_runtime("backup_missing")
        if metadata.get("sha256") != backup.sha256:
            return _invalid_runtime("artifact_invalid")
        volume = (
            await self.db.get(Volume, row.destination_volume_id, populate_existing=True)
            if row.destination_volume_id is not None
            else None
        )
        if volume is None:
            return _invalid_runtime("destination_missing")
        # The helper may finish immediately before the executor dies. A
        # `restoring` destination is activated by the completion hook from the
        # verified metadata; requiring `active` here would strand a completed
        # restore as recovery_required.
        if volume.status not in ("restoring", "active"):
            return _invalid_runtime(
                "destination_not_complete", {"destination_status": volume.status}
            )
        if volume.status == "active" and volume.size_bytes != metadata.get("logical_bytes"):
            return _invalid_runtime(
                "destination_size_mismatch",
                {
                    "destination_size_bytes": volume.size_bytes,
                    "artifact_logical_bytes": metadata.get("logical_bytes"),
                },
            )
        return _Evidence(
            RuntimeState.PRESENT,
            TerminalState.SUCCEEDED,
            "artifact_verified",
            PROOF_RECOVERY_ARTIFACT,
        )

    async def _helper_observation(
        self,
        row: VolumeBackup | VolumeRestore,
        kind: OperationKind,
        backup_id: uuid.UUID,
    ) -> str:
        name = f"nukelab-recovery-{row.id}"
        try:
            helper_id = await self.driver.get_container_by_name(name)
        except Exception:
            return "unavailable"
        if helper_id is None:
            return "absent"
        info, status = await self._container_info(helper_id)
        if status == "absent":
            return "absent"
        if status != "present" or not isinstance(info, dict):
            return "unavailable"
        if info.get("Id") != helper_id:
            return "unavailable"
        config = info.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if not isinstance(labels, dict):
            return "unavailable"
        expected = {
            "nukelab.recovery.operation": str(row.id),
            "nukelab.recovery.fence": str(row.fencing_token),
            "nukelab.recovery.backup": str(backup_id),
        }
        if any(labels.get(key) != value for key, value in expected.items()):
            return "identity_mismatch"
        state = info.get("State")
        running = state.get("Running") if isinstance(state, dict) else None
        if type(running) is not bool:
            return "unavailable"
        if running:
            return "running"
        exit_code = state.get("ExitCode")
        if type(exit_code) is int and exit_code != 0:
            return "failed"
        return "exited"


def _operation_kind(value: str | OperationKind) -> OperationKind:
    try:
        return OperationKind(value)
    except ValueError:
        raise ValueError("Unsupported operation kind") from None


def _operation_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid operation id") from None


def _is_active(
    kind: OperationKind, row: ServerLaunchOperation | VolumeBackup | VolumeRestore
) -> bool:
    if kind is OperationKind.LAUNCH:
        return row.state in _LAUNCH_ACTIVE_STATES
    return row.status in _VOLUME_ACTIVE_STATES


def _row_state(
    kind: OperationKind, row: ServerLaunchOperation | VolumeBackup | VolumeRestore
) -> str:
    return row.state if kind is OperationKind.LAUNCH else row.status


def _is_fresh(heartbeat_at: datetime | None, now: datetime) -> bool:
    if not isinstance(heartbeat_at, datetime):
        return False
    return now - heartbeat_at <= timedelta(seconds=settings.worker_heartbeat_stale_seconds)


def _missing_runtime_evidence(liveness: _LivenessObservation) -> _Evidence:
    if liveness.liveness is Liveness.STOPPED:
        return _Evidence(
            RuntimeState.ABSENT,
            TerminalState.FAILED,
            "runtime_absent",
            liveness.proof_source,
        )
    if liveness.liveness is Liveness.ALIVE:
        return _Evidence(
            RuntimeState.ABSENT,
            None,
            "runtime_absent",
            liveness.proof_source,
            {"executor_alive": "true"},
        )
    return _Evidence(
        RuntimeState.ABSENT,
        TerminalState.RECOVERY_REQUIRED,
        "runtime_absent",
        liveness.proof_source,
    )


def _deferred_or_required(
    liveness: _LivenessObservation,
    runtime_state: RuntimeState,
    reason_code: str,
    *,
    proof_source: str | None = None,
) -> _Evidence:
    if liveness.liveness is Liveness.STOPPED:
        return _Evidence(
            runtime_state,
            TerminalState.FAILED,
            reason_code,
            proof_source or liveness.proof_source,
        )
    if liveness.liveness is Liveness.ALIVE:
        return _Evidence(
            runtime_state,
            None,
            reason_code,
            proof_source or liveness.proof_source,
            {"executor_alive": "true"},
        )
    return _Evidence(
        runtime_state,
        TerminalState.RECOVERY_REQUIRED,
        reason_code,
        proof_source or liveness.proof_source,
    )


def _invalid_runtime(reason_code: str, detail: Mapping[str, Any] | None = None) -> _Evidence:
    return _Evidence(
        RuntimeState.PRESENT,
        TerminalState.RECOVERY_REQUIRED,
        reason_code,
        PROOF_RUNTIME_INSPECTION,
        detail or {},
    )


def _artifact_maximum(row: VolumeBackup | VolumeRestore, kind: OperationKind) -> int | None:
    maximum = row.max_logical_bytes if kind is OperationKind.BACKUP else row.max_size_bytes
    if type(maximum) is not int or maximum <= 0:
        return None
    if maximum > settings.volume_backup_max_logical_bytes:
        maximum = settings.volume_backup_max_logical_bytes
    return maximum


def _verified_digest_is_local(approved: ImageIdentity, local: Mapping[str, Any]) -> bool:
    reference = approved.verified_reference
    digest = approved.manifest_digest
    if not reference or not digest or not approved.descriptor_media_type:
        return False
    try:
        canonical = parse_reference(reference)
        if not canonical.is_digest or canonical.reference != digest:
            return False
        values = local.get("repository_digests")
        if not isinstance(values, list):
            return False
        for value in values:
            if not isinstance(value, str):
                continue
            candidate = parse_reference(value)
            if (
                candidate.is_digest
                and candidate.reference == digest
                and candidate.registry == canonical.registry
                and candidate.repository == canonical.repository
            ):
                return True
    except Exception:
        return False
    return False
