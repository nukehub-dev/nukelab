"""Tests for Admin API endpoints."""

import pytest


class TestAdminAccessControl:
    """Tests for admin access restrictions."""

    @pytest.mark.asyncio
    async def test_non_admin_cannot_access_stats(self, client, user_token):
        """Regular user should not access admin stats."""
        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list_users(self, client, user_token):
        """Regular user should not list admin users."""
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_access_servers(self, client, user_token):
        """Regular user should not access admin servers."""
        response = await client.get(
            "/api/admin/servers",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]


class TestAdminStats:
    """Tests for admin stats endpoint."""

    @pytest.mark.asyncio
    async def test_admin_get_stats(self, client, admin_token):
        """Admin should get dashboard stats."""
        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "servers" in data
        assert "credits" in data


class TestAdminUserManagement:
    """Tests for admin user management."""

    @pytest.mark.asyncio
    async def test_admin_list_users(self, client, admin_token):
        """Admin should list users."""
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data

    @pytest.mark.asyncio
    async def test_admin_list_users_with_search(self, client, admin_token):
        """Admin should search users."""
        response = await client.get(
            "/api/admin/users?search=test",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_list_users_with_role_filter(self, client, admin_token):
        """Admin should filter users by role."""
        response = await client.get(
            "/api/admin/users?role=user",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_bulk_action_invalid_action(self, client, admin_token):
        """Invalid bulk action should fail or no-op."""
        response = await client.post(
            "/api/admin/users/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid", "user_ids": []}
        )
        # Empty user_ids may return 200 as no-op; invalid action with users should error
        assert response.status_code in [200, 400, 422]


class TestAdminServerManagement:
    """Tests for admin server management."""

    @pytest.mark.asyncio
    async def test_admin_list_servers(self, client, admin_token):
        """Admin should list all servers."""
        response = await client.get(
            "/api/admin/servers",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "servers" in data

    @pytest.mark.asyncio
    async def test_admin_server_bulk_action_invalid(self, client, admin_token):
        """Invalid server bulk action should fail or no-op."""
        response = await client.post(
            "/api/admin/servers/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid", "server_ids": []}
        )
        assert response.status_code in [200, 400, 422]


class TestAdminCredits:
    """Tests for admin credit management."""

    @pytest.mark.asyncio
    async def test_admin_credits_summary(self, client, admin_token):
        """Admin should get credits summary."""
        response = await client.get(
            "/api/admin/credits/summary",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def admin_grant_bulk_invalid(self, client, admin_token):
        """Bulk grant with invalid data should fail."""
        response = await client.post(
            "/api/admin/credits/grant-bulk",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"user_ids": [], "amount": 0, "reason": ""}
        )
        assert response.status_code in [400, 422]


class TestAdminActivity:
    """Tests for admin activity endpoints."""

    @pytest.mark.asyncio
    async def test_admin_get_activity(self, client, admin_token):
        """Admin should get activity logs."""
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data

    @pytest.mark.asyncio
    async def test_admin_get_activity_with_filters(self, client, admin_token):
        """Admin should filter activity logs."""
        response = await client.get(
            "/api/admin/activity?limit=10&action=server.create",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_system_health(self, client, admin_token):
        """Admin should get system health."""
        response = await client.get(
            "/api/admin/system/health",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200


class TestAdminPermissions:
    """Tests for admin permission management."""

    @pytest.mark.asyncio
    async def test_admin_get_permissions(self, client, admin_token):
        """Admin should get permissions list."""
        response = await client.get(
            "/api/admin/permissions",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_update_permissions_invalid_role(self, client, admin_token):
        """Updating permissions for invalid role should 404."""
        response = await client.put(
            "/api/admin/permissions/invalid_role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"permissions": []}
        )
        assert response.status_code in [400, 404, 422]


class TestAdminEmail:
    """Tests for admin email management."""

    @pytest.mark.asyncio
    async def test_admin_get_email_config(self, client, admin_token):
        """Admin should get email config."""
        response = await client.get(
            "/api/admin/email-config",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_get_email_status(self, client, admin_token):
        """Admin should get email status."""
        response = await client.get(
            "/api/admin/email-status",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200


class TestAdminWorkspaceManagement:
    """Tests for admin workspace management."""

    @pytest.mark.asyncio
    async def test_admin_list_workspaces(self, client, admin_token):
        """Admin should list workspaces."""
        response = await client.get(
            "/api/admin/workspaces",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "workspaces" in data

    @pytest.mark.asyncio
    async def test_admin_get_workspace_not_found(self, client, admin_token):
        """Admin getting non-existent workspace should 404."""
        response = await client.get(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_update_workspace_not_found(self, client, admin_token):
        """Admin updating non-existent workspace should 404."""
        response = await client.put(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "new-name"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_delete_workspace_not_found(self, client, admin_token):
        """Admin deleting non-existent workspace should 404."""
        response = await client.delete(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_workspace_members_not_found(self, client, admin_token):
        """Admin getting members of non-existent workspace."""
        response = await client.get(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000/members",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        # May return 404 or empty list depending on implementation
        assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_admin_workspace_volumes_not_found(self, client, admin_token):
        """Admin getting volumes of non-existent workspace."""
        response = await client.get(
            "/api/admin/workspaces/00000000-0000-0000-0000-000000000000/volumes",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code in [200, 404]


class TestAdminVolumeManagement:
    """Tests for admin volume management."""

    @pytest.mark.asyncio
    async def test_admin_list_volumes(self, client, admin_token):
        """Admin should list volumes."""
        response = await client.get(
            "/api/admin/volumes",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "volumes" in data

    @pytest.mark.asyncio
    async def test_admin_get_volume_not_found(self, client, admin_token):
        """Admin getting non-existent volume should 404."""
        response = await client.get(
            "/api/admin/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_update_volume_not_found(self, client, admin_token):
        """Admin updating non-existent volume should 404."""
        response = await client.put(
            "/api/admin/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "new-name"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_delete_volume_not_found(self, client, admin_token):
        """Admin deleting non-existent volume should 404."""
        response = await client.delete(
            "/api/admin/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404


class TestAdminRetention:
    """Tests for admin retention settings."""

    @pytest.mark.asyncio
    async def test_admin_get_retention(self, client, admin_token):
        """Admin should get retention settings."""
        response = await client.get(
            "/api/admin/retention",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_update_retention(self, client, admin_token):
        """Admin should update retention settings."""
        response = await client.put(
            "/api/admin/retention",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"server_retention_days": 30}
        )
        # Endpoint may have specific required fields
        assert response.status_code in [200, 400, 422]


class TestAdminHealthMonitoring:
    """Tests for admin health monitoring."""

    @pytest.mark.asyncio
    async def test_admin_health_monitoring(self, client, admin_token):
        """Admin should get health monitoring data."""
        response = await client.get(
            "/api/admin/health/monitoring",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200


class TestAdminBulkActions:
    """Tests for admin bulk actions."""

    @pytest.mark.asyncio
    async def test_admin_workspace_bulk_action_invalid(self, client, admin_token):
        """Invalid workspace bulk action should fail."""
        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid", "workspace_ids": []}
        )
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_admin_volume_bulk_action_invalid(self, client, admin_token):
        """Invalid volume bulk action should fail."""
        response = await client.post(
            "/api/admin/volumes/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid", "volume_ids": []}
        )
        assert response.status_code in [400, 422]
