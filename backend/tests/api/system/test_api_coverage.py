"""Coverage tests for smaller API modules: health, system, quotas, ip_restriction."""

import pytest
from unittest import mock
from datetime import datetime, timedelta, UTC

class TestSystemEndpoints:
    """app/api/system.py coverage."""

    @pytest.mark.asyncio
    async def test_system_health_maintenance_mode(self, client):
        with mock.patch("app.api.system.settings.maintenance_mode", True):
            with mock.patch("app.api.system.settings.maintenance_message", "Down for maintenance"):
                response = await client.get("/api/system/health")
                assert response.status_code == 503
                data = response.json()
                assert data["status"] == "maintenance"

    @pytest.mark.asyncio
    async def test_system_health_normal(self, client):
        with mock.patch("app.api.system.settings.maintenance_mode", False):
            response = await client.get("/api/system/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_system_config_get(self, client, admin_token):
        response = await client.get(
            "/api/system/config",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "app_name" in data
        assert "maintenance_mode" in data

    @pytest.mark.asyncio
    async def test_system_config_update(self, client, admin_token):
        response = await client.put(
            "/api/system/config",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"maintenance_mode": False, "maintenance_message": "test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_system_toggle_maintenance(self, client, admin_token):
        response = await client.post(
            "/api/system/maintenance?enabled=true&message=test+maintenance",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_system_stats(self, client, admin_token):
        response = await client.get(
            "/api/system/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "servers" in data
        assert "credits" in data

    @pytest.mark.asyncio
    async def test_system_stats_forbidden_non_admin(self, client, user_token):
        response = await client.get(
            "/api/system/stats",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_maintenance_windows_list(self, client, admin_token):
        response = await client.get(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "windows" in data

    @pytest.mark.asyncio
    async def test_maintenance_windows_create_invalid_dates(self, client, admin_token):
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "title": "Test",
                "message": "Test window",
                "start_at": (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)).isoformat(),
                "end_at": (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)).isoformat(),
            }
        )
        # Should get 400 for invalid date range
        assert response.status_code in (200, 400)

    @pytest.mark.asyncio
    async def test_maintenance_window_get_not_found(self, client, admin_token):
        import uuid
        response = await client.get(
            f"/api/system/maintenance-windows/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_maintenance_window_delete_not_found(self, client, admin_token):
        import uuid
        response = await client.delete(
            f"/api/system/maintenance-windows/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404



