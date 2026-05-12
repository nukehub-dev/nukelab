"""Tests for Shared Workspace service and API with multi-volume support."""

import pytest
from httpx import AsyncClient


class TestWorkspaceModel:
    """Workspace model tests."""

    @pytest.mark.asyncio
    async def test_workspace_has_required_fields(self):
        """Workspace should have name and owner_id fields (no volume_name)."""
        from app.models.shared_workspace import SharedWorkspace, WorkspaceMember

        ws = SharedWorkspace()
        assert hasattr(ws, 'name')
        assert hasattr(ws, 'owner_id')
        assert hasattr(ws, 'description')
        assert not hasattr(ws, 'volume_name')  # Removed in new architecture

        member = WorkspaceMember()
        assert hasattr(member, 'role')
        assert hasattr(member, 'workspace_id')


class TestWorkspaceVolumeModel:
    """WorkspaceVolume association model tests."""

    @pytest.mark.asyncio
    async def test_workspace_volume_has_required_fields(self):
        """WorkspaceVolume should have workspace_id, volume_id, and role."""
        from app.models.workspace_volume import WorkspaceVolume

        wv = WorkspaceVolume()
        assert hasattr(wv, 'workspace_id')
        assert hasattr(wv, 'volume_id')
        assert hasattr(wv, 'role')
        assert hasattr(wv, 'added_at')

    @pytest.mark.asyncio
    async def test_workspace_volume_has_fields(self):
        """WorkspaceVolume should have required fields."""
        from app.models.workspace_volume import WorkspaceVolume

        wv = WorkspaceVolume()
        assert hasattr(wv, 'workspace_id')
        assert hasattr(wv, 'volume_id')
        assert hasattr(wv, 'role')
        assert hasattr(wv, 'added_at')
        # DB default is "read_write", but None before insert
        assert wv.role is None


class TestWorkspaceService:
    """Workspace service tests."""

    @pytest.mark.asyncio
    async def test_create_workspace(self, db_session, test_user):
        """Service should create a workspace without volume."""
        from app.services.workspace_service import WorkspaceService

        service = WorkspaceService(db_session)
        workspace = await service.create_workspace(
            name="Test Workspace",
            description="A test workspace",
            owner_id=str(test_user.id)
        )

        assert workspace.name == "Test Workspace"
        assert str(workspace.owner_id) == str(test_user.id)
        assert workspace.is_active is True

    @pytest.mark.asyncio
    async def test_workspace_member_management(self, db_session, test_user, admin_user):
        """Service should add, update, and remove members."""
        from app.services.workspace_service import WorkspaceService

        service = WorkspaceService(db_session)
        workspace = await service.create_workspace(
            name="Test Workspace",
            description="Test",
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

    @pytest.mark.asyncio
    async def test_workspace_volume_management(self, db_session, test_user):
        """Service should add and remove volumes from workspace."""
        from app.services.workspace_service import WorkspaceService
        from app.services.volume_service import VolumeService

        workspace_service = WorkspaceService(db_session)
        volume_service = VolumeService(db_session)

        workspace = await workspace_service.create_workspace(
            name="Multi-Volume Workspace",
            description="Test",
            owner_id=str(test_user.id)
        )

        # Create a volume
        volume = await volume_service.create_volume(
            name="test-ws-vol",
            display_name="Workspace Volume",
            owner_id=str(test_user.id),
        )

        # Add volume to workspace
        wv = await workspace_service.add_volume(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_write",
            added_by=str(test_user.id)
        )
        assert wv.volume_id == volume.id
        assert wv.role == "read_write"

        # Update volume role
        updated = await workspace_service.update_volume_role(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_only"
        )
        assert updated.role == "read_only"

        # Remove volume from workspace
        success = await workspace_service.remove_volume(str(workspace.id), str(volume.id))
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
        })
        assert resp.status_code == 201

        workspace = resp.json()
        assert workspace["name"] == "API Test Workspace"
        assert "volume_count" in workspace
        assert workspace["volume_count"] == 0

        resp = await client.get("/api/workspaces/", headers=headers)
        assert resp.status_code == 200

        data = resp.json()
        assert len(data["workspaces"]) >= 1
        assert any(w["name"] == "API Test Workspace" for w in data["workspaces"])

    @pytest.mark.asyncio
    async def test_workspace_volume_api(self, client: AsyncClient, test_user, user_token):
        """User should add volumes to workspace via API."""
        headers = {"Authorization": f"Bearer {user_token}"}

        # Create workspace
        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Volume Test Workspace",
            "description": "Testing volumes",
        })
        workspace = resp.json()

        # Create volume
        resp = await client.post("/api/volumes/", headers=headers, json={
            "display_name": "API Test Volume",
        })
        volume = resp.json()

        # Add volume to workspace
        resp = await client.post(
            f"/api/workspaces/{workspace['id']}/volumes",
            headers=headers,
            json={
                "volume_id": volume["id"],
                "role": "read_write",
            }
        )
        assert resp.status_code == 200

        wv = resp.json()
        assert wv["volume_id"] == volume["id"]
        assert wv["role"] == "read_write"

        # Remove volume from workspace
        resp = await client.delete(
            f"/api/workspaces/{workspace['id']}/volumes/{volume['id']}",
            headers=headers
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_workspace_detail(self, client: AsyncClient, test_user, user_token):
        """User should get workspace details including volumes."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Detail Test Workspace",
            "description": "Testing details",
        })
        workspace = resp.json()

        resp = await client.get(f"/api/workspaces/{workspace['id']}", headers=headers)
        assert resp.status_code == 200

        ws_data = resp.json()
        assert ws_data["name"] == "Detail Test Workspace"
        assert "members" in ws_data
        assert "volumes" in ws_data
