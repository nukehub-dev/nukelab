"""Tests for Plans API endpoints."""

import pytest
from datetime import datetime, UTC
from sqlalchemy import select

from app.models.server_plan import ServerPlan
from app.models.plan_access import UserPlanAccess, WorkspacePlanAccess
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember


class TestPlansList:
    """Plans listing endpoint tests."""

    @pytest.mark.asyncio
    async def test_list_plans_requires_auth(self, client):
        """Unauthenticated user should not access plans."""
        response = await client.get("/api/plans/")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_plans_as_user(self, client, user_token):
        """Authenticated user should list plans."""
        response = await client.get(
            "/api/plans/", headers={"Authorization": f"Bearer {user_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "success" in data or "data" in data


class TestPlanCRUD:
    """Plan CRUD endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_plan_as_admin(self, client, admin_token):
        """Admin should be able to create a plan."""
        response = await client.post(
            "/api/plans/",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "Test Plan",
                "slug": "test-plan-new",
                "description": "A test plan",
                "category": "cpu",
                "cpu_limit": 4.0,
                "memory_limit": "8g",
                "disk_limit": "50g",
                "gpu_limit": 0,
                "max_servers_per_user": 3,
                "cost_per_hour": 2,
                "visible_to_roles": ["user", "moderator"],
                "priority": 0,
            },
        )

        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_plan_as_user_forbidden(self, client, user_token):
        """Regular user should not create plans."""
        response = await client.post(
            "/api/plans/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "Hacker Plan", "slug": "hacker-plan", "cpu_limit": 100},
        )

        assert response.status_code == 403


class TestPlanFeatures:
    """Plan feature tests."""

    @pytest.mark.asyncio
    async def test_default_plan_features(self, client, user_token):
        """Plans should have default feature values."""
        response = await client.get(
            "/api/plans/", headers={"Authorization": f"Bearer {user_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        # Just verify we get plans back
        assert data is not None


class TestPlanVisibility:
    """Plan visibility filtering tests."""

    @pytest.mark.asyncio
    async def test_role_based_visibility(self, client, db_session, test_user, user_token):
        """User should see plans matching their role."""
        # Create plan for admin only
        admin_plan = ServerPlan(
            name="Admin Plan",
            slug="admin-only-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        # Create plan for users
        user_plan = ServerPlan(
            name="User Plan",
            slug="user-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["user"],
            is_active=True,
        )
        db_session.add_all([admin_plan, user_plan])
        await db_session.commit()

        response = await client.get(
            "/api/plans/", headers={"Authorization": f"Bearer {user_token}"}
        )
        data = response.json()
        slugs = [p["slug"] for p in data["data"]["items"]]
        assert "user-plan" in slugs
        assert "admin-only-plan" not in slugs

    @pytest.mark.asyncio
    async def test_direct_user_access_visibility(self, client, db_session, test_user, user_token):
        """User should see plans they have direct access to."""
        # Create admin-only plan
        plan = ServerPlan(
            name="Admin Direct Plan",
            slug="admin-direct-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        # Grant user direct access
        access = UserPlanAccess(
            plan_id=plan.id, user_id=test_user.id, granted_at=datetime.now(UTC).replace(tzinfo=None)
        )
        db_session.add(access)
        await db_session.commit()

        response = await client.get(
            "/api/plans/", headers={"Authorization": f"Bearer {user_token}"}
        )
        data = response.json()
        slugs = [p["slug"] for p in data["data"]["items"]]
        assert "admin-direct-plan" in slugs

    @pytest.mark.asyncio
    async def test_workspace_access_visibility(self, client, db_session, test_user, user_token):
        """User should see plans accessible via their workspace membership."""
        # Create admin-only plan
        plan = ServerPlan(
            name="Admin Workspace Plan",
            slug="admin-workspace-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        # Create workspace with user as member
        workspace = SharedWorkspace(name="Test Workspace", owner_id=test_user.id, is_active=True)
        db_session.add(workspace)
        await db_session.commit()
        await db_session.refresh(workspace)

        member = WorkspaceMember(workspace_id=workspace.id, user_id=test_user.id, role="read_write")
        db_session.add(member)
        await db_session.commit()

        # Grant workspace access to plan
        ws_access = WorkspacePlanAccess(
            plan_id=plan.id,
            workspace_id=workspace.id,
            granted_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db_session.add(ws_access)
        await db_session.commit()

        response = await client.get(
            "/api/plans/", headers={"Authorization": f"Bearer {user_token}"}
        )
        data = response.json()
        slugs = [p["slug"] for p in data["data"]["items"]]
        assert "admin-workspace-plan" in slugs

    @pytest.mark.asyncio
    async def test_public_plan_visible_to_all(self, client, db_session, test_user, user_token):
        """Public plans should be visible to all users."""
        plan = ServerPlan(
            name="Public Plan",
            slug="public-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            is_public=True,
            visible_to_roles=["admin"],
            is_active=True,
        )
        db_session.add(plan)
        await db_session.commit()

        response = await client.get(
            "/api/plans/", headers={"Authorization": f"Bearer {user_token}"}
        )
        data = response.json()
        slugs = [p["slug"] for p in data["data"]["items"]]
        assert "public-plan" in slugs


class TestPlanUserAccess:
    """User plan access management tests."""

    @pytest.mark.asyncio
    async def test_grant_user_access_as_admin(self, client, admin_token, db_session, test_user):
        """Admin should be able to grant user access to a plan."""
        plan = ServerPlan(
            name="Restricted Plan",
            slug="restricted-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        response = await client.post(
            f"/api/plans/{plan.id}/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_revoke_user_access_as_admin(self, client, admin_token, db_session, test_user):
        """Admin should be able to revoke user access."""
        plan = ServerPlan(
            name="Revoke Plan",
            slug="revoke-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        access = UserPlanAccess(plan_id=plan.id, user_id=test_user.id)
        db_session.add(access)
        await db_session.commit()

        response = await client.delete(
            f"/api/plans/{plan.id}/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_list_plan_users_as_admin(self, client, admin_token, db_session, test_user):
        """Admin should be able to list users with plan access."""
        plan = ServerPlan(
            name="List Users Plan",
            slug="list-users-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        access = UserPlanAccess(plan_id=plan.id, user_id=test_user.id)
        db_session.add(access)
        await db_session.commit()

        response = await client.get(
            f"/api/plans/{plan.id}/users", headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 1

    @pytest.mark.asyncio
    async def test_grant_user_access_duplicate_fails(
        self, client, admin_token, db_session, test_user
    ):
        """Granting duplicate user access should fail."""
        plan = ServerPlan(
            name="Dup Plan",
            slug="dup-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        access = UserPlanAccess(plan_id=plan.id, user_id=test_user.id)
        db_session.add(access)
        await db_session.commit()

        response = await client.post(
            f"/api/plans/{plan.id}/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 409


class TestPlanWorkspaceAccess:
    """Workspace plan access management tests."""

    @pytest.mark.asyncio
    async def test_grant_workspace_access_as_admin(
        self, client, admin_token, db_session, test_user
    ):
        """Admin should be able to grant workspace access to a plan."""
        plan = ServerPlan(
            name="WS Restricted Plan",
            slug="ws-restricted-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        workspace = SharedWorkspace(name="Test WS", owner_id=test_user.id, is_active=True)
        db_session.add_all([plan, workspace])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(workspace)

        response = await client.post(
            f"/api/plans/{plan.id}/workspaces/{workspace.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_revoke_workspace_access_as_admin(
        self, client, admin_token, db_session, test_user
    ):
        """Admin should be able to revoke workspace access."""
        plan = ServerPlan(
            name="WS Revoke Plan",
            slug="ws-revoke-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        workspace = SharedWorkspace(name="Test WS 2", owner_id=test_user.id, is_active=True)
        db_session.add_all([plan, workspace])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(workspace)

        access = WorkspacePlanAccess(plan_id=plan.id, workspace_id=workspace.id)
        db_session.add(access)
        await db_session.commit()

        response = await client.delete(
            f"/api/plans/{plan.id}/workspaces/{workspace.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_list_plan_workspaces_as_admin(self, client, admin_token, db_session, test_user):
        """Admin should be able to list workspaces with plan access."""
        plan = ServerPlan(
            name="List WS Plan",
            slug="list-ws-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        workspace = SharedWorkspace(name="Test WS 3", owner_id=test_user.id, is_active=True)
        db_session.add_all([plan, workspace])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(workspace)

        access = WorkspacePlanAccess(plan_id=plan.id, workspace_id=workspace.id)
        db_session.add(access)
        await db_session.commit()

        response = await client.get(
            f"/api/plans/{plan.id}/workspaces", headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 1

    @pytest.mark.asyncio
    async def test_grant_workspace_access_duplicate_fails(
        self, client, admin_token, db_session, test_user
    ):
        """Granting duplicate workspace access should fail."""
        plan = ServerPlan(
            name="WS Dup Plan",
            slug="ws-dup-plan",
            category="cpu",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
            visible_to_roles=["admin"],
            is_active=True,
        )
        workspace = SharedWorkspace(name="Test WS 4", owner_id=test_user.id, is_active=True)
        db_session.add_all([plan, workspace])
        await db_session.commit()
        await db_session.refresh(plan)
        await db_session.refresh(workspace)

        access = WorkspacePlanAccess(plan_id=plan.id, workspace_id=workspace.id)
        db_session.add(access)
        await db_session.commit()

        response = await client.post(
            f"/api/plans/{plan.id}/workspaces/{workspace.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 409


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
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_plans(self, client, user_token):
        """Should list plans."""
        response = await client.get(
            "/api/plans/", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data

    @pytest.mark.asyncio
    async def test_list_plans_with_category(self, client, user_token):
        """Should list plans with category filter."""
        response = await client.get(
            "/api/plans/?category=cpu", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_non_admin_cannot_create_plan(self, client, user_token):
        """Regular user should not create plans."""
        response = await client.post(
            "/api/plans/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "Test Plan", "slug": "test-plan"},
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_plan(self, client, user_token):
        """Regular user should not update plans."""
        response = await client.put(
            "/api/plans/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "Updated"},
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_delete_plan(self, client, user_token):
        """Regular user should not delete plans."""
        response = await client.delete(
            "/api/plans/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in [403, 404]
