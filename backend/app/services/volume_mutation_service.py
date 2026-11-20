# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Durable local-writer exclusion shared by file and volume metadata mutations."""

import uuid
from contextlib import asynccontextmanager
from functools import wraps

from fastapi import HTTPException

from app.core.permissions import Permission
from app.core.security import has_permission
from app.models.user import User
from app.models.volume import Volume
from app.services.admission_service import acquire_admission_lock
from app.services.volume_access_service import VolumeAccessService
from app.services.volume_operation_service import (
    VolumeOperationError,
    acquire_volume_operations,
    transition_volume_operation,
)


@asynccontextmanager
async def volume_writer(db, volume_id, *, actor_id=None):
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("Volume mutation requires a clean session")
    if db.in_transaction():
        await db.commit()
    operation_id = uuid.uuid4()
    identifier = uuid.UUID(str(volume_id))
    try:
        async with db.begin():
            await acquire_admission_lock(db)
            volume = await db.get(Volume, identifier, populate_existing=True, with_for_update=True)
            if volume is None:
                raise HTTPException(404, "Volume not found")
            if volume.status in ("restoring", "restore_failed", "deleting"):
                raise HTTPException(409, {"code": "volume_busy"})
            if actor_id is not None:
                actor = await db.get(User, uuid.UUID(str(actor_id)), populate_existing=True)
                if (
                    actor is None
                    or not actor.is_active
                    or not has_permission(actor, Permission.VOLUMES_WRITE_OWN)
                ):
                    raise HTTPException(403, "Volume write permission required")
                if not await VolumeAccessService(db).can_access_volume(
                    str(identifier), str(actor.id), "read_write"
                ) and not has_permission(actor, Permission.ADMIN_ACCESS):
                    raise HTTPException(403, "Volume write access required")
            guard = (
                await acquire_volume_operations(
                    db,
                    volume_ids=[identifier],
                    owner_id=volume.owner_id,
                    operation_id=operation_id,
                    kind="writer",
                )
            )[0]
            token = guard.fencing_token
    except VolumeOperationError as error:
        raise HTTPException(409, {"code": error.code}) from error
    failed = False
    try:
        yield volume
    except BaseException:
        failed = True
        await db.rollback()
        raise
    finally:
        # Local synchronous mutations have no detached executor after their handles close.
        # If DB finalization fails, the persisted guard remains protective.
        if db.in_transaction():
            await db.commit()
        async with db.begin():
            await transition_volume_operation(
                db,
                operation_id=operation_id,
                volume_id=identifier,
                fencing_token=token,
                state="failed" if failed else "succeeded",
                executor_terminated=True,
            )


def guarded_volume_metadata(method):
    @wraps(method)
    async def guarded(self, *args, **kwargs):
        # Workspace methods lead with workspace_id; volume methods lead with volume_id.
        volume_id = kwargs.get("volume_id")
        if volume_id is None:
            volume_id = (
                args[1]
                if method.__name__ in ("add_volume", "remove_volume", "update_volume_role")
                else args[0]
            )
        try:
            async with volume_writer(self.db, volume_id):
                return await method(self, *args, **kwargs)
        except HTTPException as error:
            if error.status_code == 404 and method.__name__ == "update_volume":
                return None
            raise

    return guarded
