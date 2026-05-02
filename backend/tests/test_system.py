"""Tests for System API endpoints."""

import pytest
from app.models.user import User


class TestSystemConfig:
    """System config endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_system_config_requires_admin(self, client, user_token):
        """Non-admin should not access system config."""
        response = await client.get(
            "/api/system/config",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_system_config_as_admin(self, client, admin_token):
        """Admin should be able to access system config."""
        response = await client.get(
            "/api/system/config",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "app_name" in data
        assert "maintenance_mode" in data

    @pytest.mark.asyncio
    async def test_update_system_config(self, client, admin_token):
        """Admin should be able to update system config."""
        response = await client.put(
            "/api/system/config",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "maintenance_message": "System down for maintenance"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestMaintenanceMode:
    """Maintenance mode endpoint tests."""

    @pytest.mark.asyncio
    async def test_enable_maintenance(self, client, admin_token):
        """Admin should be able to enable maintenance mode."""
        response = await client.post(
            "/api/system/maintenance?enabled=true&message=Under maintenance",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["maintenance_mode"] is True
        assert data["message"] == "Under maintenance"

    @pytest.mark.asyncio
    async def test_disable_maintenance(self, client, admin_token):
        """Admin should be able to disable maintenance mode."""
        response = await client.post(
            "/api/system/maintenance?enabled=false",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["maintenance_mode"] is False


class TestSystemStats:
    """System stats endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_system_stats(self, client, admin_token, test_user):
        """Admin should get system statistics."""
        response = await client.get(
            "/api/system/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "servers" in data
        assert "credits" in data
        assert "timestamp" in data


class TestHealthEndpoint:
    """Public health check tests."""

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self, client):
        """Health check should return healthy status."""
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"