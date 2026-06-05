"""Tests for System API endpoints, maintenance mode, and middleware."""

import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.system_setting import SystemSetting
from app.config import settings
from app.services.setting_service import SettingService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_maintenance_state():
    """Reset global maintenance state before and after each test."""
    settings.maintenance_mode = False
    settings.maintenance_message = "System under maintenance"
    yield
    settings.maintenance_mode = False
    settings.maintenance_message = "System under maintenance"


# ---------------------------------------------------------------------------
# SettingService Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """Public health check tests."""

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self, client):
        """Health check should return healthy status."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_returns_maintenance_when_enabled(self, client, admin_token):
        """Health check should return 503 when maintenance mode is active."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true&message=Planned downtime",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        response = await client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "maintenance"
        assert data["message"] == "Planned downtime"


# ---------------------------------------------------------------------------
# Maintenance Middleware Tests
# ---------------------------------------------------------------------------


