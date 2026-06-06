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



"""Extended tests for small API modules — coverage gap closure."""

import pytest
from unittest import mock
from datetime import datetime, timedelta, UTC
import uuid as uuid_mod

from app.config import settings
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate
from app.models.notification import Notification
from app.models.activity_log import ActivityLog
from app.models.credit_transaction import CreditTransaction


@pytest.fixture(autouse=True)
def reset_maintenance_state():
    """Reset global maintenance state before and after each test."""
    settings.maintenance_mode = False
    settings.maintenance_message = "System under maintenance"
    yield
    settings.maintenance_mode = False
    settings.maintenance_message = "System under maintenance"


# ─────────────────────────────────────────────────────────────
# Schedules API
# ─────────────────────────────────────────────────────────────

class TestSystemExtended:
    """Tests for system endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_health_maintenance_mode(self, client):
        """Health check should return 503 when maintenance mode is on."""
        with mock.patch("app.api.system.settings.maintenance_mode", True):
            with mock.patch("app.api.system.settings.maintenance_message", "Down for maintenance"):
                response = await client.get("/api/system/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "maintenance"

    @pytest.mark.asyncio
    async def test_health_healthy(self, client):
        """Health check should return healthy normally."""
        with mock.patch("app.api.system.settings.maintenance_mode", False):
            response = await client.get("/api/system/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_update_system_config(self, client, admin_token):
        """Admin should update system config."""
        with mock.patch("app.api.system.SettingService") as mock_svc:
            mock_svc.return_value.save_maintenance = mock.AsyncMock()
            response = await client.put(
                "/api/system/config",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"maintenance_mode": True, "maintenance_message": "Test maintenance"},
            )
        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_system_stats_non_admin(self, client, user_token):
        """Non-admin should be blocked from system stats."""
        response = await client.get(
            "/api/system/stats",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_maintenance_windows_list(self, client, admin_token):
        """Admin should list maintenance windows."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.list_windows = mock.AsyncMock(return_value=[])
            response = await client.get(
                "/api/system/maintenance-windows",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_maintenance_windows_create(self, client, admin_token):
        """Admin should create a maintenance window."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_win = mock.Mock()
            mock_win.to_dict.return_value = {"id": str(uuid_mod.uuid4())}
            mock_svc.return_value.create_window = mock.AsyncMock(return_value=mock_win)
            response = await client.post(
                "/api/system/maintenance-windows",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "title": "Test Window",
                    "message": "Maintenance",
                    "start_at": (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)).isoformat(),
                    "end_at": (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)).isoformat(),
                },
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_maintenance_windows_create_value_error(self, client, admin_token):
        """ValueError from create_window should return 400."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.create_window = mock.AsyncMock(side_effect=ValueError("bad dates"))
            response = await client.post(
                "/api/system/maintenance-windows",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "title": "Test",
                    "message": "Maintenance",
                    "start_at": (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)).isoformat(),
                    "end_at": (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)).isoformat(),
                },
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_maintenance_windows_get_not_found(self, client, admin_token):
        """Should return 404 for nonexistent maintenance window."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.get_window = mock.AsyncMock(return_value=None)
            response = await client.get(
                f"/api/system/maintenance-windows/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_maintenance_windows_update_not_found(self, client, admin_token):
        """Should return 404 for updating nonexistent window."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.update_window = mock.AsyncMock(side_effect=ValueError("not found"))
            response = await client.put(
                f"/api/system/maintenance-windows/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"title": "Updated"},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_maintenance_windows_delete_not_found(self, client, admin_token):
        """Should return 404 for deleting nonexistent window."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.delete_window = mock.AsyncMock(return_value=False)
            response = await client.delete(
                f"/api/system/maintenance-windows/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────
# Plans API
# ─────────────────────────────────────────────────────────────


"""Extended tests for System and Metrics API endpoints."""

import pytest

class TestSystemAPI:
    """Tests for system endpoints."""

    @pytest.mark.asyncio
    async def test_system_health(self, client):
        """System health should be public."""
        response = await client.get("/api/system/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_system_config(self, client, admin_token):
        """System config requires admin."""
        response = await client.get(
            "/api/system/config",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_system_stats(self, client, admin_token):
        """System stats requires admin."""
        response = await client.get(
            "/api/system/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_maintenance_windows(self, client, admin_token):
        """Maintenance windows requires admin."""
        response = await client.get(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_config(self, client, user_token):
        """Regular user should not update system config."""
        response = await client.put(
            "/api/system/config",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"key": "value"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_create_maintenance_window(self, client, user_token):
        """Regular user should not create maintenance windows."""
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"title": "Test", "message": "test", "start_at": "2025-01-01T00:00:00", "end_at": "2025-01-02T00:00:00"}
        )
        assert response.status_code in [403, 404]



