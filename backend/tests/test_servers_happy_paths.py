"""Happy-path tests for Servers API with mocked container spawner."""

import pytest
from unittest import mock
from sqlalchemy import select

from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate
from app.models.volume import Volume
from app.models.server_volume import ServerVolume


class TestServerGetEndpoints:
    """Tests for GET server endpoints with mocked spawner."""

    @pytest.mark.asyncio
    async def test_get_own_server(self, client, user_token, test_user, db_session):
        """User should get their own server details."""
        server = Server(
            name="my-server", user_id=test_user.id, status="stopped",
            container_id=None, allocated_cpu=1.0, allocated_memory="1g"
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.get(
            f"/api/servers/{server.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "my-server"
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_get_server_with_container_sync_running(self, client, user_token, test_user, db_session):
        """Server with container_id should sync status with spawner to running."""
        server = Server(
            name="running-srv", user_id=test_user.id, status="stopped",
            container_id="container123", allocated_cpu=2.0
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            response = await client.get(
                f"/api/servers/{server.id}",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_server_container_sync_stopped(self, client, user_token, test_user, db_session):
        """Server should sync to stopped when spawner returns stopped."""
        server = Server(
            name="sync-stopped", user_id=test_user.id, status="running",
            container_id="cid-stopped"
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            response = await client.get(
                f"/api/servers/{server.id}",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_get_server_container_sync_paused(self, client, user_token, test_user, db_session):
        """Server should sync to stopped when spawner returns paused."""
        server = Server(
            name="sync-paused", user_id=test_user.id, status="running",
            container_id="cid-paused"
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.servers.spawner.get_status", return_value="paused"):
            response = await client.get(
                f"/api/servers/{server.id}",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_get_server_container_sync_exited(self, client, user_token, test_user, db_session):
        """Server should sync to stopped when spawner returns exited."""
        server = Server(
            name="sync-exited", user_id=test_user.id, status="running",
            container_id="cid-exited"
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.servers.spawner.get_status", return_value="exited"):
            response = await client.get(
                f"/api/servers/{server.id}",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_get_server_by_path(self, client, user_token, test_user, db_session):
        """Should get server by username and name."""
        server = Server(
            name="path-srv", user_id=test_user.id, status="stopped"
        )
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/by-path/{test_user.username}/path-srv",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "path-srv"

    @pytest.mark.asyncio
    async def test_list_servers(self, client, user_token, test_user, db_session):
        """Should list user's servers."""
        server = Server(name="list-srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "servers" in data
        assert isinstance(data["servers"], list)

    @pytest.mark.asyncio
    async def test_list_servers_admin_sees_all(self, client, admin_token, test_user, admin_user, db_session):
        """Admin should see all servers including other users'."""
        user_server = Server(name="user-srv", user_id=test_user.id, status="stopped")
        admin_server = Server(name="admin-srv", user_id=admin_user.id, status="stopped")
        db_session.add_all([user_server, admin_server])
        await db_session.commit()

        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "servers" in data
        server_names = {s["name"] for s in data["servers"]}
        assert "user-srv" in server_names
        assert "admin-srv" in server_names

    @pytest.mark.asyncio
    async def test_get_server_with_volume_mounts(self, client, user_token, test_user, db_session):
        """Server with volume mounts should include them in response."""
        server = Server(name="vol-srv", user_id=test_user.id, status="stopped")
        volume = Volume(name="vol1", display_name="Volume 1", owner_id=test_user.id, size_bytes=1000)
        db_session.add_all([server, volume])
        await db_session.commit()
        await db_session.refresh(server)
        await db_session.refresh(volume)

        sv = ServerVolume(server_id=server.id, volume_id=volume.id, mount_path="/data")
        db_session.add(sv)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/{server.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "volume_mounts" in data


class TestServerActions:
    """Tests for server action endpoints with mocked spawner."""

    @pytest.mark.asyncio
    async def test_start_server(self, client, user_token, test_user, db_session):
        """Starting a stopped server should succeed."""
        server = Server(
            name="start-srv", user_id=test_user.id, status="stopped",
            container_id="cid1"
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="paused"):
            with mock.patch("app.api.servers.spawner.start", return_value=True) as mock_start:
                response = await client.post(
                    f"/api/servers/{server.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 200
        mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_server(self, client, user_token, test_user, db_session):
        """Stopping a running server should succeed."""
        server = Server(
            name="stop-srv", user_id=test_user.id, status="running",
            container_id="cid2"
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.delete", return_value=True) as mock_delete:
                response = await client.post(
                    f"/api/servers/{server.id}/stop",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 200
        mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_server(self, client, user_token, test_user, db_session):
        """Restarting a running server should succeed."""
        server = Server(
            name="restart-srv", user_id=test_user.id, status="running",
            container_id="cid3"
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.stop", return_value=True) as mock_stop:
                with mock.patch("app.api.servers.spawner.start", return_value=True) as mock_start:
                    response = await client.post(
                        f"/api/servers/{server.id}/restart",
                        headers={"Authorization": f"Bearer {user_token}"}
                    )
        assert response.status_code == 200
        mock_stop.assert_called_once()
        mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_server(self, client, user_token, test_user, db_session):
        """Deleting a server should succeed."""
        server = Server(
            name="del-srv", user_id=test_user.id, status="stopped",
            container_id="cid4"
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.delete", return_value=True) as mock_delete:
            response = await client.delete(
                f"/api/servers/{server.id}",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        mock_delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_patch_server(self, client, admin_token, test_user, db_session):
        """Patching server name as admin should succeed."""
        server = Server(
            name="patch-srv", user_id=test_user.id, status="stopped"
        )
        db_session.add(server)
        await db_session.commit()

        response = await client.patch(
            f"/api/servers/{server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "patched-name", "reason": "Testing patch"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "patched-name"
