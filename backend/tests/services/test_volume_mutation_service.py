# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Writer exclusion and deletion proof around volume recovery."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.container.driver import ContainerDriverError
from app.models.shared_workspace import SharedWorkspace
from app.models.volume import Volume
from app.models.volume_backup import VolumeBackup
from app.models.volume_operation import VolumeOperation
from app.services.user_service import UserService
from app.services.volume_mutation_service import volume_writer
from app.services.volume_operation_service import acquire_volume_operations
from app.services.volume_service import VolumeService
from app.services.workspace_service import WorkspaceService


async def volume_row(db, owner, **kwargs):
    row = Volume(
        name=f"guard-{uuid.uuid4()}", display_name="Private data", owner_id=owner.id, **kwargs
    )
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_local_writer_has_durable_guard_then_terminates(db_session, test_user, fails):
    volume = await volume_row(db_session, test_user)
    volume_id = volume.id
    try:
        async with volume_writer(db_session, volume_id):
            guard = await db_session.scalar(
                select(VolumeOperation).where(VolumeOperation.volume_id == volume_id)
            )
            assert guard.state == "reserved" and guard.kind == "writer"
            if fails:
                raise OSError("Local filesystem rejected mutation")
    except OSError:
        assert fails
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.volume_id == volume_id)
    )
    assert guard.state == ("failed" if fails else "succeeded")
    assert guard.completed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["restoring", "restore_failed", "deleting"])
async def test_unpublished_volume_rejects_writers(db_session, test_user, status):
    volume = await volume_row(db_session, test_user, status=status)
    with pytest.raises(HTTPException) as error:
        async with volume_writer(db_session, volume.id):
            pytest.fail("Protected volume admitted a writer")
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["metadata", "share", "delete", "file"])
async def test_backup_guard_excludes_every_mutation(db_session, test_user, action):
    volume = await volume_row(db_session, test_user)
    workspace = SharedWorkspace(name="Protected workspace", owner_id=test_user.id)
    db_session.add(workspace)
    await db_session.commit()
    if db_session.in_transaction():
        await db_session.commit()
    async with db_session.begin():
        await acquire_volume_operations(
            db_session,
            volume_ids=[volume.id],
            owner_id=test_user.id,
            operation_id=uuid.uuid4(),
            kind="backup",
        )
    with patch(
        "app.services.volume_service.get_container_client", new_callable=AsyncMock
    ) as runtime:
        with pytest.raises(HTTPException) as error:
            if action == "metadata":
                await VolumeService(db_session).update_volume(str(volume.id), visibility="public")
            elif action == "share":
                await WorkspaceService(db_session).add_volume(str(workspace.id), str(volume.id))
            elif action == "delete":
                await VolumeService(db_session).delete_volume(str(volume.id))
            else:
                async with volume_writer(db_session, volume.id):
                    pytest.fail("Backup admitted a local writer")
        assert error.value.status_code == 409
        runtime.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["attached", "inspect", "delete", "still_exists", "unknown_mounts"]
)
async def test_delete_retains_volume_on_missing_runtime_proof(db_session, test_user, failure):
    volume = await volume_row(db_session, test_user)
    driver = AsyncMock()
    driver.list_containers.return_value = []
    driver.get_volume.return_value = None
    if failure == "attached":
        driver.list_containers.return_value = [{"Id": "unmanaged-container", "Mounts": []}]
        driver.get_container_info.return_value = {
            "Mounts": [{"Type": "volume", "Name": volume.name}]
        }
    elif failure == "unknown_mounts":
        driver.list_containers.return_value = [{}]
    elif failure == "inspect":
        driver.list_containers.side_effect = ContainerDriverError("Unavailable")
    elif failure == "delete":
        driver.delete_volume.side_effect = ContainerDriverError("Lost response")
    else:
        driver.get_volume.return_value = {"Name": volume.name}
    with patch("app.services.volume_service.get_container_client", return_value=driver):
        with pytest.raises((HTTPException, ValueError)):
            await VolumeService(db_session).delete_volume(str(volume.id))
    current = await db_session.get(Volume, volume.id, populate_existing=True)
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.volume_id == volume.id)
    )
    uncertain = failure in ("delete", "still_exists")
    assert current.status == ("deleting" if uncertain else "active")
    assert guard.state == ("recovery_required" if uncertain else "failed")
    if not uncertain:
        driver.delete_volume.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("volume_status", ["restore_failed", "deleting"])
async def test_protected_volume_cleanup_requires_runtime_proof(
    db_session, test_user, volume_status
):
    volume = await volume_row(db_session, test_user, status=volume_status)
    driver = AsyncMock()
    driver.list_containers.return_value = []
    driver.get_volume.return_value = None
    with patch("app.services.volume_service.get_container_client", return_value=driver):
        assert await VolumeService(db_session).delete_volume(str(volume.id))
    assert await db_session.get(Volume, volume.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["volume", "backup"])
async def test_account_deletion_requires_physical_resource_cleanup(db_session, test_user, resource):
    if resource == "volume":
        await volume_row(db_session, test_user)
    else:
        db_session.add(
            VolumeBackup(user_id=test_user.id, volume_name="deleted-source", status="completed")
        )
        await db_session.commit()
    with pytest.raises(HTTPException) as error:
        await UserService(db_session).delete_user(str(test_user.id))
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "user_resources_require_cleanup"


@pytest.mark.asyncio
async def test_writer_rechecks_actor_after_request_authorization(db_session, test_user):
    volume = await volume_row(db_session, test_user)
    test_user.is_active = False
    await db_session.commit()
    with pytest.raises(HTTPException) as error:
        async with volume_writer(db_session, volume.id, actor_id=test_user.id):
            pytest.fail("Inactive actor admitted a writer")
    assert error.value.status_code == 403
