"""Tests for RetentionService."""

import pytest
from sqlalchemy import select

from app.services.retention_service import RetentionService
from app.models.system_setting import SystemSetting
from app.core.retention import DEFAULT_RETENTION_POLICIES


class TestRetentionServiceGetPolicy:
    """Tests for get_policy method."""

    @pytest.mark.asyncio
    async def test_get_policy_defaults(self, db_session):
        """Should return default policies when DB is empty."""
        service = RetentionService(db_session)
        policy = await service.get_policy()
        assert policy == DEFAULT_RETENTION_POLICIES

    @pytest.mark.asyncio
    async def test_get_policy_overrides_from_db(self, db_session):
        """Should override defaults with DB values."""
        setting = SystemSetting(key="metrics_retention_days", value="42")
        db_session.add(setting)
        await db_session.commit()

        service = RetentionService(db_session)
        policy = await service.get_policy()
        assert policy["metrics_retention_days"] == 42
        # Other defaults still present
        assert "system_metrics_retention_days" in policy

    @pytest.mark.asyncio
    async def test_get_policy_boolean_conversion(self, db_session):
        """Should convert boolean strings correctly."""
        setting = SystemSetting(key="cleanup_enabled", value="false")
        db_session.add(setting)
        await db_session.commit()

        service = RetentionService(db_session)
        policy = await service.get_policy()
        assert policy["cleanup_enabled"] is False

    @pytest.mark.asyncio
    async def test_get_policy_invalid_int_ignored(self, db_session):
        """Should keep default when DB value is invalid int."""
        setting = SystemSetting(key="metrics_retention_days", value="invalid")
        db_session.add(setting)
        await db_session.commit()

        service = RetentionService(db_session)
        policy = await service.get_policy()
        assert policy["metrics_retention_days"] == DEFAULT_RETENTION_POLICIES["metrics_retention_days"]


class TestRetentionServiceSetPolicy:
    """Tests for set_policy method."""

    @pytest.mark.asyncio
    async def test_set_valid_policy(self, db_session):
        """Should update a valid policy setting."""
        service = RetentionService(db_session)
        result = await service.set_policy({"metrics_retention_days": 14})
        assert result["metrics_retention_days"] == 14

    @pytest.mark.asyncio
    async def test_set_invalid_key_raises(self, db_session):
        """Should raise ValueError for unknown keys."""
        service = RetentionService(db_session)
        with pytest.raises(ValueError, match="Unknown retention setting"):
            await service.set_policy({"unknown_key": 123})

    @pytest.mark.asyncio
    async def test_set_out_of_range_raises(self, db_session):
        """Should raise ValueError for out-of-range values."""
        service = RetentionService(db_session)
        with pytest.raises(ValueError, match="between"):
            await service.set_policy({"metrics_retention_days": 99999})

    @pytest.mark.asyncio
    async def test_set_boolean_from_string(self, db_session):
        """Should convert string 'false' to boolean False."""
        service = RetentionService(db_session)
        result = await service.set_policy({"cleanup_enabled": "false"})
        assert result["cleanup_enabled"] is False

    @pytest.mark.asyncio
    async def test_set_creates_new_row(self, db_session):
        """Should create a new SystemSetting row if key doesn't exist."""
        service = RetentionService(db_session)
        await service.set_policy({"metrics_retention_days": 21})

        result = await db_session.execute(
            select(SystemSetting).where(SystemSetting.key == "metrics_retention_days")
        )
        row = result.scalar_one()
        assert row.value == "21"

    @pytest.mark.asyncio
    async def test_set_updates_existing_row(self, db_session):
        """Should update existing SystemSetting row."""
        db_session.add(SystemSetting(key="metrics_retention_days", value="7"))
        await db_session.commit()

        service = RetentionService(db_session)
        await service.set_policy({"metrics_retention_days": 30})

        result = await db_session.execute(
            select(SystemSetting).where(SystemSetting.key == "metrics_retention_days")
        )
        row = result.scalar_one()
        assert row.value == "30"

    @pytest.mark.asyncio
    async def test_set_invalid_int_raises(self, db_session):
        """Should raise ValueError for non-integer int values."""
        service = RetentionService(db_session)
        with pytest.raises(ValueError, match="Invalid integer value"):
            await service.set_policy({"metrics_retention_days": "abc"})

    @pytest.mark.asyncio
    async def test_set_cleanup_run_hour_range(self, db_session):
        """Should validate cleanup_run_hour is within 0-23."""
        service = RetentionService(db_session)
        with pytest.raises(ValueError, match="between"):
            await service.set_policy({"cleanup_run_hour": 25})

    @pytest.mark.asyncio
    async def test_set_valid_cleanup_run_hour(self, db_session):
        """Should accept valid cleanup_run_hour."""
        service = RetentionService(db_session)
        result = await service.set_policy({"cleanup_run_hour": 12})
        assert result["cleanup_run_hour"] == 12
