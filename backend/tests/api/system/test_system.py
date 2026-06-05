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
    async def test_update_system_config_persists_to_db(self, client, admin_token, db_session):
        """Config updates should be persisted to the database."""
        response = await client.put(
            "/api/system/config",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "maintenance_mode": True,
                "maintenance_message": "System down for maintenance"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["updates"]["maintenance_mode"] is True

        # Verify DB persistence
        result = await db_session.execute(
            select(SystemSetting).where(SystemSetting.key == "maintenance_mode")
        )
        row = result.scalar_one()
        assert row.value == "true"

        result = await db_session.execute(
            select(SystemSetting).where(SystemSetting.key == "maintenance_message")
        )
        row = result.scalar_one()
        assert row.value == "System down for maintenance"


# ---------------------------------------------------------------------------
# Maintenance Mode API Tests
# ---------------------------------------------------------------------------


class TestMaintenanceMode:
    """Maintenance mode endpoint tests."""

    @pytest.mark.asyncio
    async def test_enable_maintenance_persists(self, client, admin_token, db_session):
        """Admin should be able to enable maintenance mode and it persists to DB."""
        response = await client.post(
            "/api/system/maintenance?enabled=true&message=Under maintenance",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["maintenance_mode"] is True
        assert data["message"] == "Under maintenance"

        # Verify DB
        result = await db_session.execute(
            select(SystemSetting).where(SystemSetting.key == "maintenance_mode")
        )
        row = result.scalar_one()
        assert row.value == "true"

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


# ---------------------------------------------------------------------------
# Health Endpoint Tests
# ---------------------------------------------------------------------------


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

