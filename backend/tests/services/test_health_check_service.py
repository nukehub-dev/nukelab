# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for HealthCheckService business logic."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.models.health_check import HealthCheck
from app.models.server import Server
from app.services.health_check_service import HealthCheckService, _broadcast_health_update


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
            __import__("sqlalchemy", fromlist=["select"])
            .select(HealthCheck)
            .where(HealthCheck.server_id == server.id)
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
                checked_at=datetime.now(UTC).replace(tzinfo=None),
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
            __import__("sqlalchemy", fromlist=["select", "func"])
            .select(__import__("sqlalchemy", fromlist=["func"]).func.count())
            .select_from(HealthCheck)
            .where(HealthCheck.server_id == server.id)
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
            __import__("sqlalchemy", fromlist=["select"])
            .select(HealthCheck)
            .where(HealthCheck.server_id == server.id)
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


"""Extended tests for HealthCheckService (container health checks, auto-restart)."""

from unittest import mock

import pytest
from sqlalchemy import select


class TestCheckAllContainers:
    """Tests for check_all_containers method."""

    @pytest.mark.asyncio
    async def test_no_running_servers(self, db_session):
        """When no servers are running, should do nothing."""
        service = HealthCheckService(db_session)
        await service.check_all_containers()
        # No exception should be raised

    @pytest.mark.asyncio
    async def test_running_server_without_container_id(self, db_session, test_user):
        """Running server without container_id should be skipped."""
        server = Server(
            name="no-container", user_id=test_user.id, status="running", container_id=None
        )
        db_session.add(server)
        await db_session.commit()

        service = HealthCheckService(db_session)
        await service.check_all_containers()

    @pytest.mark.asyncio
    async def test_check_container_healthy(self, db_session, test_user):
        """Healthy container should create health check record."""
        server = Server(
            name="healthy-srv", user_id=test_user.id, status="running", container_id="container123"
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)

        mock_client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.show.return_value = {
            "State": {
                "Running": True,
                "Health": {"Status": "healthy", "Log": [{"ExitCode": 0, "Output": "OK"}]},
            }
        }
        mock_client.client.containers.get.return_value = mock_container

        with mock.patch(
            "app.services.health_check_service.get_fresh_container_client", return_value=mock_client
        ):
            await service._check_container(server)

        result = await db_session.execute(
            select(HealthCheck).where(HealthCheck.server_id == server.id)
        )
        hc = result.scalar_one()
        assert hc.status == "healthy"
        assert hc.container_id == "container123"

    @pytest.mark.asyncio
    async def test_check_container_unhealthy(self, db_session, test_user):
        """Unhealthy container should create health check with consecutive failures."""
        server = Server(
            name="unhealthy-srv",
            user_id=test_user.id,
            status="running",
            container_id="container456",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)

        mock_client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.show.return_value = {
            "State": {
                "Running": True,
                "Health": {"Status": "unhealthy", "Log": [{"ExitCode": 1, "Output": "FAIL"}]},
            }
        }
        mock_client.client.containers.get.return_value = mock_container

        with mock.patch(
            "app.services.health_check_service.get_fresh_container_client", return_value=mock_client
        ):
            await service._check_container(server)

        result = await db_session.execute(
            select(HealthCheck).where(HealthCheck.server_id == server.id)
        )
        hc = result.scalar_one()
        assert hc.status == "unhealthy"
        assert hc.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_check_container_exception(self, db_session, test_user):
        """Container check exception should create unknown status record."""
        server = Server(
            name="error-srv", user_id=test_user.id, status="running", container_id="container789"
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)

        with mock.patch(
            "app.services.health_check_service.get_fresh_container_client",
            side_effect=Exception("Docker down"),
        ):
            await service._check_container(server)

        result = await db_session.execute(
            select(HealthCheck).where(HealthCheck.server_id == server.id)
        )
        hc = result.scalar_one()
        assert hc.status == "unknown"

    @pytest.mark.asyncio
    async def test_check_container_no_health_info(self, db_session, test_user):
        """Container without health info but running should be healthy."""
        server = Server(
            name="no-health", user_id=test_user.id, status="running", container_id="container000"
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)

        mock_client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.show.return_value = {"State": {"Running": True}}
        mock_client.client.containers.get.return_value = mock_container

        with mock.patch(
            "app.services.health_check_service.get_fresh_container_client", return_value=mock_client
        ):
            await service._check_container(server)

        result = await db_session.execute(
            select(HealthCheck).where(HealthCheck.server_id == server.id)
        )
        hc = result.scalar_one()
        assert hc.status == "healthy"


class TestAutoRestart:
    """Tests for _auto_restart method."""

    @pytest.mark.asyncio
    async def test_auto_restart_disabled(self, db_session, test_user):
        """When auto-restart is disabled, should do nothing."""
        server = Server(name="auto-srv", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(server)
        await db_session.commit()

        service = HealthCheckService(db_session)
        with mock.patch(
            "app.services.health_check_service.settings.server_auto_restart_enabled", False
        ):
            await service._auto_restart(server)

    @pytest.mark.asyncio
    async def test_auto_restart_rate_limited(self, db_session, test_user):
        """When restart count exceeds limit, should not restart."""
        server = Server(name="rate-srv", user_id=test_user.id, status="running", container_id="c2")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        # Create multiple recent restarting entries
        for _ in range(5):
            hc = HealthCheck(
                server_id=server.id,
                container_id="c2",
                status="restarting",
                checked_at=datetime.now(UTC).replace(tzinfo=None),
            )
            db_session.add(hc)
        await db_session.commit()

        service = HealthCheckService(db_session)
        with (
            mock.patch(
                "app.services.health_check_service.settings.server_auto_restart_enabled", True
            ),
            mock.patch(
                "app.services.health_check_service.settings.server_auto_restart_max_attempts", 3
            ),
            mock.patch(
                "app.services.health_check_service.settings.server_auto_restart_window", 3600
            ),
        ):
            await service._auto_restart(server)

    @pytest.mark.asyncio
    async def test_auto_restart_no_container_id(self, db_session, test_user):
        """Server without container_id should log and return."""
        server = Server(name="no-cid", user_id=test_user.id, status="running", container_id=None)
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)
        with mock.patch(
            "app.services.health_check_service.settings.server_auto_restart_enabled", True
        ):
            await service._auto_restart(server)

    @pytest.mark.asyncio
    async def test_auto_restart_success(self, db_session, test_user):
        """Successful auto-restart should log and notify."""
        server = Server(
            name="restart-ok", user_id=test_user.id, status="running", container_id="c3"
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)
        with (
            mock.patch(
                "app.services.health_check_service.settings.server_auto_restart_enabled", True
            ),
            mock.patch(
                "app.services.health_check_service.settings.server_auto_restart_max_attempts", 10
            ),
            mock.patch(
                "app.services.health_check_service.settings.server_auto_restart_window", 3600
            ),
            mock.patch("app.container.spawner.spawner.stop", mock.AsyncMock()) as mock_stop,
            mock.patch("app.container.spawner.spawner.start", mock.AsyncMock()) as mock_start,
        ):
            await service._auto_restart(server)
            mock_stop.assert_called_once_with("c3")
            mock_start.assert_called_once_with("c3")

    @pytest.mark.asyncio
    async def test_auto_restart_failure(self, db_session, test_user):
        """Failed auto-restart should log failure."""
        server = Server(
            name="restart-fail", user_id=test_user.id, status="running", container_id="c4"
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)
        with (
            mock.patch(
                "app.services.health_check_service.settings.server_auto_restart_enabled", True
            ),
            mock.patch(
                "app.services.health_check_service.settings.server_auto_restart_max_attempts", 10
            ),
            mock.patch(
                "app.services.health_check_service.settings.server_auto_restart_window", 3600
            ),
            mock.patch("app.container.spawner.spawner.stop", side_effect=Exception("Stop failed")),
        ):
            await service._auto_restart(server)

        result = await db_session.execute(
            select(HealthCheck).where(
                HealthCheck.server_id == server.id, HealthCheck.status == "restart_failed"
            )
        )
        hc = result.scalar_one()
        assert "Stop failed" in hc.output


class TestBroadcastHealthUpdateExtended:
    """Tests for _broadcast_health_update."""

    @pytest.mark.asyncio
    async def test_broadcast_silent_on_redis_error(self):
        """Redis error should be silently caught."""
        with mock.patch("redis.asyncio.from_url", side_effect=Exception("Redis down")):
            await _broadcast_health_update()
