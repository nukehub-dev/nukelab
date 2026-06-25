"""Tests for SettingService."""

import pytest

from app.config import settings
from app.models.system_setting import SystemSetting
from app.services.setting_service import SettingService


class TestSettingServiceGet:
    """Tests for get method."""

    @pytest.mark.asyncio
    async def test_get_existing_key(self, db_session):
        """Should return value for existing key."""
        db_session.add(SystemSetting(key="test_key", value="test_value"))
        await db_session.commit()

        service = SettingService(db_session)
        result = await service.get("test_key")
        assert result == "test_value"

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, db_session):
        """Should return None for missing key."""
        service = SettingService(db_session)
        result = await service.get("missing_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_missing_key_with_default(self, db_session):
        """Should return default for missing key."""
        service = SettingService(db_session)
        result = await service.get("missing_key", default="fallback")
        assert result == "fallback"


class TestSettingServiceSet:
    """Tests for set method."""

    @pytest.mark.asyncio
    async def test_set_creates_new(self, db_session):
        """Should create new setting row."""
        service = SettingService(db_session)
        row = await service.set("new_key", "new_value")
        assert row.key == "new_key"
        assert row.value == "new_value"

    @pytest.mark.asyncio
    async def test_set_updates_existing(self, db_session):
        """Should update existing setting row."""
        db_session.add(SystemSetting(key="existing_key", value="old_value"))
        await db_session.commit()

        service = SettingService(db_session)
        row = await service.set("existing_key", "updated_value")
        assert row.value == "updated_value"


class TestSettingServiceLoadIntoConfig:
    """Tests for load_into_config method."""

    @pytest.mark.asyncio
    async def test_load_maintenance_mode(self, db_session):
        """Should load maintenance_mode into global settings."""
        db_session.add(SystemSetting(key="maintenance_mode", value="true"))
        await db_session.commit()

        service = SettingService(db_session)
        await service.load_into_config()
        assert settings.maintenance_mode is True

    @pytest.mark.asyncio
    async def test_load_maintenance_message(self, db_session):
        """Should load maintenance_message into global settings."""
        db_session.add(SystemSetting(key="maintenance_message", value="Down for maintenance"))
        await db_session.commit()

        service = SettingService(db_session)
        await service.load_into_config()
        assert settings.maintenance_message == "Down for maintenance"

    @pytest.mark.asyncio
    async def test_load_daily_allowance(self, db_session):
        """Should load credits_daily_allowance into global settings."""
        original = settings.credits_daily_allowance
        db_session.add(SystemSetting(key="daily_allowance_default", value="500"))
        await db_session.commit()

        service = SettingService(db_session)
        await service.load_into_config()
        assert settings.credits_daily_allowance == 500
        # Restore original
        settings.credits_daily_allowance = original

    @pytest.mark.asyncio
    async def test_load_invalid_daily_allowance_ignored(self, db_session):
        """Should ignore invalid daily_allowance_default values."""
        original = settings.credits_daily_allowance
        db_session.add(SystemSetting(key="daily_allowance_default", value="invalid"))
        await db_session.commit()

        service = SettingService(db_session)
        await service.load_into_config()
        assert settings.credits_daily_allowance == original


class TestSettingServiceMaintenance:
    """Tests for maintenance mode helpers."""

    @pytest.mark.asyncio
    async def test_save_maintenance(self, db_session):
        """Should persist maintenance settings."""
        service = SettingService(db_session)
        await service.save_maintenance(enabled=True, message="Test message")

        mode = await service.get("maintenance_mode")
        msg = await service.get("maintenance_message")
        assert mode == "true"
        assert msg == "Test message"
        assert settings.maintenance_mode is True
        assert settings.maintenance_message == "Test message"

    @pytest.mark.asyncio
    async def test_get_maintenance_from_db(self, db_session):
        """Should return maintenance settings from DB."""
        db_session.add(SystemSetting(key="maintenance_mode", value="false"))
        db_session.add(SystemSetting(key="maintenance_message", value=""))
        await db_session.commit()

        service = SettingService(db_session)
        result = await service.get_maintenance()
        assert result["maintenance_mode"] is False
        assert result["maintenance_message"] == ""

    @pytest.mark.asyncio
    async def test_get_maintenance_fallback_to_config(self, db_session):
        """Should fall back to global config when DB has no values."""
        service = SettingService(db_session)
        result = await service.get_maintenance()
        assert result["maintenance_mode"] == settings.maintenance_mode
        assert result["maintenance_message"] == settings.maintenance_message
