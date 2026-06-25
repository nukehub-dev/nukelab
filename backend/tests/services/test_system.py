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
