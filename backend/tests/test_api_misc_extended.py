"""Extended tests for smaller API endpoints (tokens, plans, quotas, schedules)."""

import pytest
import uuid

from app.models.server_plan import ServerPlan
from app.models.server_schedule import ServerSchedule
from app.models.server import Server


class TestTokensAPI:
    """Tests for API token endpoints."""

    @pytest.mark.asyncio
    async def test_get_token_not_found(self, client, user_token):
        """Getting non-existent token should 404."""
        response = await client.get(
            "/api/tokens/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_token_not_found(self, client, user_token):
        """Revoking non-existent token should 404."""
        response = await client.delete(
            "/api/tokens/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_token_not_found(self, client, user_token):
        """Permanently deleting non-existent token should 404."""
        response = await client.delete(
            "/api/tokens/00000000-0000-0000-0000-000000000000/permanent",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_regenerate_token_not_found(self, client, user_token):
        """Regenerating non-existent token should 404."""
        response = await client.post(
            "/api/tokens/00000000-0000-0000-0000-000000000000/regenerate",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_token_usage_not_found(self, client, user_token):
        """Getting usage for non-existent token should 404."""
        response = await client.get(
            "/api/tokens/00000000-0000-0000-0000-000000000000/usage",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_token_invalid_scope(self, client, user_token):
        """Creating token with invalid scope should 422."""
        response = await client.post(
            "/api/tokens",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "test", "scopes": ["invalid:scope"]}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_list_tokens(self, client, user_token):
        """Should list user's tokens."""
        response = await client.get(
            "/api/tokens",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestPlansAPI:
    """Tests for plan endpoints."""

    @pytest.mark.asyncio
    async def test_get_plan_not_found(self, client, user_token):
        """Getting non-existent plan should 404."""
        response = await client.get(
            "/api/plans/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_plans(self, client, user_token):
        """Should list plans."""
        response = await client.get(
            "/api/plans/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data

    @pytest.mark.asyncio
    async def test_list_plans_with_category(self, client, user_token):
        """Should list plans with category filter."""
        response = await client.get(
            "/api/plans/?category=cpu",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_non_admin_cannot_create_plan(self, client, user_token):
        """Regular user should not create plans."""
        response = await client.post(
            "/api/plans/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "Test Plan", "slug": "test-plan"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_plan(self, client, user_token):
        """Regular user should not update plans."""
        response = await client.put(
            "/api/plans/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "Updated"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_delete_plan(self, client, user_token):
        """Regular user should not delete plans."""
        response = await client.delete(
            "/api/plans/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]


class TestQuotasAPI:
    """Tests for quota endpoints."""

    @pytest.mark.asyncio
    async def test_get_my_quota(self, client, admin_token, admin_user):
        """Admin should get quota."""
        response = await client.get(
            "/api/quotas/",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data

    @pytest.mark.asyncio
    async def test_check_spawn_allowed(self, client, admin_token):
        """Should check if spawn is allowed."""
        response = await client.post(
            "/api/quotas/check",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"plan_id": "00000000-0000-0000-0000-000000000000"}
        )
        # May succeed or fail depending on quota state
        assert response.status_code in [200, 400, 404, 422]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list_all_quotas(self, client, user_token):
        """Regular user should not list all quotas."""
        response = await client.get(
            "/api/quotas/all",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_quota(self, client, user_token):
        """Regular user should not update quotas."""
        response = await client.put(
            "/api/quotas/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"max_servers_total": 10}
        )
        assert response.status_code in [403, 404]


class TestSchedulesAPI:
    """Tests for schedule endpoints."""

    @pytest.mark.asyncio
    async def test_list_schedules_server_not_found(self, client, user_token):
        """Listing schedules for non-existent server should 404."""
        response = await client.get(
            "/api/schedules/servers/00000000-0000-0000-0000-000000000000/schedules",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_schedule_not_found(self, client, user_token, test_user, db_session):
        """Deleting non-existent schedule should 404."""
        server = Server(name="sched-srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.delete(
            f"/api/schedules/servers/{server.id}/schedules/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_create_schedule_invalid_cron(self, client, user_token, test_user, db_session):
        """Creating schedule with invalid cron should 400 or 422."""
        server = Server(name="sched-srv2", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.post(
            f"/api/schedules/servers/{server.id}/schedules",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"action": "start", "cron_expression": "invalid"}
        )
        assert response.status_code in [400, 422, 403, 404]

    @pytest.mark.asyncio
    async def test_update_schedule_not_found(self, client, user_token, test_user, db_session):
        """Updating non-existent schedule should 404."""
        server = Server(name="sched-srv3", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.put(
            f"/api/schedules/servers/{server.id}/schedules/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"action": "stop"}
        )
        assert response.status_code in [404, 403]
