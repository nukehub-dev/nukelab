"""Tests for Shared Workspace service and API with multi-volume support."""

import pytest
from httpx import AsyncClient
from unittest import mock


@pytest.fixture(autouse=True)
def mock_docker_client():
    """Mock Docker container client to avoid real volume creation."""
    mock_vol = mock.AsyncMock()
    mock_vol.delete = mock.AsyncMock()
    
    mock_volumes = mock.AsyncMock()
    mock_volumes.create = mock.AsyncMock(return_value=mock_vol)
    mock_volumes.get = mock.AsyncMock(return_value=mock_vol)
    
    mock_client = mock.AsyncMock()
    mock_client.volumes = mock_volumes
    mock_client.close = mock.AsyncMock()
    
    mock_container_client = mock.AsyncMock()
    mock_container_client.client = mock_client
    mock_container_client.list_containers = mock.AsyncMock(return_value=[])
    mock_container_client.create_container = mock.AsyncMock(return_value=mock.Mock(id="mock-cid"))
    mock_container_client.start_container = mock.AsyncMock()
    mock_container_client.get_container_logs = mock.AsyncMock(return_value="mock logs")
    
    with mock.patch("app.services.volume_service.get_container_client", return_value=mock_container_client):
        yield


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
        assert "my_membership" in ws_data
        assert ws_data["member_count"] == 1  # Owner is a member
        assert "volume_count" in ws_data




class TestWorkspaceCollaboration:
    """Tests for leave, transfer, activity, and invitation expiry."""

    @pytest.mark.asyncio
    async def test_leave_workspace(self, client: AsyncClient, test_user, user_token):
        """Member should be able to leave a workspace; owner should not."""
        headers = {"Authorization": f"Bearer {user_token}"}

        # Create workspace
        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Leave Test Workspace",
            "description": "Testing leave",
        })
        workspace = resp.json()

        # Owner trying to leave should fail
        resp = await client.post(f"/api/workspaces/{workspace['id']}/leave", headers=headers)
        assert resp.status_code == 400
        assert "transfer ownership" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_transfer_ownership(self, client: AsyncClient, test_user, admin_user, user_token, admin_token):
        """Owner should transfer ownership to another member."""
        headers = {"Authorization": f"Bearer {user_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Create workspace
        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Transfer Test Workspace",
            "description": "Testing transfer",
        })
        workspace = resp.json()

        # Invite admin_user
        resp = await client.post(
            f"/api/workspaces/{workspace['id']}/invitations",
            headers=headers,
            json={"user_id": str(admin_user.id), "role": "read_write"}
        )
        invitation = resp.json()

        # Accept as admin_user
        resp = await client.post(
            f"/api/workspaces/{workspace['id']}/invitations/{invitation['id']}/accept",
            headers=admin_headers
        )
        assert resp.status_code == 200

        # Transfer ownership
        resp = await client.post(
            f"/api/workspaces/{workspace['id']}/transfer",
            headers=headers,
            json={"user_id": str(admin_user.id)}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner_id"] == str(admin_user.id)

    @pytest.mark.asyncio
    async def test_invitation_expiration(self, client: AsyncClient, test_user, admin_user, user_token, admin_token, db_session):
        """Expired invitations should be rejected."""
        headers = {"Authorization": f"Bearer {user_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Create workspace
        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Expiry Test Workspace",
            "description": "Testing expiry",
        })
        workspace = resp.json()

        # Invite admin_user
        resp = await client.post(
            f"/api/workspaces/{workspace['id']}/invitations",
            headers=headers,
            json={"user_id": str(admin_user.id), "role": "read_write"}
        )
        invitation = resp.json()
        assert "expires_at" in invitation

        # Manually expire the invitation in DB via db_session fixture
        from app.models.workspace_invitation import WorkspaceInvitation
        from sqlalchemy import update
        from datetime import datetime, timedelta, UTC
        await db_session.execute(
            update(WorkspaceInvitation)
            .where(WorkspaceInvitation.id == invitation["id"])
            .values(expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1))
        )
        await db_session.commit()

        # Accept as admin_user should fail
        resp = await client.post(
            f"/api/workspaces/{workspace['id']}/invitations/{invitation['id']}/accept",
            headers=admin_headers
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_workspace_activity(self, client: AsyncClient, test_user, user_token):
        """Activity feed should return workspace events."""
        headers = {"Authorization": f"Bearer {user_token}"}

        # Create workspace
        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Activity Test Workspace",
            "description": "Testing activity",
        })
        workspace = resp.json()

        # Get activity
        resp = await client.get(f"/api/workspaces/{workspace['id']}/activity", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "activity" in data
        assert isinstance(data["activity"], list)


    @pytest.mark.asyncio
    async def test_creator_is_in_members_list(self, client: AsyncClient, test_user, user_token):
        """Workspace creator/owner should appear in the members list."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Members List Test",
            "description": "Testing creator in members",
        })
        workspace = resp.json()

        # Use the paginated members endpoint
        resp = await client.get(f"/api/workspaces/{workspace['id']}/members", headers=headers)
        data = resp.json()

        member_ids = [m["user_id"] for m in data["members"]]
        assert str(test_user.id) in member_ids
        # Owner should have admin role in members list
        owner_member = next(m for m in data["members"] if m["user_id"] == str(test_user.id))
        assert owner_member["role"] == "admin"
        # Check pagination
        assert "pagination" in data
        assert data["pagination"]["total"] == 1

    @pytest.mark.asyncio
    async def test_owner_role_cannot_be_changed(self, client: AsyncClient, test_user, user_token):
        """Owner's role cannot be changed via member update."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Owner Role Test",
            "description": "Testing owner protection",
        })
        workspace = resp.json()

        resp = await client.put(
            f"/api/workspaces/{workspace['id']}/members/{test_user.id}",
            headers=headers,
            json={"role": "read_write"}
        )
        assert resp.status_code == 400
        assert "owner" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_owner_cannot_be_removed(self, client: AsyncClient, test_user, user_token):
        """Owner cannot be removed from workspace."""
        headers = {"Authorization": f"Bearer {user_token}"}

        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Owner Remove Test",
            "description": "Testing owner protection",
        })
        workspace = resp.json()

        resp = await client.delete(
            f"/api/workspaces/{workspace['id']}/members/{test_user.id}",
            headers=headers
        )
        assert resp.status_code == 400
        assert "owner" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_list_workspace_members_pagination(self, client: AsyncClient, test_user, user_token):
        """Members endpoint should support pagination, sorting, and search."""
        headers = {"Authorization": f"Bearer {user_token}"}

        # Create workspace
        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Pagination Test",
            "description": "Testing member pagination",
        })
        workspace = resp.json()

        # List members with default pagination
        resp = await client.get(f"/api/workspaces/{workspace['id']}/members", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "members" in data
        assert "pagination" in data
        assert data["pagination"]["total"] == 1
        assert data["pagination"]["page"] == 1

        # Test sorting by username
        resp = await client.get(
            f"/api/workspaces/{workspace['id']}/members?sort_by=username&sort_order=asc",
            headers=headers
        )
        assert resp.status_code == 200

        # Test role filter
        resp = await client.get(
            f"/api/workspaces/{workspace['id']}/members?role=admin",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total"] == 1

        resp = await client.get(
            f"/api/workspaces/{workspace['id']}/members?role=read_write",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total"] == 0

        # Test search
        resp = await client.get(
            f"/api/workspaces/{workspace['id']}/members?search={test_user.username[:3]}",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total"] == 1

    @pytest.mark.asyncio
    async def test_list_workspace_volumes_pagination(self, client: AsyncClient, test_user, user_token):
        """Volumes endpoint should support pagination."""
        headers = {"Authorization": f"Bearer {user_token}"}

        # Create workspace
        resp = await client.post("/api/workspaces/", headers=headers, json={
            "name": "Volume Pagination Test",
            "description": "Testing volume pagination",
        })
        workspace = resp.json()

        # List volumes (empty)
        resp = await client.get(f"/api/workspaces/{workspace['id']}/volumes", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "volumes" in data
        assert "pagination" in data
        assert data["pagination"]["total"] == 0

        # Test sorting
        resp = await client.get(
            f"/api/workspaces/{workspace['id']}/volumes?sort_by=added_at&sort_order=desc",
            headers=headers
        )
        assert resp.status_code == 200
