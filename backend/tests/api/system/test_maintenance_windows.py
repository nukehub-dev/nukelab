"""Tests for System API maintenance window endpoints."""

import pytest
import uuid
from datetime import datetime, timedelta, UTC

from app.models.maintenance_window import MaintenanceWindow


"""Tests for MaintenanceWindow model, service, and API endpoints."""

import pytest_asyncio
from uuid import uuid4

from app.models.user import User
from app.services.maintenance_window_service import MaintenanceWindowService
from app.services.setting_service import SettingService
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


@pytest_asyncio.fixture
async def sample_window(db_session):
    """Create a sample maintenance window in the future."""
    service = MaintenanceWindowService(db_session)
    now = datetime.now(UTC).replace(tzinfo=None)
    window = await service.create_window(
        title="Test Maintenance",
        message="System will be down for updates",
        start_at=now + timedelta(hours=2),
        end_at=now + timedelta(hours=3),
    )
    return window


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------


class TestMaintenanceWindowEndpoints:
    """Tests for /api/system/maintenance-windows CRUD."""

    @pytest.mark.asyncio
    async def test_list_maintenance_windows(self, client, admin_token, db_session):
        """Admin should list maintenance windows."""
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        )
        db_session.add(w)
        await db_session.commit()

        response = await client.get(
            "/api/system/maintenance-windows", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "windows" in data
        assert len(data["windows"]) == 1

    @pytest.mark.asyncio
    async def test_list_active_only(self, client, admin_token, db_session):
        """Should filter by active_only."""
        w1 = MaintenanceWindow(
            title="active",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
            is_active=True,
        )
        w2 = MaintenanceWindow(
            title="inactive",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=3),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=4),
            is_active=False,
        )
        db_session.add_all([w1, w2])
        await db_session.commit()

        response = await client.get(
            "/api/system/maintenance-windows?active_only=true",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert len(response.json()["windows"]) == 1
        assert response.json()["windows"][0]["title"] == "active"

    @pytest.mark.asyncio
    async def test_create_maintenance_window(self, client, admin_token):
        """Admin should create a maintenance window."""
        start = (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)).isoformat()
        end = (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)).isoformat()
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "title": "Scheduled Maint",
                "message": "System update",
                "start_at": start,
                "end_at": end,
                "is_active": True,
                "notify_offsets": [15, 60],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["window"]["title"] == "Scheduled Maint"

    @pytest.mark.asyncio
    async def test_create_maintenance_window_invalid_times(self, client, admin_token):
        """Should reject end before start."""
        start = (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)).isoformat()
        end = (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)).isoformat()
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "title": "Bad",
                "message": "Window",
                "start_at": start,
                "end_at": end,
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_maintenance_window(self, client, admin_token, db_session):
        """Admin should get a single maintenance window."""
        w = MaintenanceWindow(
            title="t",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        response = await client.get(
            f"/api/system/maintenance-windows/{w.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["window"]["title"] == "t"

    @pytest.mark.asyncio
    async def test_get_maintenance_window_not_found(self, client, admin_token):
        """Should 404 for missing window."""
        response = await client.get(
            f"/api/system/maintenance-windows/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_maintenance_window(self, client, admin_token, db_session):
        """Admin should update a maintenance window."""
        w = MaintenanceWindow(
            title="old",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        response = await client.put(
            f"/api/system/maintenance-windows/{w.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"title": "new title"},
        )
        assert response.status_code == 200
        assert response.json()["window"]["title"] == "new title"

    @pytest.mark.asyncio
    async def test_delete_maintenance_window(self, client, admin_token, db_session):
        """Admin should delete a maintenance window."""
        w = MaintenanceWindow(
            title="del",
            message="m",
            start_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            end_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
        )
        db_session.add(w)
        await db_session.commit()
        await db_session.refresh(w)

        response = await client.delete(
            f"/api/system/maintenance-windows/{w.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_maintenance_window_not_found(self, client, admin_token):
        """Should 404 when deleting missing window."""
        response = await client.delete(
            f"/api/system/maintenance-windows/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_maintenance_windows_forbidden_for_user(self, client, user_token):
        """Regular user should not access maintenance windows."""
        response = await client.get(
            "/api/system/maintenance-windows", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403


class TestMaintenanceWindowAPI:
    """Tests for maintenance window REST API endpoints."""

    @pytest.mark.asyncio
    async def test_list_requires_admin(self, client, user_token):
        """Non-admin should not list maintenance windows."""
        response = await client.get(
            "/api/system/maintenance-windows", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_as_admin(self, client, admin_token, sample_window):
        """Admin should list maintenance windows."""
        response = await client.get(
            "/api/system/maintenance-windows", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "windows" in data
        assert any(w["id"] == str(sample_window.id) for w in data["windows"])

    @pytest.mark.asyncio
    async def test_create_requires_admin(self, client, user_token):
        """Non-admin should not create maintenance windows."""
        now = datetime.now(UTC).replace(tzinfo=None)
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "title": "Test",
                "message": "Msg",
                "start_at": (now + timedelta(hours=1)).isoformat(),
                "end_at": (now + timedelta(hours=2)).isoformat(),
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_as_admin(self, client, admin_token):
        """Admin should create a maintenance window."""
        now = datetime.now(UTC).replace(tzinfo=None)
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "title": "API Test Window",
                "message": "Testing via API",
                "start_at": (now + timedelta(hours=1)).isoformat(),
                "end_at": (now + timedelta(hours=2)).isoformat(),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["window"]["title"] == "API Test Window"

    @pytest.mark.asyncio
    async def test_create_invalid_times(self, client, admin_token):
        """Should reject invalid time ranges."""
        now = datetime.now(UTC).replace(tzinfo=None)
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "title": "Bad",
                "message": "Msg",
                "start_at": (now + timedelta(hours=2)).isoformat(),
                "end_at": (now + timedelta(hours=1)).isoformat(),
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_window(self, client, admin_token, sample_window):
        """Admin should get a single window."""
        response = await client.get(
            f"/api/system/maintenance-windows/{sample_window.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["window"]["id"] == str(sample_window.id)

    @pytest.mark.asyncio
    async def test_get_window_not_found(self, client, admin_token):
        """Should return 404 for non-existent window."""
        response = await client.get(
            f"/api/system/maintenance-windows/{uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_window(self, client, admin_token, sample_window):
        """Admin should update a window."""
        response = await client.put(
            f"/api/system/maintenance-windows/{sample_window.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"title": "Updated via API"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["window"]["title"] == "Updated via API"

    @pytest.mark.asyncio
    async def test_delete_window(self, client, admin_token, sample_window):
        """Admin should delete a window."""
        response = await client.delete(
            f"/api/system/maintenance-windows/{sample_window.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

        # Verify deleted
        response = await client.get(
            f"/api/system/maintenance-windows/{sample_window.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404
