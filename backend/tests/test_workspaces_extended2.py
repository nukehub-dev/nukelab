"""Extended tests for workspaces.py — covering untested endpoints and error branches."""

import pytest
import pytest_asyncio
import uuid as uuid_mod
from unittest import mock

from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_volume import WorkspaceVolume
from app.models.volume import Volume


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_workspace(db_session, test_user):
    """Create a workspace owned by test_user."""
    ws = SharedWorkspace(
        name="test-ws",
        description="Test workspace",
        owner_id=test_user.id,
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)
    return ws


@pytest_asyncio.fixture
async def test_workspace_with_member(db_session, test_user, admin_user):
    """Create a workspace with test_user as owner and admin_user as member."""
    ws = SharedWorkspace(
        name="test-ws-member",
        description="Test workspace",
        owner_id=test_user.id,
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)

    member = WorkspaceMember(
        workspace_id=ws.id,
        user_id=admin_user.id,
        role="read_write",
    )
    db_session.add(member)
    await db_session.commit()
    return ws


@pytest_asyncio.fixture
async def test_workspace_volume(db_session, test_workspace, test_user):
    """Create a volume and add it to the workspace."""
    vol = Volume(
        name=f"ws-vol-{uuid_mod.uuid4().hex[:8]}",
        display_name="WS Volume",
        owner_id=test_user.id,
        size_bytes=1024,
        max_size_bytes=10737418240,
        status="active",
    )
    db_session.add(vol)
    await db_session.commit()
    await db_session.refresh(vol)

    wsv = WorkspaceVolume(
        workspace_id=test_workspace.id,
        volume_id=vol.id,
        role="read_write",
        added_by=test_user.id,
    )
    db_session.add(wsv)
    await db_session.commit()
    return vol, wsv


# ─────────────────────────────────────────────────────────────
# PUT /{id} — update_workspace
# ─────────────────────────────────────────────────────────────

class TestUpdateWorkspace:
    """Tests for update_workspace endpoint."""

    @pytest.mark.asyncio
    async def test_update_workspace_success(self, client, user_token, test_workspace):
        """Owner should be able to update workspace."""
        with mock.patch("app.api.workspaces.ActivityService") as mock_act_cls:
            mock_act = mock_act_cls.return_value
            mock_act.log = mock.AsyncMock()

            response = await client.put(
                f"/api/workspaces/{test_workspace.id}",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"name": "Updated Name", "description": "Updated desc"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["description"] == "Updated desc"
        mock_act.log.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_workspace_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.put(
            f"/api/workspaces/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "Updated Name"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_workspace_forbidden(self, client, admin_token, test_workspace):
        """Non-owner/non-admin should not be able to update."""
        response = await client.put(
            f"/api/workspaces/{test_workspace.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Hacked"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_workspace_admin_can_update(
        self, client, admin_token, test_workspace_with_member, db_session
    ):
        """Admin member should be able to update workspace."""
        # Make admin_user an admin member
        ws = test_workspace_with_member
        from sqlalchemy import select
        result = await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id != ws.owner_id
            )
        )
        member = result.scalar_one()
        member.role = "admin"
        await db_session.commit()

        response = await client.put(
            f"/api/workspaces/{ws.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Admin Updated"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Admin Updated"


# ─────────────────────────────────────────────────────────────
# DELETE /{id} — delete_workspace
# ─────────────────────────────────────────────────────────────

class TestDeleteWorkspace:
    """Tests for delete_workspace endpoint."""

    @pytest.mark.asyncio
    async def test_delete_workspace_success(self, client, user_token, test_workspace):
        """Owner should be able to delete workspace."""
        response = await client.delete(
            f"/api/workspaces/{test_workspace.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_workspace_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.delete(
            f"/api/workspaces/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_workspace_forbidden(self, client, admin_token, test_workspace):
        """Non-owner should not be able to delete."""
        response = await client.delete(
            f"/api/workspaces/{test_workspace.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 403
        assert "only the workspace owner" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_workspace_service_failure(self, client, user_token, test_workspace):
        """Service returning False should return 500."""
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_workspace = mock.AsyncMock(return_value=test_workspace)
            mock_svc.delete_workspace = mock.AsyncMock(return_value=False)

            response = await client.delete(
                f"/api/workspaces/{test_workspace.id}",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 500
        assert "failed" in response.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────
# PUT /{id}/volumes/{vid} — update_volume_role
# ─────────────────────────────────────────────────────────────

class TestUpdateVolumeRole:
    """Tests for update_volume_role endpoint."""

    @pytest.mark.asyncio
    async def test_update_volume_role_success(
        self, client, user_token, test_workspace, test_workspace_volume
    ):
        """Owner should be able to update volume role."""
        vol, _ = test_workspace_volume
        response = await client.put(
            f"/api/workspaces/{test_workspace.id}/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"role": "read_only"},
        )
        assert response.status_code == 200
        assert response.json()["role"] == "read_only"

    @pytest.mark.asyncio
    async def test_update_volume_role_not_found(self, client, user_token, test_workspace):
        """Non-existent volume should return 404."""
        response = await client.put(
            f"/api/workspaces/{test_workspace.id}/volumes/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"role": "read_only"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_volume_role_invalid_role(self, client, user_token, test_workspace, test_workspace_volume):
        """Invalid role should return 400."""
        vol, _ = test_workspace_volume
        response = await client.put(
            f"/api/workspaces/{test_workspace.id}/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"role": "admin"},
        )
        assert response.status_code == 400
        assert "invalid role" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_volume_role_forbidden(self, client, admin_token, test_workspace, test_workspace_volume):
        """Non-owner/non-admin should not be able to update volume role."""
        vol, _ = test_workspace_volume
        response = await client.put(
            f"/api/workspaces/{test_workspace.id}/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "read_only"},
        )
        assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Error branches for tested endpoints
# ─────────────────────────────────────────────────────────────

class TestWorkspaceErrorBranches:
    """Tests for missing error branches in already-tested endpoints."""

    @pytest.mark.asyncio
    async def test_get_workspace_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.get(
            f"/api/workspaces/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_workspace_no_access(self, client, admin_token, test_workspace):
        """User with no access should get 403."""
        response = await client.get(
            f"/api/workspaces/{test_workspace.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 403
        assert "don't have access" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_workspace_with_pending_invitation(
        self, client, admin_token, test_workspace, db_session, admin_user
    ):
        """Should include my_invitation when user has pending invitation."""
        inv = WorkspaceInvitation(
            workspace_id=test_workspace.id,
            user_id=admin_user.id,
            invited_by=test_workspace.owner_id,
            role="read_write",
            status="pending",
        )
        db_session.add(inv)
        await db_session.commit()

        response = await client.get(
            f"/api/workspaces/{test_workspace.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["my_invitation"] is not None
        assert data["invitation_count"] == 1

    @pytest.mark.asyncio
    async def test_leave_workspace_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.post(
            f"/api/workspaces/{uuid_mod.uuid4()}/leave",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_leave_workspace_not_member(self, client, admin_token, test_workspace):
        """Non-member should get 403."""
        response = await client.post(
            f"/api/workspaces/{test_workspace.id}/leave",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 403
        assert "not a member" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_leave_workspace_value_error(self, client, user_token, test_workspace):
        """ValueError from service should return 400."""
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_workspace = mock.AsyncMock(return_value=test_workspace)
            mock_svc.is_workspace_member = mock.AsyncMock(return_value=True)
            mock_svc.leave_workspace = mock.AsyncMock(side_effect=ValueError("owner cannot leave"))

            response = await client.post(
                f"/api/workspaces/{test_workspace.id}/leave",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 400
        assert "owner cannot leave" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_transfer_ownership_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.post(
            f"/api/workspaces/{uuid_mod.uuid4()}/transfer",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"user_id": str(uuid_mod.uuid4())},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_transfer_ownership_permission_denied(self, client, admin_token, test_workspace):
        """Non-owner should get 403."""
        response = await client.post(
            f"/api/workspaces/{test_workspace.id}/transfer",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"user_id": str(uuid_mod.uuid4())},
        )
        assert response.status_code == 403
        assert "permission" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_transfer_ownership_value_error(self, client, user_token, test_workspace):
        """ValueError from service should return 400."""
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_workspace = mock.AsyncMock(return_value=test_workspace)
            mock_svc.transfer_ownership = mock.AsyncMock(
                side_effect=ValueError("new owner is not a member")
            )

            response = await client.post(
                f"/api/workspaces/{test_workspace.id}/transfer",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"user_id": str(uuid_mod.uuid4())},
            )

        assert response.status_code == 400
        assert "new owner is not a member" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_activity_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.get(
            f"/api/workspaces/{uuid_mod.uuid4()}/activity",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_activity_no_access(self, client, admin_token, test_workspace):
        """User with no access should get 403."""
        response = await client.get(
            f"/api/workspaces/{test_workspace.id}/activity",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 403
        assert "don't have access" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_add_volume_workspace_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.post(
            f"/api/workspaces/{uuid_mod.uuid4()}/volumes",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"volume_id": str(uuid_mod.uuid4()), "role": "read_write"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_add_volume_forbidden(self, client, admin_token, test_workspace):
        """Non-owner/non-admin should get 403."""
        response = await client.post(
            f"/api/workspaces/{test_workspace.id}/volumes",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"volume_id": str(uuid_mod.uuid4()), "role": "read_write"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_add_volume_cant_manage_volume(self, client, user_token, test_workspace):
        """VolumeAccessService.can_manage_volume=False should return 403."""
        with mock.patch("app.api.workspaces.VolumeAccessService") as mock_vas_cls:
            mock_vas = mock_vas_cls.return_value
            mock_vas.can_manage_volume = mock.AsyncMock(return_value=False)

            response = await client.post(
                f"/api/workspaces/{test_workspace.id}/volumes",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"volume_id": str(uuid_mod.uuid4()), "role": "read_write"},
            )

        assert response.status_code == 403
        assert "don't have permission to share" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_remove_volume_not_found(self, client, user_token, test_workspace):
        """Non-existent workspace should return 404."""
        response = await client.delete(
            f"/api/workspaces/{test_workspace.id}/volumes/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_invite_member_workspace_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.post(
            f"/api/workspaces/{uuid_mod.uuid4()}/invitations",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"user_id": str(uuid_mod.uuid4()), "role": "read_write"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_invite_member_forbidden(self, client, admin_token, test_workspace):
        """Non-owner/non-admin should get 403."""
        response = await client.post(
            f"/api/workspaces/{test_workspace.id}/invitations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"user_id": str(uuid_mod.uuid4()), "role": "read_write"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_invite_member_value_error(self, client, user_token, test_workspace):
        """ValueError from service should return 400."""
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_workspace = mock.AsyncMock(return_value=test_workspace)
            mock_svc.can_manage_workspace = mock.AsyncMock(return_value=True)
            mock_svc.invite_member = mock.AsyncMock(side_effect=ValueError("already a member"))

            response = await client.post(
                f"/api/workspaces/{test_workspace.id}/invitations",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"user_id": str(uuid_mod.uuid4()), "role": "read_write"},
            )

        assert response.status_code == 400
        assert "already a member" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_accept_invitation_not_found_workspace(self, client, user_token):
        """Non-existent workspace should still work if invitation exists."""
        # This tests the "Unknown" workspace_name path
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_workspace = mock.AsyncMock(return_value=None)
            mock_svc.accept_invitation = mock.AsyncMock(return_value=mock.Mock(to_dict=mock.Mock(return_value={"id": "1"})))

            with mock.patch("app.api.workspaces.NotificationService") as mock_notif_cls:
                mock_notif = mock_notif_cls.return_value
                mock_notif.workspace_member_added = mock.AsyncMock()

                response = await client.post(
                    f"/api/workspaces/{uuid_mod.uuid4()}/invitations/{uuid_mod.uuid4()}/accept",
                    headers={"Authorization": f"Bearer {user_token}"},
                )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_reject_invitation_value_error(self, client, user_token):
        """ValueError from service should return 400."""
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.reject_invitation = mock.AsyncMock(side_effect=ValueError("invalid invitation"))

            response = await client.post(
                f"/api/workspaces/{uuid_mod.uuid4()}/invitations/{uuid_mod.uuid4()}/reject",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 400
        assert "invalid invitation" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_cancel_invitation_permission_error(self, client, admin_token, test_workspace):
        """PermissionError from service should return 403."""
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.cancel_invitation = mock.AsyncMock(side_effect=PermissionError("not allowed"))

            response = await client.delete(
                f"/api/workspaces/{test_workspace.id}/invitations/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 403
        assert "permission" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_list_invitations_forbidden(self, client, admin_token, test_workspace):
        """Non-owner/non-admin should get 403 before workspace lookup."""
        response = await client.get(
            f"/api/workspaces/{test_workspace.id}/invitations",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_members_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.get(
            f"/api/workspaces/{uuid_mod.uuid4()}/members",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_list_members_no_access(self, client, admin_token, test_workspace):
        """User with no access should get 403."""
        response = await client.get(
            f"/api/workspaces/{test_workspace.id}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 403
        assert "don't have access" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_list_volumes_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.get(
            f"/api/workspaces/{uuid_mod.uuid4()}/volumes",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_list_volumes_no_access(self, client, admin_token, test_workspace):
        """User with no access should get 403."""
        response = await client.get(
            f"/api/workspaces/{test_workspace.id}/volumes",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 403
        assert "don't have access" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_remove_member_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.delete(
            f"/api/workspaces/{uuid_mod.uuid4()}/members/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_remove_member_value_error(self, client, user_token, test_workspace_with_member):
        """ValueError from service should return 400."""
        ws = test_workspace_with_member
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_workspace = mock.AsyncMock(return_value=ws)
            mock_svc.remove_member = mock.AsyncMock(side_effect=ValueError("cannot remove owner"))

            response = await client.delete(
                f"/api/workspaces/{ws.id}/members/{ws.owner_id}",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 400
        assert "cannot remove owner" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_remove_member_not_found_member(self, client, user_token, test_workspace):
        """Non-existent member should return 404."""
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_workspace = mock.AsyncMock(return_value=test_workspace)
            mock_svc.remove_member = mock.AsyncMock(return_value=False)
            mock_svc.can_manage_workspace = mock.AsyncMock(return_value=True)

            response = await client.delete(
                f"/api/workspaces/{test_workspace.id}/members/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 404
        assert "member not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_member_role_not_found(self, client, user_token):
        """Non-existent workspace should return 404."""
        response = await client.put(
            f"/api/workspaces/{uuid_mod.uuid4()}/members/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"role": "admin"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_member_role_value_error(self, client, user_token, test_workspace_with_member):
        """ValueError from service should return 400."""
        ws = test_workspace_with_member
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_workspace = mock.AsyncMock(return_value=ws)
            mock_svc.can_manage_workspace = mock.AsyncMock(return_value=True)
            mock_svc.update_member_role = mock.AsyncMock(side_effect=ValueError("cannot change owner"))

            response = await client.put(
                f"/api/workspaces/{ws.id}/members/{ws.owner_id}",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"role": "admin"},
            )

        assert response.status_code == 400
        assert "cannot change owner" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_member_role_not_found_member(self, client, user_token, test_workspace):
        """Non-existent member should return 404."""
        with mock.patch("app.api.workspaces.WorkspaceService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_workspace = mock.AsyncMock(return_value=test_workspace)
            mock_svc.can_manage_workspace = mock.AsyncMock(return_value=True)
            mock_svc.update_member_role = mock.AsyncMock(return_value=None)

            response = await client.put(
                f"/api/workspaces/{test_workspace.id}/members/{uuid_mod.uuid4()}",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"role": "admin"},
            )

        assert response.status_code == 404
        assert "member not found" in response.json()["detail"].lower()
