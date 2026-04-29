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
        assert "my_credits" in data
        assert "recent_activity" in data
        assert data["my_credits"]["balance"] == test_user.credit_balance

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
