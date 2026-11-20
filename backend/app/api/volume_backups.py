# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Owner-only offline recovery metadata and durable asynchronous requests."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_scopes
from app.container.factory import get_driver
from app.core.permissions import Permission
from app.core.security import has_permission
from app.db.session import get_db
from app.dependencies import require_permissions
from app.models.user import User
from app.schemas.volume_backup import (
    BackupCreateRequest,
    BackupEligibility,
    RecoveryCapability,
    RestoreCreateRequest,
    VolumeBackupPage,
    VolumeBackupResponse,
    VolumeRestorePage,
    VolumeRestoreResponse,
)
from app.services.volume_backup_service import BackupError, VolumeBackupService
from app.services.volume_recovery_runtime import VolumeRecoveryRuntime

logger = logging.getLogger(__name__)
router = APIRouter()
ReadActor = Annotated[User, Depends(require_permissions(Permission.VOLUMES_READ_OWN))]
WriteActor = Annotated[User, Depends(require_permissions(Permission.VOLUMES_WRITE_OWN))]
Database = Annotated[AsyncSession, Depends(get_db)]


async def recovery_service(db):
    runtime = None
    try:
        from app.config import settings

        if settings.volume_backup_storage_path and settings.volume_backup_host_path:
            runtime = VolumeRecoveryRuntime(await get_driver())
    except Exception:
        # Metadata remains available during daemon/storage outages.
        pass
    return VolumeBackupService(db, runtime)


def _error(error):
    return HTTPException(status_code=error.status_code, detail={"code": error.code})


async def _dispatch(kind, operation_id):
    try:
        from app.tasks import enqueue_volume_recovery

        enqueue_volume_recovery(kind, str(operation_id))
    except Exception:
        # Durable pending state remains discoverable by the periodic dispatcher.
        logger.warning("Recovery dispatch deferred for operation %s", operation_id)


async def _can_mutate(request, actor):
    if not has_permission(actor, Permission.VOLUMES_WRITE_OWN):
        return False
    try:
        await require_scopes("volumes:manage")(request, actor)
    except HTTPException as error:
        if error.status_code != 403:
            raise
        return False
    return True


def _private(response):
    response.headers["Cache-Control"] = "private, no-store"


def _read_only_backup(row):
    return row.model_copy(update={"can_restore": False, "can_delete": False})


@router.get(
    "/volume-backups/capabilities",
    response_model=RecoveryCapability,
    dependencies=[Depends(require_scopes("volumes:read"))],
)
async def recovery_capabilities(current_user: ReadActor, db: Database, response: Response):
    _private(response)
    return await (await recovery_service(db)).capability()


@router.get(
    "/volumes/{volume_id}/backup-eligibility",
    response_model=BackupEligibility,
    dependencies=[Depends(require_scopes("volumes:read"))],
)
async def backup_eligibility(
    volume_id: UUID, request: Request, current_user: ReadActor, db: Database, response: Response
):
    owner_id, permitted = current_user.id, await _can_mutate(request, current_user)
    _private(response)
    try:
        result = await (await recovery_service(db)).eligibility(owner_id, volume_id)
    except BackupError as error:
        raise _error(error) from error
    if result.eligible and not permitted:
        return BackupEligibility(
            eligible=False,
            reason_code="insufficient_scope",
            message="Volume management permission and scope are required.",
        )
    return result


@router.post(
    "/volumes/{volume_id}/backups",
    status_code=202,
    response_model=VolumeBackupResponse,
    dependencies=[Depends(require_scopes("volumes:manage"))],
)
async def create_backup(
    volume_id: UUID,
    body: BackupCreateRequest,
    current_user: WriteActor,
    db: Database,
    response: Response,
):
    owner_id = current_user.id
    _private(response)
    try:
        result = await (await recovery_service(db)).reserve_backup(
            owner_id, volume_id, body.request_id, body.description
        )
    except BackupError as error:
        raise _error(error) from error
    if result.status == "pending":
        await _dispatch("backup", result.id)
    return result


@router.get(
    "/volume-backups",
    response_model=VolumeBackupPage,
    dependencies=[Depends(require_scopes("volumes:read"))],
)
async def list_backups(
    request: Request,
    current_user: ReadActor,
    db: Database,
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    volume_id: UUID | None = None,
):
    owner_id, permitted = current_user.id, await _can_mutate(request, current_user)
    _private(response)
    result = await (await recovery_service(db)).list_backups(
        owner_id, page=page, page_size=page_size, volume_id=volume_id
    )
    if not permitted:
        result = result.model_copy(
            update={"items": [_read_only_backup(row) for row in result.items]}
        )
    return result


@router.get(
    "/volume-backups/{backup_id}",
    response_model=VolumeBackupResponse,
    dependencies=[Depends(require_scopes("volumes:read"))],
)
async def get_backup(
    backup_id: UUID, request: Request, current_user: ReadActor, db: Database, response: Response
):
    owner_id, permitted = current_user.id, await _can_mutate(request, current_user)
    _private(response)
    try:
        result = await (await recovery_service(db)).get_backup(owner_id, backup_id)
    except BackupError as error:
        raise _error(error) from error
    return result if permitted else _read_only_backup(result)


@router.post(
    "/volume-backups/{backup_id}/restore",
    status_code=202,
    response_model=VolumeRestoreResponse,
    dependencies=[Depends(require_scopes("volumes:manage"))],
)
async def create_restore(
    backup_id: UUID,
    body: RestoreCreateRequest,
    current_user: WriteActor,
    db: Database,
    response: Response,
):
    owner_id = current_user.id
    _private(response)
    try:
        result = await (await recovery_service(db)).reserve_restore(
            owner_id, backup_id, body.display_name, body.max_size_bytes, body.request_id
        )
    except BackupError as error:
        raise _error(error) from error
    if result.status == "pending":
        await _dispatch("restore", result.id)
    return result


@router.delete(
    "/volume-backups/{backup_id}",
    status_code=202,
    response_model=VolumeBackupResponse,
    dependencies=[Depends(require_scopes("volumes:read", "volumes:manage"))],
)
async def delete_backup(
    backup_id: UUID,
    current_user: WriteActor,
    _read_actor: ReadActor,
    db: Database,
    response: Response,
):
    owner_id = current_user.id
    _private(response)
    try:
        result = await (await recovery_service(db)).request_delete(owner_id, backup_id)
    except BackupError as error:
        raise _error(error) from error
    if result.status == "deleting":
        await _dispatch("delete", result.id)
    return result


@router.get(
    "/volume-restores",
    response_model=VolumeRestorePage,
    dependencies=[Depends(require_scopes("volumes:read"))],
)
async def list_restores(
    current_user: ReadActor,
    db: Database,
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    backup_id: UUID | None = None,
):
    owner_id = current_user.id
    _private(response)
    return await (await recovery_service(db)).list_restores(
        owner_id, page=page, page_size=page_size, backup_id=backup_id
    )


@router.get(
    "/volume-restores/{restore_id}",
    response_model=VolumeRestoreResponse,
    dependencies=[Depends(require_scopes("volumes:read"))],
)
async def get_restore(restore_id: UUID, current_user: ReadActor, db: Database, response: Response):
    owner_id = current_user.id
    _private(response)
    try:
        return await (await recovery_service(db)).get_restore(owner_id, restore_id)
    except BackupError as error:
        raise _error(error) from error
