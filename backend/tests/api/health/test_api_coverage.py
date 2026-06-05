"""Coverage tests for smaller API modules: health, system, quotas, ip_restriction."""

import pytest
from unittest import mock
from datetime import datetime, timedelta, UTC

class TestHealthEndpoints:
    """app/api/health.py coverage."""

    @pytest.mark.asyncio
    async def test_health_check_basic(self, client):
        response = await client.get("/api/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_health_check_detailed(self, client, admin_token):
        response = await client.get(
            "/api/health/detailed",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "resources" in data
        assert "database" in data["services"]

    @pytest.mark.asyncio
    async def test_platform_status(self, client):
        response = await client.get("/api/health/status")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "features" in data
        assert "limits" in data
        assert "auth_mode" in data["features"]



