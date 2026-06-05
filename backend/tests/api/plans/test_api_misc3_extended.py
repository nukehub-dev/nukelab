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


