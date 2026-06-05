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

class TestSettingService:
    """Tests for the SettingService DB persistence layer."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, db_session):
        """Should persist and retrieve settings."""
        service = SettingService(db_session)
        await service.set("maintenance_mode", "true")
        await service.set("maintenance_message", "Down for upgrades")

        assert await service.get("maintenance_mode") == "true"
        assert await service.get("maintenance_message") == "Down for upgrades"

    @pytest.mark.asyncio
    async def test_get_returns_default_when_missing(self, db_session):
        """Should return default when key doesn't exist."""
        service = SettingService(db_session)
        assert await service.get("nonexistent", "default_val") == "default_val"
        assert await service.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_set_updates_existing(self, db_session):
        """Should update existing rows."""
        service = SettingService(db_session)
        await service.set("maintenance_mode", "true")
        await service.set("maintenance_mode", "false")

        result = await db_session.execute(
            select(SystemSetting).where(SystemSetting.key == "maintenance_mode")
        )
        row = result.scalar_one()
        assert row.value == "false"

    @pytest.mark.asyncio
    async def test_load_into_config(self, db_session):
        """Should load DB values into global settings."""
        service = SettingService(db_session)
        await service.set("maintenance_mode", "true")
        await service.set("maintenance_message", "DB message")

        await service.load_into_config()

        assert settings.maintenance_mode is True
        assert settings.maintenance_message == "DB message"

    @pytest.mark.asyncio
    async def test_save_maintenance(self, db_session):
        """Should save maintenance state and sync to global config."""
        service = SettingService(db_session)
        await service.save_maintenance(enabled=True, message="Planned downtime")

        assert settings.maintenance_mode is True
        assert settings.maintenance_message == "Planned downtime"
        assert await service.get("maintenance_mode") == "true"
        assert await service.get("maintenance_message") == "Planned downtime"

    @pytest.mark.asyncio
    async def test_get_maintenance(self, db_session):
        """Should return maintenance settings from DB."""
        service = SettingService(db_session)
        await service.set("maintenance_mode", "true")
        await service.set("maintenance_message", "Test msg")

        maint = await service.get_maintenance()
        assert maint["maintenance_mode"] is True
        assert maint["maintenance_message"] == "Test msg"

    @pytest.mark.asyncio
    async def test_get_maintenance_fallback_to_config(self, db_session):
        """Should fall back to env config when DB row is missing."""
        original_mode = settings.maintenance_mode
        original_msg = settings.maintenance_message
        try:
            settings.maintenance_mode = True
            settings.maintenance_message = "Fallback msg"

            service = SettingService(db_session)
            maint = await service.get_maintenance()

            assert maint["maintenance_mode"] is True
            assert maint["maintenance_message"] == "Fallback msg"
        finally:
            settings.maintenance_mode = original_mode
            settings.maintenance_message = original_msg


# ---------------------------------------------------------------------------
# System Config API Tests
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

class TestMaintenanceMiddleware:
    """Tests for the maintenance mode middleware blocking behavior."""

    @pytest.mark.asyncio
    async def test_non_admin_blocked_during_maintenance(self, client, user_token, admin_token):
        """Non-admin requests should be blocked with 503 during maintenance."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true&message=Back soon",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        # Non-admin tries to access servers
        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "maintenance"
        assert "Back soon" in data["detail"]

    @pytest.mark.asyncio
    async def test_admin_allowed_during_maintenance(self, client, admin_token):
        """Admin requests should be allowed through during maintenance."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        # Admin can still access servers
        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_super_admin_allowed_during_maintenance(self, client, superadmin_token):
        """Super admin requests should be allowed through during maintenance."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true",
            headers={"Authorization": f"Bearer {superadmin_token}"}
        )

        # Super admin can still access servers
        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {superadmin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_moderator_blocked_during_maintenance(self, client, moderator_token, admin_token):
        """Moderator requests should be blocked with 503 during maintenance (no ADMIN_ACCESS)."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        # Moderator tries to access servers
        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {moderator_token}"}
        )
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "maintenance"

    @pytest.mark.asyncio
    async def test_auth_endpoints_exempt(self, client, admin_token):
        """Auth endpoints should work even during maintenance."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        # Public auth methods endpoint should work
        response = await client.get("/api/auth/methods")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_system_endpoints_exempt(self, client, admin_token):
        """System endpoints should work during maintenance (admin only)."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        # Admin can still access system config to turn it off
        response = await client.get(
            "/api/system/config",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limiting_on_blocked_requests(self, client, user_token, admin_token):
        """Blocked requests should be rate-limited after too many attempts."""
        from unittest import mock
        from app.config import settings
        from app.middleware.maintenance import MaintenanceMiddleware

        # Completely isolate the request log so prior tests cannot pollute state.
        with mock.patch.object(MaintenanceMiddleware, '_request_log', {}):
            # Enable maintenance
            response = await client.post(
                "/api/system/maintenance?enabled=true",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            assert settings.maintenance_mode is True

            # Fire many requests quickly to hit the rate limit
            rate_limited = False
            for _ in range(35):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
                if response.status_code == 429:
                    rate_limited = True

            # At least one should be rate-limited (429)
            assert rate_limited, f"Expected at least one 429, got {response.status_code}"
            data = response.json()
            assert data["status"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_normal_operation_when_maintenance_off(self, client, user_token):
        """Requests should proceed normally when maintenance is disabled."""
        # Ensure maintenance is off
        settings.maintenance_mode = False

        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# System Stats Tests
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
