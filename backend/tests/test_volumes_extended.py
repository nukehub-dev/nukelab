"""Extended tests for Volume API endpoints."""

import pytest
from unittest import mock
from fastapi import HTTPException

from app.models.volume import Volume


class TestRefreshVolumeSize:
    @pytest.mark.asyncio
    async def test_refresh_volume_size(self, client, user_token, test_user, db_session):
        vol = Volume(name="refresh-vol", display_name="Refresh Vol", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch("app.api.volumes.VolumeService.update_volume_size", new_callable=mock.AsyncMock, return_value=1024):
            response = await client.post(
                f"/api/volumes/{vol.id}/refresh-size",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["size_bytes"] == 1024

    @pytest.mark.asyncio
    async def test_refresh_volume_not_found(self, client, user_token):
        import uuid
        response = await client.post(
            f"/api/volumes/{uuid.uuid4()}/refresh-size",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404


class TestVolumeFiles:
    @pytest.mark.asyncio
    async def test_list_volume_files_not_found(self, client, user_token, test_user, db_session):
        vol = Volume(name="files-vol", display_name="Files Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch("app.api.volumes.secure_path", side_effect=HTTPException(status_code=404, detail="Path not found")):
            response = await client.get(
                f"/api/volumes/{vol.id}/files?path=/nonexistent",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_volume_file_not_found(self, client, user_token, test_user, db_session):
        vol = Volume(name="del-vol", display_name="Del Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch("app.api.volumes.secure_path", side_effect=HTTPException(status_code=404, detail="Path not found")):
            response = await client.delete(
                f"/api/volumes/{vol.id}/files?path=/nonexistent",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_download_volume_file_not_found(self, client, user_token, test_user, db_session):
        vol = Volume(name="dl-vol", display_name="DL Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch("app.api.volumes.secure_path", side_effect=HTTPException(status_code=404, detail="Path not found")):
            response = await client.get(
                f"/api/volumes/{vol.id}/download?path=/nonexistent",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_volume_files_volume_not_found(self, client, user_token):
        import uuid
        response = await client.get(
            f"/api/volumes/{uuid.uuid4()}/files",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404


class TestVolumeAccessControl:
    @pytest.mark.asyncio
    async def test_get_other_user_volume_forbidden(self, client, user_token, admin_user, db_session):
        vol = Volume(name="private-vol", display_name="Private Vol", owner_id=admin_user.id, visibility="private")
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        response = await client.get(
            f"/api/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_other_user_volume_forbidden(self, client, user_token, admin_user, db_session):
        vol = Volume(name="upd-private", display_name="Upd Private", owner_id=admin_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        response = await client.put(
            f"/api/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"display_name": "Hacked"}
        )
        assert response.status_code == 403
