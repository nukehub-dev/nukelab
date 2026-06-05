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


