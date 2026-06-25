"""Tests for System API endpoints, maintenance mode, and middleware."""

import pytest

from app.config import settings

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


class TestMaintenanceMiddleware:
    """Tests for the maintenance mode middleware blocking behavior."""

    @pytest.mark.asyncio
    async def test_non_admin_blocked_during_maintenance(self, client, user_token, admin_token):
        """Non-admin requests should be blocked with 503 during maintenance."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true&message=Back soon",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Non-admin tries to access servers
        response = await client.get(
            "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}
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
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Admin can still access servers
        response = await client.get(
            "/api/servers/", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_super_admin_allowed_during_maintenance(self, client, superadmin_token):
        """Super admin requests should be allowed through during maintenance."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true",
            headers={"Authorization": f"Bearer {superadmin_token}"},
        )

        # Super admin can still access servers
        response = await client.get(
            "/api/servers/", headers={"Authorization": f"Bearer {superadmin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_moderator_blocked_during_maintenance(self, client, moderator_token, admin_token):
        """Moderator requests should be blocked with 503 during maintenance (no ADMIN_ACCESS)."""
        # Enable maintenance
        await client.post(
            "/api/system/maintenance?enabled=true",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Moderator tries to access servers
        response = await client.get(
            "/api/servers/", headers={"Authorization": f"Bearer {moderator_token}"}
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
            headers={"Authorization": f"Bearer {admin_token}"},
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
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # Admin can still access system config to turn it off
        response = await client.get(
            "/api/system/config", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limiting_on_blocked_requests(self, client, user_token, admin_token):
        """Blocked requests should be rate-limited after too many attempts."""
        from unittest import mock

        from app.config import settings
        from app.middleware.maintenance import MaintenanceMiddleware

        # Completely isolate the request log so prior tests cannot pollute state.
        with mock.patch.object(MaintenanceMiddleware, "_request_log", {}):
            # Enable maintenance
            response = await client.post(
                "/api/system/maintenance?enabled=true",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert response.status_code == 200
            assert settings.maintenance_mode is True

            # Fire many requests quickly to hit the rate limit
            rate_limited = False
            for _ in range(35):
                response = await client.get(
                    "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}
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
            "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# System Stats Tests
# ---------------------------------------------------------------------------
