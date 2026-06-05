"""Extended tests for smaller API endpoints (tokens, plans, quotas, schedules)."""

import pytest
import uuid

from app.models.server_plan import ServerPlan
from app.models.server_schedule import ServerSchedule
from app.models.server import Server

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



