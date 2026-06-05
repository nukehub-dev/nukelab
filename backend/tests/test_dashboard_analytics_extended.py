"""Extended tests for Dashboard and Analytics API endpoints."""

import pytest
from datetime import datetime, timedelta, UTC

from app.models.activity_log import ActivityLog


class TestDashboard:
    """Tests for dashboard endpoints."""

    @pytest.mark.asyncio
    async def test_user_dashboard(self, client, user_token, test_user, db_session):
        """Regular user should get their dashboard."""
        # Seed some activity
        log = ActivityLog(actor_id=test_user.id, action="server.create", target_type="server")
        db_session.add(log)
        await db_session.commit()

        response = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "my_servers" in data
        assert "my_nukes" in data
        assert "recent_activity" in data
        assert "platform_stats" not in data

    @pytest.mark.asyncio
    async def test_admin_dashboard(self, client, admin_token):
        """Admin should get dashboard with platform stats."""
        response = await client.get(
            "/api/dashboard/",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "platform_stats" in data
        assert "total_users" in data["platform_stats"]
        assert "system_health" in data["platform_stats"]

    @pytest.mark.asyncio
    async def test_admin_activity_feed(self, client, admin_token):
        """Admin should get activity feed."""
        response = await client.get(
            "/api/dashboard/activity",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "activities" in data

    @pytest.mark.asyncio
    async def test_non_admin_activity_feed_denied(self, client, user_token):
        """Regular user should not access admin activity feed."""
        response = await client.get(
            "/api/dashboard/activity",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]


class TestAnalytics:
    """Tests for analytics endpoints."""

    @pytest.mark.asyncio
    async def test_user_own_usage(self, client, user_token, test_user):
        """User should get their own usage analytics."""
        response = await client.get(
            f"/api/analytics/users/{test_user.id}/usage",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_user_cannot_access_others_usage(self, client, user_token, admin_user):
        """User should not access another user's usage analytics."""
        response = await client.get(
            f"/api/analytics/users/{admin_user.id}/usage",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_admin_global_usage(self, client, admin_token):
        """Admin should get global usage analytics."""
        response = await client.get(
            "/api/analytics/global",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_top_consumers(self, client, admin_token):
        """Admin should get top consumers."""
        response = await client.get(
            "/api/analytics/top-consumers",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "consumers" in data

    @pytest.mark.asyncio
    async def test_admin_credit_flow(self, client, admin_token):
        """Admin should get credit flow analytics."""
        response = await client.get(
            "/api/analytics/credit-flow",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "credit_flow" in data

    @pytest.mark.asyncio
    async def test_admin_login_events(self, client, admin_token):
        """Admin should get login event analytics."""
        response = await client.get(
            "/api/analytics/logins",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "login_events" in data

    @pytest.mark.asyncio
    async def test_admin_user_growth(self, client, admin_token):
        """Admin should get user growth analytics."""
        response = await client.get(
            "/api/analytics/user-growth",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_analytics_date_range_validation(self, client, admin_token):
        """Invalid date range should 422."""
        from_date = datetime.now(UTC).replace(tzinfo=None).isoformat()
        to_date = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).isoformat()
        response = await client.get(
            f"/api/analytics/global?from={from_date}&to={to_date}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_non_admin_cannot_access_global_analytics(self, client, user_token):
        """Regular user should not access global analytics."""
        response = await client.get(
            "/api/analytics/global",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]
