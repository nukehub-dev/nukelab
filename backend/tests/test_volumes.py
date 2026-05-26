"""Tests for Volume model, service, and API."""

import pytest
from httpx import AsyncClient


class TestVolumeModel:
    """Volume model tests."""

    @pytest.mark.asyncio
    async def test_volume_has_required_fields(self):
        """Volume should have all required fields."""
        from app.models.volume import Volume

        vol = Volume()
        assert hasattr(vol, 'id')
        assert hasattr(vol, 'name')
        assert hasattr(vol, 'display_name')
        assert hasattr(vol, 'owner_id')
        assert hasattr(vol, 'visibility')
        assert hasattr(vol, 'size_bytes')
        assert hasattr(vol, 'max_size_bytes')
        assert hasattr(vol, 'status')
        assert hasattr(vol, 'last_mounted_at')

    @pytest.mark.asyncio
    async def test_volume_defaults(self):
        """Volume should have correct defaults when created via service."""
        from app.services.volume_service import VolumeService
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
    async def test_check_quota_exceeded(self, db_session, test_user):
        """Quota check should fail when volume exceeds plan limit."""
        from app.services.volume_service import VolumeService
        from unittest.mock import AsyncMock, patch

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-quota-fail",
            display_name="Quota Fail Volume",
            owner_id=str(test_user.id),
        )

        # Mock the filesystem size check to return 15GB
        with patch.object(service, 'get_volume_size', new_callable=AsyncMock) as mock_size:
            mock_size.return_value = 16106127360  # 15GB
            
            result = await service.check_quota(str(volume.id), "10g")
            assert result["allowed"] is False
            assert "exceeds" in result["reason"].lower()
            assert result["volume_size"] == 16106127360
            assert result["plan_limit"] == 10737418240  # 10GB

    @pytest.mark.asyncio
    async def test_server_count_computed_from_mounts(self, db_session, test_user):
        """server_count in to_dict() should reflect actual server_mounts."""
        from app.services.volume_service import VolumeService
        from app.models.volume import Volume
        from app.models.server import Server
        from app.models.server_volume import ServerVolume
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
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
            select(Volume)
            .options(selectinload(Volume.server_mounts))
            .where(Volume.id == volume.id)
        )
        volume_loaded = result.scalar_one()
        assert volume_loaded.to_dict()["server_count"] == 1

    @pytest.mark.asyncio
    async def test_delete_volume_rejects_mounted_volume(self, db_session, test_user):
        """delete_volume should reject a volume that still has server mounts."""
        from app.services.volume_service import VolumeService
        from app.models.server import Server
        from app.models.server_volume import ServerVolume

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
    async def test_check_aggregate_quota_passes(self, db_session, test_user):
        """Aggregate quota should pass when total volume sizes are within plan limit."""
        from app.services.volume_service import VolumeService
        from unittest.mock import AsyncMock, patch

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

        with patch.object(service, 'get_volume_size', new_callable=AsyncMock) as mock_size:
            # 3GB + 4GB = 7GB total, under 10GB plan
            mock_size.side_effect = [3221225472, 4294967296]

            result = await service.check_aggregate_quota(
                [str(vol1.id), str(vol2.id)], "10g"
            )
            assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_check_aggregate_quota_fails(self, db_session, test_user):
        """Aggregate quota should fail when total volume sizes exceed plan limit."""
        from app.services.volume_service import VolumeService
        from unittest.mock import AsyncMock, patch

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

        with patch.object(service, 'get_volume_size', new_callable=AsyncMock) as mock_size:
            # 6GB + 6GB = 12GB total, over 10GB plan
            mock_size.side_effect = [6442450944, 6442450944]

            result = await service.check_aggregate_quota(
                [str(vol1.id), str(vol2.id)], "10g"
            )
            assert result["allowed"] is False
            assert "total mounted volume capacity" in result["reason"].lower()
            assert result["total_size"] == 12884901888
            assert result["plan_limit"] == 10737418240
            assert "volumes" in result
            assert len(result["volumes"]) == 2

    @pytest.mark.asyncio
    async def test_check_aggregate_quota_single_volume(self, db_session, test_user):
        """Aggregate quota with a single volume should behave like per-volume check."""
        from app.services.volume_service import VolumeService
        from unittest.mock import AsyncMock, patch

        service = VolumeService(db_session)
        vol = await service.create_volume(
            name="test-vol-agg-single",
            display_name="Aggregate Single Volume",
            owner_id=str(test_user.id),
        )

        with patch.object(service, 'get_volume_size', new_callable=AsyncMock) as mock_size:
            mock_size.return_value = 16106127360  # 15GB

            result = await service.check_aggregate_quota([str(vol.id)], "10g")
            assert result["allowed"] is False
            assert result["total_size"] == 16106127360
            assert result["plan_limit"] == 10737418240

            # Should pass with 20GB plan
            result = await service.check_aggregate_quota([str(vol.id)], "20g")
            assert result["allowed"] is True


class TestVolumeAPI:
    """Volume API endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_volume_via_api(self, client: AsyncClient, test_user, user_token):
        """User should create a volume via API."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post("/api/volumes/", headers=headers, json={
            "display_name": "API Test Volume",
            "description": "Created via API",
            "max_size_bytes": 10737418240,
        })
        assert resp.status_code == 201

        volume = resp.json()
        assert volume["display_name"] == "API Test Volume"
        assert volume["owner_id"] == str(test_user.id)
        assert volume["status"] == "active"

    @pytest.mark.asyncio
    async def test_list_volumes_via_api(self, client: AsyncClient, test_user, user_token):
        """User should list their volumes via API."""
        headers = {"Authorization": f"Bearer {user_token}"}

        # Create a volume first
        await client.post("/api/volumes/", headers=headers, json={
            "display_name": "List Test Volume",
        })

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

        resp = await client.post("/api/volumes/", headers=headers, json={
            "display_name": "Get Test Volume",
        })
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

        resp = await client.post("/api/volumes/", headers=headers, json={
            "display_name": "Delete Test Volume",
        })
        volume = resp.json()

        resp = await client.delete(f"/api/volumes/{volume['id']}", headers=headers)
        assert resp.status_code == 200

        # Verify it's gone
        resp = await client.get(f"/api/volumes/{volume['id']}", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_user_cannot_shrink_volume_below_used_size(self, client: AsyncClient, test_user, user_token, db_session):
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
        resp = await client.put(f"/api/volumes/{volume.id}", headers=headers, json={
            "max_size_bytes": 3 * 1024 * 1024 * 1024,
        })
        assert resp.status_code == 400
        assert "cannot set volume limit" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_user_can_increase_volume_max_size(self, client: AsyncClient, test_user, user_token, db_session):
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

        resp = await client.put(f"/api/volumes/{volume.id}", headers=headers, json={
            "max_size_bytes": 20 * 1024 * 1024 * 1024,
        })
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
