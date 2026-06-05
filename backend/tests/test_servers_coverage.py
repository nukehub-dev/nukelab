"""Coverage-focused tests for servers.py gaps."""

import pytest
from unittest import mock
from datetime import datetime

from app.models.server import Server
from app.models.volume import Volume
from app.models.server_volume import ServerVolume


class TestGetServerVolumes:
    """GET /{id}/volumes endpoint."""

    @pytest.mark.asyncio
    async def test_get_server_volumes(self, client, user_token, test_user, db_session):
        server = Server(name="srv-vol", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.flush()

        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.flush()

        sv = ServerVolume(server_id=server.id, volume_id=vol.id, mount_path="/data")
        db_session.add(sv)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{server.id}/volumes",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "volume_mounts" in data

    @pytest.mark.asyncio
    async def test_get_server_volumes_not_found(self, client, user_token):
        import uuid
        response = await client.get(
            f"/api/servers/{uuid.uuid4()}/volumes",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404


class TestCrossUserAuditMissingReason:
    """Cross-user access without reason -> 400."""

    @pytest.mark.asyncio
    async def test_start_server_cross_user_no_reason(self, client, admin_token, test_user, db_session):
        server = Server(name="srv-start", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(server)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{server.id}/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={}
        )
        assert response.status_code == 400
        assert "reason" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_stop_server_cross_user_no_reason(self, client, admin_token, test_user, db_session):
        server = Server(name="srv-stop", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.container.spawner.spawner.stop", return_value=True):
            response = await client.post(
                f"/api/servers/{server.id}/stop",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={}
            )
        assert response.status_code == 400
        assert "reason" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_server_cross_user_no_reason(self, client, admin_token, test_user, db_session):
        server = Server(name="srv-del", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(server)
        await db_session.commit()

        response = await client.delete(
            f"/api/servers/{server.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400
        assert "reason" in response.json()["detail"].lower()


class TestCreateServerValidation:
    """create_server validation branches."""

    @pytest.mark.asyncio
    async def test_create_server_plan_not_available_for_role(self, client, user_token, test_user, db_session):
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate
        env = EnvironmentTemplate(name="test-env", slug="test-env", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(name="admin-plan", slug="admin-plan", cpu_limit=1.0, memory_limit="512m", disk_limit="10g", is_active=True, visible_to_roles=["admin"])
        db_session.add(plan)
        await db_session.commit()

        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "srv-plan",
                "plan_id": str(plan.id),
                "environment_id": str(env.id)
            }
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_server_quota_exceeded(self, client, user_token, test_user, db_session):
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate
        env = EnvironmentTemplate(name="test-env2", slug="test-env2", image="python:3.11")
        db_session.add(env)
        await db_session.flush()
        plan = ServerPlan(name="basic-plan", slug="basic-plan", cpu_limit=1.0, memory_limit="512m", disk_limit="10g", is_active=True, visible_to_roles=["user"])
        db_session.add(plan)
        await db_session.commit()

        with mock.patch("app.services.quota_service.QuotaService.check_spawn_allowed", return_value={"allowed": False, "reason": "quota exceeded"}):
            response = await client.post(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={
                    "name": "srv-quota",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id)
                }
            )
        assert response.status_code == 429


class TestPerformServerStopNoContainer:
    """_perform_server_stop no container_id path."""

    @pytest.mark.asyncio
    async def test_stop_server_no_container(self, client, user_token, test_user, db_session):
        server = Server(name="srv-nc", user_id=test_user.id, status="running", container_id=None)
        db_session.add(server)
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{server.id}/stop",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "stopped"


class TestGetServerLogsException:
    """get_server_logs generic exception handler."""

    @pytest.mark.asyncio
    async def test_get_server_logs_generic_exception(self, client, user_token, test_user, db_session):
        server = Server(name="srv-logs", user_id=test_user.id, status="running", container_id="c1")
        db_session.add(server)
        await db_session.commit()

        mock_client = mock.MagicMock()
        mock_client.get_container_logs = mock.AsyncMock(side_effect=RuntimeError("boom"))
        with mock.patch("app.api.servers.spawner.container_client", mock_client):
            response = await client.get(
                f"/api/servers/{server.id}/logs",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 500


class TestUpdateServerBranches:
    """update_server untested branches."""

    @pytest.mark.asyncio
    async def test_update_server_cross_user_without_reason(self, client, admin_token, test_user, db_session):
        server = Server(name="srv-patch", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(server)
        await db_session.commit()

        response = await client.patch(
            f"/api/servers/{server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "new-name"}
        )
        assert response.status_code == 400
        assert "reason" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_server_name_only(self, client, admin_token, test_user, db_session):
        server = Server(name="srv-old", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(server)
        await db_session.commit()

        response = await client.patch(
            f"/api/servers/{server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "srv-new", "reason": "Admin update"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "srv-new"
