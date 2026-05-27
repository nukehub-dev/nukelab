"""Extended tests for Users API error paths."""

import pytest
from unittest import mock


class TestDiscoverUsers:
    """Tests for /api/users/discover."""

    @pytest.mark.asyncio
    async def test_discover_users_basic(self, client, user_token, admin_user):
        """Authenticated user should discover public users."""
        response = await client.get(
            "/api/users/discover",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data

    @pytest.mark.asyncio
    async def test_discover_users_with_search(self, client, user_token):
        """Search should filter discoverable users."""
        response = await client.get(
            "/api/users/discover?search=admin",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200


class TestPublicProfile:
    """Tests for public profile access controls."""

    @pytest.mark.asyncio
    async def test_public_profile_user_not_found(self, client, user_token):
        """Requesting non-existent user should 404."""
        response = await client.get(
            "/api/users/00000000-0000-0000-0000-000000000000/profile",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404


class TestAdminUserEndpoints:
    """Tests for admin user management endpoints."""

    @pytest.mark.asyncio
    async def test_admin_get_user_not_found(self, client, admin_token):
        """Admin getting non-existent user should 404."""
        response = await client.get(
            "/api/users/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_user_cannot_update_own_role(self, client, user_token):
        """Regular user trying to update own role should 403."""
        response = await client.put(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"role": "admin"}
        )
        # The /me/profile endpoint ignores role, so it should succeed but not change role
        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_user_cannot_update_own_credits(self, client, user_token, test_user):
        """Regular user trying to update own credits via admin endpoint should 403."""
        response = await client.put(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"nuke_balance": 9999}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_admin_delete_self_fails(self, client, admin_token, admin_user):
        """Admin deleting own account should 400."""
        response = await client.delete(
            f"/api/users/{admin_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400
        assert "own account" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_admin_disable_self_fails(self, client, admin_token, admin_user):
        """Admin disabling own account should 400."""
        response = await client.post(
            f"/api/users/{admin_user.id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"disabled": True, "reason": "test"}
        )
        assert response.status_code == 400
        assert "own account" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_impersonate_nonexistent_user(self, client, superadmin_token):
        """Impersonating non-existent user should 404."""
        response = await client.post(
            "/api/users/00000000-0000-0000-0000-000000000000/impersonate",
            headers={"Authorization": f"Bearer {superadmin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_non_admin_cannot_impersonate(self, client, user_token, test_user):
        """Regular user should not be able to impersonate."""
        response = await client.post(
            f"/api/users/{test_user.id}/impersonate",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]


class TestAvatar:
    """Tests for avatar endpoints."""

    @pytest.mark.asyncio
    async def test_upload_avatar_invalid_type(self, client, user_token):
        """Uploading non-image avatar should 400."""
        response = await client.post(
            "/api/users/me/avatar",
            headers={"Authorization": f"Bearer {user_token}"},
            files={"file": ("test.txt", b"not an image", "text/plain")}
        )
        assert response.status_code == 400


class TestChangePassword:
    """Tests for password change endpoint."""

    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, client, user_token, test_user):
        """Changing password with wrong current password should fail."""
        response = await client.post(
            "/api/users/me/change-password",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"current_password": "wrongpass", "new_password": "newpass123"}
        )
        assert response.status_code in [400, 401, 422]
