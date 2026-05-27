"""Extended tests for Volumes API error paths."""

import pytest
import uuid

from app.models.volume import Volume


class TestVolumeAPIErrors:
    """Tests for volume endpoint error paths."""

    @pytest.mark.asyncio
    async def test_get_volume_not_found(self, client, user_token):
        """Getting non-existent volume should 404."""
        response = await client.get(
            "/api/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_volume_not_found(self, client, user_token):
        """Updating non-existent volume should 404."""
        response = await client.put(
            "/api/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"display_name": "new name"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_volume_not_found(self, client, user_token):
        """Deleting non-existent volume should 404."""
        response = await client.delete(
            "/api/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_user_cannot_access_others_volume(self, client, user_token, admin_user, db_session):
        """User should not be able to access another user's private volume."""
        volume = Volume(
            owner_id=admin_user.id,
            name="admin-volume",
            display_name="Admin Volume",
            size_bytes=10 * 1024 * 1024 * 1024,
            visibility="private",
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        response = await client.get(
            f"/api/volumes/{volume.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_create_volume_invalid_size(self, client, user_token):
        """Creating volume with invalid size should 422."""
        response = await client.post(
            "/api/volumes/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "vol1", "size_gb": -1}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_volume_missing_name(self, client, user_token):
        """Creating volume without name should 422."""
        response = await client.post(
            "/api/volumes/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"size_gb": 10}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_mount_volume_not_found(self, client, user_token):
        """Mounting non-existent volume should 404."""
        response = await client.post(
            "/api/volumes/00000000-0000-0000-0000-000000000000/mount",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"server_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_unmount_volume_not_found(self, client, user_token):
        """Unmounting non-existent volume should 404."""
        response = await client.post(
            "/api/volumes/00000000-0000-0000-0000-000000000000/unmount",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"server_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_volume_backups_not_found(self, client, user_token):
        """Listing backups for non-existent volume should 404."""
        response = await client.get(
            "/api/volumes/00000000-0000-0000-0000-000000000000/backups",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_backup_volume_not_found(self, client, user_token):
        """Creating backup for non-existent volume should 404."""
        response = await client.post(
            "/api/volumes/00000000-0000-0000-0000-000000000000/backups",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404
