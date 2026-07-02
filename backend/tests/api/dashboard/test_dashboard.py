# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Dashboard API endpoints."""

import pytest


class TestUserDashboard:
    """Standard user dashboard tests."""

    @pytest.mark.asyncio
    async def test_dashboard_has_user_stats(self, client, test_user, user_token):
        """Dashboard should include my_servers, my_credits, recent_activity."""
        response = await client.get(
            "/api/dashboard/", headers={"Authorization": f"Bearer {user_token}"}
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
            "/api/dashboard/", headers={"Authorization": f"Bearer {user_token}"}
        )

        assert response.status_code == 200
        servers = response.json()["my_servers"]
        assert "total" in servers
        assert "running" in servers
        assert "stopped" in servers
        assert "pending" in servers

    @pytest.mark.asyncio
    async def test_dashboard_hourly_cost_with_running_server(
        self, client, test_user, user_token, db_session
    ):
        """Dashboard should calculate hourly cost from running servers."""
        from app.models.server import Server

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
            "/api/dashboard/", headers={"Authorization": f"Bearer {user_token}"}
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
            "/api/dashboard/", headers={"Authorization": f"Bearer {user_token}"}
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
            "/api/dashboard/", headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "platform_stats" in data
        assert "total_users" in data["platform_stats"]
        assert "total_servers" in data["platform_stats"]
        assert "active_servers" in data["platform_stats"]


"""Extended tests for small API modules — coverage gap closure."""

import uuid as uuid_mod

import pytest

from app.config import settings
from app.models.activity_log import ActivityLog
from app.models.server import Server
from app.models.server_plan import ServerPlan


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


class TestDashboardExtended:
    """Tests for dashboard endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_dashboard_activity_feed_admin(self, client, admin_token):
        """Admin should access activity feed."""
        response = await client.get(
            "/api/dashboard/activity",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert "activities" in response.json()

    @pytest.mark.asyncio
    async def test_dashboard_activity_feed_non_admin(self, client, user_token):
        """Non-admin should be blocked from activity feed."""
        response = await client.get(
            "/api/dashboard/activity",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Analytics API
# ─────────────────────────────────────────────────────────────


"""Extended tests for dashboard API endpoints."""

import pytest

from app.models.health_check import HealthCheck


class TestDashboardGet:
    """Tests for GET /api/dashboard/."""

    @pytest.mark.asyncio
    async def test_dashboard_basic_user(self, client, user_token, test_user, db_session):
        """Regular user should see own server stats."""
        # Create a server for the user
        server = Server(name="dash-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            "/api/dashboard/", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "my_servers" in data
        assert data["my_servers"]["total"] == 1
        assert data["my_servers"]["running"] == 1
        assert "my_nukes" in data
        assert "recent_activity" in data
        assert "platform_stats" not in data  # user doesn't have admin access

    @pytest.mark.asyncio
    async def test_dashboard_admin_sees_platform_stats(
        self, client, admin_token, admin_user, db_session
    ):
        """Admin should see platform statistics."""
        response = await client.get(
            "/api/dashboard/", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "platform_stats" in data
        assert "total_users" in data["platform_stats"]
        assert "system_health" in data["platform_stats"]

    @pytest.mark.asyncio
    async def test_dashboard_no_servers(self, client, user_token, test_user, db_session):
        """User with no servers should see zeros."""
        response = await client.get(
            "/api/dashboard/", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["my_servers"]["total"] == 0
        assert data["my_servers"]["running"] == 0
        assert data["my_nukes"]["hourly_cost"] == 0
        assert data["my_nukes"]["estimated_hours_left"] == 0

    @pytest.mark.asyncio
    async def test_dashboard_with_activity(self, client, user_token, test_user, db_session):
        """Recent activity should be included."""
        activity = ActivityLog(actor_id=test_user.id, action="test.action", target_type="server")
        db_session.add(activity)
        await db_session.commit()

        response = await client.get(
            "/api/dashboard/", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["recent_activity"]) >= 1
        assert data["recent_activity"][0]["action"] == "test.action"


class TestDashboardSystemHealth:
    """Tests for _get_system_health helper."""

    @pytest.mark.asyncio
    async def test_system_health_no_checks(self, client, admin_token, db_session):
        """Should be healthy when no recent health checks exist."""
        response = await client.get(
            "/api/dashboard/", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["platform_stats"]["system_health"] == "healthy"

    @pytest.mark.asyncio
    async def test_system_health_healthy(self, client, admin_token, admin_user, db_session):
        """Should be healthy when all recent checks pass."""
        from app.models.server import Server

        server = Server(name="health-srv", user_id=admin_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        hc = HealthCheck(
            server_id=server.id, container_id="cid1", status="healthy", consecutive_failures=0
        )
        db_session.add(hc)
        await db_session.commit()

        response = await client.get(
            "/api/dashboard/", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["platform_stats"]["system_health"] == "healthy"

    @pytest.mark.asyncio
    async def test_system_health_degraded(self, client, admin_token, admin_user, db_session):
        """Should be degraded when some checks fail."""
        from app.models.server import Server

        s1 = Server(name="s1", user_id=admin_user.id, status="running")
        s2 = Server(name="s2", user_id=admin_user.id, status="running")
        db_session.add_all([s1, s2])
        await db_session.commit()

        hc1 = HealthCheck(
            server_id=s1.id, container_id="cid1", status="healthy", consecutive_failures=0
        )
        hc2 = HealthCheck(
            server_id=s2.id, container_id="cid2", status="unhealthy", consecutive_failures=1
        )
        db_session.add_all([hc1, hc2])
        await db_session.commit()

        response = await client.get(
            "/api/dashboard/", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["platform_stats"]["system_health"] == "degraded"

    @pytest.mark.asyncio
    async def test_system_health_unhealthy(self, client, admin_token, admin_user, db_session):
        """Should be unhealthy when most checks fail."""
        from app.models.server import Server

        s1 = Server(name="s1", user_id=admin_user.id, status="running")
        s2 = Server(name="s2", user_id=admin_user.id, status="running")
        s3 = Server(name="s3", user_id=admin_user.id, status="running")
        db_session.add_all([s1, s2, s3])
        await db_session.commit()

        hc1 = HealthCheck(
            server_id=s1.id, container_id="cid1", status="healthy", consecutive_failures=0
        )
        hc2 = HealthCheck(
            server_id=s2.id, container_id="cid2", status="unhealthy", consecutive_failures=2
        )
        hc3 = HealthCheck(
            server_id=s3.id, container_id="cid3", status="unhealthy", consecutive_failures=1
        )
        db_session.add_all([hc1, hc2, hc3])
        await db_session.commit()

        response = await client.get(
            "/api/dashboard/", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["platform_stats"]["system_health"] == "unhealthy"


class TestActivityFeed:
    """Tests for GET /api/dashboard/activity."""

    @pytest.mark.asyncio
    async def test_activity_feed_admin_only(self, client, user_token, test_user, db_session):
        """Regular user should not access admin activity feed."""
        response = await client.get(
            "/api/dashboard/activity", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_activity_feed_admin(self, client, admin_token, db_session):
        """Admin should get activity feed."""
        response = await client.get(
            "/api/dashboard/activity", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "activities" in data
        assert "has_more" in data

    @pytest.mark.asyncio
    async def test_activity_feed_with_pagination(self, client, admin_token, db_session):
        """Should respect limit parameter."""
        response = await client.get(
            "/api/dashboard/activity?limit=5", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["activities"]) <= 5
