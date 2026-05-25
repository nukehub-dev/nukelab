"""Tests for admin workspace management endpoints."""

import pytest
from httpx import AsyncClient


class TestAdminWorkspaceList:
    """Admin workspace listing tests."""

    @pytest.mark.asyncio
    async def test_admin_can_list_all_workspaces(self, client: AsyncClient, test_user, admin_user, admin_token):
        """Admin should see all workspaces, not just their own."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create workspaces via API
        resp1 = await client.post("/api/workspaces/", json={"name": "Workspace One", "description": "First"}, headers=headers)
        assert resp1.status_code == 201
        resp2 = await client.post("/api/workspaces/", json={"name": "Workspace Two", "description": "Second"}, headers=headers)
        assert resp2.status_code == 201

        # Admin list
        response = await client.get("/api/admin/workspaces", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "workspaces" in data
        assert "pagination" in data
        assert len(data["workspaces"]) >= 2
        names = [w["name"] for w in data["workspaces"]]
        assert "Workspace One" in names
        assert "Workspace Two" in names

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list_workspaces(self, client: AsyncClient, test_user, user_token):
        """Regular user should get 403 on admin workspace list."""
        headers = {"Authorization": f"Bearer {user_token}"}
        response = await client.get("/api/admin/workspaces", headers=headers)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_search_workspaces(self, client: AsyncClient, admin_user, admin_token):
        """Admin should be able to search workspaces by name."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        resp1 = await client.post("/api/workspaces/", json={"name": "Alpha Workspace", "description": "Alpha"}, headers=headers)
        assert resp1.status_code == 201
        resp2 = await client.post("/api/workspaces/", json={"name": "Beta Workspace", "description": "Beta"}, headers=headers)
        assert resp2.status_code == 201

        response = await client.get("/api/admin/workspaces?search=Alpha", headers=headers)
        assert response.status_code == 200
        data = response.json()
        names = [w["name"] for w in data["workspaces"]]
        assert "Alpha Workspace" in names
        assert "Beta Workspace" not in names

    @pytest.mark.asyncio
    async def test_admin_filter_by_status(self, client: AsyncClient, admin_user, admin_token):
        """Admin should be able to filter workspaces by status."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        await client.post("/workspaces", json={"name": "Active WS", "description": ""}, headers=headers)

        # Filter active
        response = await client.get("/admin/workspaces?status=active", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert all(w["is_active"] for w in data["workspaces"])


class TestAdminWorkspaceDetail:
    """Admin workspace detail tests."""

    @pytest.mark.asyncio
    async def test_admin_can_get_workspace_details(self, client: AsyncClient, admin_user, admin_token):
        """Admin should get workspace with members and volumes."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp = await client.post("/api/workspaces/", json={"name": "Detail WS", "description": ""}, headers=headers)
        assert create_resp.status_code == 201
        ws_id = create_resp.json()["id"]

        response = await client.get(f"/api/admin/workspaces/{ws_id}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "workspace" in data
        assert "members" in data
        assert "volumes" in data
        assert data["workspace"]["name"] == "Detail WS"

    @pytest.mark.asyncio
    async def test_admin_get_nonexistent_workspace(self, client: AsyncClient, admin_user, admin_token):
        """Admin should get 404 for nonexistent workspace."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = await client.get("/api/admin/workspaces/00000000-0000-0000-0000-000000000000", headers=headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_non_admin_cannot_get_workspace_details(self, client: AsyncClient, test_user, user_token):
        """Regular user should get 403."""
        headers = {"Authorization": f"Bearer {user_token}"}
        response = await client.get("/api/admin/workspaces/00000000-0000-0000-0000-000000000000", headers=headers)
        assert response.status_code == 403


class TestAdminWorkspaceUpdate:
    """Admin workspace update tests."""

    @pytest.mark.asyncio
    async def test_admin_can_update_workspace(self, client: AsyncClient, admin_user, admin_token):
        """Admin with WORKSPACES_MANAGE should update any workspace."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp = await client.post("/api/workspaces/", json={"name": "Update WS", "description": "Old desc"}, headers=headers)
        assert create_resp.status_code == 201
        ws_id = create_resp.json()["id"]

        response = await client.put(f"/api/admin/workspaces/{ws_id}", json={
            "name": "Updated Name",
            "description": "New desc",
            "is_active": False
        }, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["workspace"]["name"] == "Updated Name"
        assert data["workspace"]["description"] == "New desc"
        assert data["workspace"]["is_active"] is False

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_workspace(self, client: AsyncClient, test_user, user_token, admin_user, admin_token):
        """Regular user should get 403."""
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}

        create_resp = await client.post("/api/workspaces/", json={"name": "Protected WS", "description": ""}, headers=admin_headers)
        assert create_resp.status_code == 201
        ws_id = create_resp.json()["id"]

        response = await client.put(f"/api/admin/workspaces/{ws_id}", json={"name": "Hacked"}, headers=user_headers)
        assert response.status_code == 403


class TestAdminWorkspaceDelete:
    """Admin workspace delete tests."""

    @pytest.mark.asyncio
    async def test_admin_can_delete_workspace(self, client: AsyncClient, admin_user, admin_token):
        """Admin with WORKSPACES_MANAGE should delete any workspace."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp = await client.post("/api/workspaces/", json={"name": "Delete WS", "description": ""}, headers=headers)
        assert create_resp.status_code == 201
        ws_id = create_resp.json()["id"]

        response = await client.delete(f"/api/admin/workspaces/{ws_id}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify it's gone
        get_resp = await client.get(f"/api/admin/workspaces/{ws_id}", headers=headers)
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_non_admin_cannot_delete_workspace(self, client: AsyncClient, test_user, user_token, admin_user, admin_token):
        """Regular user should get 403."""
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}

        create_resp = await client.post("/api/workspaces/", json={"name": "Protected WS", "description": ""}, headers=admin_headers)
        assert create_resp.status_code == 201
        ws_id = create_resp.json()["id"]

        response = await client.delete(f"/api/admin/workspaces/{ws_id}", headers=user_headers)
        assert response.status_code == 403


class TestAdminWorkspaceMembers:
    """Admin workspace member listing tests."""

    @pytest.mark.asyncio
    async def test_admin_can_list_workspace_members(self, client: AsyncClient, admin_user, admin_token):
        """Admin should list workspace members."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp = await client.post("/api/workspaces/", json={"name": "Members WS", "description": ""}, headers=headers)
        assert create_resp.status_code == 201
        ws_id = create_resp.json()["id"]

        response = await client.get(f"/api/admin/workspaces/{ws_id}/members", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "members" in data
        assert "pagination" in data
        # At least owner as member
        assert len(data["members"]) >= 1

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list_members(self, client: AsyncClient, test_user, user_token, admin_user, admin_token):
        """Regular user should get 403."""
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}

        create_resp = await client.post("/api/workspaces/", json={"name": "Members WS", "description": ""}, headers=admin_headers)
        assert create_resp.status_code == 201
        ws_id = create_resp.json()["id"]

        response = await client.get(f"/api/admin/workspaces/{ws_id}/members", headers=user_headers)
        assert response.status_code == 403


class TestBulkWorkspaceActions:
    """Bulk workspace action tests."""

    @pytest.mark.asyncio
    async def test_invalid_action_rejected(self, client: AsyncClient, admin_token):
        """Bulk endpoint should reject unknown actions."""
        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "invalid_action", "workspace_ids": ["123", "456"]}
        )
        assert response.status_code == 400
        assert "Invalid action" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_delete_action_accepted(self, client: AsyncClient, admin_token):
        """Bulk endpoint should accept 'delete' as a valid action."""
        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "delete", "workspace_ids": []}
        )
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_activate_action_accepted(self, client: AsyncClient, admin_token):
        """Bulk endpoint should accept 'activate' as a valid action."""
        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "activate", "workspace_ids": []}
        )
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_valid_deactivate_action_accepted(self, client: AsyncClient, admin_token):
        """Bulk endpoint should accept 'deactivate' as a valid action."""
        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "deactivate", "workspace_ids": []}
        )
        assert response.status_code != 400

    @pytest.mark.asyncio
    async def test_non_admin_cannot_bulk_action(self, client: AsyncClient, user_token):
        """Regular user should get 403 on workspace bulk action."""
        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"action": "delete", "workspace_ids": []}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_bulk_delete_workspaces(self, client: AsyncClient, admin_token):
        """Admin should be able to bulk delete workspaces."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp1 = await client.post("/api/workspaces/", json={"name": "Bulk Delete WS 1", "description": ""}, headers=headers)
        assert create_resp1.status_code == 201
        ws_id1 = create_resp1.json()["id"]

        create_resp2 = await client.post("/api/workspaces/", json={"name": "Bulk Delete WS 2", "description": ""}, headers=headers)
        assert create_resp2.status_code == 201
        ws_id2 = create_resp2.json()["id"]

        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers=headers,
            json={"action": "delete", "workspace_ids": [ws_id1, ws_id2]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "delete"
        assert ws_id1 in data["results"]["success"]
        assert ws_id2 in data["results"]["success"]

        # Verify they're gone
        get_resp1 = await client.get(f"/api/admin/workspaces/{ws_id1}", headers=headers)
        assert get_resp1.status_code == 404
        get_resp2 = await client.get(f"/api/admin/workspaces/{ws_id2}", headers=headers)
        assert get_resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_can_bulk_activate_deactivate_workspaces(self, client: AsyncClient, admin_token):
        """Admin should be able to bulk activate and deactivate workspaces."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        create_resp = await client.post("/api/workspaces/", json={"name": "Bulk Toggle WS", "description": ""}, headers=headers)
        assert create_resp.status_code == 201
        ws_id = create_resp.json()["id"]

        # Deactivate
        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers=headers,
            json={"action": "deactivate", "workspace_ids": [ws_id]}
        )
        assert response.status_code == 200
        data = response.json()
        assert ws_id in data["results"]["success"]

        # Verify deactivated
        get_resp = await client.get(f"/api/admin/workspaces/{ws_id}", headers=headers)
        assert get_resp.json()["workspace"]["is_active"] is False

        # Activate
        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers=headers,
            json={"action": "activate", "workspace_ids": [ws_id]}
        )
        assert response.status_code == 200
        data = response.json()
        assert ws_id in data["results"]["success"]

        # Verify activated
        get_resp = await client.get(f"/api/admin/workspaces/{ws_id}", headers=headers)
        assert get_resp.json()["workspace"]["is_active"] is True

    @pytest.mark.asyncio
    async def test_api_token_rejected_for_bulk_workspace_action(self, client: AsyncClient, admin_user, db_session):
        """API token authentication should be rejected for workspace bulk actions (JWT only)."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)

        token = ApiToken(
            user_id=admin_user.id,
            name="Admin API Token",
            token_hash=token_hash,
            token_prefix=raw_token[:16],
            scopes=["servers:read"],
            is_active=True,
        )
        db_session.add(token)
        await db_session.commit()

        response = await client.post(
            "/api/admin/workspaces/bulk-action",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"action": "delete", "workspace_ids": []}
        )
        assert response.status_code == 403
        assert "JWT authentication required" in response.json()["detail"]
