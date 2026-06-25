"""Tests for MaintenanceWindow model, service, and API endpoints."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.config import settings
from app.models.maintenance_window import MaintenanceWindow
from app.services.maintenance_window_service import MaintenanceWindowService

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


class TestMaintenanceWindowModel:
    """Tests for the MaintenanceWindow database model."""

    @pytest.mark.asyncio
    async def test_create_window(self, db_session):
        """Should create a maintenance window with correct defaults."""
        now = datetime.now(UTC).replace(tzinfo=None)
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
        now = datetime.now(UTC).replace(tzinfo=None)
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
