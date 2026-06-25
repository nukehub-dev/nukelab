"""Tests for WorkspaceService business logic."""

import pytest
import uuid as uuid_mod
from datetime import datetime, timedelta

from sqlalchemy import select, and_

from app.services.workspace_service import WorkspaceService
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_volume import WorkspaceVolume
from app.models.volume import Volume
from app.models.user import User


class TestWorkspaceServiceCreate:
    """Tests for create_workspace."""

    @pytest.mark.asyncio
    async def test_create_workspace(self, db_session, test_user):
        """Should create workspace and add owner as admin."""
        service = WorkspaceService(db_session)
        ws = await service.create_workspace(
            name="Test Workspace", description="A test workspace", owner_id=str(test_user.id)
        )
        assert ws.name == "Test Workspace"
        assert ws.owner_id == test_user.id

    @pytest.mark.asyncio
    async def test_create_workspace_adds_owner_member(self, db_session, test_user):
        """Owner should be added as admin member."""
        service = WorkspaceService(db_session)
        ws = await service.create_workspace(
            name="Test Workspace", description="A test workspace", owner_id=str(test_user.id)
        )

        members = await db_session.execute(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id)
        )
        member = members.scalar_one_or_none()
        assert member is not None
        assert member.user_id == test_user.id
        assert member.role == "admin"


class TestWorkspaceServiceGet:
    """Tests for get_workspace."""

    @pytest.mark.asyncio
    async def test_get_workspace_found(self, db_session, test_user):
        """Should return workspace when found."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()

        service = WorkspaceService(db_session)
        result = await service.get_workspace(str(ws.id))
        assert result is not None
        assert result.name == "Test"

    @pytest.mark.asyncio
    async def test_get_workspace_not_found(self, db_session):
        """Should return None when not found."""
        service = WorkspaceService(db_session)
        result = await service.get_workspace(str(uuid_mod.uuid4()))
        assert result is None


class TestWorkspaceServiceUpdate:
    """Tests for update_workspace."""

    @pytest.mark.asyncio
    async def test_update_workspace(self, db_session, test_user):
        """Should update workspace fields."""
        ws = SharedWorkspace(name="Old", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()

        service = WorkspaceService(db_session)
        updated = await service.update_workspace(
            str(ws.id), name="New", description="Updated description"
        )
        assert updated.name == "New"
        assert updated.description == "Updated description"

    @pytest.mark.asyncio
    async def test_update_workspace_not_found(self, db_session):
        """Should return None when workspace not found."""
        service = WorkspaceService(db_session)
        result = await service.update_workspace(str(uuid_mod.uuid4()), name="X")
        assert result is None


class TestWorkspaceServiceDelete:
    """Tests for delete_workspace."""

    @pytest.mark.asyncio
    async def test_delete_workspace(self, db_session, test_user):
        """Should delete workspace and members."""
        ws = SharedWorkspace(name="To Delete", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="admin")
        db_session.add(member)
        await db_session.commit()

        service = WorkspaceService(db_session)
        await service.delete_workspace(str(ws.id))

        result = await db_session.execute(
            select(SharedWorkspace).where(SharedWorkspace.id == ws.id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_workspace_not_found(self, db_session):
        """Should not raise when workspace not found."""
        service = WorkspaceService(db_session)
        await service.delete_workspace(str(uuid_mod.uuid4()))  # Should not raise


class TestWorkspaceServiceMembers:
    """Tests for member management."""

    @pytest.mark.asyncio
    async def test_add_member(self, db_session, test_user, admin_user):
        """Should add member to workspace."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()

        service = WorkspaceService(db_session)
        member = await service.add_member(str(ws.id), str(admin_user.id), role="editor")
        assert member.user_id == admin_user.id
        assert member.role == "editor"

    @pytest.mark.asyncio
    async def test_add_member_already_exists(self, db_session, test_user):
        """Should not duplicate member."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="admin")
        db_session.add(member)
        await db_session.commit()

        service = WorkspaceService(db_session)
        result = await service.add_member(str(ws.id), str(test_user.id), role="editor")
        # Should return existing or update role depending on implementation
        assert result is not None

    @pytest.mark.asyncio
    async def test_remove_member(self, db_session, test_user, admin_user):
        """Should remove member from workspace."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="editor")
        db_session.add(member)
        await db_session.commit()

        service = WorkspaceService(db_session)
        await service.remove_member(str(ws.id), str(admin_user.id))

        result = await db_session.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == admin_user.id
                )
            )
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_update_member_role(self, db_session, test_user, admin_user):
        """Should update member role."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="viewer")
        db_session.add(member)
        await db_session.commit()

        service = WorkspaceService(db_session)
        updated = await service.update_member_role(str(ws.id), str(admin_user.id), "admin")
        assert updated.role == "admin"

    @pytest.mark.asyncio
    async def test_list_workspace_members(self, db_session, test_user, admin_user):
        """Should list workspace members."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="editor")
        db_session.add(member)
        await db_session.commit()

        service = WorkspaceService(db_session)
        result = await service.list_workspace_members(str(ws.id))
        assert result["total"] >= 1
        assert len(result["members"]) >= 1

    @pytest.mark.asyncio
    async def test_list_workspace_members_filter_role(self, db_session, test_user, admin_user):
        """Should filter members by role."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="editor")
        db_session.add(member)
        await db_session.commit()

        service = WorkspaceService(db_session)
        result = await service.list_workspace_members(str(ws.id), role="editor")
        assert all(m["role"] == "editor" for m in result["members"])

    @pytest.mark.asyncio
    async def test_list_workspace_members_search(self, db_session, test_user, admin_user):
        """Should search members by username."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="editor")
        db_session.add(member)
        await db_session.commit()

        service = WorkspaceService(db_session)
        result = await service.list_workspace_members(str(ws.id), search=admin_user.username)
        # Search should return filtered results
        assert isinstance(result["members"], list)


class TestWorkspaceServiceInvitations:
    """Tests for invitation management."""

    @pytest.mark.asyncio
    async def test_invite_member(self, db_session, test_user, admin_user):
        """Should create workspace invitation."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()

        service = WorkspaceService(db_session)
        inv = await service.invite_member(
            str(ws.id), str(admin_user.id), str(test_user.id), role="editor"
        )
        assert str(inv.workspace_id) == str(ws.id)
        assert str(inv.user_id) == str(admin_user.id)
        assert inv.role == "editor"

    @pytest.mark.asyncio
    async def test_accept_invitation(self, db_session, test_user, admin_user):
        """Should accept invitation and add member."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        inv = WorkspaceInvitation(
            workspace_id=ws.id,
            user_id=admin_user.id,
            invited_by=test_user.id,
            role="editor",
            status="pending",
        )
        db_session.add(inv)
        await db_session.commit()

        service = WorkspaceService(db_session)
        result = await service.accept_invitation(str(inv.id), str(admin_user.id))
        assert result is not None

        member = await db_session.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == admin_user.id
                )
            )
        )
        assert member.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_reject_invitation(self, db_session, test_user, admin_user):
        """Should reject invitation."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        inv = WorkspaceInvitation(
            workspace_id=ws.id,
            user_id=admin_user.id,
            invited_by=test_user.id,
            role="editor",
            status="pending",
        )
        db_session.add(inv)
        await db_session.commit()

        service = WorkspaceService(db_session)
        await service.reject_invitation(str(inv.id), str(admin_user.id))

        refreshed = await db_session.execute(
            select(WorkspaceInvitation).where(WorkspaceInvitation.id == inv.id)
        )
        inv_refreshed = refreshed.scalar_one()
        assert inv_refreshed.status == "rejected"

    @pytest.mark.asyncio
    async def test_cancel_invitation(self, db_session, test_user, admin_user):
        """Should cancel invitation."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        inv = WorkspaceInvitation(
            workspace_id=ws.id,
            user_id=admin_user.id,
            invited_by=test_user.id,
            role="editor",
            status="pending",
        )
        db_session.add(inv)
        await db_session.commit()

        service = WorkspaceService(db_session)
        result = await service.cancel_invitation(str(inv.id), str(test_user.id))
        assert result is True

        refreshed = await db_session.execute(
            select(WorkspaceInvitation).where(WorkspaceInvitation.id == inv.id)
        )
        assert refreshed.scalar_one_or_none() is None


class TestWorkspaceServiceVolumes:
    """Tests for workspace volume management."""

    @pytest.mark.asyncio
    async def test_add_volume(self, db_session, test_user):
        """Should add volume to workspace."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        vol = Volume(
            name="test-vol", display_name="Test Vol", owner_id=test_user.id, max_size_bytes=1024**3
        )
        db_session.add(vol)
        await db_session.commit()

        service = WorkspaceService(db_session)
        ws_vol = await service.add_volume(
            str(ws.id), str(vol.id), role="rw", added_by=str(test_user.id)
        )
        assert ws_vol.workspace_id == ws.id
        assert ws_vol.volume_id == vol.id
        assert ws_vol.role == "rw"

    @pytest.mark.asyncio
    async def test_remove_volume(self, db_session, test_user):
        """Should remove volume from workspace."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        vol = Volume(
            name="test-vol", display_name="Test Vol", owner_id=test_user.id, max_size_bytes=1024**3
        )
        db_session.add(vol)
        await db_session.flush()

        ws_vol = WorkspaceVolume(
            workspace_id=ws.id, volume_id=vol.id, added_by=test_user.id, role="rw"
        )
        db_session.add(ws_vol)
        await db_session.commit()

        service = WorkspaceService(db_session)
        await service.remove_volume(str(ws.id), str(vol.id))

        result = await db_session.execute(
            select(WorkspaceVolume).where(
                and_(WorkspaceVolume.workspace_id == ws.id, WorkspaceVolume.volume_id == vol.id)
            )
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_list_workspace_volumes(self, db_session, test_user):
        """Should list workspace volumes."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        vol = Volume(
            name="test-vol", display_name="Test Vol", owner_id=test_user.id, max_size_bytes=1024**3
        )
        db_session.add(vol)
        await db_session.flush()

        ws_vol = WorkspaceVolume(
            workspace_id=ws.id, volume_id=vol.id, added_by=test_user.id, role="rw"
        )
        db_session.add(ws_vol)
        await db_session.commit()

        service = WorkspaceService(db_session)
        result = await service.list_workspace_volumes(str(ws.id))
        assert result["total"] >= 1
        assert len(result["volumes"]) >= 1


class TestWorkspaceServiceTransferOwnership:
    """Tests for ownership transfer."""

    @pytest.mark.asyncio
    async def test_transfer_ownership(self, db_session, test_user, admin_user):
        """Should transfer workspace ownership."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="admin")
        db_session.add(member)
        await db_session.commit()

        service = WorkspaceService(db_session)
        updated = await service.transfer_ownership(
            str(ws.id), str(test_user.id), str(admin_user.id)
        )
        assert updated.owner_id == admin_user.id

    @pytest.mark.asyncio
    async def test_transfer_ownership_not_member(self, db_session, test_user, admin_user):
        """Should fail when new owner is not a member."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()

        service = WorkspaceService(db_session)
        with pytest.raises(Exception):
            await service.transfer_ownership(str(ws.id), str(test_user.id), str(admin_user.id))


class TestWorkspaceServiceLeave:
    """Tests for leaving workspace."""

    @pytest.mark.asyncio
    async def test_leave_workspace(self, db_session, test_user, admin_user):
        """Should allow member to leave workspace."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        member = WorkspaceMember(workspace_id=ws.id, user_id=admin_user.id, role="editor")
        db_session.add(member)
        await db_session.commit()

        service = WorkspaceService(db_session)
        result = await service.leave_workspace(str(ws.id), str(admin_user.id))
        assert result is True

        result = await db_session.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == admin_user.id
                )
            )
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_owner_cannot_leave(self, db_session, test_user):
        """Owner should not be able to leave without transferring."""
        ws = SharedWorkspace(name="Test", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()

        service = WorkspaceService(db_session)
        with pytest.raises(Exception):
            await service.leave_workspace(str(ws.id), str(test_user.id))
