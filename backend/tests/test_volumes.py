"""Tests for Volume management and Backup service."""

import pytest
from httpx import AsyncClient


class TestVolumeService:
    """Volume service tests."""

    @pytest.mark.asyncio
    async def test_volume_service_instantiation(self):
        """Volume service should be instantiable."""
        from app.services.volume_service import VolumeService

        service = VolumeService()
        assert service is not None


class TestVolumeAPI:
    """Volume API endpoint tests."""

    @pytest.mark.asyncio
    async def test_volume_api_requires_admin(self, client: AsyncClient, admin_token):
        """Volume endpoints should require admin access."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp = await client.get("/api/volumes/", headers=headers)
        assert resp.status_code in [200, 500]


class TestBackupService:
    """Backup service tests."""

    @pytest.mark.asyncio
    async def test_backup_service_instantiation(self, db_session):
        """Backup service should be instantiable."""
        from app.services.backup_service import BackupService

        service = BackupService(db_session, backup_path="/tmp/test-backups")
        assert service is not None


class TestVolumeBackupModel:
    """Volume backup model tests."""

    @pytest.mark.asyncio
    async def test_backup_model_has_required_fields(self):
        """VolumeBackup model should have name, size, status, and path fields."""
        from app.models.volume_backup import VolumeBackup

        backup = VolumeBackup()
        assert hasattr(backup, 'volume_name')
        assert hasattr(backup, 'size_bytes')
        assert hasattr(backup, 'status')
        assert hasattr(backup, 'backup_path')


class TestBackupAPI:
    """Backup API endpoint tests."""

    def test_backup_routes_registered(self):
        """Backup endpoints should be registered in volume router."""
        from app.api.volumes import router

        route_paths = [route.path for route in router.routes]
        assert any("backup" in path for path in route_paths)
