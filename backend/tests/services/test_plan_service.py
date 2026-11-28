# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for PlanService business logic."""

import uuid as uuid_mod

import pytest
from fastapi import HTTPException
from sqlalchemy import and_, select

from app.models.plan_access import UserPlanAccess, WorkspacePlanAccess
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.services.plan_service import PlanService


class TestPlanServiceGetById:
    """Tests for get_by_id and get_by_slug."""

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, db_session):
        """get_by_id should return plan when found."""
        plan = ServerPlan(name="Test Plan", slug="test-plan", cpu_limit=2)
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        result = await service.get_by_id(str(plan.id))
        assert result is not None
        assert result.name == "Test Plan"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session):
        """get_by_id should return None when not found."""
        service = PlanService(db_session)
        result = await service.get_by_id(str(uuid_mod.uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_slug_found(self, db_session):
        """get_by_slug should return plan when found."""
        plan = ServerPlan(name="Test Plan", slug="unique-slug", cpu_limit=2)
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        result = await service.get_by_slug("unique-slug")
        assert result is not None
        assert result.slug == "unique-slug"

    @pytest.mark.asyncio
    async def test_get_by_slug_not_found(self, db_session):
        """get_by_slug should return None when not found."""
        service = PlanService(db_session)
        result = await service.get_by_slug("nonexistent")
        assert result is None


class TestPlanServiceList:
    """Tests for list_plans."""

    @pytest.mark.asyncio
    async def test_list_plans_no_filters(self, db_session):
        """list_plans should return all plans without filters."""
        plan1 = ServerPlan(name="Plan 1", slug="plan-1", cpu_limit=1, priority=1)
        plan2 = ServerPlan(name="Plan 2", slug="plan-2", cpu_limit=2, priority=2)
        db_session.add_all([plan1, plan2])
        await db_session.commit()

        service = PlanService(db_session)
        result = await service.list_plans()
        assert result["total"] >= 2
        assert len(result["items"]) >= 2

    @pytest.mark.asyncio
    async def test_list_plans_with_category_filter(self, db_session):
        """list_plans should filter by category."""
        plan = ServerPlan(name="GPU Plan", slug="gpu-plan", category="gpu", cpu_limit=1)
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        result = await service.list_plans(category="gpu")
        assert all(p["category"] == "gpu" for p in result["items"])

    @pytest.mark.asyncio
    async def test_list_plans_with_user_role(self, db_session, test_user):
        """list_plans should filter by user role visibility."""
        public_plan = ServerPlan(
            name="Public Plan", slug="public-plan", is_public=True, cpu_limit=1
        )
        private_plan = ServerPlan(
            name="Private Plan",
            slug="private-plan",
            is_public=False,
            visible_to_roles=["admin"],
            cpu_limit=1,
        )
        db_session.add_all([public_plan, private_plan])
        await db_session.commit()

        service = PlanService(db_session)
        result = await service.list_plans(user_role="user", user_id=str(test_user.id))
        slugs = [p["slug"] for p in result["items"]]
        assert "public-plan" in slugs
        assert "private-plan" not in slugs

    @pytest.mark.asyncio
    async def test_list_plans_admin_sees_all(self, db_session):
        """Admin should see all plans regardless of visibility."""
        private_plan = ServerPlan(
            name="Private Plan", slug="admin-private", is_public=False, cpu_limit=1
        )
        db_session.add(private_plan)
        await db_session.commit()

        service = PlanService(db_session)
        result = await service.list_plans(user_role="admin")
        slugs = [p["slug"] for p in result["items"]]
        assert "admin-private" in slugs

    @pytest.mark.asyncio
    async def test_list_plans_role_visible(self, db_session):
        """User should see plans visible to their role."""
        role_plan = ServerPlan(
            name="User Plan",
            slug="user-plan",
            is_public=False,
            visible_to_roles=["user"],
            cpu_limit=1,
        )
        db_session.add(role_plan)
        await db_session.commit()

        service = PlanService(db_session)
        result = await service.list_plans(user_role="user")
        slugs = [p["slug"] for p in result["items"]]
        assert "user-plan" in slugs

    @pytest.mark.asyncio
    async def test_list_plans_user_access_override(self, db_session, test_user):
        """User should see plans they have direct access to."""
        private_plan = ServerPlan(
            name="Direct Access Plan", slug="direct-plan", is_public=False, cpu_limit=1
        )
        db_session.add(private_plan)
        await db_session.flush()

        access = UserPlanAccess(
            plan_id=private_plan.id,
            user_id=test_user.id,
        )
        db_session.add(access)
        await db_session.commit()

        service = PlanService(db_session)
        result = await service.list_plans(user_role="user", user_id=str(test_user.id))
        slugs = [p["slug"] for p in result["items"]]
        assert "direct-plan" in slugs

    @pytest.mark.asyncio
    async def test_list_plans_workspace_access(self, db_session, test_user):
        """User should see plans accessible via workspace."""
        ws = SharedWorkspace(name="Test WS", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="member")
        db_session.add(member)
        await db_session.flush()

        private_plan = ServerPlan(name="WS Plan", slug="ws-plan", is_public=False, cpu_limit=1)
        db_session.add(private_plan)
        await db_session.flush()

        ws_access = WorkspacePlanAccess(
            plan_id=private_plan.id,
            workspace_id=ws.id,
        )
        db_session.add(ws_access)
        await db_session.commit()

        service = PlanService(db_session)
        result = await service.list_plans(user_role="user", user_id=str(test_user.id))
        slugs = [p["slug"] for p in result["items"]]
        assert "ws-plan" in slugs


class TestPlanServiceCRUD:
    """Tests for create, update, delete plans."""

    @pytest.mark.asyncio
    async def test_create_plan_success(self, db_session):
        """create_plan should create a new plan."""
        service = PlanService(db_session)
        plan = await service.create_plan(
            name="New Plan",
            slug="new-plan",
            description="A new plan",
            cpu_limit=4,
            memory_limit="8g",
            cost_per_hour=5,
        )
        assert plan.name == "New Plan"
        assert plan.slug == "new-plan"
        assert plan.cpu_limit == 4

    @pytest.mark.asyncio
    async def test_create_plan_duplicate_slug(self, db_session):
        """create_plan should reject duplicate slug."""
        plan = ServerPlan(name="Existing", slug="existing", cpu_limit=1)
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.create_plan(name="Existing 2", slug="existing", cpu_limit=2)
        assert "already exists" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cannot_disable_server_availability_for_used_plan(self, db_session, test_user):
        service = PlanService(db_session)
        plan = await service.create_plan(
            name="Used Plan",
            slug="used-plan",
            cpu_limit=1,
            allow_servers=True,
            allow_batch_jobs=True,
        )
        db_session.add(
            Server(
                name="uses-the-plan",
                user_id=test_user.id,
                plan_id=plan.id,
                status="stopped",
            )
        )
        await db_session.commit()

        with pytest.raises(HTTPException) as exc:
            await service.update_plan(str(plan.id), allow_servers=False)
        assert exc.value.status_code == 409
        assert "servers use this plan" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_update_plan_success(self, db_session):
        """update_plan should update plan fields."""
        plan = ServerPlan(name="Old Name", slug="update-plan", cpu_limit=1)
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        updated = await service.update_plan(str(plan.id), name="New Name", cpu_limit=8)
        assert updated.name == "New Name"
        assert updated.cpu_limit == 8

    @pytest.mark.asyncio
    async def test_update_plan_not_found(self, db_session):
        """update_plan should raise when plan not found."""
        service = PlanService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.update_plan(str(uuid_mod.uuid4()), name="X")
        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_deactivate_plan(self, db_session):
        """deactivate_plan should set is_active=False when another active plan remains."""
        plan = ServerPlan(name="Active", slug="active-plan", is_active=True, cpu_limit=1)
        fallback = ServerPlan(
            name="Fallback", slug="active-fallback", is_active=True, is_public=True, cpu_limit=1
        )
        db_session.add_all([plan, fallback])
        await db_session.commit()

        service = PlanService(db_session)
        updated = await service.deactivate_plan(str(plan.id))
        assert updated.is_active is False

    @pytest.mark.asyncio
    async def test_activate_plan(self, db_session):
        """activate_plan should set is_active=True."""
        plan = ServerPlan(name="Inactive", slug="inactive-plan", is_active=False, cpu_limit=1)
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        updated = await service.activate_plan(str(plan.id))
        assert updated.is_active is True

    @pytest.mark.asyncio
    async def test_delete_plan_success(self, db_session):
        """delete_plan should remove plan when another active plan remains."""
        plan = ServerPlan(name="To Delete", slug="delete-plan", cpu_limit=1)
        fallback = ServerPlan(
            name="Fallback", slug="delete-fallback", is_active=True, is_public=True, cpu_limit=1
        )
        db_session.add_all([plan, fallback])
        await db_session.commit()

        service = PlanService(db_session)
        await service.delete_plan(str(plan.id))

        result = await db_session.execute(select(ServerPlan).where(ServerPlan.id == plan.id))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_plan_not_found(self, db_session):
        """delete_plan should raise when plan not found."""
        service = PlanService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.delete_plan(str(uuid_mod.uuid4()))
        assert "not found" in str(exc_info.value)


class TestPlanServiceAvailabilityGuard:
    """Tests for the safeguard against leaving the platform without a plan."""

    @pytest.mark.asyncio
    async def test_cannot_deactivate_last_active_plan(self, db_session):
        """Deactivating the only active plan should be rejected."""
        plan = ServerPlan(
            name="Only Plan", slug="only-plan", is_public=True, is_active=True, cpu_limit=1
        )
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.deactivate_plan(str(plan.id))

        assert exc_info.value.status_code == 409
        assert "last active plan" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_cannot_delete_last_active_plan(self, db_session):
        """Deleting the only active plan should be rejected."""
        plan = ServerPlan(
            name="Only Plan Delete",
            slug="only-plan-delete",
            is_public=True,
            is_active=True,
            cpu_limit=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_plan(str(plan.id))

        assert exc_info.value.status_code == 409
        assert "last active plan" in exc_info.value.detail
        result = await db_session.execute(select(ServerPlan).where(ServerPlan.id == plan.id))
        assert result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_cannot_make_last_user_usable_plan_private(self, db_session):
        """Hiding the only user-usable plan should be rejected."""
        plan = ServerPlan(
            name="User Plan", slug="user-visible-plan", is_public=True, is_active=True, cpu_limit=1
        )
        private_plan = ServerPlan(
            name="Admin Plan",
            slug="admin-private-plan",
            is_public=False,
            visible_to_roles=[],
            is_active=True,
            cpu_limit=1,
        )
        db_session.add_all([plan, private_plan])
        await db_session.commit()

        service = PlanService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.update_plan(str(plan.id), is_public=False)

        assert exc_info.value.status_code == 409
        assert "last plan available to users" in exc_info.value.detail
        result = await db_session.execute(select(ServerPlan).where(ServerPlan.id == plan.id))
        assert result.scalar_one().is_public is True

    @pytest.mark.asyncio
    async def test_cannot_remove_user_role_from_last_user_usable_plan(self, db_session):
        """Removing the user role from the only user-visible plan should be rejected."""
        plan = ServerPlan(
            name="Role Plan",
            slug="role-visible-plan",
            is_public=False,
            visible_to_roles=["user"],
            is_active=True,
            cpu_limit=1,
        )
        private_plan = ServerPlan(
            name="Admin Plan",
            slug="admin-private-role-plan",
            is_public=False,
            visible_to_roles=[],
            is_active=True,
            cpu_limit=1,
        )
        db_session.add_all([plan, private_plan])
        await db_session.commit()

        service = PlanService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.update_plan(str(plan.id), visible_to_roles=[])

        assert exc_info.value.status_code == 409
        assert "last plan available to users" in exc_info.value.detail
        result = await db_session.execute(select(ServerPlan).where(ServerPlan.id == plan.id))
        assert "user" in result.scalar_one().visible_to_roles

    @pytest.mark.asyncio
    async def test_cannot_delete_last_user_usable_plan(self, db_session):
        """Deleting the only user-usable plan should be rejected."""
        plan = ServerPlan(
            name="User Plan Delete",
            slug="user-visible-delete",
            is_public=True,
            is_active=True,
            cpu_limit=1,
        )
        private_plan = ServerPlan(
            name="Admin Plan",
            slug="admin-private-delete",
            is_public=False,
            visible_to_roles=[],
            is_active=True,
            cpu_limit=1,
        )
        db_session.add_all([plan, private_plan])
        await db_session.commit()

        service = PlanService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_plan(str(plan.id))

        assert exc_info.value.status_code == 409
        assert "last plan available to users" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_can_deactivate_when_another_active_plan_remains(self, db_session):
        """Deactivation is allowed when another active plan remains."""
        plan = ServerPlan(
            name="Active Plan", slug="deactivate-allowed", is_active=True, cpu_limit=1
        )
        fallback = ServerPlan(
            name="Fallback", slug="deactivate-fallback", is_active=True, is_public=True, cpu_limit=1
        )
        db_session.add_all([plan, fallback])
        await db_session.commit()

        service = PlanService(db_session)
        updated = await service.deactivate_plan(str(plan.id))
        assert updated.is_active is False

    @pytest.mark.asyncio
    async def test_can_delete_when_another_user_usable_plan_remains(self, db_session):
        """Deletion is allowed when another active user-usable plan remains."""
        plan = ServerPlan(
            name="User Plan", slug="delete-allowed", is_public=True, is_active=True, cpu_limit=1
        )
        fallback = ServerPlan(
            name="Fallback",
            slug="delete-allowed-fallback",
            is_public=True,
            is_active=True,
            cpu_limit=1,
        )
        db_session.add_all([plan, fallback])
        await db_session.commit()

        service = PlanService(db_session)
        await service.delete_plan(str(plan.id))

        result = await db_session.execute(select(ServerPlan).where(ServerPlan.id == plan.id))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_can_hide_plan_when_another_user_usable_plan_remains(self, db_session):
        """Making a plan private is allowed when another user-usable plan remains."""
        plan = ServerPlan(
            name="User Plan", slug="hide-allowed", is_public=True, is_active=True, cpu_limit=1
        )
        fallback = ServerPlan(
            name="Fallback",
            slug="hide-allowed-fallback",
            is_public=True,
            is_active=True,
            cpu_limit=1,
        )
        db_session.add_all([plan, fallback])
        await db_session.commit()

        service = PlanService(db_session)
        updated = await service.update_plan(str(plan.id), is_public=False)
        assert updated.is_public is False

    @pytest.mark.asyncio
    async def test_can_activate_and_publish_inactive_private_plan(self, db_session):
        """Activating or publishing a plan is always allowed."""
        plan = ServerPlan(
            name="Dormant Plan",
            slug="dormant-plan",
            is_active=False,
            is_public=False,
            visible_to_roles=[],
            cpu_limit=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        activated = await service.activate_plan(str(plan.id))
        assert activated.is_active is True

        published = await service.update_plan(str(plan.id), is_public=True)
        assert published.is_public is True

    @pytest.mark.asyncio
    async def test_can_delete_inactive_private_plan(self, db_session):
        """A plan that is already inactive/private does not trip the guard."""
        active_plan = ServerPlan(
            name="Active Plan",
            slug="inactive-delete-active",
            is_public=True,
            is_active=True,
            cpu_limit=1,
        )
        stale_plan = ServerPlan(
            name="Stale Plan",
            slug="inactive-delete-stale",
            is_active=False,
            is_public=False,
            visible_to_roles=[],
            cpu_limit=1,
        )
        db_session.add_all([active_plan, stale_plan])
        await db_session.commit()

        service = PlanService(db_session)
        await service.delete_plan(str(stale_plan.id))

        result = await db_session.execute(select(ServerPlan).where(ServerPlan.id == stale_plan.id))
        assert result.scalar_one_or_none() is None


class TestPlanServiceCanUse:
    """Tests for can_user_use_plan."""

    @pytest.mark.asyncio
    async def test_can_use_public_plan(self, db_session):
        """Any user can use public plan."""
        plan = ServerPlan(name="Public", slug="public", is_public=True, is_active=True, cpu_limit=1)
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        assert await service.can_user_use_plan(str(plan.id), "user") is True

    @pytest.mark.asyncio
    async def test_can_use_inactive_plan(self, db_session):
        """Inactive plan should be rejected."""
        plan = ServerPlan(name="Inactive", slug="inactive", is_active=False, cpu_limit=1)
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        assert await service.can_user_use_plan(str(plan.id), "user") is False

    @pytest.mark.asyncio
    async def test_can_use_admin_override(self, db_session):
        """Admin can use any active plan."""
        plan = ServerPlan(
            name="Private", slug="private", is_public=False, is_active=True, cpu_limit=1
        )
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        assert await service.can_user_use_plan(str(plan.id), "admin") is True

    @pytest.mark.asyncio
    async def test_can_use_role_visible(self, db_session):
        """User can use plan visible to their role."""
        plan = ServerPlan(
            name="Role Plan",
            slug="role-plan",
            is_public=False,
            visible_to_roles=["user"],
            is_active=True,
            cpu_limit=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        assert await service.can_user_use_plan(str(plan.id), "user") is True

    @pytest.mark.asyncio
    async def test_can_use_direct_access(self, db_session, test_user):
        """User can use plan they have direct access to."""
        plan = ServerPlan(
            name="Direct", slug="direct", is_public=False, is_active=True, cpu_limit=1
        )
        db_session.add(plan)
        await db_session.flush()

        access = UserPlanAccess(plan_id=plan.id, user_id=test_user.id)
        db_session.add(access)
        await db_session.commit()

        service = PlanService(db_session)
        assert await service.can_user_use_plan(str(plan.id), "user", str(test_user.id)) is True

    @pytest.mark.asyncio
    async def test_can_use_workspace_access(self, db_session, test_user):
        """User can use plan accessible via workspace."""
        ws = SharedWorkspace(name="Test WS", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="member")
        db_session.add(member)
        await db_session.flush()

        plan = ServerPlan(
            name="WS Plan", slug="ws-plan-2", is_public=False, is_active=True, cpu_limit=1
        )
        db_session.add(plan)
        await db_session.flush()

        ws_access = WorkspacePlanAccess(plan_id=plan.id, workspace_id=ws.id)
        db_session.add(ws_access)
        await db_session.commit()

        service = PlanService(db_session)
        assert await service.can_user_use_plan(str(plan.id), "user", str(test_user.id)) is True


class TestPlanServiceUserAccess:
    """Tests for user plan access management."""

    @pytest.mark.asyncio
    async def test_grant_user_access(self, db_session, test_user):
        """grant_user_access should create access record."""
        plan = ServerPlan(name="Plan", slug="grant-plan", cpu_limit=1)
        db_session.add(plan)
        await db_session.commit()

        service = PlanService(db_session)
        access = await service.grant_user_access(str(plan.id), str(test_user.id))
        assert access.plan_id == plan.id
        assert access.user_id == test_user.id

    @pytest.mark.asyncio
    async def test_grant_user_access_duplicate(self, db_session, test_user):
        """grant_user_access should reject duplicate."""
        plan = ServerPlan(name="Plan", slug="dup-plan", cpu_limit=1)
        db_session.add(plan)
        await db_session.flush()

        access = UserPlanAccess(plan_id=plan.id, user_id=test_user.id)
        db_session.add(access)
        await db_session.commit()

        service = PlanService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.grant_user_access(str(plan.id), str(test_user.id))
        assert "already has access" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_revoke_user_access(self, db_session, test_user):
        """revoke_user_access should remove access."""
        plan = ServerPlan(name="Plan", slug="revoke-plan", cpu_limit=1)
        db_session.add(plan)
        await db_session.flush()

        access = UserPlanAccess(plan_id=plan.id, user_id=test_user.id)
        db_session.add(access)
        await db_session.commit()

        service = PlanService(db_session)
        await service.revoke_user_access(str(plan.id), str(test_user.id))

        result = await db_session.execute(
            select(UserPlanAccess).where(
                and_(UserPlanAccess.plan_id == plan.id, UserPlanAccess.user_id == test_user.id)
            )
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_list_plan_users(self, db_session, test_user, admin_user):
        """list_plan_users should return users with access."""
        plan = ServerPlan(name="Plan", slug="list-plan", cpu_limit=1)
        db_session.add(plan)
        await db_session.flush()

        access = UserPlanAccess(plan_id=plan.id, user_id=test_user.id, granted_by=admin_user.id)
        db_session.add(access)
        await db_session.commit()

        service = PlanService(db_session)
        users = await service.list_plan_users(str(plan.id))
        assert len(users) == 1
        assert users[0]["username"] == test_user.username


class TestPlanServiceWorkspaceAccess:
    """Tests for workspace plan access management."""

    @pytest.mark.asyncio
    async def test_grant_workspace_access(self, db_session, test_user):
        """grant_workspace_access should create access record."""
        plan = ServerPlan(name="Plan", slug="ws-grant-plan", cpu_limit=1)
        ws = SharedWorkspace(name="WS", owner_id=test_user.id)
        db_session.add_all([plan, ws])
        await db_session.commit()

        service = PlanService(db_session)
        access = await service.grant_workspace_access(str(plan.id), str(ws.id))
        assert access.plan_id == plan.id
        assert access.workspace_id == ws.id

    @pytest.mark.asyncio
    async def test_revoke_workspace_access(self, db_session, test_user):
        """revoke_workspace_access should remove access."""
        plan = ServerPlan(name="Plan", slug="ws-revoke-plan", cpu_limit=1)
        ws = SharedWorkspace(name="WS", owner_id=test_user.id)
        db_session.add_all([plan, ws])
        await db_session.flush()

        access = WorkspacePlanAccess(plan_id=plan.id, workspace_id=ws.id)
        db_session.add(access)
        await db_session.commit()

        service = PlanService(db_session)
        await service.revoke_workspace_access(str(plan.id), str(ws.id))

        result = await db_session.execute(
            select(WorkspacePlanAccess).where(
                and_(
                    WorkspacePlanAccess.plan_id == plan.id,
                    WorkspacePlanAccess.workspace_id == ws.id,
                )
            )
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_list_plan_workspaces(self, db_session, test_user):
        """list_plan_workspaces should return workspaces with access."""
        plan = ServerPlan(name="Plan", slug="ws-list-plan", cpu_limit=1)
        ws = SharedWorkspace(name="WS", owner_id=test_user.id)
        db_session.add_all([plan, ws])
        await db_session.flush()

        access = WorkspacePlanAccess(plan_id=plan.id, workspace_id=ws.id)
        db_session.add(access)
        await db_session.commit()

        service = PlanService(db_session)
        workspaces = await service.list_plan_workspaces(str(plan.id))
        assert len(workspaces) == 1
        assert workspaces[0]["workspace_name"] == "WS"
