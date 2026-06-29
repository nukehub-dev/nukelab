# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Security regression tests for Broken Function Level Authorization (BFLA).

These tests verify that low-privilege users cannot perform administrative or
privileged actions.
"""

import pytest
from httpx import AsyncClient


class TestAdminBFLA:
    """BFLA tests for admin-only endpoints."""

    @pytest.mark.asyncio
    async def test_regular_user_cannot_list_all_users(self, client: AsyncClient, user_token):
        """Regular user should not access admin user list."""
        response = await client.get(
            "/api/users/",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_regular_user_cannot_create_user(self, client: AsyncClient, user_token):
        """Regular user should not create new users."""
        response = await client.post(
            "/api/users/",
            json={
                "username": "hackeduser",
                "email": "hacked@example.com",
                "password": "hackedpass123",
                "first_name": "Hacked",
                "last_name": "User",
                "role": "user",
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_regular_user_cannot_delete_user(
        self, client: AsyncClient, test_user, user_token
    ):
        """Regular user should not delete users."""
        response = await client.delete(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_regular_user_cannot_impersonate(
        self, client: AsyncClient, test_user, user_token
    ):
        """Regular user should not impersonate another user."""
        response = await client.post(
            f"/api/users/{test_user.id}/impersonate",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_moderator_cannot_impersonate(
        self, client: AsyncClient, test_user, moderator_token
    ):
        """Moderator should not impersonate another user."""
        response = await client.post(
            f"/api/users/{test_user.id}/impersonate",
            headers={"Authorization": f"Bearer {moderator_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_superadmin_can_impersonate(
        self, client: AsyncClient, test_user, superadmin_token
    ):
        """Super admin should be able to impersonate users."""
        response = await client.post(
            f"/api/users/{test_user.id}/impersonate",
            headers={"Authorization": f"Bearer {superadmin_token}"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )


class TestSystemBFLA:
    """BFLA tests for system configuration endpoints."""

    @pytest.mark.asyncio
    async def test_regular_user_cannot_toggle_maintenance(self, client: AsyncClient, user_token):
        """Regular user should not toggle maintenance mode."""
        response = await client.post(
            "/api/system/maintenance",
            json={"enabled": True},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_regular_user_cannot_update_system_config(self, client: AsyncClient, user_token):
        """Regular user should not update platform configuration."""
        response = await client.put(
            "/api/system/config",
            json={"app_name": "HackedLab"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_admin_can_toggle_maintenance(self, client: AsyncClient, admin_token):
        """Admin should be able to toggle maintenance mode."""
        response = await client.post(
            "/api/system/maintenance",
            params={"enabled": True},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )


class TestCreditBFLA:
    """BFLA tests for credit/NUKE management endpoints."""

    @pytest.mark.asyncio
    async def test_regular_user_cannot_grant_credits(
        self, client: AsyncClient, test_user, user_token
    ):
        """Regular user should not grant credits to themselves or others."""
        response = await client.post(
            f"/api/credits/users/{test_user.id}/grant",
            json={"amount": 1000, "reason": "hax"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (403, 404), (
            f"Expected 403/404, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_regular_user_cannot_set_daily_allowance(
        self, client: AsyncClient, test_user, user_token
    ):
        """Regular user should not modify daily allowance."""
        response = await client.put(
            f"/api/credits/users/{test_user.id}/daily-allowance",
            json={"daily_allowance": 9999},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (403, 404), (
            f"Expected 403/404, got {response.status_code}: {response.text}"
        )


class TestPlanBFLA:
    """BFLA tests for plan management endpoints."""

    @pytest.mark.asyncio
    async def test_regular_user_cannot_create_plan(self, client: AsyncClient, user_token):
        """Regular user should not create server plans."""
        response = await client.post(
            "/api/plans/",
            json={
                "name": "Hacked Plan",
                "slug": "hacked-plan",
                "cpu_limit": 32,
                "memory_limit": "64g",
                "disk_limit": "1t",
                "cost_per_hour": 0,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403, (
            f"Expected 403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_regular_user_cannot_assign_plan_to_user(
        self, client: AsyncClient, test_user, user_token
    ):
        """Regular user should not assign custom plans to users."""
        response = await client.post(
            f"/api/plans/00000000-0000-0000-0000-000000000001/users/{test_user.id}",
            json={"expires_at": "2030-01-01T00:00:00Z"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (403, 404), (
            f"Expected 403/404, got {response.status_code}: {response.text}"
        )


class TestMassAssignment:
    """Tests for mass assignment attempts that could lead to privilege escalation."""

    @pytest.mark.asyncio
    async def test_user_cannot_escalate_role_via_profile_update(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User should not be able to set their own role to admin via profile update."""
        response = await client.put(
            "/api/users/me/profile",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        # Either rejected as invalid field or user remains unchanged
        assert response.status_code in (200, 422), (
            f"Unexpected status: {response.status_code}: {response.text}"
        )

        await db_session.refresh(test_user)
        assert test_user.role == "user", "User role was escalated via mass assignment"

    @pytest.mark.asyncio
    async def test_user_cannot_set_nuke_balance_via_profile_update(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User should not be able to set their own NUKE balance via profile update."""
        original_balance = test_user.nuke_balance
        response = await client.put(
            "/api/users/me/profile",
            json={"nuke_balance": 999999},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (200, 422), (
            f"Unexpected status: {response.status_code}: {response.text}"
        )

        await db_session.refresh(test_user)
        assert test_user.nuke_balance == original_balance, (
            "NUKE balance was modified via mass assignment"
        )
