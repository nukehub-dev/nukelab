"""Tests for miscellaneous server API endpoints."""

import pytest
from unittest import mock
import uuid as uuid_mod
import aiodocker

from app.models.server import Server
from app.models.server_queue import ServerQueue
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate
from app.api.servers import spawner


class TestServerQueueStatus:
    """Tests for GET /api/servers/{id}/queue-status."""

    @pytest.mark.asyncio
    async def test_queue_status_empty(self, client, user_token, test_user, db_session):
        """Should return not queued when no entries."""
        server = Server(name="q-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{server.id}/queue-status",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["queued"] is False
        assert data["entries"] == []

    @pytest.mark.asyncio
    async def test_queue_status_with_entries(self, client, user_token, test_user, db_session):
        """Should return queue entries with positions."""
        server = Server(name="q-srv", user_id=test_user.id, status="running")
        db_session.add(server)

        env = EnvironmentTemplate(
            id=uuid_mod.uuid4(),
            name=f"env-{uuid_mod.uuid4().hex[:8]}",
            slug=f"env-{uuid_mod.uuid4().hex[:8]}",
            image="img",
        )
        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name=f"plan-{uuid_mod.uuid4().hex[:8]}",
            slug=f"plan-{uuid_mod.uuid4().hex[:8]}",
            cpu_limit=1.0,
            memory_limit="1g",
            disk_limit="10g",
            is_active=True,
        )
        db_session.add_all([env, plan])
        await db_session.commit()

        entry = ServerQueue(
            user_id=test_user.id,
            environment_id=env.id,
            plan_id=plan.id,
            server_name="queued-srv",
            status="pending",
            priority=1,
        )
        db_session.add(entry)
        await db_session.commit()

        with mock.patch("app.services.resource_pool_service.ResourcePoolService") as mock_pool_cls:
            mock_pool = mock_pool_cls.return_value
            mock_pool.get_queue_position = mock.AsyncMock(return_value=1)
            response = await client.get(
                f"/api/servers/{server.id}/queue-status",
                headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["queued"] is True
        assert len(data["entries"]) == 1
        assert data["entries"][0]["server_name"] == "queued-srv"


class TestServerLogs:
    """Tests for GET /api/servers/{id}/logs."""

    @pytest.mark.asyncio
    async def test_logs_server_stopped(self, client, user_token, test_user, db_session):
        """Stopped server should return empty logs."""
        server = Server(name="log-srv", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{server.id}/logs",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["logs"] == ""
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_logs_running_server(self, client, user_token, test_user, db_session):
        """Running server should return logs."""
        server = Server(name="log-srv", user_id=test_user.id, status="running", container_id="cid-logs")
        db_session.add(server)
        await db_session.commit()

        mock_client = mock.AsyncMock()
        mock_client.get_container_logs = mock.AsyncMock(return_value="log output")
        original = spawner.container_client
        spawner.container_client = mock_client
        try:
            response = await client.get(
                f"/api/servers/{server.id}/logs",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        finally:
            spawner.container_client = original

        assert response.status_code == 200
        data = response.json()
        assert data["logs"] == "log output"
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_logs_docker_error(self, client, user_token, test_user, db_session):
        """DockerError should return empty logs with error status."""
        server = Server(name="log-docker-err", user_id=test_user.id, status="running", container_id="cid-err")
        db_session.add(server)
        await db_session.commit()

        mock_client = mock.AsyncMock()
        mock_client.get_container_logs = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=404, data={"message": "not found"})
        )
        original = spawner.container_client
        spawner.container_client = mock_client
        try:
            response = await client.get(
                f"/api/servers/{server.id}/logs",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        finally:
            spawner.container_client = original

        assert response.status_code == 200
        data = response.json()
        assert data["logs"] == ""
        assert data["status"] == "error"


class TestServerActivity:
    """Tests for POST /api/servers/{id}/activity."""

    @pytest.mark.asyncio
    async def test_ping_server_activity_success(self, client, user_token, test_user, db_session):
        """Activity ping on running server should succeed."""
        server = Server(name="act-srv", user_id=test_user.id, status="running", container_id="cid-act")
        db_session.add(server)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{server.id}/activity",
            headers={"Authorization": f"Bearer {user_token}"},
            json={}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Activity recorded"
        assert "last_activity" in data

    @pytest.mark.asyncio
    async def test_ping_server_activity_not_running(self, client, user_token, test_user, db_session):
        """Activity ping on non-running server should return 400."""
        server = Server(name="act-stopped", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{server.id}/activity",
            headers={"Authorization": f"Bearer {user_token}"},
            json={}
        )
        assert response.status_code == 400
        assert "not running" in response.json()["detail"].lower()


class TestServerTestMetric:
    """Tests for POST /api/servers/{id}/test-metric."""

    @pytest.mark.asyncio
    async def test_test_metric_smoke(self, client, user_token, test_user, db_session):
        """Test metric endpoint should publish and return connection info."""
        server = Server(name="metric-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        with mock.patch("redis.asyncio.from_url") as mock_redis_cls:
            mock_r = mock.AsyncMock()
            mock_redis_cls.return_value = mock_r

            response = await client.post(
                f"/api/servers/{server.id}/test-metric",
                headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Test metric published"
        assert data["server_id"] == str(server.id)
        assert "metric" in data
        mock_r.publish.assert_called()


class TestServerAccessToken:
    """Tests for POST /api/servers/{id}/access-token."""

    @pytest.mark.asyncio
    async def test_access_token_server_not_running(self, client, user_token, test_user, db_session):
        """Should return 400 if server is not running."""
        server = Server(name="tok-srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{server.id}/access-token",
            headers={"Authorization": f"Bearer {user_token}"},
            json={}
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_access_token_auth_disabled(self, client, user_token, test_user, db_session):
        """Should return 503 if server auth is disabled."""
        server = Server(name="tok-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.config.settings.rate_limit_enabled", False):
            with mock.patch("app.services.server_auth_service.server_auth_service") as mock_svc:
                mock_svc.is_enabled = False
                response = await client.post(
                    f"/api/servers/{server.id}/access-token",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={}
                )

        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_access_token_success(self, client, user_token, test_user, db_session):
        """Should return 200 with cookie when auth is enabled."""
        server = Server(name="tok-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.services.server_auth_service.server_auth_service") as mock_svc:
            mock_svc.is_enabled = True
            mock_svc.generate_access_token = mock.AsyncMock(return_value="test-token")
            response = await client.post(
                f"/api/servers/{server.id}/access-token",
                headers={"Authorization": f"Bearer {user_token}"},
                json={}
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_access_token_rate_limit(self, client, user_token, test_user, db_session):
        """Should return 429 when rate limit is exceeded."""
        server = Server(name="tok-rate", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.config.settings.rate_limit_enabled", False):
            with mock.patch("app.services.server_auth_service.server_auth_service") as mock_svc:
                mock_svc.is_enabled = True
                mock_svc.generate_access_token = mock.AsyncMock(side_effect=ValueError("rate limit"))
                response = await client.post(
                    f"/api/servers/{server.id}/access-token",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={}
                )

        assert response.status_code == 429
        assert "rate limit" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_access_stats(self, client, user_token, test_user, db_session):
        """Should return access stats for a server."""
        server = Server(name="tok-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.services.server_auth_service.server_auth_service") as mock_svc:
            mock_svc.get_server_access_stats = mock.AsyncMock(return_value={"total_requests": 10})
            response = await client.get(
                f"/api/servers/{server.id}/access-stats",
                headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total_requests"] == 10
