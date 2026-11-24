# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Protected restore output and backup inputs never reach file mutation paths."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.container.driver import ContainerDriverError
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.services.volume_operation_service import acquire_volume_operations
from app.services.volume_service import VolumeService


@pytest.mark.asyncio
@pytest.mark.parametrize("volume_status", ["restoring", "restore_failed", "deleting"])
@pytest.mark.parametrize("action", ["files", "download", "delete", "update"])
async def test_restore_output_inaccessible_before_verified_publication(
    client, db_session, test_user, user_token, tmp_path, volume_status, action
):
    volume = Volume(
        name=f"unpublished-{uuid.uuid4()}",
        display_name="Unpublished data",
        owner_id=test_user.id,
        status=volume_status,
    )
    db_session.add(volume)
    await db_session.commit()
    data = tmp_path / volume.name / "_data"
    data.mkdir(parents=True)
    (data / "file.txt").write_text("partial output")
    headers = {"Authorization": f"Bearer {user_token}"}
    with patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
        path = f"/api/volumes/{volume.id}"
        if action == "update":
            response = await client.put(path, json={"status": "active"}, headers=headers)
        elif action == "delete":
            response = await client.delete(
                path + "/files", params={"path": "file.txt"}, headers=headers
            )
        else:
            response = await client.get(
                path + "/" + action, params={"path": "file.txt"}, headers=headers
            )
    assert response.status_code == 409
    assert (data / "file.txt").read_text() == "partial output"


@pytest.mark.asyncio
async def test_file_delete_cannot_cross_active_backup_guard(
    client, db_session, test_user, user_token, tmp_path
):
    volume = Volume(
        name=f"backup-{uuid.uuid4()}", display_name="Backup input", owner_id=test_user.id
    )
    db_session.add(volume)
    await db_session.commit()
    async with db_session.begin():
        await acquire_volume_operations(
            db_session,
            volume_ids=[volume.id],
            owner_id=test_user.id,
            operation_id=uuid.uuid4(),
            kind="backup",
        )
    data = tmp_path / volume.name / "_data"
    data.mkdir(parents=True)
    (data / "file.txt").write_text("preserve input")
    with patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
        response = await client.delete(
            f"/api/volumes/{volume.id}/files",
            params={"path": "file.txt"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    assert response.status_code == 409
    assert (data / "file.txt").read_text() == "preserve input"


@pytest.mark.asyncio
async def test_file_delete_rechecks_revoked_access_inside_writer_guard(
    client, db_session, test_user, user_token, tmp_path
):
    volume = Volume(
        name=f"revoked-{uuid.uuid4()}", display_name="Revoked input", owner_id=test_user.id
    )
    db_session.add(volume)
    await db_session.commit()
    volume_id = volume.id
    data = tmp_path / volume.name / "_data"
    data.mkdir(parents=True)
    (data / "file.txt").write_text("preserve input")
    # The first check models request-time authorization. Admission must repeat it
    # because sharing or membership can have changed while the request waited.
    access = AsyncMock(side_effect=[True, False])
    with (
        patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)),
        patch("app.services.volume_access_service.VolumeAccessService.can_access_volume", access),
    ):
        response = await client.delete(
            f"/api/volumes/{volume_id}/files",
            params={"path": "file.txt"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    assert response.status_code == 403
    assert access.await_count == 2
    assert (data / "file.txt").read_text() == "preserve input"
    assert (
        await db_session.scalar(
            select(VolumeOperation).where(VolumeOperation.volume_id == volume_id)
        )
        is None
    )


@pytest.mark.asyncio
async def test_bulk_account_delete_cannot_orphan_owned_volume(
    client, db_session, test_user, admin_token
):
    from app.models.user import User

    owner_id = test_user.id
    volume = Volume(
        name=f"account-cleanup-{uuid.uuid4()}", display_name="Retained data", owner_id=owner_id
    )
    db_session.add(volume)
    await db_session.commit()
    response = await client.post(
        "/api/admin/users/bulk-action",
        json={"action": "delete", "user_ids": [str(owner_id)]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["results"]["success"] == []
    failed = response.json()["results"]["failed"]
    assert failed[0]["user_id"] == str(owner_id)
    assert "user_resources_require_cleanup" in failed[0]["error"]
    assert await db_session.get(User, owner_id) is not None
    assert await db_session.get(Volume, volume.id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["same", "ancestor", "descendant"])
async def test_volume_delete_blocks_unmanaged_bind_aliases(db_session, test_user, alias):
    from app.services.volume_service import VolumeService

    volume = Volume(
        name=f"bound-data-{uuid.uuid4()}", display_name="Bound data", owner_id=test_user.id
    )
    db_session.add(volume)
    await db_session.commit()
    mountpoint = f"/var/lib/docker/volumes/{volume.name}/_data"
    source = {
        "same": mountpoint,
        "ancestor": "/var/lib/docker/volumes",
        "descendant": mountpoint + "/nested",
    }[alias]
    driver = AsyncMock()
    driver.get_volume.return_value = {"Name": volume.name, "Mountpoint": mountpoint}
    # Cached listing claims no mounts. Only the required fresh inspection exposes
    # this stopped, unmanaged container's bind into the named volume's data.
    driver.list_containers.return_value = [{"Id": "operator-container", "Mounts": []}]
    driver.get_container_info.return_value = {
        "State": {"Running": False},
        "Mounts": [{"Type": "bind", "Source": source}],
    }
    with patch("app.services.volume_service.get_container_client", return_value=driver):
        with pytest.raises(ValueError, match="volume_attached"):
            await VolumeService(db_session).delete_volume(str(volume.id))
    driver.list_containers.assert_awaited_once_with(all=True)
    driver.get_container_info.assert_awaited_once_with("operator-container")
    driver.delete_volume.assert_not_awaited()
    assert (await db_session.get(Volume, volume.id, populate_existing=True)).status == "active"
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.volume_id == volume.id)
    )
    assert guard.state == "failed"


def _volume_delete_driver(volume_name, inspection):
    driver = AsyncMock()
    driver.get_volume.side_effect = inspection
    driver.list_containers.return_value = []
    driver.delete_volume = AsyncMock()
    return driver


@pytest.mark.asyncio
async def test_delete_retains_guard_and_metadata_when_daemon_delete_fails(db_session, test_user):
    from fastapi import HTTPException

    from app.services.xfs_quota_service import xfs_quota_service

    volume = Volume(
        name=f"delete-failure-{uuid.uuid4()}", display_name="Delete failure", owner_id=test_user.id
    )
    db_session.add(volume)
    await db_session.commit()
    mountpoint = f"/var/lib/docker/volumes/{volume.name}/_data"
    driver = _volume_delete_driver(volume.name, [{"Name": volume.name, "Mountpoint": mountpoint}])
    driver.delete_volume.side_effect = ContainerDriverError("daemon unavailable", status=500)
    with (
        patch("app.services.volume_service.get_container_client", return_value=driver),
        patch.object(xfs_quota_service, "remove_quota") as remove_quota,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await VolumeService(db_session).delete_volume(str(volume.id))
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {"code": "volume_recovery_required"}
    current = await db_session.get(Volume, volume.id, populate_existing=True)
    assert current is not None and current.status == "deleting"
    guard = await db_session.scalar(
        select(VolumeOperation)
        .where(VolumeOperation.volume_id == volume.id)
        .execution_options(populate_existing=True)
    )
    assert guard is not None and guard.state == "recovery_required"
    driver.delete_volume.assert_awaited_once_with(volume.name)
    remove_quota.assert_not_called()


@pytest.mark.asyncio
async def test_delete_retains_guard_when_post_delete_inspection_errors(db_session, test_user):
    from fastapi import HTTPException

    from app.services.xfs_quota_service import xfs_quota_service

    volume = Volume(
        name=f"inspect-failure-{uuid.uuid4()}",
        display_name="Inspect failure",
        owner_id=test_user.id,
    )
    db_session.add(volume)
    await db_session.commit()
    mountpoint = f"/var/lib/docker/volumes/{volume.name}/_data"
    driver = _volume_delete_driver(
        volume.name,
        [
            {"Name": volume.name, "Mountpoint": mountpoint},
            ContainerDriverError("daemon unavailable", status=500),
        ],
    )
    with (
        patch("app.services.volume_service.get_container_client", return_value=driver),
        patch.object(xfs_quota_service, "remove_quota") as remove_quota,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await VolumeService(db_session).delete_volume(str(volume.id))
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {"code": "volume_recovery_required"}
    current = await db_session.get(Volume, volume.id, populate_existing=True)
    assert current is not None and current.status == "deleting"
    guard = await db_session.scalar(
        select(VolumeOperation)
        .where(VolumeOperation.volume_id == volume.id)
        .execution_options(populate_existing=True)
    )
    assert guard is not None and guard.state == "recovery_required"
    assert driver.get_volume.await_count == 2
    remove_quota.assert_not_called()


@pytest.mark.asyncio
async def test_delete_retains_guard_when_post_delete_inspection_still_finds_volume(
    db_session, test_user
):
    from fastapi import HTTPException

    volume = Volume(
        name=f"still-present-{uuid.uuid4()}", display_name="Still present", owner_id=test_user.id
    )
    db_session.add(volume)
    await db_session.commit()
    mountpoint = f"/var/lib/docker/volumes/{volume.name}/_data"
    inspection = {"Name": volume.name, "Mountpoint": mountpoint}
    driver = _volume_delete_driver(volume.name, [inspection, inspection])
    with patch("app.services.volume_service.get_container_client", return_value=driver):
        with pytest.raises(HTTPException) as exc_info:
            await VolumeService(db_session).delete_volume(str(volume.id))
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {"code": "volume_recovery_required"}
    assert await db_session.get(Volume, volume.id, populate_existing=True) is not None
    guard = await db_session.scalar(
        select(VolumeOperation)
        .where(VolumeOperation.volume_id == volume.id)
        .execution_options(populate_existing=True)
    )
    assert guard is not None and guard.state == "recovery_required"


@pytest.mark.asyncio
async def test_delete_accepts_only_daemon_404_then_verified_absence(db_session, test_user):
    from app.services.xfs_quota_service import xfs_quota_service

    volume = Volume(
        name=f"verified-absence-{uuid.uuid4()}",
        display_name="Verified absence",
        owner_id=test_user.id,
    )
    db_session.add(volume)
    await db_session.commit()
    mountpoint = f"/var/lib/docker/volumes/{volume.name}/_data"
    driver = _volume_delete_driver(
        volume.name, [{"Name": volume.name, "Mountpoint": mountpoint}, None]
    )
    driver.delete_volume.side_effect = ContainerDriverError("not found", status=404)
    with (
        patch("app.services.volume_service.get_container_client", return_value=driver),
        patch.object(xfs_quota_service, "remove_quota") as remove_quota,
    ):
        assert await VolumeService(db_session).delete_volume(str(volume.id)) is True
    assert await db_session.get(Volume, volume.id, populate_existing=True) is None
    assert (
        await db_session.scalar(
            select(VolumeOperation).where(VolumeOperation.volume_id == volume.id)
        )
        is None
    )
    remove_quota.assert_called_once_with(volume.name)


@pytest.mark.asyncio
async def test_delete_preserves_metadata_when_pre_mutation_inspection_fails(db_session, test_user):
    from app.services.xfs_quota_service import xfs_quota_service

    volume = Volume(
        name=f"inspection-down-{uuid.uuid4()}",
        display_name="Inspection down",
        owner_id=test_user.id,
    )
    db_session.add(volume)
    await db_session.commit()
    driver = _volume_delete_driver(
        volume.name, ContainerDriverError("daemon unavailable", status=500)
    )
    with (
        patch("app.services.volume_service.get_container_client", return_value=driver),
        patch.object(xfs_quota_service, "remove_quota") as remove_quota,
    ):
        with pytest.raises(ValueError, match="runtime_inspection_unavailable"):
            await VolumeService(db_session).delete_volume(str(volume.id))
    current = await db_session.get(Volume, volume.id, populate_existing=True)
    assert current is not None and current.status == "active"
    guard = await db_session.scalar(
        select(VolumeOperation)
        .where(VolumeOperation.volume_id == volume.id)
        .execution_options(populate_existing=True)
    )
    assert guard is not None and guard.state == "failed"
    driver.delete_volume.assert_not_awaited()
    remove_quota.assert_not_called()
