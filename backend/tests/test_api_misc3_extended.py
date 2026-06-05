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

class TestSchedulesAPI:
    """Tests for schedule CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_list_schedules(self, client, user_token, test_user, db_session):
        """Should list schedules for a server."""
        plan = ServerPlan(
            name="sch-plan", slug="sch-plan", cpu_limit=1, memory_limit="1g", disk_limit="10g",
            is_public=True, is_active=True, cost_per_hour=0, visible_to_roles=["user"],
        )
        env = EnvironmentTemplate(name="sch-env", slug="sch-env", image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        server = Server(name="sch-srv", user_id=test_user.id, status="stopped", plan_id=plan.id, environment_id=env.id)
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.get(
            f"/api/schedules/servers/{server.id}/schedules",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        assert "schedules" in response.json()

    @pytest.mark.asyncio
    async def test_create_schedule(self, client, admin_token, admin_user, db_session):
        """Should create a schedule for a server."""
        plan = ServerPlan(
            name="sch-plan2", slug="sch-plan2", cpu_limit=1, memory_limit="1g", disk_limit="10g",
            is_public=True, is_active=True, cost_per_hour=0, visible_to_roles=["user"],
        )
        env = EnvironmentTemplate(name="sch-env2", slug="sch-env2", image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        server = Server(name="sch-srv2", user_id=admin_user.id, status="stopped", plan_id=plan.id, environment_id=env.id)
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.schedules.ScheduleService") as mock_svc:
            mock_sched = mock.Mock()
            mock_sched.to_dict.return_value = {"id": str(uuid_mod.uuid4()), "action": "start"}
            mock_svc.return_value.create_schedule = mock.AsyncMock(return_value=mock_sched)
            response = await client.post(
                f"/api/schedules/servers/{server.id}/schedules",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "start", "cron_expression": "0 9 * * *", "timezone": "UTC", "is_active": True},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_create_schedule_value_error(self, client, admin_token, admin_user, db_session):
        """ValueError from create_schedule should return 400."""
        plan = ServerPlan(
            name="sch-plan3", slug="sch-plan3", cpu_limit=1, memory_limit="1g", disk_limit="10g",
            is_public=True, is_active=True, cost_per_hour=0, visible_to_roles=["user"],
        )
        env = EnvironmentTemplate(name="sch-env3", slug="sch-env3", image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        server = Server(name="sch-srv3", user_id=admin_user.id, status="stopped", plan_id=plan.id, environment_id=env.id)
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.schedules.ScheduleService") as mock_svc:
            mock_svc.return_value.create_schedule = mock.AsyncMock(side_effect=ValueError("bad cron"))
            response = await client.post(
                f"/api/schedules/servers/{server.id}/schedules",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "start", "cron_expression": "invalid", "timezone": "UTC"},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_update_schedule(self, client, admin_token, admin_user, db_session):
        """Should update a schedule."""
        plan = ServerPlan(
            name="sch-plan4", slug="sch-plan4", cpu_limit=1, memory_limit="1g", disk_limit="10g",
            is_public=True, is_active=True, cost_per_hour=0, visible_to_roles=["user"],
        )
        env = EnvironmentTemplate(name="sch-env4", slug="sch-env4", image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        server = Server(name="sch-srv4", user_id=admin_user.id, status="stopped", plan_id=plan.id, environment_id=env.id)
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.schedules.ScheduleService") as mock_svc:
            mock_sched = mock.Mock()
            mock_sched.to_dict.return_value = {"id": str(uuid_mod.uuid4()), "action": "stop"}
            mock_svc.return_value.update_schedule = mock.AsyncMock(return_value=mock_sched)
            response = await client.put(
                f"/api/schedules/servers/{server.id}/schedules/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"action": "stop", "cron_expression": "0 18 * * *"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_schedule(self, client, admin_token, admin_user, db_session):
        """Should delete a schedule."""
        plan = ServerPlan(
            name="sch-plan5", slug="sch-plan5", cpu_limit=1, memory_limit="1g", disk_limit="10g",
            is_public=True, is_active=True, cost_per_hour=0, visible_to_roles=["user"],
        )
        env = EnvironmentTemplate(name="sch-env5", slug="sch-env5", image="test:latest")
        db_session.add_all([plan, env])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(env)

        server = Server(name="sch-srv5", user_id=admin_user.id, status="stopped", plan_id=plan.id, environment_id=env.id)
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.schedules.ScheduleService") as mock_svc:
            mock_svc.return_value.delete_schedule = mock.AsyncMock(return_value=True)
            response = await client.delete(
                f"/api/schedules/servers/{server.id}/schedules/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────
# Notifications API
# ─────────────────────────────────────────────────────────────

class TestNotificationsExtended:
    """Tests for notifications endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_delete_notification(self, client, user_token, test_user, db_session):
        """Should delete a notification."""
        notif = Notification(
            user_id=test_user.id, type="test", title="t", message="m", severity="info"
        )
        db_session.add(notif)
        await db_session.commit()
        await db_session.refresh(notif)

        response = await client.delete(
            f"/api/notifications/{notif.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_notification_not_found(self, client, user_token):
        """Should return 404 for nonexistent notification."""
        response = await client.delete(
            f"/api/notifications/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_notifications_filter_type(self, client, user_token, test_user, db_session):
        """Should filter notifications by type."""
        notif = Notification(
            user_id=test_user.id, type="server", title="t", message="m", severity="info"
        )
        db_session.add(notif)
        await db_session.commit()

        response = await client.get(
            "/api/notifications/?type=server",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert all(n["type"] == "server" for n in data["notifications"])

    @pytest.mark.asyncio
    async def test_list_notifications_unread_only(self, client, user_token, test_user, db_session):
        """Should filter to unread notifications only."""
        notif = Notification(
            user_id=test_user.id, type="test", title="t", message="m", severity="info", read=False
        )
        db_session.add(notif)
        await db_session.commit()

        response = await client.get(
            "/api/notifications/?unread_only=true",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["unread_count"] >= 1

    @pytest.mark.asyncio
    async def test_admin_create_notification(self, client, admin_token, test_user, db_session):
        """Admin should be able to create a notification."""
        response = await client.post(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={
                "user_id": str(test_user.id),
                "type": "info",
                "title": "Test",
                "message": "Hello",
                "severity": "info",
            },
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_user_cannot_create_notification(self, client, user_token, test_user):
        """Non-admin should be blocked from creating notifications."""
        response = await client.post(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {user_token}"},
            params={
                "user_id": str(test_user.id),
                "type": "info",
                "title": "Test",
                "message": "Hello",
            },
        )
        assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Credits API
# ─────────────────────────────────────────────────────────────

class TestCreditsExtended:
    """Tests for credits endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_get_credit_history(self, client, user_token):
        """Should get credit transaction history."""
        response = await client.get(
            "/api/credits/history",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_user_credit_history_admin(self, client, admin_token, test_user):
        """Admin should get any user's credit history."""
        response = await client.get(
            f"/api/credits/users/{test_user.id}/history",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_deduct_credits(self, client, admin_token, test_user, db_session):
        """Admin should be able to deduct credits."""
        test_user.nuke_balance = 100
        await db_session.commit()

        with mock.patch("app.api.credits.CreditService") as mock_credit:
            mock_tx = mock.Mock()
            mock_tx.balance_after = 50
            mock_tx.to_dict.return_value = {"id": str(uuid_mod.uuid4()), "amount": -50}
            mock_credit.return_value.deduct_credits = mock.AsyncMock(return_value=mock_tx)
            with mock.patch("app.api.credits.NotificationService") as mock_notif:
                mock_notif.return_value.credits_deducted = mock.AsyncMock()
                response = await client.post(
                    f"/api/credits/users/{test_user.id}/deduct",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"amount": 50, "reason": "test deduction"},
                )
        assert response.status_code == 200
        assert "deducted" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_get_low_balance_users(self, client, admin_token):
        """Admin should get low balance users."""
        response = await client.get(
            "/api/credits/low-balance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert "users" in response.json()


# ─────────────────────────────────────────────────────────────
# System API
# ─────────────────────────────────────────────────────────────

class TestSystemExtended:
    """Tests for system endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_health_maintenance_mode(self, client):
        """Health check should return 503 when maintenance mode is on."""
        with mock.patch("app.api.system.settings.maintenance_mode", True):
            with mock.patch("app.api.system.settings.maintenance_message", "Down for maintenance"):
                response = await client.get("/api/system/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "maintenance"

    @pytest.mark.asyncio
    async def test_health_healthy(self, client):
        """Health check should return healthy normally."""
        with mock.patch("app.api.system.settings.maintenance_mode", False):
            response = await client.get("/api/system/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_update_system_config(self, client, admin_token):
        """Admin should update system config."""
        with mock.patch("app.api.system.SettingService") as mock_svc:
            mock_svc.return_value.save_maintenance = mock.AsyncMock()
            response = await client.put(
                "/api/system/config",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"maintenance_mode": True, "maintenance_message": "Test maintenance"},
            )
        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_system_stats_non_admin(self, client, user_token):
        """Non-admin should be blocked from system stats."""
        response = await client.get(
            "/api/system/stats",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_maintenance_windows_list(self, client, admin_token):
        """Admin should list maintenance windows."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.list_windows = mock.AsyncMock(return_value=[])
            response = await client.get(
                "/api/system/maintenance-windows",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_maintenance_windows_create(self, client, admin_token):
        """Admin should create a maintenance window."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_win = mock.Mock()
            mock_win.to_dict.return_value = {"id": str(uuid_mod.uuid4())}
            mock_svc.return_value.create_window = mock.AsyncMock(return_value=mock_win)
            response = await client.post(
                "/api/system/maintenance-windows",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "title": "Test Window",
                    "message": "Maintenance",
                    "start_at": (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)).isoformat(),
                    "end_at": (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)).isoformat(),
                },
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_maintenance_windows_create_value_error(self, client, admin_token):
        """ValueError from create_window should return 400."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.create_window = mock.AsyncMock(side_effect=ValueError("bad dates"))
            response = await client.post(
                "/api/system/maintenance-windows",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "title": "Test",
                    "message": "Maintenance",
                    "start_at": (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)).isoformat(),
                    "end_at": (datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)).isoformat(),
                },
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_maintenance_windows_get_not_found(self, client, admin_token):
        """Should return 404 for nonexistent maintenance window."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.get_window = mock.AsyncMock(return_value=None)
            response = await client.get(
                f"/api/system/maintenance-windows/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_maintenance_windows_update_not_found(self, client, admin_token):
        """Should return 404 for updating nonexistent window."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.update_window = mock.AsyncMock(side_effect=ValueError("not found"))
            response = await client.put(
                f"/api/system/maintenance-windows/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"title": "Updated"},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_maintenance_windows_delete_not_found(self, client, admin_token):
        """Should return 404 for deleting nonexistent window."""
        with mock.patch("app.api.system.MaintenanceWindowService") as mock_svc:
            mock_svc.return_value.delete_window = mock.AsyncMock(return_value=False)
            response = await client.delete(
                f"/api/system/maintenance-windows/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────
# Plans API
# ─────────────────────────────────────────────────────────────

class TestPlansExtended:
    """Tests for plans endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_get_plan_success(self, client, user_token):
        """Should get a single plan."""
        with mock.patch("app.api.plans.PlanService") as mock_svc:
            mock_plan = mock.Mock()
            mock_plan.to_dict.return_value = {"id": str(uuid_mod.uuid4()), "name": "test-plan"}
            mock_svc.return_value.get_by_id = mock.AsyncMock(return_value=mock_plan)
            mock_svc.return_value.check_plan_access = mock.AsyncMock(return_value=True)
            response = await client.get(
                f"/api/plans/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_plan_not_found(self, client, user_token):
        """Should return 404 for nonexistent plan."""
        with mock.patch("app.api.plans.PlanService") as mock_svc:
            mock_svc.return_value.get_by_id = mock.AsyncMock(return_value=None)
            response = await client.get(
                f"/api/plans/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_plan(self, client, admin_token):
        """Admin should update a plan."""
        with mock.patch("app.api.plans.PlanService") as mock_svc:
            mock_plan = mock.Mock()
            mock_plan.to_dict.return_value = {"id": str(uuid_mod.uuid4()), "name": "updated"}
            mock_svc.return_value.update_plan = mock.AsyncMock(return_value=mock_plan)
            response = await client.put(
                f"/api/plans/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"name": "updated", "cpu_limit": 2},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_deactivate_plan(self, client, admin_token):
        """Admin should deactivate a plan."""
        with mock.patch("app.api.plans.PlanService") as mock_svc:
            mock_plan = mock.Mock()
            mock_plan.to_dict.return_value = {"id": str(uuid_mod.uuid4())}
            mock_svc.return_value.deactivate_plan = mock.AsyncMock(return_value=mock_plan)
            response = await client.delete(
                f"/api/plans/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_activate_plan(self, client, admin_token):
        """Admin should activate a plan."""
        with mock.patch("app.api.plans.PlanService") as mock_svc:
            mock_plan = mock.Mock()
            mock_plan.to_dict.return_value = {"id": str(uuid_mod.uuid4())}
            mock_svc.return_value.activate_plan = mock.AsyncMock(return_value=mock_plan)
            response = await client.post(
                f"/api/plans/{uuid_mod.uuid4()}/activate",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_plan_permanent(self, client, admin_token):
        """Admin should permanently delete a plan."""
        with mock.patch("app.api.plans.PlanService") as mock_svc:
            mock_svc.return_value.delete_plan = mock.AsyncMock(return_value=None)
            response = await client.delete(
                f"/api/plans/{uuid_mod.uuid4()}/permanent",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_plan_users_success(self, client, admin_token):
        """Admin should list plan users."""
        with mock.patch("app.api.plans.PlanService") as mock_svc:
            mock_svc.return_value.list_plan_users = mock.AsyncMock(return_value=[])
            response = await client.get(
                f"/api/plans/{uuid_mod.uuid4()}/users",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────
# Bulk API
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

class TestAnalyticsExtended:
    """Tests for analytics endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_analytics_environments(self, client, admin_token):
        """Admin should get environment usage analytics."""
        with mock.patch("app.api.analytics.AnalyticsService") as mock_svc:
            mock_svc.return_value.get_environment_usage = mock.AsyncMock(return_value=[])
            response = await client.get(
                "/api/analytics/environments",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200
        assert "environments" in response.json()

    @pytest.mark.asyncio
    async def test_analytics_plans(self, client, admin_token):
        """Admin should get plan usage analytics."""
        with mock.patch("app.api.analytics.AnalyticsService") as mock_svc:
            mock_svc.return_value.get_plan_usage = mock.AsyncMock(return_value=[])
            response = await client.get(
                "/api/analytics/plans",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200
        assert "plans" in response.json()

    @pytest.mark.asyncio
    async def test_analytics_export_csv(self, client, admin_token):
        """Admin should export analytics as CSV."""
        with mock.patch("app.api.analytics.AnalyticsService") as mock_svc:
            mock_svc.return_value.get_platform_metrics = mock.AsyncMock(return_value=[{"day": "2024-01-01", "users": 5}])
            response = await client.post(
                "/api/analytics/export",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"metric": "platform-metrics", "format": "csv"},
            )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_analytics_export_invalid_metric(self, client, admin_token):
        """Invalid metric should return 400."""
        response = await client.post(
            "/api/analytics/export",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"metric": "invalid-metric", "format": "json"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_analytics_date_validation(self, client, admin_token):
        """Invalid date range should return 422."""
        response = await client.get(
            "/api/analytics/global?from=2024-01-15T00:00:00&to=2024-01-10T00:00:00",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analytics_date_range_too_large(self, client, admin_token):
        """Date range > 365 days should return 422."""
        response = await client.get(
            "/api/analytics/global?from=2023-01-01T00:00:00&to=2024-01-15T00:00:00",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422
