# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Durable owner-private recovery with proof-gated exclusion and storage accounting."""

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.permissions import Permission
from app.core.security import has_permission
from app.core.time_utils import utc_now
from app.models.server import Server
from app.models.server_volume import ServerVolume
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_backup import VolumeBackup
from app.models.volume_operation import VolumeOperation
from app.models.volume_restore import VolumeRestore
from app.models.workspace_volume import WorkspaceVolume
from app.schemas.volume_backup import (
    BackupEligibility,
    RecoveryCapability,
    VolumeBackupPage,
    VolumeBackupResponse,
    VolumeRestorePage,
    VolumeRestoreResponse,
)
from app.services.admission_service import acquire_admission_lock
from app.services.operation_heartbeat import SessionFactory, operation_heartbeat
from app.services.operation_reconciliation import Liveness, ReconciliationService
from app.services.quota_service import QuotaService
from app.services.volume_access_service import VolumeAccessService
from app.services.volume_operation_service import (
    ACTIVE_STATES,
    VolumeOperationError,
    acquire_volume_operations,
    transition_volume_operation,
)
from app.services.worker_heartbeat import current_executor_id
from app.services.xfs_quota_service import xfs_quota_service

FORMAT = "nukelab.volume/v1"
ACTIVE = ("pending", "in_progress", "recovery_required")
logger = logging.getLogger(__name__)
MESSAGES = {
    "pending": "Waiting for the recovery worker.",
    "in_progress": "Recovery work is in progress.",
    "completed": "Recovery work completed.",
    "failed": "Recovery work failed safely.",
    "recovery_required": "The runtime outcome needs verification; conflicting work remains blocked.",
    "deleting": "Backup cleanup is in progress.",
    "delete_failed": "Backup cleanup could not finish. Retry when storage is available.",
    "deleted": "Backup removed.",
    "storage_unavailable": "Backup storage is not configured or available.",
    "helper_unavailable": "The recovery helper is unavailable.",
    "permission_revoked": "Volume write permission is required.",
    "private_volume_required": "Backups support private volumes outside workspaces only.",
    "volume_busy": "This volume is attached or has an active operation.",
    "quota_exceeded": "The recovery request exceeds available quota or reserved storage.",
    "quota_enforcement_failed": "The restored volume size limit could not be enforced.",
    "artifact_corrupt": "Backup integrity verification failed.",
    "artifact_missing": "The backup artifact is unavailable.",
    "unsupported_backup": "This backup has no supported, verified recovery artifact.",
    "backup_expired": "This backup has expired.",
    "backup_in_progress": "This backup has active recovery work.",
    "volume_not_found": "The private volume is unavailable.",
    "operation_conflict": "The recovery request conflicts with an existing request.",
    "archive_timeout": "Recovery exceeded its execution limit.",
    "archive_size_limit": "The archive exceeds its size limit.",
    "archive_member_limit": "The archive exceeds its file count limit.",
    "unsafe_archive_path": "The archive contains an unsupported path.",
    "unsupported_archive_member": "The archive contains unsupported data.",
    "helper_failed": "The recovery helper could not complete this request.",
}


class BackupError(ValueError):
    def __init__(self, code: str, status_code: int = 409):
        self.code, self.status_code = code, status_code
        super().__init__(code)


@dataclass(frozen=True)
class RecoveryPolicy:
    retention_days: int
    max_per_volume: int
    max_owner_bytes: int
    max_total_bytes: int
    max_logical_bytes: int
    max_members: int

    @classmethod
    def configured(cls):
        return cls(
            settings.volume_backup_retention_days,
            settings.volume_backup_max_per_volume,
            settings.volume_backup_max_owner_bytes,
            settings.volume_backup_max_total_bytes,
            settings.volume_backup_max_logical_bytes,
            settings.volume_backup_max_members,
        )

    def reservation(self, logical_bound):
        return 3 * (logical_bound + self.max_members * 4096 + 8 * 1024**2)


class VolumeBackupService:
    def __init__(
        self,
        db: AsyncSession,
        runtime=None,
        policy: RecoveryPolicy | None = None,
        *,
        heartbeat_session_factory: SessionFactory | None = None,
    ):
        self.db, self.runtime = db, runtime
        self.policy = policy or RecoveryPolicy.configured()
        self.heartbeat_session_factory = heartbeat_session_factory

    async def _clean(self):
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Volume recovery requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def _actor(self, owner_id, *, write=True):
        actor = await self.db.get(User, owner_id, populate_existing=True)
        permission = Permission.VOLUMES_WRITE_OWN if write else Permission.VOLUMES_READ_OWN
        if actor is None or not actor.is_active or not has_permission(actor, permission):
            raise BackupError("permission_revoked", 403)
        return actor

    async def capability(self):
        try:
            if self.runtime is None:
                raise BackupError("storage_unavailable", 503)
            await self.runtime.check_helper()
        except Exception as error:
            code = getattr(error, "code", "storage_unavailable")
            if code not in ("storage_unavailable", "helper_unavailable"):
                code = "storage_unavailable"
            return RecoveryCapability(enabled=False, reason_code=code, message=MESSAGES[code])
        return RecoveryCapability(
            enabled=True, message="Private offline volume recovery is available."
        )

    async def _enabled(self):
        capability = await self.capability()
        if not capability.enabled:
            raise BackupError(capability.reason_code, 503)

    async def _owned_volume(self, owner_id, volume_id, *, lock=False):
        statement = (
            select(Volume)
            .where(Volume.id == volume_id, Volume.owner_id == owner_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        volume = await self.db.scalar(statement)
        if volume is None:
            raise BackupError("volume_not_found", 404)
        return volume

    async def _private_offline(self, owner_id, volume):
        if (
            volume.visibility != "private"
            or await self.db.scalar(
                select(WorkspaceVolume.volume_id)
                .where(WorkspaceVolume.volume_id == volume.id)
                .limit(1)
            )
            is not None
        ):
            raise BackupError("private_volume_required", 409)
        if volume.status != "active":
            raise BackupError("volume_busy", 409)
        if not await VolumeAccessService(self.db).can_access_volume(
            str(volume.id), str(owner_id), "read_write"
        ):
            raise BackupError("permission_revoked", 403)
        mounted = select(ServerVolume.server_id).where(ServerVolume.volume_id == volume.id)
        if (
            await self.db.scalar(
                select(Server.id)
                .where(
                    or_(Server.volume_id == volume.id, Server.id.in_(mounted)),
                    Server.status.in_(["running", "healthy", "starting", "stopping"]),
                )
                .limit(1)
            )
            is not None
        ):
            raise BackupError("volume_busy", 409)

    async def eligibility(self, owner_id, volume_id):
        volume = await self._owned_volume(owner_id, volume_id)
        try:
            await self._actor(owner_id)
            await self._private_offline(owner_id, volume)
            if (
                await self.db.scalar(
                    select(VolumeOperation.operation_id)
                    .where(
                        VolumeOperation.volume_id == volume_id,
                        VolumeOperation.state.in_(ACTIVE_STATES),
                    )
                    .limit(1)
                )
                is not None
            ):
                raise BackupError("volume_busy")
            capability = await self.capability()
            if not capability.enabled:
                raise BackupError(capability.reason_code, 503)
            await self.runtime.assert_detached(volume.name)
        except Exception as error:
            code = self._error_code(error)
            return BackupEligibility(
                eligible=False,
                reason_code=code,
                message=MESSAGES.get(code, "The volume is not currently eligible for backup."),
            )
        return BackupEligibility(
            eligible=True, message="This private volume is offline and eligible for backup."
        )

    @staticmethod
    def _valid_backup(row):
        return (
            row.status == "completed"
            and row.format_version == FORMAT
            and bool(row.sha256 and re.fullmatch(r"[a-f0-9]{64}", row.sha256))
            and all(
                type(value) is int and value >= 0
                for value in (row.size_bytes, row.logical_bytes, row.member_count)
            )
        )

    def describe_backup(self, row, *, available=True):
        status = row.status if row.status in MESSAGES else "failed"
        valid = self._valid_backup(row) and (row.expires_at is None or row.expires_at > utc_now())
        reason = row.reason_code if row.reason_code in MESSAGES else None
        if row.status == "completed" and not self._valid_backup(row):
            reason = "unsupported_backup"
        return VolumeBackupResponse(
            id=row.id,
            source_volume_id=row.source_volume_id,
            source_display_name=row.source_display_name or "Private volume",
            status=status,
            reason_code=reason,
            message=MESSAGES.get(reason, MESSAGES[status]),
            description=row.description,
            created_at=row.created_at,
            completed_at=row.completed_at,
            expires_at=row.expires_at,
            compressed_bytes=row.size_bytes,
            logical_bytes=row.logical_bytes,
            member_count=row.member_count,
            can_restore=bool(available and valid),
            can_delete=bool(
                available
                and row.format_version == FORMAT
                and row.status in ("completed", "failed", "delete_failed")
            ),
        )

    @staticmethod
    def describe_restore(row):
        reason = row.reason_code if row.reason_code in MESSAGES else None
        return VolumeRestoreResponse(
            id=row.id,
            backup_id=row.backup_id,
            status=row.status,
            reason_code=reason,
            message=MESSAGES.get(reason, MESSAGES.get(row.status, "Recovery work is unavailable.")),
            destination_volume_id=row.destination_volume_id,
            destination_display_name=row.display_name,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )

    async def _backup(self, owner_id, backup_id, *, lock=False):
        statement = (
            select(VolumeBackup)
            .where(VolumeBackup.id == backup_id, VolumeBackup.user_id == owner_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        row = await self.db.scalar(statement)
        if row is None:
            raise BackupError("backup_not_found", 404)
        return row

    async def _restore(self, owner_id, restore_id):
        row = await self.db.scalar(
            select(VolumeRestore)
            .where(VolumeRestore.id == restore_id, VolumeRestore.user_id == owner_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise BackupError("restore_not_found", 404)
        return row

    async def get_backup(self, owner_id, backup_id):
        return self.describe_backup(
            await self._backup(owner_id, backup_id), available=(await self.capability()).enabled
        )

    async def get_restore(self, owner_id, restore_id):
        return self.describe_restore(await self._restore(owner_id, restore_id))

    async def list_backups(self, owner_id, *, page=1, page_size=25, volume_id=None):
        conditions = [VolumeBackup.user_id == owner_id]
        if volume_id is not None:
            conditions.append(VolumeBackup.source_volume_id == volume_id)
        total = await self.db.scalar(
            select(func.count()).select_from(VolumeBackup).where(*conditions)
        )
        rows = list(
            await self.db.scalars(
                select(VolumeBackup)
                .where(*conditions)
                .order_by(VolumeBackup.created_at.desc(), VolumeBackup.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        available = (await self.capability()).enabled
        return VolumeBackupPage(
            items=[self.describe_backup(row, available=available) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_restores(self, owner_id, *, page=1, page_size=25, backup_id=None):
        conditions = [VolumeRestore.user_id == owner_id]
        if backup_id is not None:
            conditions.append(VolumeRestore.backup_id == backup_id)
        total = await self.db.scalar(
            select(func.count()).select_from(VolumeRestore).where(*conditions)
        )
        rows = list(
            await self.db.scalars(
                select(VolumeRestore)
                .where(*conditions)
                .order_by(VolumeRestore.created_at.desc(), VolumeRestore.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return VolumeRestorePage(
            items=[self.describe_restore(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def _storage(self, owner_id, requested):
        backups = list(
            await self.db.scalars(select(VolumeBackup).where(VolumeBackup.status != "deleted"))
        )
        restores = list(await self.db.scalars(select(VolumeRestore)))
        owner_used = total_used = pending = 0
        for row in backups:
            amount = row.reserved_bytes or (row.size_bytes or 0)
            total_used += amount
            pending += row.reserved_bytes or 0
            if row.user_id == owner_id:
                owner_used += amount
        for row in restores:
            total_used += row.reserved_bytes or 0
            pending += row.reserved_bytes or 0
            if row.user_id == owner_id:
                owner_used += row.reserved_bytes or 0
        if (
            owner_used + requested > self.policy.max_owner_bytes
            or total_used + requested > self.policy.max_total_bytes
        ):
            raise BackupError("quota_exceeded", 429)
        try:
            available = self.runtime.available_bytes()
        except Exception as error:
            raise BackupError("storage_unavailable", 503) from error
        if available < pending + requested:
            raise BackupError("quota_exceeded", 429)

    async def reserve_backup(self, owner_id, volume_id, request_id=None, description=None):
        await self._enabled()
        await self._clean()
        operation_id = request_id or uuid.uuid4()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            existing = await self.db.get(VolumeBackup, operation_id, populate_existing=True)
            if existing is not None:
                if (
                    existing.user_id != owner_id
                    or (
                        existing.source_volume_id
                        or (existing.source_metadata or {}).get("source_volume_id")
                    )
                    not in (volume_id, str(volume_id))
                    or existing.description != description
                ):
                    raise BackupError("operation_conflict", 409)
                return self.describe_backup(existing)
            await self._actor(owner_id)
            volume = await self._owned_volume(owner_id, volume_id, lock=True)
            await self._private_offline(owner_id, volume)
            count = await self.db.scalar(
                select(func.count())
                .select_from(VolumeBackup)
                .where(VolumeBackup.source_volume_id == volume_id, VolumeBackup.status != "deleted")
            )
            if count >= self.policy.max_per_volume:
                raise BackupError("quota_exceeded", 429)
            logical = min(
                volume.max_size_bytes or self.policy.max_logical_bytes,
                self.policy.max_logical_bytes,
            )
            if logical <= 0:
                raise BackupError("quota_exceeded", 429)
            reservation = self.policy.reservation(logical)
            await self._storage(owner_id, reservation)
            try:
                guards = await acquire_volume_operations(
                    self.db,
                    volume_ids=[volume_id],
                    owner_id=owner_id,
                    operation_id=operation_id,
                    kind="backup",
                )
            except VolumeOperationError as error:
                raise BackupError(error.code) from error
            row = VolumeBackup(
                id=operation_id,
                volume_name=volume.name,
                source_volume_id=volume_id,
                source_display_name=volume.display_name,
                source_metadata={
                    "was_home_volume": bool((volume.labels or {}).get("was_home_volume")),
                    "source_volume_id": str(volume_id),
                },
                user_id=owner_id,
                status="in_progress",
                format_version=FORMAT,
                max_logical_bytes=logical,
                reserved_bytes=reservation,
                fencing_token=guards[0].fencing_token,
                description=description,
                expires_at=utc_now() + timedelta(days=self.policy.retention_days),
            )
            self.db.add(row)
            await self.db.flush()
            source_name, token = volume.name, row.fencing_token
        # The worker only claims pending work. No executor can start this preparing row.
        try:
            await self.runtime.assert_detached(source_name)
        except BaseException as error:
            await self._finish_backup(
                operation_id, token, error=error, terminated=True, cleaned=True
            )
            if not isinstance(error, Exception):
                raise
            raise BackupError(self._error_code(error), 409) from error
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            row = await self.db.get(
                VolumeBackup, operation_id, populate_existing=True, with_for_update=True
            )
            if row.status != "in_progress" or row.fencing_token != token:
                raise BackupError("operation_conflict")
            row.status = "pending"
        return self.describe_backup(row)

    async def reserve_restore(
        self, owner_id, backup_id, display_name, max_size_bytes, request_id=None
    ):
        await self._enabled()
        await self._clean()
        operation_id = request_id or uuid.uuid4()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            existing = await self.db.get(VolumeRestore, operation_id, populate_existing=True)
            if existing is not None:
                if (
                    existing.user_id != owner_id
                    or existing.backup_id != backup_id
                    or existing.display_name != display_name
                    or existing.max_size_bytes != max_size_bytes
                ):
                    raise BackupError("operation_conflict")
                return self.describe_restore(existing)
            await self._actor(owner_id)
            backup = await self._backup(owner_id, backup_id, lock=True)
            if not self._valid_backup(backup):
                raise BackupError("unsupported_backup")
            if backup.expires_at and backup.expires_at <= utc_now():
                raise BackupError("backup_expired")
            if max_size_bytes < backup.logical_bytes:
                raise BackupError("quota_exceeded", 429)
            quota = await QuotaService(self.db).check_volume_creation_allowed(
                str(owner_id), requested_size_bytes=max_size_bytes, commit=False
            )
            if not quota["allowed"]:
                raise BackupError("quota_exceeded", 429)
            reservation = self.policy.reservation(backup.logical_bytes)
            await self._storage(owner_id, reservation)
            volume_id = uuid.uuid4()
            volume_name = f"nukelab-restore-{volume_id}"
            volume = Volume(
                id=volume_id,
                name=volume_name,
                display_name=display_name,
                owner_id=owner_id,
                visibility="private",
                status="restoring",
                size_bytes=0,
                max_size_bytes=max_size_bytes,
                labels={
                    "restore_id": str(operation_id),
                    "was_home_volume": bool((backup.source_metadata or {}).get("was_home_volume")),
                },
            )
            self.db.add(volume)
            await self.db.flush()
            try:
                guard = (
                    await acquire_volume_operations(
                        self.db,
                        volume_ids=[volume_id],
                        owner_id=owner_id,
                        operation_id=operation_id,
                        kind="restore",
                    )
                )[0]
            except VolumeOperationError as error:
                raise BackupError(error.code) from error
            row = VolumeRestore(
                id=operation_id,
                backup_id=backup_id,
                user_id=owner_id,
                destination_volume_id=volume_id,
                destination_name=volume_name,
                display_name=display_name,
                max_size_bytes=max_size_bytes,
                reserved_bytes=reservation,
                fencing_token=guard.fencing_token,
                status="pending",
            )
            self.db.add(row)
            await self.db.flush()
        return self.describe_restore(row)

    async def _finish_backup(
        self, backup_id, token, *, metadata=None, error=None, terminated=False, cleaned=False
    ):
        await self.db.rollback()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            row = await self.db.get(
                VolumeBackup, backup_id, populate_existing=True, with_for_update=True
            )
            if row is None or row.fencing_token != token or row.status not in ACTIVE:
                raise BackupError("operation_conflict")
            if metadata is not None:
                if metadata.get("executor_terminated") is not True:
                    raise BackupError("executor_unconfirmed")
                self._check_metadata(metadata, row.max_logical_bytes)
                row.status, row.sha256, row.size_bytes, row.logical_bytes, row.member_count = (
                    "completed",
                    metadata["sha256"],
                    metadata["compressed_bytes"],
                    metadata["logical_bytes"],
                    metadata["member_count"],
                )
                row.completed_at, row.reserved_bytes = utc_now(), 0
                row.reason_code = None
                terminated = True
            else:
                row.status = "failed" if terminated else "recovery_required"
                row.reason_code = self._error_code(error)
                if terminated and cleaned:
                    row.reserved_bytes = 0
                if terminated:
                    row.completed_at = utc_now()
            if row.source_volume_id is not None:
                await transition_volume_operation(
                    self.db,
                    operation_id=row.id,
                    volume_id=row.source_volume_id,
                    fencing_token=token,
                    state="succeeded"
                    if row.status == "completed"
                    else "failed"
                    if terminated
                    else "recovery_required",
                    executor_terminated=terminated,
                )
            return self.describe_backup(row)

    @staticmethod
    def _error_code(error):
        code = getattr(error, "code", None)
        code = {
            "volume_attached": "volume_busy",
            "runtime_inspection_unavailable": "volume_busy",
            "storage_unconfigured": "storage_unavailable",
        }.get(code, code)
        return code if code in MESSAGES else "recovery_required"

    def _check_metadata(self, metadata, maximum):
        if not isinstance(metadata.get("sha256"), str) or not re.fullmatch(
            r"[a-f0-9]{64}", metadata["sha256"]
        ):
            raise BackupError("artifact_corrupt")
        for key in ("compressed_bytes", "logical_bytes", "member_count"):
            if type(metadata.get(key)) is not int or metadata[key] < 0:
                raise BackupError("artifact_corrupt")
        if (
            metadata["logical_bytes"] > maximum
            or metadata["member_count"] > self.policy.max_members
            or metadata["compressed_bytes"] > maximum + self.policy.max_members * 4096 + 8 * 1024**2
        ):
            raise BackupError("artifact_corrupt")

    async def execute_backup(self, backup_id):
        await self._clean()
        token = None
        try:
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                row = await self.db.get(
                    VolumeBackup, backup_id, populate_existing=True, with_for_update=True
                )
                if row is None:
                    raise BackupError("backup_not_found", 404)
                if row.status != "pending":
                    return self.describe_backup(row)
                token = row.fencing_token
                await self._actor(row.user_id)
                volume = await self._owned_volume(row.user_id, row.source_volume_id, lock=True)
                await self._private_offline(row.user_id, volume)
                token, name, maximum = row.fencing_token, row.volume_name, row.max_logical_bytes
                row.status = "in_progress"
                await transition_volume_operation(
                    self.db,
                    operation_id=row.id,
                    volume_id=row.source_volume_id,
                    fencing_token=token,
                    state="running",
                )
        except BackupError as error:
            if token is None:
                raise
            return await self._finish_backup(
                backup_id, token, error=error, terminated=True, cleaned=True
            )
        try:
            async with operation_heartbeat(
                self.heartbeat_session_factory,
                kind="backup",
                operation_id=backup_id,
                fencing_token=token,
                executor_id=current_executor_id(),
            ):
                await self.runtime.assert_detached(name)
                metadata = await self.runtime.capture(
                    backup_id, token, name, backup_id, max_logical_bytes=maximum
                )
            return await self._finish_backup(backup_id, token, metadata=metadata)
        except BaseException as error:
            result = await self._finish_backup(
                backup_id,
                token,
                error=error,
                terminated=getattr(error, "executor_terminated", False) is True,
                cleaned=getattr(error, "artifacts_removed", False) is True,
            )
            if not isinstance(error, Exception):
                raise
            return result

    async def execute_restore(self, restore_id):
        await self._clean()
        token = None
        try:
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                row = await self.db.get(
                    VolumeRestore, restore_id, populate_existing=True, with_for_update=True
                )
                if row is None:
                    raise BackupError("restore_not_found", 404)
                if row.status != "pending":
                    return self.describe_restore(row)
                token = row.fencing_token
                await self._actor(row.user_id)
                backup = await self._backup(row.user_id, row.backup_id, lock=True)
                if not self._valid_backup(backup):
                    raise BackupError("unsupported_backup")
                token, backup_id, name, digest, maximum, volume_id = (
                    row.fencing_token,
                    row.backup_id,
                    row.destination_name,
                    backup.sha256,
                    min(row.max_size_bytes, self.policy.max_logical_bytes),
                    row.destination_volume_id,
                )
                destination_size = row.max_size_bytes
                row.status = "in_progress"
                await transition_volume_operation(
                    self.db,
                    operation_id=row.id,
                    volume_id=volume_id,
                    fencing_token=token,
                    state="running",
                )
        except BackupError as error:
            if token is None:
                raise
            return await self._finish_restore(
                restore_id, token, error=error, terminated=True, cleaned=True
            )
        try:
            quota_error = None
            async with operation_heartbeat(
                self.heartbeat_session_factory,
                kind="restore",
                operation_id=restore_id,
                fencing_token=token,
                executor_id=current_executor_id(),
            ):
                metadata = await self.runtime.restore(
                    restore_id, token, name, backup_id, digest, max_logical_bytes=maximum
                )
                self._check_metadata(metadata, maximum)
                if metadata["sha256"] != digest or metadata.get("executor_terminated") is not True:
                    raise BackupError("artifact_corrupt")
                if settings.xfs_quota_enabled:
                    try:
                        quota_set = xfs_quota_service.set_quota(name, destination_size)
                    except Exception:
                        quota_set = False
                    if not quota_set:
                        quota_error = BackupError("quota_enforcement_failed", 503)
            if quota_error is not None:
                return await self._finish_restore(
                    restore_id,
                    token,
                    error=quota_error,
                    terminated=True,
                    cleaned=metadata.get("artifacts_removed") is True,
                )
            return await self._finish_restore(restore_id, token, metadata=metadata)
        except BaseException as error:
            result = await self._finish_restore(
                restore_id,
                token,
                error=error,
                terminated=getattr(error, "executor_terminated", False) is True,
                cleaned=getattr(error, "artifacts_removed", False) is True,
            )
            if not isinstance(error, Exception):
                raise
            return result

    async def _finish_restore(
        self, restore_id, token, *, metadata=None, error=None, terminated=False, cleaned=False
    ):
        await self.db.rollback()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            row = await self.db.get(
                VolumeRestore, restore_id, populate_existing=True, with_for_update=True
            )
            if row is None or row.fencing_token != token or row.status not in ACTIVE:
                raise BackupError("operation_conflict")
            volume = await self.db.get(
                Volume, row.destination_volume_id, populate_existing=True, with_for_update=True
            )
            # A verified completion may arrive after the destination was already
            # activated by the live executor. Completing such a row is
            # idempotent; an active destination is never changed or downgraded.
            already_active = bool(
                volume is not None
                and metadata is not None
                and volume.status == "active"
                and volume.size_bytes == metadata.get("logical_bytes")
            )
            if (
                volume is None
                or volume.name != row.destination_name
                or (volume.status != "restoring" and not already_active)
            ):
                raise BackupError("operation_conflict")
            if metadata is not None:
                row.status, row.reason_code, row.reserved_bytes, row.completed_at = (
                    "completed",
                    None,
                    0,
                    utc_now(),
                )
                if not already_active:
                    volume.status, volume.size_bytes = "active", metadata["logical_bytes"]
                terminated = True
            else:
                row.status = "failed" if terminated else "recovery_required"
                row.reason_code = self._error_code(error)
                if terminated and cleaned:
                    row.reserved_bytes = 0
                if terminated:
                    row.completed_at = utc_now()
                    volume.status = "restore_failed"
            await transition_volume_operation(
                self.db,
                operation_id=row.id,
                volume_id=row.destination_volume_id,
                fencing_token=token,
                state="succeeded"
                if row.status == "completed"
                else "failed"
                if terminated
                else "recovery_required",
                executor_terminated=terminated,
            )
            return self.describe_restore(row)

    async def request_delete(self, owner_id, backup_id):
        await self._enabled()
        await self._clean()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            await self._actor(owner_id)
            row = await self._backup(owner_id, backup_id, lock=True)
            if row.status in ("deleted", "deleting"):
                return self.describe_backup(row)
            if row.format_version != FORMAT:
                raise BackupError("unsupported_backup")
            if row.status not in ("completed", "failed", "delete_failed"):
                raise BackupError("backup_in_progress")
            if (
                await self.db.scalar(
                    select(VolumeRestore.id)
                    .where(VolumeRestore.backup_id == backup_id, VolumeRestore.status.in_(ACTIVE))
                    .limit(1)
                )
                is not None
            ):
                raise BackupError("backup_in_progress")
            row.status, row.reason_code, row.helper_identity = "deleting", None, None
        return self.describe_backup(row)

    async def execute_delete(self, backup_id):
        await self._clean()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            row = await self.db.get(
                VolumeBackup, backup_id, populate_existing=True, with_for_update=True
            )
            if row is None:
                raise BackupError("backup_not_found", 404)
            if row.status != "deleting" or (row.helper_identity or "").startswith("delete:"):
                return self.describe_backup(row)
            claim = "delete:" + str(uuid.uuid4())
            row.helper_identity = claim
            row.executor_id = current_executor_id()
            row.heartbeat_at = utc_now()
            # Retain this claim through I/O: duplicate delivery cannot race cleanup.
        try:
            await self.runtime.delete_artifact(backup_id)
        except Exception:
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                row = await self.db.get(
                    VolumeBackup, backup_id, populate_existing=True, with_for_update=True
                )
                if row.status == "deleting" and row.helper_identity == claim:
                    row.status, row.reason_code, row.helper_identity = (
                        "delete_failed",
                        "storage_unavailable",
                        None,
                    )
                    row.executor_id = None
                    row.heartbeat_at = None
            return self.describe_backup(row)
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            row = await self.db.get(
                VolumeBackup, backup_id, populate_existing=True, with_for_update=True
            )
            if row.status != "deleting" or row.helper_identity != claim:
                raise BackupError("operation_conflict")
            row.status, row.reason_code, row.reserved_bytes = "deleted", None, 0
            row.helper_identity = None
            row.executor_id = None
            row.heartbeat_at = None
            for restore in await self.db.scalars(
                select(VolumeRestore).where(VolumeRestore.backup_id == backup_id)
            ):
                restore.reserved_bytes = 0
        return self.describe_backup(row)

    async def recover_stale_deletions(self, *, limit: int = 20) -> int:
        """Resume artifact deletion only after the claimant is proven stopped.

        A crash between the durable ``delete:<uuid>`` claim and the artifact
        removal leaves the backup in ``deleting``. The dispatcher deliberately
        does not blindly retry it. This bounded maintenance path uses the
        executor registry: a live or ambiguous claimant is left alone, while a
        stopped claimant releases the claim and lets the normal deletion path
        re-inspect mounts and finish or fail safely.
        """
        if self.runtime is None or limit < 1:
            return 0
        await self._clean()
        rows = list(
            await self.db.scalars(
                select(VolumeBackup)
                .where(
                    VolumeBackup.status == "deleting",
                    VolumeBackup.helper_identity.like("delete:%"),
                )
                .order_by(VolumeBackup.created_at, VolumeBackup.id)
                .limit(limit)
            )
        )
        targets = [(row.id, row.helper_identity, row.executor_id) for row in rows]
        # The read above autobegins a transaction; each row uses its own.
        await self.db.rollback()
        recovered = 0
        for backup_id, claim, executor_id in targets:
            if executor_id is None:
                continue
            liveness = await ReconciliationService(self.db, self.runtime.driver).observe_liveness(
                "backup", backup_id
            )
            await self.db.rollback()
            if liveness is not Liveness.STOPPED:
                continue
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                current = await self.db.get(
                    VolumeBackup, backup_id, populate_existing=True, with_for_update=True
                )
                if (
                    current is None
                    or current.status != "deleting"
                    or current.helper_identity != claim
                ):
                    continue
                current.helper_identity = None
                current.executor_id = None
                current.heartbeat_at = None
            try:
                result = await self.execute_delete(backup_id)
                if result.status == "deleted":
                    recovered += 1
            except Exception:
                if self.db.in_transaction():
                    await self.db.rollback()
                logger.warning(
                    "Stale backup deletion recovery deferred",
                    extra={"backup_id": str(backup_id)},
                )
        return recovered

    async def retention_candidates(self, *, limit=100):
        return list(
            await self.db.scalars(
                select(VolumeBackup.id)
                .where(
                    VolumeBackup.expires_at <= utc_now(),
                    VolumeBackup.status.in_(["completed", "failed", "delete_failed"]),
                    VolumeBackup.format_version == FORMAT,
                    ~select(VolumeRestore.id)
                    .where(
                        VolumeRestore.backup_id == VolumeBackup.id,
                        VolumeRestore.status.in_(ACTIVE),
                    )
                    .exists(),
                )
                .order_by(VolumeBackup.expires_at, VolumeBackup.id)
                .limit(limit)
            )
        )

    async def expire_backup(self, backup_id):
        await self._clean()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            row = await self.db.get(
                VolumeBackup, backup_id, populate_existing=True, with_for_update=True
            )
            if (
                row is None
                or row.expires_at is None
                or row.expires_at > utc_now()
                or row.status not in ("completed", "failed", "delete_failed")
            ):
                return False
            if (
                await self.db.scalar(
                    select(VolumeRestore.id)
                    .where(VolumeRestore.backup_id == backup_id, VolumeRestore.status.in_(ACTIVE))
                    .limit(1)
                )
                is not None
            ):
                return False
            if row.format_version != FORMAT:
                return False
            row.status, row.reason_code, row.helper_identity = "deleting", None, None
        await self.execute_delete(backup_id)
        return True
