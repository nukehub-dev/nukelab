"""Extended tests for HealthCheckService (container health checks, auto-restart)."""

import pytest
from datetime import datetime, timedelta, UTC
from unittest import mock
from sqlalchemy import select

from app.services.health_check_service import HealthCheckService, _broadcast_health_update
from app.models.server import Server
from app.models.health_check import HealthCheck


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
        server = Server(name="no-container", user_id=test_user.id, status="running", container_id=None)
        db_session.add(server)
        await db_session.commit()

        service = HealthCheckService(db_session)
        await service.check_all_containers()

    @pytest.mark.asyncio
    async def test_check_container_healthy(self, db_session, test_user):
        """Healthy container should create health check record."""
        server = Server(name="healthy-srv", user_id=test_user.id, status="running", container_id="container123")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)

        mock_client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.show.return_value = {
            "State": {
                "Running": True,
                "Health": {
                    "Status": "healthy",
                    "Log": [{"ExitCode": 0, "Output": "OK"}]
                }
            }
        }
        mock_client.client.containers.get.return_value = mock_container

        with mock.patch("app.services.health_check_service.get_fresh_container_client", return_value=mock_client):
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
        server = Server(name="unhealthy-srv", user_id=test_user.id, status="running", container_id="container456")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)

        mock_client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.show.return_value = {
            "State": {
                "Running": True,
                "Health": {
                    "Status": "unhealthy",
                    "Log": [{"ExitCode": 1, "Output": "FAIL"}]
                }
            }
        }
        mock_client.client.containers.get.return_value = mock_container

        with mock.patch("app.services.health_check_service.get_fresh_container_client", return_value=mock_client):
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
        server = Server(name="error-srv", user_id=test_user.id, status="running", container_id="container789")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)

        with mock.patch("app.services.health_check_service.get_fresh_container_client", side_effect=Exception("Docker down")):
            await service._check_container(server)

        result = await db_session.execute(
            select(HealthCheck).where(HealthCheck.server_id == server.id)
        )
        hc = result.scalar_one()
        assert hc.status == "unknown"

    @pytest.mark.asyncio
    async def test_check_container_no_health_info(self, db_session, test_user):
        """Container without health info but running should be healthy."""
        server = Server(name="no-health", user_id=test_user.id, status="running", container_id="container000")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)

        mock_client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.show.return_value = {
            "State": {"Running": True}
        }
        mock_client.client.containers.get.return_value = mock_container

        with mock.patch("app.services.health_check_service.get_fresh_container_client", return_value=mock_client):
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
        with mock.patch("app.services.health_check_service.settings.server_auto_restart_enabled", False):
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
                server_id=server.id, container_id="c2",
                status="restarting", checked_at=datetime.now(UTC).replace(tzinfo=None)
            )
            db_session.add(hc)
        await db_session.commit()

        service = HealthCheckService(db_session)
        with mock.patch("app.services.health_check_service.settings.server_auto_restart_enabled", True):
            with mock.patch("app.services.health_check_service.settings.server_auto_restart_max_attempts", 3):
                with mock.patch("app.services.health_check_service.settings.server_auto_restart_window", 3600):
                    await service._auto_restart(server)

    @pytest.mark.asyncio
    async def test_auto_restart_no_container_id(self, db_session, test_user):
        """Server without container_id should log and return."""
        server = Server(name="no-cid", user_id=test_user.id, status="running", container_id=None)
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)
        with mock.patch("app.services.health_check_service.settings.server_auto_restart_enabled", True):
            await service._auto_restart(server)

    @pytest.mark.asyncio
    async def test_auto_restart_success(self, db_session, test_user):
        """Successful auto-restart should log and notify."""
        server = Server(name="restart-ok", user_id=test_user.id, status="running", container_id="c3")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)
        with mock.patch("app.services.health_check_service.settings.server_auto_restart_enabled", True):
            with mock.patch("app.services.health_check_service.settings.server_auto_restart_max_attempts", 10):
                with mock.patch("app.services.health_check_service.settings.server_auto_restart_window", 3600):
                    with mock.patch("app.container.spawner.spawner.stop", mock.AsyncMock()) as mock_stop:
                        with mock.patch("app.container.spawner.spawner.start", mock.AsyncMock()) as mock_start:
                            await service._auto_restart(server)
                            mock_stop.assert_called_once_with("c3")
                            mock_start.assert_called_once_with("c3")

    @pytest.mark.asyncio
    async def test_auto_restart_failure(self, db_session, test_user):
        """Failed auto-restart should log failure."""
        server = Server(name="restart-fail", user_id=test_user.id, status="running", container_id="c4")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        service = HealthCheckService(db_session)
        with mock.patch("app.services.health_check_service.settings.server_auto_restart_enabled", True):
            with mock.patch("app.services.health_check_service.settings.server_auto_restart_max_attempts", 10):
                with mock.patch("app.services.health_check_service.settings.server_auto_restart_window", 3600):
                    with mock.patch("app.container.spawner.spawner.stop", side_effect=Exception("Stop failed")):
                        await service._auto_restart(server)

        result = await db_session.execute(
            select(HealthCheck).where(
                HealthCheck.server_id == server.id,
                HealthCheck.status == "restart_failed"
            )
        )
        hc = result.scalar_one()
        assert "Stop failed" in hc.output


class TestBroadcastHealthUpdate:
    """Tests for _broadcast_health_update."""

    @pytest.mark.asyncio
    async def test_broadcast_silent_on_redis_error(self):
        """Redis error should be silently caught."""
        with mock.patch("redis.asyncio.from_url", side_effect=Exception("Redis down")):
            await _broadcast_health_update()
