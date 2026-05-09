"""Tests for Shared Workspace service and API."""

import pytest
from httpx import AsyncClient


class TestWorkspaceModel:
    """Workspace model tests."""

    @pytest.mark.asyncio
    async def test_workspace_has_required_fields(self):
        """Workspace should have name, volume_name, and owner_id fields."""
        from app.models.shared_workspace import SharedWorkspace, WorkspaceMember

        ws = SharedWorkspace()
        assert hasattr(ws, 'name')
        assert hasattr(ws, 'volume_name')
        assert hasattr(ws, 'owner_id')

        member = WorkspaceMember()
        assert hasattr(member, 'role')
        assert hasattr(member, 'workspace_id')


class TestWorkspaceService:
    """Workspace service tests."""

    @pytest.mark.asyncio
    async def test_create_workspace(self, db_session, test_user):
        """Service should create a workspace."""
        from app.services.workspace_service import WorkspaceService

        service = WorkspaceService(db_session)
        workspace = await service.create_workspace(
            name="Test Workspace",
            description="A test workspace",
            volume_name="test-volume",
            owner_id=str(test_user.id)
        )

        assert workspace.name == "Test Workspace"
        assert workspace.volume_name == "test-volume"
        assert str(workspace.owner_id) == str(test_user.id)

    @pytest.mark.asyncio
    async def test_workspace_member_management(self, db_session, test_user, admin_user):
        """Service should add, update, and remove members."""
        from app.services.workspace_service import WorkspaceService

        service = WorkspaceService(db_session)
        workspace = await service.create_workspace(
            name="Test Workspace",
            description="Test",
            volume_name="test-volume",
            owner_id=str(test_user.id)
        )

        member = await service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(admin_user.id),
            role="read_write"
        )
        assert member.role == "read_write"

        is_member = await service.is_workspace_member(str(workspace.id), str(admin_user.id))
        assert is_member is True

        updated = await service.update_member_role(
            workspace_id=str(workspace.id),
            user_id=str(admin_user.id),
            role="admin"
        )
        assert updated.role == "admin"

        success = await service.remove_member(str(workspace.id), str(admin_user.id))
        assert success is True


class TestWorkspaceAPI:
    """Workspace API endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_and_list_workspaces(self, client: AsyncClient, test_user, user_token):
        """User should create and list workspaces via API."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "API Test Workspace",
            "description": "Testing",
            "volume_name": "test-vol"
        })
        assert resp.status_code == 201

        workspace = resp.json()
        assert workspace["name"] == "API Test Workspace"

        resp = await client.get("/api/workspaces/", headers=headers)
        assert resp.status_code == 200

        data = resp.json()
        assert len(data["workspaces"]) >= 1

        resp = await client.get(f"/api/workspaces/{workspace['id']}", headers=headers)
        assert resp.status_code == 200

        ws_data = resp.json()
        assert ws_data["name"] == "API Test Workspace"
