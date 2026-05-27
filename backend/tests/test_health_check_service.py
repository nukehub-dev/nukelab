"""Tests for HealthCheckService business logic."""

import pytest
import uuid as uuid_mod
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.health_check_service import HealthCheckService, _broadcast_health_update
from app.models.health_check import HealthCheck
from app.models.server import Server


class TestBroadcastHealthUpdate:
    """Tests for _broadcast_health_update."""

    @pytest.mark.asyncio
    async def test_broadcast_health_update_no_redis(self):
        """Should not raise when redis is unavailable."""
        # This should silently pass even without redis
        await _broadcast_health_update()


class TestHealthCheckServiceAutoRestart:
    """Tests for _auto_restart."""

    @pytest.mark.asyncio
    async def test_auto_restart_disabled(self, db_session, test_user):
        """Should not restart when disabled in settings."""
        server = Server(
            name="srv",
            user_id=test_user.id,
            status="running",
            container_id="abc123",
        )
        db_session.add(server)
        await db_session.commit()

        service = HealthCheckService(db_session)

        with patch("app.config.settings.server_auto_restart_enabled", False):
            await service._auto_restart(server)

        # No health check should be created
        result = await db_session.execute(
            __import__('sqlalchemy', fromlist=['select']).select(HealthCheck).where(HealthCheck.server_id == server.id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_auto_restart_rate_limited(self, db_session, test_user):
        """Should not restart when rate limit exceeded."""
        server = Server(
            name="srv",
            user_id=test_user.id,
            status="running",
            container_id="abc123",
        )
        db_session.add(server)
        await db_session.flush()

        # Create recent restart attempts
        for _ in range(5):
            hc = HealthCheck(
                server_id=server.id,
                container_id="abc123",
                status="restarting",
                checked_at=datetime.utcnow(),
            )
            db_session.add(hc)
        await db_session.commit()

        service = HealthCheckService(db_session)

        with patch("app.config.settings.server_auto_restart_enabled", True):
            with patch("app.config.settings.server_auto_restart_window", 3600):
                with patch("app.config.settings.server_auto_restart_max_attempts", 3):
                    await service._auto_restart(server)

        # Should not create additional restart entries
        result = await db_session.execute(
            __import__('sqlalchemy', fromlist=['select', 'func']).select(__import__('sqlalchemy', fromlist=['func']).func.count()).select_from(HealthCheck).where(HealthCheck.server_id == server.id)
        )
        assert result.scalar() == 5


class TestHealthCheckServiceCheckContainer:
    """Tests for _check_container error paths."""

    @pytest.mark.asyncio
    async def test_check_container_no_container_id(self, db_session, test_user):
        """Should log unknown status when no container_id."""
        server = Server(
            name="srv",
            user_id=test_user.id,
            status="running",
            container_id=None,
        )
        db_session.add(server)
        await db_session.commit()

        service = HealthCheckService(db_session)
        await service._check_container(server)

        result = await db_session.execute(
            __import__('sqlalchemy', fromlist=['select']).select(HealthCheck).where(HealthCheck.server_id == server.id)
        )
        hc = result.scalar_one_or_none()
        assert hc is not None
        assert hc.status == "unknown"


class TestHealthCheckServiceCheckAll:
    """Tests for check_all_containers."""

    @pytest.mark.asyncio
    async def test_check_all_no_running(self, db_session):
        """Should do nothing when no running servers."""
        service = HealthCheckService(db_session)
        await service.check_all_containers()  # Should not raise

    @pytest.mark.asyncio
    async def test_check_all_skips_missing_container_id(self, db_session, test_user):
        """Should skip servers without container_id."""
        server = Server(
            name="srv",
            user_id=test_user.id,
            status="running",
            container_id=None,
        )
        db_session.add(server)
        await db_session.commit()

        service = HealthCheckService(db_session)
        await service.check_all_containers()  # Should not raise
