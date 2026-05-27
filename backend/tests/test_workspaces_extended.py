"""Extended tests for Workspaces API error paths."""

import pytest
import uuid

from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.workspace_invitation import WorkspaceInvitation


class TestWorkspaceAPIErrors:
    """Tests for workspace endpoint error paths."""

    @pytest.mark.asyncio
    async def test_get_workspace_not_found(self, client, user_token):
        """Getting non-existent workspace should 404."""
        response = await client.get(
            "/api/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_workspace_not_found(self, client, user_token):
        """Updating non-existent workspace should 404."""
        response = await client.put(
            "/api/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "new name"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_workspace_not_found(self, client, user_token):
        """Deleting non-existent workspace should 404."""
        response = await client.delete(
            "/api/workspaces/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_user_cannot_access_foreign_workspace(self, client, user_token, admin_user, db_session):
        """User should not access workspace they don't belong to."""
        ws = SharedWorkspace(name="private-ws", owner_id=str(admin_user.id))
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        response = await client.get(
            f"/api/workspaces/{ws.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_owner_cannot_delete_workspace(self, client, user_token, test_user, admin_user, db_session):
        """Non-owner member should not be able to delete workspace."""
        ws = SharedWorkspace(name="team-ws", owner_id=str(admin_user.id))
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        # Add test_user as member
        member = WorkspaceMember(workspace_id=ws.id, user_id=str(test_user.id), role="read_write")
        db_session.add(member)
        await db_session.commit()

        response = await client.delete(
            f"/api/workspaces/{ws.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_invite_to_nonexistent_workspace(self, client, user_token):
        """Inviting to non-existent workspace should 404."""
        response = await client.post(
            "/api/workspaces/00000000-0000-0000-0000-000000000000/invitations",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"user_id": str(uuid.uuid4()), "role": "read_only"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_accept_nonexistent_invitation(self, client, user_token):
        """Accepting non-existent invitation should 404."""
        response = await client.post(
            "/api/workspaces/invitations/00000000-0000-0000-0000-000000000000/accept",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_reject_nonexistent_invitation(self, client, user_token):
        """Rejecting non-existent invitation should 404."""
        response = await client.post(
            "/api/workspaces/invitations/00000000-0000-0000-0000-000000000000/reject",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_add_volume_to_nonexistent_workspace(self, client, user_token):
        """Adding volume to non-existent workspace should 404."""
        response = await client.post(
            "/api/workspaces/00000000-0000-0000-0000-000000000000/volumes",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"volume_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_remove_volume_from_nonexistent_workspace(self, client, user_token):
        """Removing volume from non-existent workspace should 404."""
        response = await client.delete(
            "/api/workspaces/00000000-0000-0000-0000-000000000000/volumes/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_remove_member_from_nonexistent_workspace(self, client, user_token):
        """Removing member from non-existent workspace should 404."""
        response = await client.delete(
            "/api/workspaces/00000000-0000-0000-0000-000000000000/members/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_member_role_nonexistent_workspace(self, client, user_token):
        """Updating member role in non-existent workspace should 404."""
        response = await client.put(
            "/api/workspaces/00000000-0000-0000-0000-000000000000/members/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"role": "admin"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_workspace_activity_not_found(self, client, user_token):
        """Getting activity for non-existent workspace should 404."""
        response = await client.get(
            "/api/workspaces/00000000-0000-0000-0000-000000000000/activity",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404
