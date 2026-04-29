"""Tests for Health and Status API endpoints."""

import pytest


class TestBasicHealth:
    """Public health endpoint tests."""

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self, client):
        """Basic health check should return healthy status."""
        response = await client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestDetailedHealth:
    """Admin-only detailed health check tests."""

    @pytest.mark.asyncio
    async def test_detailed_health_requires_admin(self, client, admin_token):
        """Detailed health should be accessible to admins only."""
        response = await client.get(
            "/api/health/detailed",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "resources" in data
        assert "database" in data["services"]
        assert "redis" in data["services"]

    @pytest.mark.asyncio
    async def test_detailed_health_services_have_status(self, client, admin_token):
        """Each service in detailed health should have a status field."""
        response = await client.get(
            "/api/health/detailed",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        services = response.json()["services"]
        for service_name, service_data in services.items():
            assert "status" in service_data, f"Service {service_name} missing status"


class TestPlatformStatus:
    """Platform feature flags endpoint tests."""

    @pytest.mark.asyncio
    async def test_status_has_version_and_features(self, client):
        """Platform status should expose version and feature flags."""
        response = await client.get("/api/health/status")
        
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "features" in data
        assert data["features"]["gravatar_enabled"] is True
        assert data["features"]["themes_enabled"] is True
        assert data["features"]["notifications_enabled"] is True

    @pytest.mark.asyncio
    async def test_status_has_limits(self, client):
        """Platform status should expose rate limits and quotas."""
        response = await client.get("/api/health/status")
        
        assert response.status_code == 200
        data = response.json()
        assert "limits" in data
        assert "max_servers_per_user" in data["limits"]
        assert "api_rate_limit" in data["limits"]
