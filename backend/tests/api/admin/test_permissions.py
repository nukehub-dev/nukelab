"""Tests for Permission Matrix API."""

import pytest
from httpx import AsyncClient


class TestPermissionMatrixAccess:
    """Permission matrix access control tests."""

    @pytest.mark.asyncio
    async def test_get_permissions_requires_admin(self, client: AsyncClient, test_user, user_token):
        """Permission matrix should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.get("/api/admin/permissions", headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_permissions_as_admin(self, client: AsyncClient, admin_token):
        """Admin should retrieve full permission matrix."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp = await client.get("/api/admin/permissions", headers=headers)
        assert resp.status_code == 200

        data = resp.json()
        assert "roles" in data
        assert "permissions" in data
        assert "matrix" in data
        assert "super_admin" in data["matrix"]
        assert "admin" in data["matrix"]


class TestPermissionMatrixUpdates:
    """Permission matrix modification tests."""

    @pytest.mark.asyncio
    async def test_update_role_permissions(self, client: AsyncClient, admin_token):
        """Admin should update role permissions."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp = await client.get("/api/admin/permissions", headers=headers)
        data = resp.json()

        new_perms = ["users:read", "servers:read_all"]

        resp = await client.put(
            "/api/admin/permissions/moderator", headers=headers, json={"permissions": new_perms}
        )
        assert resp.status_code == 200

        updated = resp.json()
        assert updated["role"] == "moderator"
        assert updated["permissions"] == new_perms

    @pytest.mark.asyncio
    async def test_cannot_update_super_admin(self, client: AsyncClient, admin_token):
        """Super admin permissions should be immutable."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp = await client.put(
            "/api/admin/permissions/super_admin", headers=headers, json={"permissions": []}
        )
        assert resp.status_code == 403
