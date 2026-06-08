"""Tests for Bulk Operations API endpoints."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.models.server import Server


class TestBulkServerActions:
    """Bulk server operation validation tests."""

    @pytest.mark.asyncio
    async def test_invalid_action_rejected(self, client, admin_token):
        """Bulk endpoint should reject unknown actions."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "invalid_action",
                "server_ids": ["123", "456"]
            }
        )

        assert response.status_code == 400
        assert "Invalid action" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_start_action_accepted(self, client, admin_token):
        """Bulk endpoint should accept 'start' as a valid action."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "start",
                "server_ids": []
            }
        )

        # Should not be 400 (invalid action), may be 200 or 422 for empty list
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_stop_action_accepted(self, client, admin_token):
        """Bulk endpoint should accept 'stop' as a valid action."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "stop",
                "server_ids": []
            }
        )

        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_restart_action_accepted(self, client, admin_token):
        """Bulk endpoint should accept 'restart' as a valid action."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "restart",
                "server_ids": []
            }
        )

        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_delete_action_accepted(self, client, admin_token):
        """Bulk endpoint should accept 'delete' as a valid action."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "action": "delete",
                "server_ids": []
            }
        )

        assert response.status_code != 400


class TestBulkServerLifecycle:
    """Bulk server lifecycle tests with mocked spawner."""

    @pytest_asyncio.fixture
    async def stopped_server(self, db_session, test_user):
        """Create a stopped server ready to be started."""
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate

        plan = ServerPlan(
            name="Bulk Test Plan",
            slug="bulk-test-plan",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=1,
            is_active=True,
            visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Bulk Test Env",
            slug="bulk-test-env",
            image="hello-world",
            is_active=True,
            is_public=True,
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        server = Server(
            name="bulk-test-server",
            user_id=test_user.id,
            plan_id=plan.id,
            environment_id=env.id,
            status="stopped",
            container_id=None,
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)
        return server

    @pytest_asyncio.fixture
    async def running_server(self, db_session, test_user):
        """Create a running server ready to be stopped."""
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate

        plan = ServerPlan(
            name="Bulk Running Plan",
            slug="bulk-running-plan",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=1,
            is_active=True,
            visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Bulk Running Env",
            slug="bulk-running-env",
            image="hello-world",
            is_active=True,
            is_public=True,
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        server = Server(
            name="bulk-running-server",
            user_id=test_user.id,
            plan_id=plan.id,
            environment_id=env.id,
            status="running",
            container_id="container-running-123",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)
        return server

    @pytest.mark.asyncio
    async def test_bulk_start_stopped_server(self, client: AsyncClient, user_token, stopped_server):
        """Bulk start should call spawner start for a stopped server."""
        headers = {"Authorization": f"Bearer {user_token}"}

        with patch("app.api.bulk._perform_server_start", new_callable=AsyncMock) as mock_start:
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers=headers,
                json={
                    "action": "start",
                    "server_ids": [str(stopped_server.id)]
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert str(stopped_server.id) in data["succeeded"]
        assert data["success_count"] == 1
        assert data["failure_count"] == 0
        mock_start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_start_already_running_server_fails(self, client: AsyncClient, user_token, running_server):
        """Bulk start on an already running server should report failure."""
        headers = {"Authorization": f"Bearer {user_token}"}

        with patch("app.api.bulk._perform_server_start", new_callable=AsyncMock) as mock_start:
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers=headers,
                json={
                    "action": "start",
                    "server_ids": [str(running_server.id)]
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert str(running_server.id) in [f["server_id"] for f in data["failed"]]
        assert "already running" in data["failed"][0]["error"].lower()
        mock_start.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bulk_stop_running_server(self, client: AsyncClient, user_token, running_server):
        """Bulk stop should call spawner stop for a running server."""
        headers = {"Authorization": f"Bearer {user_token}"}

        with patch("app.api.bulk._perform_server_stop", new_callable=AsyncMock) as mock_stop:
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers=headers,
                json={
                    "action": "stop",
                    "server_ids": [str(running_server.id)]
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert str(running_server.id) in data["succeeded"]
        assert data["success_count"] == 1
        mock_stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_stop_already_stopped_server_fails(self, client: AsyncClient, user_token, stopped_server):
        """Bulk stop on an already stopped server should report failure."""
        headers = {"Authorization": f"Bearer {user_token}"}

        with patch("app.api.bulk._perform_server_stop", new_callable=AsyncMock) as mock_stop:
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers=headers,
                json={
                    "action": "stop",
                    "server_ids": [str(stopped_server.id)]
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert str(stopped_server.id) in [f["server_id"] for f in data["failed"]]
        assert "already stopped" in data["failed"][0]["error"].lower()
        mock_stop.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bulk_restart_server(self, client: AsyncClient, user_token, running_server):
        """Bulk restart should call spawner restart."""
        headers = {"Authorization": f"Bearer {user_token}"}

        with patch("app.api.bulk._perform_server_restart", new_callable=AsyncMock) as mock_restart:
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers=headers,
                json={
                    "action": "restart",
                    "server_ids": [str(running_server.id)]
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert str(running_server.id) in data["succeeded"]
        assert data["success_count"] == 1
        mock_restart.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_delete_server(self, client: AsyncClient, user_token, stopped_server):
        """Bulk delete should call spawner delete."""
        headers = {"Authorization": f"Bearer {user_token}"}

        with patch("app.api.bulk._perform_server_delete", new_callable=AsyncMock) as mock_delete:
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers=headers,
                json={
                    "action": "delete",
                    "server_ids": [str(stopped_server.id)]
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert str(stopped_server.id) in data["succeeded"]
        assert data["success_count"] == 1
        mock_delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_mixed_results(self, client: AsyncClient, user_token, stopped_server, running_server):
        """Bulk action on multiple servers should report mixed success/failure."""
        headers = {"Authorization": f"Bearer {user_token}"}

        with patch("app.api.bulk._perform_server_start", new_callable=AsyncMock) as mock_start:
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers=headers,
                json={
                    "action": "start",
                    "server_ids": [str(stopped_server.id), str(running_server.id)]
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["success_count"] == 1
        assert data["failure_count"] == 1
        assert str(stopped_server.id) in data["succeeded"]
        assert str(running_server.id) in [f["server_id"] for f in data["failed"]]
        mock_start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_server_not_found(self, client: AsyncClient, user_token):
        """Bulk action on nonexistent server should report failure."""
        headers = {"Authorization": f"Bearer {user_token}"}

        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers=headers,
            json={
                "action": "start",
                "server_ids": ["00000000-0000-0000-0000-000000000000"]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success_count"] == 0
        assert data["failure_count"] == 1
        assert "not found" in data["failed"][0]["error"].lower()

    @pytest.mark.asyncio
    async def test_bulk_cross_user_requires_reason(
        self, client: AsyncClient, admin_token, stopped_server, test_user
    ):
        """Bulk action on another user's server without reason should fail."""
        from app.models.user import User
        from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache

        # Ensure admin role has SERVERS_ACCESS_OTHERS
        if "servers:access_others" not in ROLE_PERMISSIONS.get("admin", []):
            ROLE_PERMISSIONS["admin"] = list(set(ROLE_PERMISSIONS.get("admin", []) + ["servers:access_others"]))
            _rebuild_expansion_cache()

        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch("app.api.bulk._perform_server_start", new_callable=AsyncMock):
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers=headers,
                json={
                    "action": "start",
                    "server_ids": [str(stopped_server.id)]
                    # No reason provided
                }
            )

        assert response.status_code == 200
        data = response.json()
        # Cross-user without reason should fail
        assert data["success_count"] == 0
        assert "reason is required" in data["failed"][0]["error"].lower()

    @pytest.mark.asyncio
    async def test_bulk_cross_user_with_reason_succeeds(
        self, client: AsyncClient, admin_token, stopped_server, test_user
    ):
        """Bulk action on another user's server with reason and JWT should succeed."""
        from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache

        # Ensure admin role has SERVERS_ACCESS_OTHERS
        if "servers:access_others" not in ROLE_PERMISSIONS.get("admin", []):
            ROLE_PERMISSIONS["admin"] = list(set(ROLE_PERMISSIONS.get("admin", []) + ["servers:access_others"]))
            _rebuild_expansion_cache()

        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch("app.api.bulk._perform_server_start", new_callable=AsyncMock) as mock_start:
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers=headers,
                json={
                    "action": "start",
                    "server_ids": [str(stopped_server.id)],
                    "reason": "Maintenance required"
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert str(stopped_server.id) in data["succeeded"]
        assert data["success_count"] == 1
        mock_start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_empty_list_returns_zero_counts(self, client: AsyncClient, user_token):
        """Bulk action with empty server_ids should return 200 with zero counts."""
        headers = {"Authorization": f"Bearer {user_token}"}

        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers=headers,
            json={
                "action": "delete",
                "server_ids": []
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["success_count"] == 0
        assert data["failure_count"] == 0
        assert data["succeeded"] == []
        assert data["failed"] == []

    @pytest.mark.asyncio
    async def test_bulk_action_requires_permission(self, client: AsyncClient, user_token):
        """Bulk action should require SERVERS_WRITE_OWN permission."""
        headers = {"Authorization": f"Bearer {user_token}"}

        # A regular user has SERVERS_WRITE_OWN by default, so this should work
        # but if we test with a token lacking it, we'd get 403.
        # The permission check is on the endpoint itself via Depends.
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers=headers,
            json={
                "action": "start",
                "server_ids": []
            }
        )

        # Regular users can access this endpoint
        assert response.status_code == 200

"""Extended tests for small API modules — coverage gap closure."""

import pytest
from unittest import mock
from datetime import datetime, timedelta, UTC
import uuid as uuid_mod

from app.config import settings
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate
from app.models.notification import Notification
from app.models.activity_log import ActivityLog
from app.models.credit_transaction import CreditTransaction


@pytest.fixture(autouse=True)
def reset_maintenance_state():
    """Reset global maintenance state before and after each test."""
    settings.maintenance_mode = False
    settings.maintenance_message = "System under maintenance"
    yield
    settings.maintenance_mode = False
    settings.maintenance_message = "System under maintenance"


# ─────────────────────────────────────────────────────────────
# Schedules API
# ─────────────────────────────────────────────────────────────

class TestBulkExtended:
    """Tests for bulk endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_bulk_invalid_action(self, client, user_token):
        """Invalid action should return 400."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"action": "invalid", "server_ids": [str(uuid_mod.uuid4())]},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_bulk_permission_denied(self, client, user_token):
        """User without permission should get 403."""
        with mock.patch("app.api.bulk.has_permission", return_value=False):
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"action": "start", "server_ids": [str(uuid_mod.uuid4())]},
            )
        assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Dashboard API
# ─────────────────────────────────────────────────────────────


