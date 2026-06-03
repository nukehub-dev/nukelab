"""Tests for VolumeAccessService permission checks."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def mock_docker_client():
    """Mock Docker container client to avoid real volume creation."""
    mock_vol = AsyncMock()
    mock_vol.delete = AsyncMock()
    mock_volumes = AsyncMock()
    mock_volumes.create = AsyncMock(return_value=mock_vol)
    mock_volumes.get = AsyncMock(return_value=mock_vol)
    mock_client = AsyncMock()
    mock_client.volumes = mock_volumes
    mock_client.close = AsyncMock()
    mock_container_client = AsyncMock()
    mock_container_client.client = mock_client
    mock_container_client.list_containers = AsyncMock(return_value=[])
    mock_container_client.create_container = AsyncMock(return_value=MagicMock(id="mock-cid"))
    mock_container_client.start_container = AsyncMock()
    mock_container_client.get_container_logs = AsyncMock(return_value="mock logs")
    with patch("app.services.volume_service.get_container_client", return_value=mock_container_client):
        yield


class TestVolumeAccessService:
    """Volume access control tests."""

    @pytest.mark.asyncio
    async def test_owner_full_access_no_workspace(self, db_session, test_user):
        """Owner should have read_write access to their volume when not in any workspace."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)

        volume = await vol_service.create_volume(
            name="test-owner-access",
            display_name="Owner Access Test",
            owner_id=str(test_user.id),
        )

        assert await access_service.can_access_volume(
            str(volume.id), str(test_user.id), "read_write"
        ) is True
        assert await access_service.can_access_volume(
            str(volume.id), str(test_user.id), "read_only"
        ) is True
        assert await access_service.can_manage_volume(
            str(volume.id), str(test_user.id)
        ) is True

    @pytest.mark.asyncio
    async def test_owner_capped_by_workspace_ro(self, db_session, test_user, admin_user):
        """Owner's access should be capped to RO when volume is shared as RO in workspace."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService
        from app.services.workspace_service import WorkspaceService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)
        ws_service = WorkspaceService(db_session)

        workspace = await ws_service.create_workspace(
            name="Owner Cap Test",
            description="Test",
            owner_id=str(admin_user.id)
        )

        volume = await vol_service.create_volume(
            name="test-owner-capped",
            display_name="Owner Capped Volume",
            owner_id=str(test_user.id),
        )

        # Add volume to workspace as read_only
        await ws_service.add_volume(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_only",
        )

        # Add test_user as workspace member
        await ws_service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(test_user.id),
            role="read_write",
        )

        # Owner should now be capped to RO
        assert await access_service.can_access_volume(
            str(volume.id), str(test_user.id), "read_only"
        ) is True
        assert await access_service.can_access_volume(
            str(volume.id), str(test_user.id), "read_write"
        ) is False

    @pytest.mark.asyncio
    async def test_owner_rw_when_workspace_rw(self, db_session, test_user, admin_user):
        """Owner should retain RW when volume is shared as RW in workspace."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService
        from app.services.workspace_service import WorkspaceService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)
        ws_service = WorkspaceService(db_session)

        workspace = await ws_service.create_workspace(
            name="Owner RW Test",
            description="Test",
            owner_id=str(admin_user.id)
        )

        volume = await vol_service.create_volume(
            name="test-owner-rw",
            display_name="Owner RW Volume",
            owner_id=str(test_user.id),
        )

        # Add volume to workspace as read_write
        await ws_service.add_volume(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_write",
        )

        # Add test_user as workspace member
        await ws_service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(test_user.id),
            role="read_write",
        )

        # Owner should still have RW
        assert await access_service.can_access_volume(
            str(volume.id), str(test_user.id), "read_write"
        ) is True
        assert await access_service.can_access_volume(
            str(volume.id), str(test_user.id), "read_only"
        ) is True

    @pytest.mark.asyncio
    async def test_other_user_no_private_access(self, db_session, test_user, admin_user):
        """Other users should not access private volumes."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)

        volume = await vol_service.create_volume(
            name="test-private-access",
            display_name="Private Access Test",
            owner_id=str(test_user.id),
            visibility="private",
        )

        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_write"
        ) is False
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_only"
        ) is False
        assert await access_service.can_manage_volume(
            str(volume.id), str(admin_user.id)
        ) is False

    @pytest.mark.asyncio
    async def test_public_volume_read_access(self, db_session, test_user, admin_user):
        """Public volume should allow read_only access to anyone."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)

        volume = await vol_service.create_volume(
            name="test-public-access",
            display_name="Public Access Test",
            owner_id=str(test_user.id),
            visibility="public",
        )

        # Admin can read
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_only"
        ) is True

        # But not write
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_write"
        ) is False

        # Owner still has full access
        assert await access_service.can_access_volume(
            str(volume.id), str(test_user.id), "read_write"
        ) is True

    @pytest.mark.asyncio
    async def test_workspace_member_access(self, db_session, test_user, admin_user):
        """Workspace members should access workspace volumes."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService
        from app.services.workspace_service import WorkspaceService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)
        ws_service = WorkspaceService(db_session)

        # Create workspace and volume
        workspace = await ws_service.create_workspace(
            name="Access Test Workspace",
            description="Test",
            owner_id=str(test_user.id)
        )

        volume = await vol_service.create_volume(
            name="test-ws-access-vol",
            display_name="Workspace Access Volume",
            owner_id=str(test_user.id),
        )

        # Add volume to workspace
        await ws_service.add_volume(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_write",
        )

        # Add admin as member
        await ws_service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(admin_user.id),
            role="read_write",
        )

        # Admin should now have access
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_write"
        ) is True

    @pytest.mark.asyncio
    async def test_workspace_read_only_member(self, db_session, test_user, admin_user):
        """Read-only workspace members should only read, not write."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService
        from app.services.workspace_service import WorkspaceService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)
        ws_service = WorkspaceService(db_session)

        workspace = await ws_service.create_workspace(
            name="ReadOnly Test Workspace",
            description="Test",
            owner_id=str(test_user.id)
        )

        volume = await vol_service.create_volume(
            name="test-ws-ro-vol",
            display_name="Read-Only Volume",
            owner_id=str(test_user.id),
        )

        # Add volume with read_write role
        await ws_service.add_volume(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_write",
        )

        # Add admin as read_only member
        await ws_service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(admin_user.id),
            role="read_only",
        )

        # Admin can read
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_only"
        ) is True

        # But not write (read_only member cannot write even if volume role is read_write)
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_write"
        ) is False

    @pytest.mark.asyncio
    async def test_multiple_workspaces_most_restrictive(self, db_session, test_user, admin_user):
        """Volume in multiple workspaces: most restrictive role wins."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService
        from app.services.workspace_service import WorkspaceService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)
        ws_service = WorkspaceService(db_session)

        workspace_rw = await ws_service.create_workspace(
            name="RW Workspace",
            description="Test",
            owner_id=str(test_user.id)
        )
        workspace_ro = await ws_service.create_workspace(
            name="RO Workspace",
            description="Test",
            owner_id=str(test_user.id)
        )

        volume = await vol_service.create_volume(
            name="test-multi-ws",
            display_name="Multi Workspace Volume",
            owner_id=str(test_user.id),
        )

        # Add volume to both workspaces with different roles
        await ws_service.add_volume(
            workspace_id=str(workspace_rw.id),
            volume_id=str(volume.id),
            role="read_write",
        )
        await ws_service.add_volume(
            workspace_id=str(workspace_ro.id),
            volume_id=str(volume.id),
            role="read_only",
        )

        # Add admin to both workspaces
        await ws_service.add_member(
            workspace_id=str(workspace_rw.id),
            user_id=str(admin_user.id),
            role="read_write",
        )
        await ws_service.add_member(
            workspace_id=str(workspace_ro.id),
            user_id=str(admin_user.id),
            role="read_write",
        )

        # Most restrictive (RO) wins
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_only"
        ) is True
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_write"
        ) is False

    @pytest.mark.asyncio
    async def test_member_workspace_ro_blocked_rw(self, db_session, test_user, admin_user):
        """Member with workspace RO volume role should be blocked from RW."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService
        from app.services.workspace_service import WorkspaceService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)
        ws_service = WorkspaceService(db_session)

        workspace = await ws_service.create_workspace(
            name="RO Volume Workspace",
            description="Test",
            owner_id=str(test_user.id)
        )

        volume = await vol_service.create_volume(
            name="test-ws-vol-ro",
            display_name="Workspace RO Volume",
            owner_id=str(test_user.id),
        )

        # Add volume as read_only
        await ws_service.add_volume(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_only",
        )

        # Add admin as read_write member
        await ws_service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(admin_user.id),
            role="read_write",
        )

        # Member can read
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_only"
        ) is True
        # But cannot write because volume role is RO
        assert await access_service.can_access_volume(
            str(volume.id), str(admin_user.id), "read_write"
        ) is False

    @pytest.mark.asyncio
    async def test_get_accessible_volume_ids(self, db_session, test_user, admin_user):
        """Should return list of accessible volume IDs."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)

        # Create volumes
        vol1 = await vol_service.create_volume(
            name="test-accessible-1",
            display_name="Accessible 1",
            owner_id=str(test_user.id),
        )
        vol2 = await vol_service.create_volume(
            name="test-accessible-2",
            display_name="Accessible 2",
            owner_id=str(test_user.id),
            visibility="public",
        )

        # Test user should see both owned volumes (mode=read_write doesn't include public)
        ids = await access_service.get_accessible_volume_ids(str(test_user.id), mode="read_write")
        assert str(vol1.id) in ids
        assert str(vol2.id) in ids  # Also owned by test_user

        # Admin should see public one in read_only mode
        ids = await access_service.get_accessible_volume_ids(str(admin_user.id), mode="read_only")
        assert str(vol1.id) not in ids
        assert str(vol2.id) in ids

    @pytest.mark.asyncio
    async def test_workspace_permission_matrix(self, db_session, test_user, admin_user):
        """Member role and volume role should interact correctly."""
        from app.services.volume_access_service import VolumeAccessService
        from app.services.volume_service import VolumeService
        from app.services.workspace_service import WorkspaceService

        vol_service = VolumeService(db_session)
        access_service = VolumeAccessService(db_session)
        ws_service = WorkspaceService(db_session)

        workspace = await ws_service.create_workspace(
            name="Permission Matrix",
            description="Test",
            owner_id=str(test_user.id)
        )

        vol_rw = await vol_service.create_volume(
            name="test-rw", display_name="RW Vol", owner_id=str(test_user.id),
        )
        vol_ro = await vol_service.create_volume(
            name="test-ro", display_name="RO Vol", owner_id=str(test_user.id),
        )

        await ws_service.add_volume(workspace_id=str(workspace.id), volume_id=str(vol_rw.id), role="read_write")
        await ws_service.add_volume(workspace_id=str(workspace.id), volume_id=str(vol_ro.id), role="read_only")

        # Admin member should write only to read_write volume (no admin override)
        await ws_service.add_member(workspace_id=str(workspace.id), user_id=str(admin_user.id), role="admin")
        assert await access_service.can_access_volume(str(vol_rw.id), str(admin_user.id), "read_write") is True
        assert await access_service.can_access_volume(str(vol_ro.id), str(admin_user.id), "read_write") is False

        # Editor member: same behavior as admin for volume access
        # (Documented by test_workspace_read_only_member above)

        # Viewer member should not write to either
        # (Documented by test_workspace_read_only_member above)
