# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Volume model, service, and API."""

from unittest import mock

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def mock_docker_client():
    """Mock Docker container client to avoid real volume creation."""
    mock_vol = mock.AsyncMock()
    mock_vol.delete = mock.AsyncMock()

    mock_volumes = mock.AsyncMock()
    mock_volumes.create = mock.AsyncMock(return_value=mock_vol)
    mock_volumes.get = mock.AsyncMock(return_value=mock_vol)

    mock_client = mock.AsyncMock()
    mock_client.volumes = mock_volumes
    mock_client.close = mock.AsyncMock()

    mock_container_client = mock.AsyncMock()
    mock_container_client.client = mock_client
    mock_container_client.list_containers = mock.AsyncMock(return_value=[])
    mock_container_client.get_volume = mock.AsyncMock(return_value=None)
    mock_container_client.create_container = mock.AsyncMock(return_value=mock.Mock(id="mock-cid"))
    mock_container_client.start_container = mock.AsyncMock()
    mock_container_client.get_container_logs = mock.AsyncMock(return_value="mock logs")

    with mock.patch(
        "app.services.volume_service.get_container_client", return_value=mock_container_client
    ):
        yield


class TestVolumeModel:
    """Volume model tests."""

    @pytest.mark.asyncio
    async def test_volume_has_required_fields(self):
        """Volume should have all required fields."""
        from app.models.volume import Volume

        vol = Volume()
        assert hasattr(vol, "id")
        assert hasattr(vol, "name")
        assert hasattr(vol, "display_name")
        assert hasattr(vol, "owner_id")
        assert hasattr(vol, "visibility")
        assert hasattr(vol, "size_bytes")
        assert hasattr(vol, "max_size_bytes")
        assert hasattr(vol, "status")
        assert hasattr(vol, "last_mounted_at")

    @pytest.mark.asyncio
    async def test_volume_defaults(self):
        """Volume should have correct defaults when created via service."""
        from app.models.volume import Volume

        # When instantiated directly, defaults are None (set by DB)
        vol = Volume()
        assert vol.visibility is None  # DB default
        assert vol.status is None  # DB default
        assert vol.size_bytes is None  # DB default
        assert vol.last_mounted_at is None  # DB default


class TestVolumeService:
    """Volume service tests."""

    @pytest.mark.asyncio
    async def test_create_volume(self, db_session, test_user):
        """Service should create a volume."""
        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-123",
            display_name="Test Volume",
            owner_id=str(test_user.id),
            max_size_bytes=10737418240,  # 10GB
            description="A test volume",
        )

        assert volume.name == "test-vol-123"
        assert volume.display_name == "Test Volume"
        assert str(volume.owner_id) == str(test_user.id)
        assert volume.max_size_bytes == 10737418240
        assert volume.status == "active"

    @pytest.mark.asyncio
    async def test_list_volumes(self, db_session, test_user):
        """Service should list volumes for a user."""
        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)

        # Create a volume
        await service.create_volume(
            name="test-vol-list",
            display_name="List Test Volume",
            owner_id=str(test_user.id),
        )

        volumes = await service.list_volumes(str(test_user.id))
        assert len(volumes) >= 1
        assert any(v.name == "test-vol-list" for v in volumes)

    @pytest.mark.asyncio
    async def test_update_volume(self, db_session, test_user):
        """Service should update volume metadata."""
        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-update",
            display_name="Original Name",
            owner_id=str(test_user.id),
        )

        updated = await service.update_volume(
            volume_id=str(volume.id),
            display_name="Updated Name",
            visibility="public",
        )

        assert updated.display_name == "Updated Name"
        assert updated.visibility == "public"

    @pytest.mark.asyncio
    async def test_delete_volume(self, db_session, test_user):
        """Service should delete an unused volume."""
        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-delete",
            display_name="Delete Test Volume",
            owner_id=str(test_user.id),
        )

        success = await service.delete_volume(str(volume.id))
        assert success is True

        # Verify it's gone
        deleted = await service.get_volume(str(volume.id))
        assert deleted is None

    @pytest.mark.asyncio
    async def test_check_volumes_quota_exceeded(self, db_session, test_user):
        """Quota check should fail when volume exceeds plan limit."""
        from unittest.mock import AsyncMock, patch

        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-quota-fail",
            display_name="Quota Fail Volume",
            owner_id=str(test_user.id),
        )

        # Mock the filesystem size check to return 15GB
        with patch.object(service, "get_volume_size", new_callable=AsyncMock) as mock_size:
            mock_size.return_value = 16106127360  # 15GB

            result = await service.check_volumes_quota([str(volume.id)], "10g")
            assert result["allowed"] is False
            assert "exceeds" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_server_count_computed_from_mounts(self, db_session, test_user):
        """server_count in to_dict() should reflect actual server_mounts."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.models.server import Server
        from app.models.server_volume import ServerVolume
        from app.models.volume import Volume
        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-count",
            display_name="Count Test Volume",
            owner_id=str(test_user.id),
        )

        # Without server_mounts loaded, count is 0
        assert volume.to_dict()["server_count"] == 0

        # Create a server and mount the volume
        server = Server(
            name="count-test-server",
            user_id=test_user.id,
            status="running",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        sv = ServerVolume(
            server_id=server.id,
            volume_id=volume.id,
            mount_path="/data",
            mode="read_write",
        )
        db_session.add(sv)
        await db_session.commit()

        # Load volume with server_mounts and verify count
        result = await db_session.execute(
            select(Volume).options(selectinload(Volume.server_mounts)).where(Volume.id == volume.id)
        )
        volume_loaded = result.scalar_one()
        assert volume_loaded.to_dict()["server_count"] == 1

    @pytest.mark.asyncio
    async def test_delete_volume_rejects_mounted_volume(self, db_session, test_user):
        """delete_volume should reject a volume that still has server mounts."""
        from app.models.server import Server
        from app.models.server_volume import ServerVolume
        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-mounted",
            display_name="Mounted Volume",
            owner_id=str(test_user.id),
        )

        server = Server(
            name="mounted-server",
            user_id=test_user.id,
            status="running",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        sv = ServerVolume(
            server_id=server.id,
            volume_id=volume.id,
            mount_path="/data",
            mode="read_write",
        )
        db_session.add(sv)
        await db_session.commit()

        with pytest.raises(ValueError, match="still mounted"):
            await service.delete_volume(str(volume.id))

    @pytest.mark.asyncio
    async def test_check_volumes_quota_aggregate_passes(self, db_session, test_user):
        """Aggregate quota should pass when total volume sizes are within plan limit."""
        from unittest.mock import AsyncMock, patch

        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        vol1 = await service.create_volume(
            name="test-vol-agg-1",
            display_name="Aggregate Volume 1",
            owner_id=str(test_user.id),
        )
        vol2 = await service.create_volume(
            name="test-vol-agg-2",
            display_name="Aggregate Volume 2",
            owner_id=str(test_user.id),
        )

        with patch.object(service, "get_volume_size", new_callable=AsyncMock) as mock_size:
            # 3GB + 4GB = 7GB total, under 10GB plan
            mock_size.side_effect = [3221225472, 4294967296]

            result = await service.check_volumes_quota([str(vol1.id), str(vol2.id)], "10g")
            assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_check_volumes_quota_aggregate_fails(self, db_session, test_user):
        """Aggregate quota should fail when total volume sizes exceed plan limit."""
        from unittest.mock import AsyncMock, patch

        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        vol1 = await service.create_volume(
            name="test-vol-agg-fail-1",
            display_name="Aggregate Fail Volume 1",
            owner_id=str(test_user.id),
        )
        vol2 = await service.create_volume(
            name="test-vol-agg-fail-2",
            display_name="Aggregate Fail Volume 2",
            owner_id=str(test_user.id),
        )

        with patch.object(service, "get_volume_size", new_callable=AsyncMock) as mock_size:
            # 6GB + 6GB = 12GB total, over 10GB plan
            mock_size.side_effect = [6442450944, 6442450944]

            result = await service.check_volumes_quota([str(vol1.id), str(vol2.id)], "10g")
            assert result["allowed"] is False
            assert "total mounted volume capacity" in result["reason"].lower()
            assert result["total_size"] == 12884901888
            assert result["plan_limit"] == 10737418240

    @pytest.mark.asyncio
    async def test_check_volumes_quota_single_volume(self, db_session, test_user):
        """Volumes quota with a single volume should behave like per-volume check."""
        from unittest.mock import AsyncMock, patch

        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        vol = await service.create_volume(
            name="test-vol-agg-single",
            display_name="Aggregate Single Volume",
            owner_id=str(test_user.id),
        )

        with patch.object(service, "get_volume_size", new_callable=AsyncMock) as mock_size:
            mock_size.return_value = 16106127360  # 15GB

            result = await service.check_volumes_quota([str(vol.id)], "10g")
            assert result["allowed"] is False
            assert "exceeds" in result["reason"].lower()

            # Should pass with 20GB plan
            result = await service.check_volumes_quota([str(vol.id)], "20g")
            assert result["allowed"] is True


class TestVolumeAPI:
    """Volume API endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_volume_via_api(self, client: AsyncClient, test_user, user_token):
        """User should create a volume via API."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post(
            "/api/volumes/",
            headers=headers,
            json={
                "display_name": "API Test Volume",
                "description": "Created via API",
                "max_size_bytes": 10737418240,
            },
        )
        assert resp.status_code == 201

        volume = resp.json()
        assert volume["display_name"] == "API Test Volume"
        assert volume["owner_id"] == str(test_user.id)
        assert volume["status"] == "active"

    @pytest.mark.asyncio
    async def test_create_volume_without_size_rejected(
        self, client: AsyncClient, test_user, user_token
    ):
        """Non-admin users must provide a size limit (unlimited volumes bypass quota)."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post(
            "/api/volumes/",
            headers=headers,
            json={"display_name": "Unlimited Volume"},
        )
        assert resp.status_code == 422
        assert "max_size_bytes" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_volumes_via_api(self, client: AsyncClient, test_user, user_token):
        """User should list their volumes via API."""
        headers = {"Authorization": f"Bearer {user_token}"}

        # Create a volume first
        await client.post(
            "/api/volumes/",
            headers=headers,
            json={
                "display_name": "List Test Volume",
                "max_size_bytes": 10737418240,
            },
        )

        resp = await client.get("/api/volumes/", headers=headers)
        assert resp.status_code == 200

        data = resp.json()
        assert "volumes" in data
        assert len(data["volumes"]) >= 1
        assert any(v["display_name"] == "List Test Volume" for v in data["volumes"])

    @pytest.mark.asyncio
    async def test_get_volume_via_api(self, client: AsyncClient, test_user, user_token):
        """User should get a specific volume via API."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post(
            "/api/volumes/",
            headers=headers,
            json={
                "display_name": "Get Test Volume",
                "max_size_bytes": 10737418240,
            },
        )
        volume = resp.json()

        resp = await client.get(f"/api/volumes/{volume['id']}", headers=headers)
        assert resp.status_code == 200

        data = resp.json()
        assert data["id"] == volume["id"]
        assert data["display_name"] == "Get Test Volume"

    @pytest.mark.asyncio
    async def test_delete_volume_via_api(self, client: AsyncClient, test_user, user_token):
        """User should delete their unused volume via API."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post(
            "/api/volumes/",
            headers=headers,
            json={
                "display_name": "Delete Test Volume",
                "max_size_bytes": 10737418240,
            },
        )
        volume = resp.json()

        resp = await client.delete(f"/api/volumes/{volume['id']}", headers=headers)
        assert resp.status_code == 200

        # Verify it's gone
        resp = await client.get(f"/api/volumes/{volume['id']}", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_user_cannot_shrink_volume_below_used_size(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User should get 400 when trying to set max_size below current size_bytes."""
        from app.services.volume_service import VolumeService

        headers = {"Authorization": f"Bearer {user_token}"}
        service = VolumeService(db_session)

        # Create volume with 10 GB limit
        volume = await service.create_volume(
            name="shrink-test-vol",
            display_name="Shrink Test Volume",
            owner_id=str(test_user.id),
            max_size_bytes=10 * 1024 * 1024 * 1024,
        )
        # Simulate 5 GB of used data
        volume.size_bytes = 5 * 1024 * 1024 * 1024
        await db_session.commit()

        # Try to shrink to 3 GB
        resp = await client.put(
            f"/api/volumes/{volume.id}",
            headers=headers,
            json={
                "max_size_bytes": 3 * 1024 * 1024 * 1024,
            },
        )
        assert resp.status_code == 400
        assert "cannot set volume limit" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_user_can_increase_volume_max_size(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User should be able to increase volume max_size."""
        from app.services.volume_service import VolumeService

        headers = {"Authorization": f"Bearer {user_token}"}
        service = VolumeService(db_session)

        volume = await service.create_volume(
            name="grow-test-vol",
            display_name="Grow Test Volume",
            owner_id=str(test_user.id),
            max_size_bytes=10 * 1024 * 1024 * 1024,
        )
        volume.size_bytes = 2 * 1024 * 1024 * 1024
        await db_session.commit()

        resp = await client.put(
            f"/api/volumes/{volume.id}",
            headers=headers,
            json={
                "max_size_bytes": 20 * 1024 * 1024 * 1024,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_size_bytes"] == 20 * 1024 * 1024 * 1024


class TestVolumeAccessService:
    """Volume access control tests."""

    @pytest.mark.asyncio
    async def test_owner_can_access_volume(self, db_session, test_user):
        """Volume owner should have full access."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)

        volume = await vol_service.create_volume(
            name="test-vol-access",
            display_name="Access Test Volume",
            owner_id=str(test_user.id),
        )

        can_access = await access_service.can_access_volume(
            str(volume.id), str(test_user.id), "read_write"
        )
        assert can_access is True

    @pytest.mark.asyncio
    async def test_non_owner_cannot_access_private_volume(self, db_session, test_user, admin_user):
        """Non-owner should not access private volume."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)

        volume = await vol_service.create_volume(
            name="test-vol-private",
            display_name="Private Test Volume",
            owner_id=str(test_user.id),
        )

        can_access = await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_write"
        )
        assert can_access is False

    @pytest.mark.asyncio
    async def test_validate_max_size_rejects_shrink(self, db_session, test_user):
        """VolumeService.validate_max_size should reject shrinking below used bytes."""
        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-validate",
            display_name="Validate Test Volume",
            owner_id=str(test_user.id),
            max_size_bytes=10 * 1024 * 1024 * 1024,  # 10 GB
        )
        # Simulate used data by setting size_bytes directly
        volume.size_bytes = 5 * 1024 * 1024 * 1024  # 5 GB used
        await db_session.commit()

        # Shrinking to 3 GB should fail
        with pytest.raises(ValueError, match="Cannot set volume limit"):
            service.validate_max_size(volume, 3 * 1024 * 1024 * 1024)

        # Keeping at 10 GB should succeed
        service.validate_max_size(volume, 10 * 1024 * 1024 * 1024)

        # Expanding to 20 GB should succeed
        service.validate_max_size(volume, 20 * 1024 * 1024 * 1024)

    @pytest.mark.asyncio
    async def test_validate_max_size_allows_unlimited(self, db_session, test_user):
        """Setting max_size_bytes to None (unlimited) should always pass."""
        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-unlimited",
            display_name="Unlimited Test Volume",
            owner_id=str(test_user.id),
        )
        volume.size_bytes = 100 * 1024 * 1024 * 1024  # 100 GB used
        await db_session.commit()

        # None means unlimited — should always pass
        service.validate_max_size(volume, None)

    @pytest.mark.asyncio
    async def test_public_volume_read_only_access(self, db_session, test_user, admin_user):
        """Public volume should allow read-only access to anyone."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)

        volume = await vol_service.create_volume(
            name="test-vol-public",
            display_name="Public Test Volume",
            owner_id=str(test_user.id),
            visibility="public",
        )

        # Admin user can read
        can_read = await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_only"
        )
        assert can_read is True

        # But not write
        can_write = await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_write"
        )
        assert can_write is False


"""Coverage-focused tests for volumes.py gaps."""

import errno
import os
import tempfile

import pytest

from app.models.shared_workspace import SharedWorkspace
from app.models.volume import Volume
from app.models.workspace_volume import WorkspaceVolume


class TestVolumeAccessControl:
    """403 + admin override for endpoints beyond GET/PUT."""

    @pytest.mark.asyncio
    async def test_refresh_size_non_owner_forbidden(
        self, client, user_token, test_user, admin_user, db_session
    ):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.post(
            f"/api/volumes/{vol.id}/refresh-size", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_refresh_size_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.api.volumes.VolumeService.update_volume_size", return_value=1024):
            response = await client.post(
                f"/api/volumes/{vol.id}/refresh-size",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_refresh_size_owner_success(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.api.volumes.VolumeService.update_volume_size", return_value=2048):
            response = await client.post(
                f"/api/volumes/{vol.id}/refresh-size",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code == 200
        assert response.json()["size_bytes"] == 2048

    @pytest.mark.asyncio
    async def test_list_files_non_owner_forbidden(
        self, client, user_token, test_user, admin_user, db_session
    ):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.get(
            f"/api/volumes/{vol.id}/files", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_files_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                os.makedirs(os.path.join(tmpdir, vol.name, "_data"))
                response = await client.get(
                    f"/api/volumes/{vol.id}/files",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_file_non_owner_forbidden(
        self, client, user_token, test_user, admin_user, db_session
    ):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.delete(
            f"/api/volumes/{vol.id}/files?path=foo.txt",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_file_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                file_path = os.path.join(data_dir, "foo.txt")
                with open(file_path, "w") as f:
                    f.write("hello")

                response = await client.delete(
                    f"/api/volumes/{vol.id}/files?path=foo.txt",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_download_non_owner_forbidden(
        self, client, user_token, test_user, admin_user, db_session
    ):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.get(
            f"/api/volumes/{vol.id}/download?path=foo.txt",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_download_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                file_path = os.path.join(data_dir, "foo.txt")
                with open(file_path, "w") as f:
                    f.write("hello")

                response = await client.get(
                    f"/api/volumes/{vol.id}/download?path=foo.txt",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_volume_non_owner_forbidden(
        self, client, user_token, test_user, admin_user, db_session
    ):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.delete(
            f"/api/volumes/{vol.id}", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_volume_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.api.volumes.VolumeService.delete_volume", return_value=True):
            response = await client.delete(
                f"/api/volumes/{vol.id}", headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200


class TestListVolumeFilesSorting:
    """Sort branches in list_volume_files."""

    @pytest.fixture
    def _setup_volume_and_files(self, test_user, db_session):
        vol = Volume(name="vol-sort", display_name="Vol Sort", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        db_session.commit()
        return vol

    @pytest.mark.asyncio
    async def test_sort_by_modified(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-sort", display_name="Vol Sort", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                for name in ["a.txt", "b.txt"]:
                    with open(os.path.join(data_dir, name), "w") as f:
                        f.write("x")

                response = await client.get(
                    f"/api/volumes/{vol.id}/files?sort_by=modified&sort_order=desc",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["type"] == "directory"

    @pytest.mark.asyncio
    async def test_sort_by_name_desc(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-sort", display_name="Vol Sort", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                for name in ["a.txt", "b.txt"]:
                    with open(os.path.join(data_dir, name), "w") as f:
                        f.write("x")

                response = await client.get(
                    f"/api/volumes/{vol.id}/files?sort_by=name&sort_order=desc",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                assert response.status_code == 200
                data = response.json()
                names = [i["name"] for i in data["items"]]
                assert names == sorted(names, reverse=True)

    @pytest.mark.asyncio
    async def test_sort_by_invalid(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-sort", display_name="Vol Sort", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                with open(os.path.join(data_dir, "a.txt"), "w") as f:
                    f.write("x")

                response = await client.get(
                    f"/api/volumes/{vol.id}/files?sort_by=invalid",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                assert response.status_code == 200


class TestListVolumeFilesPagination:
    """Pagination edge cases."""

    @pytest.mark.asyncio
    async def test_empty_directory(self, client, user_token, test_user, db_session):
        vol = Volume(
            name="vol-empty", display_name="Vol Empty", owner_id=test_user.id, size_bytes=0
        )
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                os.makedirs(os.path.join(tmpdir, vol.name, "_data"), exist_ok=True)
                response = await client.get(
                    f"/api/volumes/{vol.id}/files",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["total"] == 0
                assert data["total_pages"] == 1

    @pytest.mark.asyncio
    async def test_page_beyond_total(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-page", display_name="Vol Page", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                with open(os.path.join(data_dir, "a.txt"), "w") as f:
                    f.write("x")

                response = await client.get(
                    f"/api/volumes/{vol.id}/files?page=100&page_size=10",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["page"] == 1


class TestDeleteVolumeFileErrors:
    """Exception handlers in delete_volume_file."""

    @pytest.mark.asyncio
    async def test_delete_read_only_filesystem(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-ro", display_name="Vol RO", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                file_path = os.path.join(data_dir, "foo.txt")
                with open(file_path, "w") as f:
                    f.write("hello")

                def raise_readonly(*a, **k):
                    e = OSError(errno.EROFS, "Read-only file system")
                    raise e

                with mock.patch("pathlib.Path.unlink", side_effect=raise_readonly):
                    response = await client.delete(
                        f"/api/volumes/{vol.id}/files?path=foo.txt",
                        headers={"Authorization": f"Bearer {user_token}"},
                    )
                assert response.status_code == 403
                assert "read-only" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_generic_exception(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-err", display_name="Vol Err", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                file_path = os.path.join(data_dir, "foo.txt")
                with open(file_path, "w") as f:
                    f.write("hello")

                with mock.patch("pathlib.Path.unlink", side_effect=RuntimeError("boom")):
                    response = await client.delete(
                        f"/api/volumes/{vol.id}/files?path=foo.txt",
                        headers={"Authorization": f"Bearer {user_token}"},
                    )
                assert response.status_code == 500


class TestDownloadVolumeFileErrors:
    """Exception handler in download_volume_file."""

    @pytest.mark.asyncio
    async def test_download_generic_exception(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-dl", display_name="Vol DL", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                with open(os.path.join(data_dir, "foo.txt"), "w") as f:
                    f.write("hello")

                with mock.patch(
                    "fastapi.responses.FileResponse.__init__", side_effect=RuntimeError("boom")
                ):
                    response = await client.get(
                        f"/api/volumes/{vol.id}/download?path=foo.txt",
                        headers={"Authorization": f"Bearer {user_token}"},
                    )
                assert response.status_code == 500


class TestListVolumeFilesGenericException:
    """Generic exception handler in list_volume_files."""

    @pytest.mark.asyncio
    async def test_list_files_generic_exception(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-list", display_name="Vol List", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.api.volumes._get_volume_base_path", side_effect=RuntimeError("boom")):
            response = await client.get(
                f"/api/volumes/{vol.id}/files", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 500


class TestUpdateVolumeFields:
    """Update description, visibility, status."""

    @pytest.mark.asyncio
    async def test_update_volume_description_visibility_status(
        self, client, user_token, test_user, db_session
    ):
        vol = Volume(name="vol-up", display_name="Vol Up", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.put(
            f"/api/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"description": "New desc", "visibility": "public", "status": "active"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "New desc"
        assert data["visibility"] == "public"
        assert data["status"] == "active"


class TestListVolumesWorkspaceAssociations:
    """Workspace associations truthy path."""

    @pytest.mark.asyncio
    async def test_list_volumes_with_workspace(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-ws", display_name="Vol WS", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.flush()

        ws = SharedWorkspace(name="test-ws", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        assoc = WorkspaceVolume(workspace_id=ws.id, volume_id=vol.id)
        db_session.add(assoc)
        await db_session.commit()

        response = await client.get(
            "/api/volumes/", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        vol_data = next(v for v in data["volumes"] if v["id"] == str(vol.id))
        assert vol_data["workspace_count"] == 1


class TestCreateVolumeNotificationFallback:
    """Notification fallback when display_name is empty."""

    @pytest.mark.asyncio
    async def test_create_volume_fallback_name(self, client, user_token):
        with mock.patch(
            "app.api.volumes.QuotaService.check_volume_creation_allowed",
            return_value={"allowed": True},
        ):
            with mock.patch("app.api.volumes.VolumeService.create_volume") as mock_create:
                vol = Volume(name="vol-fallback", display_name="", owner_id="x", size_bytes=0)
                mock_create.return_value = vol
                response = await client.post(
                    "/api/volumes/",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={"display_name": "", "max_size_bytes": 1024},
                )
                assert response.status_code == 201


"""Extended tests for Volume API endpoints."""

import pytest
from fastapi import HTTPException


class TestRefreshVolumeSize:
    @pytest.mark.asyncio
    async def test_refresh_volume_size(self, client, user_token, test_user, db_session):
        vol = Volume(
            name="refresh-vol", display_name="Refresh Vol", owner_id=test_user.id, size_bytes=0
        )
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch(
            "app.api.volumes.VolumeService.update_volume_size",
            new_callable=mock.AsyncMock,
            return_value=1024,
        ):
            response = await client.post(
                f"/api/volumes/{vol.id}/refresh-size",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["size_bytes"] == 1024

    @pytest.mark.asyncio
    async def test_refresh_volume_not_found(self, client, user_token):
        import uuid

        response = await client.post(
            f"/api/volumes/{uuid.uuid4()}/refresh-size",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404


class TestVolumeFiles:
    @pytest.mark.asyncio
    async def test_list_volume_files_not_found(self, client, user_token, test_user, db_session):
        vol = Volume(name="files-vol", display_name="Files Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch(
            "app.api.volumes.secure_path",
            side_effect=HTTPException(status_code=404, detail="Path not found"),
        ):
            response = await client.get(
                f"/api/volumes/{vol.id}/files?path=/nonexistent",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_volume_file_not_found(self, client, user_token, test_user, db_session):
        vol = Volume(name="del-vol", display_name="Del Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch(
            "app.api.volumes.secure_path",
            side_effect=HTTPException(status_code=404, detail="Path not found"),
        ):
            response = await client.delete(
                f"/api/volumes/{vol.id}/files?path=/nonexistent",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_download_volume_file_not_found(self, client, user_token, test_user, db_session):
        vol = Volume(name="dl-vol", display_name="DL Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch(
            "app.api.volumes.secure_path",
            side_effect=HTTPException(status_code=404, detail="Path not found"),
        ):
            response = await client.get(
                f"/api/volumes/{vol.id}/download?path=/nonexistent",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_volume_files_volume_not_found(self, client, user_token):
        import uuid

        response = await client.get(
            f"/api/volumes/{uuid.uuid4()}/files", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404


class TestVolumeAccessControlExtended:
    @pytest.mark.asyncio
    async def test_get_other_user_volume_forbidden(
        self, client, user_token, admin_user, db_session
    ):
        vol = Volume(
            name="private-vol",
            display_name="Private Vol",
            owner_id=admin_user.id,
            visibility="private",
        )
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        response = await client.get(
            f"/api/volumes/{vol.id}", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_other_user_volume_forbidden(
        self, client, user_token, admin_user, db_session
    ):
        vol = Volume(name="upd-private", display_name="Upd Private", owner_id=admin_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        response = await client.put(
            f"/api/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"display_name": "Hacked"},
        )
        assert response.status_code == 403
