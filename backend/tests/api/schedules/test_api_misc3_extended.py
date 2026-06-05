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


