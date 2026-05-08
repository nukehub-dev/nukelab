"""
Shared workspace service for managing collaborative workspaces.
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.user import User


class WorkspaceService:
    """Shared workspace management"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_workspace(
        self,
        name: str,
        description: Optional[str],
        volume_name: str,
        owner_id: str
    ) -> SharedWorkspace:
        """Create a new shared workspace"""
        workspace = SharedWorkspace(
            name=name,
            description=description,
            volume_name=volume_name,
            owner_id=owner_id,
        )
        self.db.add(workspace)
        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace
    
    async def get_workspace(self, workspace_id: str) -> Optional[SharedWorkspace]:
        """Get workspace by ID with members loaded"""
        result = await self.db.execute(
            select(SharedWorkspace)
            .options(selectinload(SharedWorkspace.members).selectinload(WorkspaceMember.user))
            .where(SharedWorkspace.id == workspace_id)
        )
        return result.scalar_one_or_none()
    
    async def list_workspaces(
        self,
        user_id: str,
        include_memberships: bool = True
    ) -> List[SharedWorkspace]:
        """List workspaces accessible to user (owned or member of)"""
        query = select(SharedWorkspace).options(
            selectinload(SharedWorkspace.members).selectinload(WorkspaceMember.user)
        )
        
        if include_memberships:
            query = query.where(
                or_(
                    SharedWorkspace.owner_id == user_id,
                    SharedWorkspace.members.any(WorkspaceMember.user_id == user_id)
                )
            )
        else:
            query = query.where(SharedWorkspace.owner_id == user_id)
        
        query = query.where(SharedWorkspace.is_active == True)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def update_workspace(
        self,
        workspace_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Optional[SharedWorkspace]:
        """Update workspace details"""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            return None
        
        if name is not None:
            workspace.name = name
        if description is not None:
            workspace.description = description
        if is_active is not None:
            workspace.is_active = is_active
        
        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace
    
    async def delete_workspace(self, workspace_id: str) -> bool:
        """Delete a workspace"""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            return False
        
        await self.db.delete(workspace)
        await self.db.commit()
        return True
    
    async def add_member(
        self,
        workspace_id: str,
        user_id: str,
        role: str = "read_write"
    ) -> WorkspaceMember:
        """Add a member to a workspace"""
        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role
        )
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(member)
        return member
    
    async def remove_member(self, workspace_id: str, user_id: str) -> bool:
        """Remove a member from a workspace"""
        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id
                )
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            return False
        
        await self.db.delete(member)
        await self.db.commit()
        return True
    
    async def update_member_role(
        self,
        workspace_id: str,
        user_id: str,
        role: str
    ) -> Optional[WorkspaceMember]:
        """Update a member's role"""
        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id
                )
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            return None
        
        member.role = role
        await self.db.commit()
        await self.db.refresh(member)
        return member
    
    async def is_workspace_member(
        self,
        workspace_id: str,
        user_id: str
    ) -> bool:
        """Check if user is a member or owner of workspace"""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            return False
        
        if str(workspace.owner_id) == user_id:
            return True
        
        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id
                )
            )
        )
        return result.scalar_one_or_none() is not None
    
    async def can_manage_workspace(
        self,
        workspace_id: str,
        user_id: str
    ) -> bool:
        """Check if user can manage workspace (owner or admin member)"""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            return False
        
        if str(workspace.owner_id) == user_id:
            return True
        
        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                    WorkspaceMember.role == "admin"
                )
            )
        )
        return result.scalar_one_or_none() is not None
