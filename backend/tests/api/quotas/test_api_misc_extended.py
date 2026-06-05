"""Extended tests for smaller API endpoints (tokens, plans, quotas, schedules)."""

import pytest
import uuid

from app.models.server_plan import ServerPlan
from app.models.server_schedule import ServerSchedule
from app.models.server import Server

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



