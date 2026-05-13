"""Tests for Dashboard API endpoints."""

import pytest


class TestUserDashboard:
    """Standard user dashboard tests."""

    @pytest.mark.asyncio
    async def test_dashboard_has_user_stats(self, client, test_user, user_token):
        """Dashboard should include my_servers, my_credits, recent_activity."""
        response = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "my_servers" in data
        assert "my_nukes" in data
        assert "recent_activity" in data
        assert data["my_nukes"]["balance"] == test_user.nuke_balance

    @pytest.mark.asyncio
    async def test_dashboard_server_counts(self, client, user_token):
        """my_servers should have total, running, stopped, pending keys."""
        response = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        servers = response.json()["my_servers"]
        assert "total" in servers
        assert "running" in servers
        assert "stopped" in servers
        assert "pending" in servers

    @pytest.mark.asyncio
    async def test_dashboard_hourly_cost_with_running_server(self, client, test_user, user_token, db_session):
        """Dashboard should calculate hourly cost from running servers."""
        import uuid as uuid_mod
        from app.models.server import Server
        from app.models.server_plan import ServerPlan

        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name="Test Plan",
            slug="test-plan",
            cost_per_hour=10,
        )
        db_session.add(plan)
        await db_session.flush()

        server = Server(
            id=uuid_mod.uuid4(),
            name="running-server",
            user_id=test_user.id,
            plan_id=plan.id,
            status="running",
            container_id="test-container",
        )
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        nukes = data["my_nukes"]
        assert nukes["hourly_cost"] == 10
        assert nukes["estimated_hours_left"] == test_user.nuke_balance // 10

    @pytest.mark.asyncio
    async def test_dashboard_hourly_cost_no_running_servers(self, client, user_token):
        """Dashboard should show 0 hourly cost when no servers are running."""
        response = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        nukes = data["my_nukes"]
        assert nukes["hourly_cost"] == 0
        assert nukes["estimated_hours_left"] == 0


class TestAdminDashboard:
    """Admin-only dashboard features."""

    @pytest.mark.asyncio
    async def test_admin_sees_platform_stats(self, client, admin_user, admin_token):
        """Admin dashboard should include platform-wide statistics."""
        response = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "platform_stats" in data
        assert "total_users" in data["platform_stats"]
        assert "total_servers" in data["platform_stats"]
        assert "active_servers" in data["platform_stats"]
