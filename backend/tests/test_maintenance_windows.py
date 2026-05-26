"""Tests for MaintenanceWindow model, service, and API endpoints."""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from app.models.maintenance_window import MaintenanceWindow
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
    now = datetime.utcnow()
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

class TestMaintenanceWindowModel:
    """Tests for the MaintenanceWindow database model."""

    @pytest.mark.asyncio
    async def test_create_window(self, db_session):
        """Should create a maintenance window with correct defaults."""
        now = datetime.utcnow()
        window = MaintenanceWindow(
            title="Planned Downtime",
            message="Upgrading database",
            start_at=now + timedelta(hours=1),
            end_at=now + timedelta(hours=2),
        )
        db_session.add(window)
        await db_session.commit()
        await db_session.refresh(window)

        assert window.title == "Planned Downtime"
        assert window.is_active is True
        assert window.auto_enabled is False
        assert window.auto_disabled is False
        assert window.notified_at is None
        assert window.id is not None

    @pytest.mark.asyncio
    async def test_to_dict(self, db_session):
        """Should serialize to dict correctly."""
        now = datetime.utcnow()
        window = MaintenanceWindow(
            title="Test",
            message="Msg",
            start_at=now,
            end_at=now + timedelta(hours=1),
        )
        db_session.add(window)
        await db_session.commit()

        d = window.to_dict()
        assert d["title"] == "Test"
        assert d["message"] == "Msg"
        assert "id" in d
        assert d["is_active"] is True
        assert d["auto_enabled"] is False


# ---------------------------------------------------------------------------
# Service Tests
# ---------------------------------------------------------------------------

class TestMaintenanceWindowService:
    """Tests for MaintenanceWindowService business logic."""

    @pytest.mark.asyncio
    async def test_create_window(self, db_session):
        """Should create a window with valid times."""
        service = MaintenanceWindowService(db_session)
        now = datetime.utcnow()
        window = await service.create_window(
            title="Window",
            message="Msg",
            start_at=now + timedelta(hours=1),
            end_at=now + timedelta(hours=2),
        )
        assert window.title == "Window"
        assert window.is_active is True

    @pytest.mark.asyncio
    async def test_create_window_end_before_start(self, db_session):
        """Should reject end time before start time."""
        service = MaintenanceWindowService(db_session)
        now = datetime.utcnow()
        with pytest.raises(ValueError, match="End time must be after start time"):
            await service.create_window(
                title="Bad",
                message="Msg",
                start_at=now + timedelta(hours=2),
                end_at=now + timedelta(hours=1),
            )

    @pytest.mark.asyncio
    async def test_create_window_past_start(self, db_session):
        """Should reject start time in the past."""
        service = MaintenanceWindowService(db_session)
        now = datetime.utcnow()
        with pytest.raises(ValueError, match="Start time must be in the future"):
            await service.create_window(
                title="Bad",
                message="Msg",
                start_at=now - timedelta(hours=1),
                end_at=now + timedelta(hours=1),
            )

    @pytest.mark.asyncio
    async def test_list_windows(self, db_session, sample_window):
        """Should list windows."""
        service = MaintenanceWindowService(db_session)
        windows = await service.list_windows()
        assert len(windows) >= 1
        assert any(w["id"] == str(sample_window.id) for w in windows)

    @pytest.mark.asyncio
    async def test_list_active_only(self, db_session, sample_window):
        """Should filter by active status."""
        service = MaintenanceWindowService(db_session)
        # Deactivate the sample
        sample_window.is_active = False
        await db_session.commit()

        active = await service.list_windows(active_only=True)
        assert not any(w["id"] == str(sample_window.id) for w in active)

    @pytest.mark.asyncio
    async def test_update_window(self, db_session, sample_window):
        """Should update a window."""
        service = MaintenanceWindowService(db_session)
        updated = await service.update_window(
            str(sample_window.id),
            title="Updated Title",
        )
        assert updated.title == "Updated Title"

    @pytest.mark.asyncio
    async def test_update_window_not_found(self, db_session):
        """Should raise error for non-existent window."""
        service = MaintenanceWindowService(db_session)
        with pytest.raises(ValueError, match="Maintenance window not found"):
            await service.update_window(str(uuid4()), title="X")

    @pytest.mark.asyncio
    async def test_delete_window(self, db_session, sample_window):
        """Should delete a window."""
        service = MaintenanceWindowService(db_session)
        deleted = await service.delete_window(str(sample_window.id))
        assert deleted is True
        assert await service.get_window(str(sample_window.id)) is None

    @pytest.mark.asyncio
    async def test_delete_window_not_found(self, db_session):
        """Should return False for non-existent window."""
        service = MaintenanceWindowService(db_session)
        assert await service.delete_window(str(uuid4())) is False

    @pytest.mark.asyncio
    async def test_get_pending_notifications(self, db_session):
        """Should find windows needing advance notification."""
        service = MaintenanceWindowService(db_session)
        now = datetime.utcnow()
        # Window starts in 10 minutes — within 15-minute threshold
        window = await service.create_window(
            title="Soon",
            message="Msg",
            start_at=now + timedelta(minutes=10),
            end_at=now + timedelta(minutes=20),
        )
        pending = await service.get_pending_notifications()
        assert len(pending) >= 1
        assert any(w.id == window.id for w, offset in pending)

    @pytest.mark.asyncio
    async def test_get_pending_notifications_already_notified(self, db_session):
        """Should not return already-notified windows."""
        service = MaintenanceWindowService(db_session)
        now = datetime.utcnow()
        window = await service.create_window(
            title="Soon",
            message="Msg",
            start_at=now + timedelta(minutes=10),
            end_at=now + timedelta(minutes=20),
        )
        window.notified_offsets = [15]
        await db_session.commit()

        pending = await service.get_pending_notifications()
        assert not any(w.id == window.id for w, offset in pending)

    @pytest.mark.asyncio
    async def test_get_windows_to_enable(self, db_session):
        """Should find windows that should start now."""
        service = MaintenanceWindowService(db_session)
        now = datetime.utcnow()
        window = MaintenanceWindow(
            title="Now",
            message="Msg",
            start_at=now - timedelta(minutes=1),
            end_at=now + timedelta(hours=1),
        )
        db_session.add(window)
        await db_session.commit()
        await db_session.refresh(window)
        to_enable = await service.get_windows_to_enable()
        assert any(w.id == window.id for w in to_enable)

    @pytest.mark.asyncio
    async def test_get_windows_to_disable(self, db_session):
        """Should find windows that should end now."""
        service = MaintenanceWindowService(db_session)
        now = datetime.utcnow()
        window = MaintenanceWindow(
            title="Done",
            message="Msg",
            start_at=now - timedelta(hours=2),
            end_at=now - timedelta(minutes=1),
        )
        window.auto_enabled = True
        db_session.add(window)
        await db_session.commit()
        await db_session.refresh(window)

        to_disable = await service.get_windows_to_disable()
        assert any(w.id == window.id for w in to_disable)

    @pytest.mark.asyncio
    async def test_enable_maintenance(self, db_session, sample_window):
        """Should enable maintenance mode and set auto_enabled flag."""
        service = MaintenanceWindowService(db_session)
        await service.enable_maintenance(sample_window)

        assert settings.maintenance_mode is True
        assert sample_window.auto_enabled is True

    @pytest.mark.asyncio
    async def test_disable_maintenance(self, db_session, sample_window):
        """Should disable maintenance mode and set auto_disabled flag."""
        service = MaintenanceWindowService(db_session)
        # First enable
        await service.enable_maintenance(sample_window)
        # Then disable
        await service.disable_maintenance(sample_window)

        assert settings.maintenance_mode is False
        assert sample_window.auto_disabled is True

    @pytest.mark.asyncio
    async def test_evaluate_windows_full_cycle(self, db_session):
        """Should run full evaluate cycle: notify, enable, disable."""
        service = MaintenanceWindowService(db_session)
        now = datetime.utcnow()

        # Create a user for notification
        user = User(
            username="maintuser",
            email="maint@example.com",
            first_name="Maint",
            last_name="User",
            password_hash="x",
            role="user",
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()

        # Window starting in 10 min (needs notification)
        w1 = await service.create_window(
            title="Notify Window",
            message="Msg",
            start_at=now + timedelta(minutes=10),
            end_at=now + timedelta(minutes=20),
        )

        # Window that started 1 min ago (needs enabling)
        w2 = MaintenanceWindow(
            title="Enable Window",
            message="Msg",
            start_at=now - timedelta(minutes=1),
            end_at=now + timedelta(hours=1),
        )
        db_session.add(w2)

        # Window that ended 1 min ago (needs disabling)
        w3 = MaintenanceWindow(
            title="Disable Window",
            message="Msg",
            start_at=now - timedelta(hours=2),
            end_at=now - timedelta(minutes=1),
        )
        w3.auto_enabled = True
        db_session.add(w3)
        await db_session.commit()
        await db_session.refresh(w2)
        await db_session.refresh(w3)

        result = await service.evaluate_windows()

        assert result["notifications_sent"] >= 1
        assert result["enabled_count"] == 1
        assert result["disabled_count"] == 1

        # Verify flags updated
        await db_session.refresh(w1)
        await db_session.refresh(w2)
        await db_session.refresh(w3)
        assert w1.notified_offsets is not None and len(w1.notified_offsets) > 0
        assert w2.auto_enabled is True
        assert w3.auto_disabled is True


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------

class TestMaintenanceWindowAPI:
    """Tests for maintenance window REST API endpoints."""

    @pytest.mark.asyncio
    async def test_list_requires_admin(self, client, user_token):
        """Non-admin should not list maintenance windows."""
        response = await client.get(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_as_admin(self, client, admin_token, sample_window):
        """Admin should list maintenance windows."""
        response = await client.get(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "windows" in data
        assert any(w["id"] == str(sample_window.id) for w in data["windows"])

    @pytest.mark.asyncio
    async def test_create_requires_admin(self, client, user_token):
        """Non-admin should not create maintenance windows."""
        now = datetime.utcnow()
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "title": "Test",
                "message": "Msg",
                "start_at": (now + timedelta(hours=1)).isoformat(),
                "end_at": (now + timedelta(hours=2)).isoformat(),
            }
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_as_admin(self, client, admin_token):
        """Admin should create a maintenance window."""
        now = datetime.utcnow()
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "title": "API Test Window",
                "message": "Testing via API",
                "start_at": (now + timedelta(hours=1)).isoformat(),
                "end_at": (now + timedelta(hours=2)).isoformat(),
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["window"]["title"] == "API Test Window"

    @pytest.mark.asyncio
    async def test_create_invalid_times(self, client, admin_token):
        """Should reject invalid time ranges."""
        now = datetime.utcnow()
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "title": "Bad",
                "message": "Msg",
                "start_at": (now + timedelta(hours=2)).isoformat(),
                "end_at": (now + timedelta(hours=1)).isoformat(),
            }
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_window(self, client, admin_token, sample_window):
        """Admin should get a single window."""
        response = await client.get(
            f"/api/system/maintenance-windows/{sample_window.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["window"]["id"] == str(sample_window.id)

    @pytest.mark.asyncio
    async def test_get_window_not_found(self, client, admin_token):
        """Should return 404 for non-existent window."""
        response = await client.get(
            f"/api/system/maintenance-windows/{uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_window(self, client, admin_token, sample_window):
        """Admin should update a window."""
        response = await client.put(
            f"/api/system/maintenance-windows/{sample_window.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"title": "Updated via API"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["window"]["title"] == "Updated via API"

    @pytest.mark.asyncio
    async def test_delete_window(self, client, admin_token, sample_window):
        """Admin should delete a window."""
        response = await client.delete(
            f"/api/system/maintenance-windows/{sample_window.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

        # Verify deleted
        response = await client.get(
            f"/api/system/maintenance-windows/{sample_window.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404
