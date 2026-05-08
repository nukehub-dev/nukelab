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

router = APIRouter()


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: Optional[str] = None
    volume_name: str


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AddMemberRequest(BaseModel):
    user_id: str
    role: str = "read_write"  # read_only, read_write, admin


class UpdateMemberRequest(BaseModel):
    role: str


@router.get("/")
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List workspaces user has access to (owned or member)."""
    service = WorkspaceService(db)
    workspaces = await service.list_workspaces(str(current_user.id))
    
    return {
        "workspaces": [w.to_dict() for w in workspaces]
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
        volume_name=request.volume_name,
        owner_id=str(current_user.id)
    )
    
    return workspace.to_dict()


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get workspace details. Must be owner or member."""
    service = WorkspaceService(db)
    
    workspace = await service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    # Check access
    if not await service.is_workspace_member(workspace_id, str(current_user.id)):
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    data = workspace.to_dict()
    data["members"] = [m.to_dict() for m in workspace.members]
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


# ========== Member Management ==========

@router.post("/{workspace_id}/members")
async def add_member(
    workspace_id: str,
    request: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a member to workspace. Must be owner or admin."""
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
    
    member = await service.add_member(
        workspace_id=workspace_id,
        user_id=request.user_id,
        role=request.role
    )
    
    return member.to_dict()


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
