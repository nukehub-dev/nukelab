"""
Shared Workspace API endpoints.
"""

from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.dependencies import PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.services.workspace_service import WorkspaceService
from app.services.volume_access_service import VolumeAccessService
from app.services.notification_service import NotificationService

router = APIRouter()


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: Optional[str] = None


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AddMemberRequest(BaseModel):
    user_id: str
    role: str = "read_write"  # read_only, read_write, admin


class UpdateMemberRequest(BaseModel):
    role: str


class InviteMemberRequest(BaseModel):
    user_id: str
    role: str = "read_write"  # read_only, read_write, admin


class AddVolumeRequest(BaseModel):
    volume_id: str
    role: str = "read_write"  # read_only, read_write


class UpdateVolumeRoleRequest(BaseModel):
    role: str


@router.get("/")
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List workspaces user has access to (owned, member, or invited)."""
    service = WorkspaceService(db)
    workspaces = await service.list_workspaces(str(current_user.id))
    
    result = []
    for w in workspaces:
        data = w.to_dict()
        # Check if current user has a pending invitation to this workspace
        has_pending = any(
            str(i.user_id) == str(current_user.id) and i.status == "pending"
            for i in (w.invitations or [])
        )
        data["has_pending_invitation"] = has_pending
        result.append(data)
    
    return {
        "workspaces": result
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    request: CreateWorkspaceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new shared workspace."""
    service = WorkspaceService(db)
    
    workspace = await service.create_workspace(
        name=request.name,
        description=request.description,
        owner_id=str(current_user.id)
    )
    
    return workspace.to_dict()


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get workspace details. Must be owner, member, or invited user."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    # Check access: owner, member, or has pending invitation
    if not await service.can_view_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(status_code=403, detail="You don't have access to this workspace")
    
    data = workspace.to_dict()
    data["members"] = [m.to_dict() for m in workspace.members]
    data["volumes"] = [v.to_dict() for v in workspace.volume_associations]
    data["invitations"] = [i.to_dict() for i in workspace.invitations if i.status == "pending"]
    # Include current user's pending invitation status
    user_invitation = next(
        (i for i in workspace.invitations if str(i.user_id) == str(current_user.id) and i.status == "pending"),
        None
    )
    if user_invitation:
        data["my_invitation"] = user_invitation.to_dict()
    else:
        data["my_invitation"] = None
    return data


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    request: UpdateWorkspaceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update workspace. Must be owner or admin member."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    # Check permission
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    updated = await service.update_workspace(
        workspace_id=workspace_id,
        name=request.name,
        description=request.description,
        is_active=request.is_active
    )
    
    return updated.to_dict()


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete workspace. Must be owner."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    # Only owner or admin can delete
    if str(workspace.owner_id) != str(current_user.id):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    success = await service.delete_workspace(workspace_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete workspace")
    
    return {"message": "Workspace deleted", "workspace_id": workspace_id}


# ========== Volume Management ==========

@router.post("/{workspace_id}/volumes")
async def add_volume_to_workspace(
    workspace_id: str,
    request: AddVolumeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a volume to workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    volume_access = VolumeAccessService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    # Verify user can manage the volume
    if not await volume_access.can_manage_volume(request.volume_id, str(current_user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to share this volume"
        )
    
    if request.role not in ("read_only", "read_write"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be: read_only, read_write")
    
    workspace_volume = await service.add_volume(
        workspace_id=workspace_id,
        volume_id=request.volume_id,
        role=request.role,
        added_by=str(current_user.id)
    )
    
    return workspace_volume.to_dict()


@router.delete("/{workspace_id}/volumes/{volume_id}")
async def remove_volume_from_workspace(
    workspace_id: str,
    volume_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove a volume from workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    success = await service.remove_volume(workspace_id, volume_id)
    if not success:
        raise HTTPException(status_code=404, detail="Volume not found in workspace")
    
    return {"message": "Volume removed from workspace", "volume_id": volume_id}


@router.put("/{workspace_id}/volumes/{volume_id}")
async def update_volume_role(
    workspace_id: str,
    volume_id: str,
    request: UpdateVolumeRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update volume role in workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    if request.role not in ("read_only", "read_write"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be: read_only, read_write")
    
    updated = await service.update_volume_role(workspace_id, volume_id, request.role)
    if not updated:
        raise HTTPException(status_code=404, detail="Volume not found in workspace")
    
    return updated.to_dict()


# ========== Member Management ==========

@router.post("/{workspace_id}/invitations")
async def invite_member(
    workspace_id: str,
    request: InviteMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Invite a user to workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    # Validate role
    if request.role not in ("read_only", "read_write", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be: read_only, read_write, admin")
    
    try:
        invitation = await service.invite_member(
            workspace_id=workspace_id,
            user_id=request.user_id,
            invited_by=str(current_user.id),
            role=request.role
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Send notification to invited user
    notif_service = NotificationService(db)
    await notif_service.workspace_invitation(
        user_id=request.user_id,
        workspace_name=workspace.name,
        inviter_name=current_user.display_name or current_user.username,
        action_url=f"/workspaces/{workspace_id}"
    )
    
    return invitation.to_dict()


@router.post("/{workspace_id}/invitations/{invitation_id}/accept")
async def accept_invitation(
    workspace_id: str,
    invitation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Accept a workspace invitation."""
    service = WorkspaceService(db)
    
    try:
        member = await service.accept_invitation(invitation_id, str(current_user.id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return member.to_dict()


@router.post("/{workspace_id}/invitations/{invitation_id}/reject")
async def reject_invitation(
    workspace_id: str,
    invitation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Reject a workspace invitation."""
    service = WorkspaceService(db)
    
    try:
        await service.reject_invitation(invitation_id, str(current_user.id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {"message": "Invitation rejected", "invitation_id": invitation_id}


@router.delete("/{workspace_id}/invitations/{invitation_id}")
async def cancel_invitation(
    workspace_id: str,
    invitation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a workspace invitation. Must be owner, admin, or the inviter."""
    service = WorkspaceService(db)
    
    try:
        success = await service.cancel_invitation(invitation_id, str(current_user.id))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
    if not success:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    return {"message": "Invitation cancelled", "invitation_id": invitation_id}


@router.get("/{workspace_id}/invitations")
async def list_invitations(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List pending invitations for a workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    pending = [i.to_dict() for i in workspace.invitations if i.status == "pending"]
    return {"invitations": pending}


@router.delete("/{workspace_id}/members/{user_id}")
async def remove_member(
    workspace_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove a member from workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    # Can remove self, or must be owner/admin
    if str(current_user.id) != user_id:
        if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
            checker = PermissionChecker(current_user)
            checker.require(Permission.ADMIN_ACCESS)
    
    success = await service.remove_member(workspace_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")
    
    return {"message": "Member removed", "user_id": user_id}


@router.put("/{workspace_id}/members/{user_id}")
async def update_member_role(
    workspace_id: str,
    user_id: str,
    request: UpdateMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update member role. Must be owner or admin."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    if request.role not in ("read_only", "read_write", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be: read_only, read_write, admin")
    
    member = await service.update_member_role(workspace_id, user_id, request.role)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    
    return member.to_dict()
