"""
Shared Workspace API endpoints.
"""

import logging
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.dependencies import require_permissions
from app.db.session import get_db
from app.models.user import User
from app.services.workspace_service import WorkspaceService
from app.services.volume_access_service import VolumeAccessService
from app.services.notification_service import NotificationService
from app.services.activity_service import ActivityService

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


class TransferOwnershipRequest(BaseModel):
    user_id: str


@router.get("/")
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_READ_OWN, Permission.WORKSPACES_READ_ALL)),
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
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
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
    _ = Depends(require_permissions(Permission.WORKSPACES_READ_OWN, Permission.WORKSPACES_READ_ALL)),
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
    # Current user's membership (for role checks without loading all members)
    my_membership = next(
        (m.to_dict() for m in workspace.members if str(m.user_id) == str(current_user.id)),
        None
    )
    data["my_membership"] = my_membership
    # Pending invitation count for stats
    data["invitation_count"] = sum(1 for i in workspace.invitations if i.status == "pending")
    # Current user's pending invitation
    user_invitation = next(
        (i for i in workspace.invitations if str(i.user_id) == str(current_user.id) and i.status == "pending"),
        None
    )
    data["my_invitation"] = user_invitation.to_dict() if user_invitation else None
    return data


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    request: UpdateWorkspaceRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Update workspace. Must be owner or admin member."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    # Check permission
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update this workspace"
        )
    
    updated = await service.update_workspace(
        workspace_id=workspace_id,
        name=request.name,
        description=request.description,
        is_active=request.is_active
    )
    
    # Log activity
    activity = ActivityService(db)
    await activity.log(
        action="workspace_updated",
        target_type="workspace",
        target_id=workspace_id,
        actor_id=str(current_user.id),
        details={
            "changed_fields": [
                f for f in ["name", "description", "is_active"]
                if getattr(request, f) is not None
            ],
            "name": request.name,
            "description": request.description,
            "is_active": request.is_active,
        }
    )
    
    return updated.to_dict()


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Delete workspace. Must be owner."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    # Only owner can delete via regular API
    if str(workspace.owner_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workspace owner can delete this workspace"
        )
    
    success = await service.delete_workspace(workspace_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete workspace")
    
    return {"message": "Workspace deleted", "workspace_id": workspace_id}


@router.post("/{workspace_id}/leave")
async def leave_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Leave a workspace. Owner must transfer ownership first."""
    service = WorkspaceService(db)
    activity = ActivityService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.is_workspace_member(workspace_id, str(current_user.id)):
        raise HTTPException(status_code=403, detail="You are not a member of this workspace")
    
    try:
        success = await service.leave_workspace(workspace_id, str(current_user.id))
    except ValueError as e:
        logger.exception("Failed to leave workspace")
        raise HTTPException(status_code=400, detail=str(e))
    
    if success:
        await activity.log(
            action="member_left",
            target_type="workspace",
            target_id=workspace_id,
            actor_id=str(current_user.id),
            details={
                "user_id": str(current_user.id),
                "username": current_user.username,
                "display_name": current_user.display_name,
            }
        )
    
    return {"message": "Left workspace", "workspace_id": workspace_id}


@router.post("/{workspace_id}/transfer")
async def transfer_ownership(
    workspace_id: str,
    request: TransferOwnershipRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Transfer workspace ownership to another member."""
    service = WorkspaceService(db)
    activity = ActivityService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    try:
        updated = await service.transfer_ownership(
            workspace_id=workspace_id,
            current_owner_id=str(current_user.id),
            new_owner_id=request.user_id
        )
    except ValueError as e:
        logger.exception("Failed to transfer ownership")
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError:
        logger.exception("Permission denied for ownership transfer")
        raise HTTPException(status_code=403, detail="You don't have permission to transfer ownership.")
    
    if updated:
        await activity.log(
            action="ownership_transferred",
            target_type="workspace",
            target_id=workspace_id,
            actor_id=str(current_user.id),
            details={
                "from_user_id": str(current_user.id),
                "from_username": current_user.username,
                "to_user_id": request.user_id,
            }
        )

        # Notify new owner
        notif_service = NotificationService(db)
        await notif_service.ownership_transferred(
            user_id=request.user_id,
            workspace_name=workspace.name,
            previous_owner=current_user.display_name or current_user.username,
            action_url=f"/workspaces/{workspace_id}"
        )

    return updated.to_dict()


@router.get("/{workspace_id}/activity")
async def get_workspace_activity(
    workspace_id: str,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_READ_OWN, Permission.WORKSPACES_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """Get activity feed for a workspace. Must be member or owner."""
    from sqlalchemy import select, func, and_, desc
    from app.models.activity_log import ActivityLog
    import uuid
    
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_view_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(status_code=403, detail="You don't have access to this workspace")
    
    offset = (page - 1) * limit
    
    # Get total count
    count_result = await db.execute(
        select(func.count())
        .select_from(ActivityLog)
        .where(
            and_(
                ActivityLog.target_type == "workspace",
                ActivityLog.target_id == uuid.UUID(workspace_id)
            )
        )
    )
    total = count_result.scalar() or 0
    
    # Get paginated logs
    logs_result = await db.execute(
        select(ActivityLog)
        .where(
            and_(
                ActivityLog.target_type == "workspace",
                ActivityLog.target_id == uuid.UUID(workspace_id)
            )
        )
        .order_by(desc(ActivityLog.created_at))
        .offset(offset)
        .limit(limit)
    )
    logs = logs_result.scalars().all()
    
    # Enrich with actor info
    actor_ids = {str(log.actor_id) for log in logs if log.actor_id}
    actors = {}
    if actor_ids:
        user_result = await db.execute(
            select(User).where(User.id.in_([uuid.UUID(aid) for aid in actor_ids]))
        )
        for user in user_result.scalars().all():
            actors[str(user.id)] = {
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.get_avatar_url(),
            }
    
    total_pages = (total + limit - 1) // limit
    
    return {
        "activity": [
            {
                **log.to_dict(),
                "actor": actors.get(str(log.actor_id)) if log.actor_id else None,
            }
            for log in logs
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
        },
    }


# ========== Volume Management ==========

@router.post("/{workspace_id}/volumes")
async def add_volume_to_workspace(
    workspace_id: str,
    request: AddVolumeRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Add a volume to workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    volume_access = VolumeAccessService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to manage this workspace's volumes"
        )
    
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
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Remove a volume from workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to manage this workspace's volumes"
        )
    
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
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Update volume role in workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to manage this workspace's volumes"
        )
    
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
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Invite a user to workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to invite members to this workspace"
        )
    
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
        logger.exception("Failed to invite member")
        raise HTTPException(status_code=400, detail=str(e))
    
    # Send notification to invited user
    notif_service = NotificationService(db)
    await notif_service.workspace_invitation(
        user_id=request.user_id,
        workspace_name=workspace.name,
        inviter_name=current_user.display_name or current_user.username,
        action_url=f"/workspaces/{workspace_id}"
    )
    
    # Log activity
    activity = ActivityService(db)
    await activity.log(
        action="invitation_sent",
        target_type="workspace",
        target_id=workspace_id,
        actor_id=str(current_user.id),
        details={
            "invited_user_id": request.user_id,
            "role": request.role,
        }
    )
    
    return invitation.to_dict()


@router.post("/{workspace_id}/invitations/{invitation_id}/accept")
async def accept_invitation(
    workspace_id: str,
    invitation_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Accept a workspace invitation."""
    service = WorkspaceService(db)

    # Get workspace for notification
    workspace = await service.get_workspace(workspace_id)
    workspace_name = workspace.name if workspace else "Unknown"

    try:
        member = await service.accept_invitation(invitation_id, str(current_user.id))
    except ValueError as e:
        logger.exception("Failed to accept invitation")
        raise HTTPException(status_code=400, detail=str(e))

    # Notify user they were added
    notif_service = NotificationService(db)
    await notif_service.workspace_member_added(
        user_id=current_user.id,
        workspace_name=workspace_name,
        action_url=f"/workspaces/{workspace_id}"
    )

    # Log activity
    activity = ActivityService(db)
    await activity.log(
        action="invitation_accepted",
        target_type="workspace",
        target_id=workspace_id,
        actor_id=str(current_user.id),
        details={
            "user_id": str(current_user.id),
            "username": current_user.username,
        }
    )

    return member.to_dict()


@router.post("/{workspace_id}/invitations/{invitation_id}/reject")
async def reject_invitation(
    workspace_id: str,
    invitation_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Reject a workspace invitation."""
    service = WorkspaceService(db)
    
    try:
        await service.reject_invitation(invitation_id, str(current_user.id))
    except ValueError as e:
        logger.exception("Failed to reject invitation")
        raise HTTPException(status_code=400, detail=str(e))
    
    # Log activity
    activity = ActivityService(db)
    await activity.log(
        action="invitation_rejected",
        target_type="workspace",
        target_id=workspace_id,
        actor_id=str(current_user.id),
        details={
            "user_id": str(current_user.id),
            "username": current_user.username,
        }
    )
    
    return {"message": "Invitation rejected", "invitation_id": invitation_id}


@router.delete("/{workspace_id}/invitations/{invitation_id}")
async def cancel_invitation(
    workspace_id: str,
    invitation_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a workspace invitation. Must be owner, admin, or the inviter."""
    service = WorkspaceService(db)
    
    try:
        success = await service.cancel_invitation(invitation_id, str(current_user.id))
    except PermissionError:
        logger.exception("Permission denied for invitation cancellation")
        raise HTTPException(status_code=403, detail="You don't have permission to cancel this invitation.")
    
    if not success:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    return {"message": "Invitation cancelled", "invitation_id": invitation_id}


@router.get("/{workspace_id}/invitations")
async def list_invitations(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_READ_OWN, Permission.WORKSPACES_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """List pending invitations for a workspace. Must be owner or admin."""
    service = WorkspaceService(db)
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this workspace's invitations"
        )
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    pending = [i.to_dict() for i in workspace.invitations if i.status == "pending"]
    return {"invitations": pending}


@router.get("/{workspace_id}/members")
async def list_workspace_members(
    workspace_id: str,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "joined_at",
    sort_order: str = "desc",
    search: Optional[str] = None,
    role: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_READ_OWN, Permission.WORKSPACES_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """List workspace members with pagination. Must be member or owner."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_view_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(status_code=403, detail="You don't have access to this workspace")
    
    result = await service.list_workspace_members(
        workspace_id=workspace_id,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        role=role,
    )
    
    total_pages = (result["total"] + limit - 1) // limit
    
    return {
        "members": result["members"],
        "pagination": {
            "page": result["page"],
            "limit": result["limit"],
            "total": result["total"],
            "total_pages": total_pages,
        },
    }


@router.get("/{workspace_id}/volumes")
async def list_workspace_volumes(
    workspace_id: str,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "added_at",
    sort_order: str = "desc",
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_READ_OWN, Permission.WORKSPACES_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """List workspace volumes with pagination. Must be member or owner."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_view_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(status_code=403, detail="You don't have access to this workspace")
    
    result = await service.list_workspace_volumes(
        workspace_id=workspace_id,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
    )
    
    total_pages = (result["total"] + limit - 1) // limit
    
    return {
        "volumes": result["volumes"],
        "pagination": {
            "page": result["page"],
            "limit": result["limit"],
            "total": result["total"],
            "total_pages": total_pages,
        },
    }


@router.delete("/{workspace_id}/members/{user_id}")
async def remove_member(
    workspace_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
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
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to remove members from this workspace"
            )
    
    # Get workspace name before removal for notification
    workspace_name = workspace.name

    try:
        success = await service.remove_member(workspace_id, user_id)
    except ValueError as e:
        logger.exception("Failed to remove member")
        raise HTTPException(status_code=400, detail=str(e))

    if not success:
        raise HTTPException(status_code=404, detail="Member not found")

    # Notify removed member
    notif_service = NotificationService(db)
    await notif_service.workspace_member_removed(
        user_id=user_id,
        workspace_name=workspace_name,
        action_url=f"/workspaces"
    )

    return {"message": "Member removed", "user_id": user_id}


@router.put("/{workspace_id}/members/{user_id}")
async def update_member_role(
    workspace_id: str,
    user_id: str,
    request: UpdateMemberRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.WORKSPACES_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Update member role. Must be owner or admin."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if not await service.can_manage_workspace(workspace_id, str(current_user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update member roles in this workspace"
        )
    
    if request.role not in ("read_only", "read_write", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be: read_only, read_write, admin")
    
    try:
        member = await service.update_member_role(workspace_id, user_id, request.role)
    except ValueError as e:
        logger.exception("Failed to update member role")
        raise HTTPException(status_code=400, detail=str(e))
    
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    
    return member.to_dict()
