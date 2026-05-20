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
        assert hasattr(vol, 'server_count')

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
        assert vol.server_count is None  # DB default


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
    async def test_server_count_tracking(self, db_session, test_user):
        """Server count should increment and decrement."""
        from app.services.volume_service import VolumeService

        service = VolumeService(db_session)
        volume = await service.create_volume(
            name="test-vol-count",
            display_name="Count Test Volume",
            owner_id=str(test_user.id),
        )

        assert volume.server_count == 0

        await service.increment_server_count(str(volume.id))
        await db_session.refresh(volume)
        assert volume.server_count == 1

        await service.decrement_server_count(str(volume.id))
        await db_session.refresh(volume)
        assert volume.server_count == 0

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
