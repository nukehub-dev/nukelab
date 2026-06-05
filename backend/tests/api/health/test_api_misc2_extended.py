"""Extended tests for Environments, Notifications, and Health API endpoints."""

import pytest
import uuid

from app.models.environment_template import EnvironmentTemplate
from app.models.notification import Notification
from app.models.health_check import HealthCheck
from app.models.server import Server

class TestHealthAPI:
    """Tests for health endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Health check should be public."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    @pytest.mark.asyncio
    async def test_health_status(self, client):
        """Status check should be public."""
        response = await client.get("/api/health/status")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_detailed(self, client, admin_token):
        """Detailed health check may require admin."""
        response = await client.get(
            "/api/health/detailed",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "resources" in data

