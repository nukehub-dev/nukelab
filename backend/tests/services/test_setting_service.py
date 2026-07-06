# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

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
        db_session.add(SystemSetting(key="credits_daily_allowance", value="500"))
        await db_session.commit()

        service = SettingService(db_session)
        await service.load_into_config()
        assert settings.credits_daily_allowance == 500
        # Restore original
        settings.credits_daily_allowance = original

    @pytest.mark.asyncio
    async def test_load_invalid_daily_allowance_ignored(self, db_session):
        """Should ignore invalid credits_daily_allowance values."""
        original = settings.credits_daily_allowance
        db_session.add(SystemSetting(key="credits_daily_allowance", value="invalid"))
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


class TestSettingServiceQuotaDefaults:
    """Tests for default resource quota settings."""

    @pytest.mark.asyncio
    async def test_get_quota_defaults_fallback(self, db_session):
        """Should return hardcoded defaults when no settings exist."""
        service = SettingService(db_session)
        result = await service.get_quota_defaults()
        assert result["max_cpu_total"] == 8.0
        assert result["max_memory_total"] == "16g"
        assert result["max_disk_total"] == "100g"
        assert result["max_gpu_total"] == 0
        assert result["max_servers_total"] == 5

    @pytest.mark.asyncio
    async def test_get_quota_defaults_from_db(self, db_session):
        """Should read defaults from system settings."""
        db_session.add(SystemSetting(key="quota_default_max_cpu_total", value="16"))
        db_session.add(SystemSetting(key="quota_default_max_memory_total", value="32g"))
        db_session.add(SystemSetting(key="quota_default_max_servers_total", value="10"))
        await db_session.commit()

        service = SettingService(db_session)
        result = await service.get_quota_defaults()
        assert result["max_cpu_total"] == 16.0
        assert result["max_memory_total"] == "32g"
        assert result["max_servers_total"] == 10

    @pytest.mark.asyncio
    async def test_set_quota_defaults(self, db_session):
        """Should persist default quota settings."""
        service = SettingService(db_session)
        await service.set_quota_defaults(
            {
                "max_cpu_total": 4.0,
                "max_memory_total": "8g",
                "max_disk_total": "50g",
                "max_gpu_total": 0,
                "max_servers_total": 3,
            }
        )

        result = await service.get_quota_defaults()
        assert result["max_cpu_total"] == 4.0
        assert result["max_memory_total"] == "8g"
        assert result["max_disk_total"] == "50g"
        assert result["max_gpu_total"] == 0
        assert result["max_servers_total"] == 3
