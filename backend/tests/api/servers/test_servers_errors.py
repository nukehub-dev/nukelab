# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Extended tests for Servers API error paths."""

import pytest

from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_plan import ServerPlan


class TestCreateServerErrors:
    """Tests for server creation error paths."""

    @pytest.mark.asyncio
    async def test_create_server_plan_not_found(self, client, user_token):
        """Creating server with non-existent plan should 404."""
        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "test-srv",
                "plan_id": "00000000-0000-0000-0000-000000000000",
                "environment_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert response.status_code == 404
        assert "Plan not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_server_environment_not_found(self, client, user_token, db_session):
        """Creating server with non-existent environment should 404."""
        plan = ServerPlan(
            name="test-plan",
            slug="test-plan",
            cpu_limit=1,
            memory_limit="1g",
            is_public=True,
            is_active=True,
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "test-srv",
                "plan_id": str(plan.id),
                "environment_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert response.status_code == 404
        assert "Environment not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_server_inactive_plan(self, client, user_token, db_session):
        """Creating server with inactive plan should 400."""
        import uuid as uuid_mod

        slug = f"inactive-plan-{uuid_mod.uuid4().hex[:8]}"
        plan = ServerPlan(
            name="inactive-plan",
            slug=slug,
            cpu_limit=1,
            memory_limit="1g",
            is_public=True,
            is_active=False,
        )
        env_name = f"test-env-{uuid_mod.uuid4().hex[:8]}"
        env = EnvironmentTemplate(name=env_name, slug=env_name, image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "test-srv", "plan_id": str(plan.id), "environment_id": str(env.id)},
        )
        assert response.status_code in [400, 403]


class TestServerActionErrors:
    """Tests for server action error paths."""

    @pytest.mark.asyncio
    async def test_get_server_not_found(self, client, user_token):
        """Getting non-existent server should 404."""
        response = await client.get(
            "/api/servers/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_start_server_not_found(self, client, user_token):
        """Starting non-existent server should 404."""
        response = await client.post(
            "/api/servers/00000000-0000-0000-0000-000000000000/start",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_stop_server_not_found(self, client, user_token):
        """Stopping non-existent server should 404."""
        response = await client.post(
            "/api/servers/00000000-0000-0000-0000-000000000000/stop",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_restart_server_not_found(self, client, user_token):
        """Restarting non-existent server should 404."""
        response = await client.post(
            "/api/servers/00000000-0000-0000-0000-000000000000/restart",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_server_not_found(self, client, user_token):
        """Deleting non-existent server should 404."""
        response = await client.delete(
            "/api/servers/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_server_not_found(self, client, user_token):
        """Patching non-existent server should 404 or 403."""
        response = await client.patch(
            "/api/servers/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "new-name"},
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_get_server_volumes_not_found(self, client, user_token):
        """Getting volumes for non-existent server should 404."""
        response = await client.get(
            "/api/servers/00000000-0000-0000-0000-000000000000/volumes",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_server_logs_not_found(self, client, user_token):
        """Getting logs for non-existent server should 404."""
        response = await client.get(
            "/api/servers/00000000-0000-0000-0000-000000000000/logs",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_server_queue_status_not_found(self, client, user_token):
        """Getting queue status for non-existent server."""
        response = await client.get(
            "/api/servers/00000000-0000-0000-0000-000000000000/queue-status",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        # Endpoint may return 200 with not_queued or 404
        assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_get_server_access_token_not_found(self, client, user_token):
        """Getting access token for non-existent server."""
        response = await client.post(
            "/api/servers/00000000-0000-0000-0000-000000000000/access-token",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        # May 404 or 422 depending on body validation
        assert response.status_code in [404, 422]

    @pytest.mark.asyncio
    async def test_get_server_access_stats_not_found(self, client, user_token):
        """Getting access stats for non-existent server should 404."""
        response = await client.get(
            "/api/servers/00000000-0000-0000-0000-000000000000/access-stats",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_server_activity_not_found(self, client, user_token):
        """Posting activity for non-existent server should 404."""
        response = await client.post(
            "/api/servers/00000000-0000-0000-0000-000000000000/activity",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"action": "keepalive"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_user_cannot_access_others_server(
        self, client, user_token, admin_user, db_session
    ):
        """User should not access another user's server."""
        server = Server(name="admin-srv", user_id=admin_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.get(
            f"/api/servers/{server.id}", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]


class TestServerByPath:
    """Tests for server lookup by path."""

    @pytest.mark.asyncio
    async def test_get_server_by_path_not_found(self, client, user_token):
        """Looking up non-existent server by path should 404."""
        response = await client.get(
            "/api/servers/by-path/nonexistent/nonexistent-server",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
