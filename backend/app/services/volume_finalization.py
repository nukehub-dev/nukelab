# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Proof-backed volume completion hooks for operation finalization.

The read-only reconciliation inspector decides that a backup archive or a
restore destination is complete. These hooks re-read the completion metadata
and the active journal row through fresh sessions before calling the recovery
service's existing ``_finish_backup`` / ``_finish_restore`` primitives.

Hooks never delete an artifact, attach or mount a destination volume, release
a reservation on their own, or adopt an incomplete restore. A missing or
invalid completion leaves the journal row protected and operator-visible.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver, ContainerDriverError
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.services.operation_reconciliation import (
    PROOF_RECOVERY_ARTIFACT,
    OperationKind,
    ReconcileDecision,
    RecoveryArtifactInspector,
    RuntimeState,
    TerminalState,
    _RuntimeArtifactInspector,
)
from app.services.volume_backup_service import RecoveryPolicy, VolumeBackupService

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_ACTIVE_STATES = frozenset({"pending", "in_progress", "recovery_required"})


def _proof_backed(decision: ReconcileDecision, kind: OperationKind) -> bool:
    return (
        isinstance(decision, ReconcileDecision)
        and decision.kind is kind
        and decision.terminal_state is TerminalState.SUCCEEDED
        and decision.proof_source == PROOF_RECOVERY_ARTIFACT
        and decision.runtime_state is RuntimeState.PRESENT
    )


class VolumeFinalizationHooks:
    """Completion hooks backed by the existing recovery service primitives.

    A hook creates its own short-lived sessions, re-reads completion metadata
    through the read-only artifact inspector, and confirms that the recovery
    helper is no longer running before the service primitive can publish the
    terminal result.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        driver: ContainerDriver,
        *,
        policy: RecoveryPolicy | None = None,
        artifact_inspector: RecoveryArtifactInspector | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._driver = driver
        self._policy = policy or RecoveryPolicy.configured()
        self._artifacts = artifact_inspector or _RuntimeArtifactInspector(driver)

    async def finish_backup(
        self,
        *,
        backup_id: uuid.UUID,
        fencing_token: uuid.UUID,
        decision: ReconcileDecision,
    ) -> bool:
        if not _proof_backed(decision, OperationKind.BACKUP):
            return False
        if decision.operation_id != backup_id:
            return False
        try:
            async with self._session_factory() as db:
                row = await db.get(VolumeBackup, backup_id, populate_existing=True)
                if (
                    row is None
                    or row.status not in _ACTIVE_STATES
                    or row.fencing_token != fencing_token
                ):
                    return False
                maximum = row.max_logical_bytes
            metadata = await self._completion(
                kind=OperationKind.BACKUP,
                operation_id=backup_id,
                backup_id=backup_id,
                fencing_token=fencing_token,
                maximum=maximum,
            )
            if metadata is None:
                return False
            if not await self._executor_terminated(
                operation_id=backup_id,
                backup_id=backup_id,
                fencing_token=fencing_token,
            ):
                return False
            if not await self._archive_matches(backup_id, metadata):
                return False
            metadata["executor_terminated"] = True
            async with self._session_factory() as db:
                service = VolumeBackupService(db, policy=self._policy)
                result = await service._finish_backup(backup_id, fencing_token, metadata=metadata)
            return result.status == "completed"
        except Exception:
            return False

    async def finish_restore(
        self,
        *,
        restore_id: uuid.UUID,
        fencing_token: uuid.UUID,
        decision: ReconcileDecision,
    ) -> bool:
        if not _proof_backed(decision, OperationKind.RESTORE):
            return False
        if decision.operation_id != restore_id:
            return False
        try:
            async with self._session_factory() as db:
                row = await db.get(VolumeRestore, restore_id, populate_existing=True)
                if (
                    row is None
                    or row.status not in _ACTIVE_STATES
                    or row.fencing_token != fencing_token
                    or row.destination_volume_id is None
                ):
                    return False
                backup = await db.get(VolumeBackup, row.backup_id, populate_existing=True)
                if (
                    backup is None
                    or not isinstance(backup.sha256, str)
                    or not _SHA256.fullmatch(backup.sha256)
                ):
                    return False
                backup_id, backup_digest = row.backup_id, backup.sha256
                maximum = row.max_size_bytes
            if type(maximum) is not int or maximum <= 0:
                return False
            maximum = min(maximum, settings.volume_backup_max_logical_bytes)
            maximum = min(maximum, self._policy.max_logical_bytes)
            metadata = await self._completion(
                kind=OperationKind.RESTORE,
                operation_id=restore_id,
                backup_id=backup_id,
                fencing_token=fencing_token,
                maximum=maximum,
            )
            if metadata is None or metadata["sha256"] != backup_digest:
                return False
            if not await self._executor_terminated(
                operation_id=restore_id,
                backup_id=backup_id,
                fencing_token=fencing_token,
            ):
                return False
            metadata["executor_terminated"] = True
            async with self._session_factory() as db:
                service = VolumeBackupService(db, policy=self._policy)
                result = await service._finish_restore(restore_id, fencing_token, metadata=metadata)
            return result.status == "completed"
        except Exception:
            return False

    async def _completion(
        self,
        *,
        kind: OperationKind,
        operation_id: uuid.UUID,
        backup_id: uuid.UUID,
        fencing_token: uuid.UUID,
        maximum: int,
    ) -> dict | None:
        if type(maximum) is not int or maximum <= 0:
            return None
        try:
            metadata = await asyncio.to_thread(
                self._artifacts.read_completion,
                kind=kind,
                operation_id=operation_id,
                backup_id=backup_id,
                fencing_token=fencing_token,
                maximum=maximum,
            )
        except Exception:
            return None
        if not self._valid_metadata(metadata, maximum=maximum):
            return None
        return dict(metadata)

    def _valid_metadata(self, metadata: Mapping | None, *, maximum: int) -> bool:
        if not isinstance(metadata, Mapping):
            return False
        if not isinstance(metadata.get("sha256"), str) or not _SHA256.fullmatch(metadata["sha256"]):
            return False
        for key in ("compressed_bytes", "logical_bytes", "member_count"):
            if type(metadata.get(key)) is not int or metadata[key] < 0:
                return False
        return (
            metadata["logical_bytes"] <= maximum
            and metadata["member_count"] <= self._policy.max_members
            and metadata["compressed_bytes"]
            <= maximum + self._policy.max_members * 4096 + 8 * 1024**2
        )

    async def _archive_matches(self, backup_id: uuid.UUID, metadata: Mapping) -> bool:
        try:
            return bool(
                await asyncio.to_thread(
                    self._artifacts.backup_archive_matches,
                    backup_id=backup_id,
                    metadata=metadata,
                )
            )
        except Exception:
            return False

    async def _executor_terminated(
        self,
        *,
        operation_id: uuid.UUID,
        backup_id: uuid.UUID,
        fencing_token: uuid.UUID,
    ) -> bool:
        """Confirm no matching recovery helper is still running.

        The live executor deletes the helper before finalization, so a missing
        helper is the expected end state once a valid completion artifact has
        been read. An existing helper must carry the exact operation/fence/
        backup labels and must be exited or dead.
        """
        name = f"nukelab-recovery-{operation_id}"
        try:
            identity = await self._driver.get_container_by_name(name)
        except Exception:
            return False
        if identity is None:
            return True
        if not isinstance(identity, str):
            return False
        try:
            info = await self._driver.get_container_info(identity)
        except ContainerDriverError as error:
            return error.status == 404
        except Exception:
            return False
        if not isinstance(info, dict) or info.get("Id") != identity:
            return False
        config = info.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if not isinstance(labels, dict):
            return False
        expected = {
            "nukelab.recovery.operation": str(operation_id),
            "nukelab.recovery.fence": str(fencing_token),
            "nukelab.recovery.backup": str(backup_id),
        }
        if any(labels.get(key) != value for key, value in expected.items()):
            return False
        state = info.get("State")
        if not isinstance(state, dict) or state.get("Running") is not False:
            return False
        return state.get("Status") in ("exited", "dead")
