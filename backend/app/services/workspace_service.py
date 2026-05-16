"""
Shared workspace service for managing collaborative workspaces.
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.workspace_volume import WorkspaceVolume
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.user import User


class WorkspaceService:
    """Shared workspace management"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_workspace(
        self,
        name: str,
        description: Optional[str],
        owner_id: str
    ) -> SharedWorkspace:
        """Create a new shared workspace"""
        workspace = SharedWorkspace(
            name=name,
            description=description,
            owner_id=owner_id,
        )
        self.db.add(workspace)
        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace
    
    async def get_workspace(self, workspace_id: str) -> Optional[SharedWorkspace]:
        """Get workspace by ID with members, volumes, and invitations loaded"""
        result = await self.db.execute(
            select(SharedWorkspace)
            .options(
                selectinload(SharedWorkspace.members).selectinload(WorkspaceMember.user),
                selectinload(SharedWorkspace.volume_associations).selectinload(WorkspaceVolume.volume),
                selectinload(SharedWorkspace.invitations).selectinload(WorkspaceInvitation.user)
            )
            .where(SharedWorkspace.id == workspace_id)
        )
        return result.scalar_one_or_none()
    
    async def list_workspaces(
        self,
        user_id: str,
        include_memberships: bool = True
    ) -> List[SharedWorkspace]:
        """List workspaces accessible to user (owned, member of, or invited to)"""
        query = select(SharedWorkspace).options(
            selectinload(SharedWorkspace.members).selectinload(WorkspaceMember.user),
            selectinload(SharedWorkspace.invitations)
        )
        
        if include_memberships:
            query = query.where(
                or_(
                    SharedWorkspace.owner_id == user_id,
                    SharedWorkspace.members.any(WorkspaceMember.user_id == user_id),
                    SharedWorkspace.invitations.any(
                        and_(
                            WorkspaceInvitation.user_id == user_id,
                            WorkspaceInvitation.status == "pending"
                        )
                    )
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
    
    # ========== Volume Management ==========
    
    async def add_volume(
        self,
        workspace_id: str,
        volume_id: str,
        role: str = "read_write",
        added_by: Optional[str] = None
    ) -> WorkspaceVolume:
        """Add a volume to a workspace"""
        workspace_volume = WorkspaceVolume(
            workspace_id=workspace_id,
            volume_id=volume_id,
            role=role,
            added_by=added_by
        )
        self.db.add(workspace_volume)
        await self.db.commit()
        await self.db.refresh(workspace_volume)
        return workspace_volume
    
    async def remove_volume(self, workspace_id: str, volume_id: str) -> bool:
        """Remove a volume from a workspace"""
        result = await self.db.execute(
            select(WorkspaceVolume).where(
                and_(
                    WorkspaceVolume.workspace_id == workspace_id,
                    WorkspaceVolume.volume_id == volume_id
                )
            )
        )
        workspace_volume = result.scalar_one_or_none()
        if not workspace_volume:
            return False
        
        await self.db.delete(workspace_volume)
        await self.db.commit()
        return True
    
    async def update_volume_role(
        self,
        workspace_id: str,
        volume_id: str,
        role: str
    ) -> Optional[WorkspaceVolume]:
        """Update a volume's role in a workspace"""
        result = await self.db.execute(
            select(WorkspaceVolume).where(
                and_(
                    WorkspaceVolume.workspace_id == workspace_id,
                    WorkspaceVolume.volume_id == volume_id
                )
            )
        )
        workspace_volume = result.scalar_one_or_none()
        if not workspace_volume:
            return None
        
        workspace_volume.role = role
        await self.db.commit()
        await self.db.refresh(workspace_volume)
        return workspace_volume
    
    # ========== Member Management ==========
    
    async def add_member(
        self,
        workspace_id: str,
        user_id: str,
        role: str = "read_write"
    ) -> WorkspaceMember:
        """Add a member to a workspace"""
        # Check if member already exists (eagerly load user to avoid lazy load issues in async)
        result = await self.db.execute(
            select(WorkspaceMember)
            .options(selectinload(WorkspaceMember.user))
            .where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        
        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role
        )
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(member, attribute_names=["user"])
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
    
    # ========== Invitation Management ==========
    
    async def invite_member(
        self,
        workspace_id: str,
        user_id: str,
        invited_by: str,
        role: str = "read_write"
    ) -> WorkspaceInvitation:
        """Send a workspace invitation to a user."""
        # Check if already a member
        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id
                )
            )
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError("User is already a member of this workspace")
        
        # Check if invitation already exists
        result = await self.db.execute(
            select(WorkspaceInvitation).where(
                and_(
                    WorkspaceInvitation.workspace_id == workspace_id,
                    WorkspaceInvitation.user_id == user_id,
                    WorkspaceInvitation.status == "pending"
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        
        invitation = WorkspaceInvitation(
            workspace_id=workspace_id,
            user_id=user_id,
            invited_by=invited_by,
            role=role
        )
        self.db.add(invitation)
        await self.db.commit()
        await self.db.refresh(invitation, attribute_names=["user", "inviter", "workspace"])
        return invitation
    
    async def accept_invitation(
        self,
        invitation_id: str,
        user_id: str
    ) -> WorkspaceMember:
        """Accept a workspace invitation."""
        from uuid import UUID
        result = await self.db.execute(
            select(WorkspaceInvitation)
            .options(selectinload(WorkspaceInvitation.workspace))
            .where(
                and_(
                    WorkspaceInvitation.id == UUID(invitation_id),
                    WorkspaceInvitation.user_id == user_id,
                    WorkspaceInvitation.status == "pending"
                )
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise ValueError("Invitation not found or already processed")
        
        # Create workspace member
        member = WorkspaceMember(
            workspace_id=invitation.workspace_id,
            user_id=user_id,
            role=invitation.role
        )
        self.db.add(member)
        
        # Update invitation status
        invitation.status = "accepted"
        await self.db.commit()
        await self.db.refresh(member, attribute_names=["user"])
        return member
    
    async def reject_invitation(
        self,
        invitation_id: str,
        user_id: str
    ) -> None:
        """Reject a workspace invitation."""
        from uuid import UUID
        result = await self.db.execute(
            select(WorkspaceInvitation).where(
                and_(
                    WorkspaceInvitation.id == UUID(invitation_id),
                    WorkspaceInvitation.user_id == user_id,
                    WorkspaceInvitation.status == "pending"
                )
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise ValueError("Invitation not found or already processed")
        
        invitation.status = "rejected"
        await self.db.commit()
    
    async def cancel_invitation(
        self,
        invitation_id: str,
        cancelled_by: str
    ) -> bool:
        """Cancel a workspace invitation (by inviter or admin)."""
        from uuid import UUID
        result = await self.db.execute(
            select(WorkspaceInvitation)
            .options(selectinload(WorkspaceInvitation.workspace))
            .where(
                and_(
                    WorkspaceInvitation.id == UUID(invitation_id),
                    WorkspaceInvitation.status == "pending"
                )
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            return False
        
        # Check permission: only inviter or workspace owner can cancel
        if str(invitation.invited_by) != cancelled_by and str(invitation.workspace.owner_id) != cancelled_by:
            raise PermissionError("Only the inviter or workspace owner can cancel this invitation")
        
        await self.db.delete(invitation)
        await self.db.commit()
        return True
    
    async def get_invitation(self, invitation_id: str) -> Optional[WorkspaceInvitation]:
        """Get invitation by ID with user loaded"""
        from uuid import UUID
        result = await self.db.execute(
            select(WorkspaceInvitation)
            .options(selectinload(WorkspaceInvitation.user))
            .where(WorkspaceInvitation.id == UUID(invitation_id))
        )
        return result.scalar_one_or_none()
    
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
    
    async def can_view_workspace(
        self,
        workspace_id: str,
        user_id: str
    ) -> bool:
        """Check if user can view workspace (owner, member, or has pending invitation)"""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            return False
        
        if str(workspace.owner_id) == user_id:
            return True
        
        # Check if member
        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id
                )
            )
        )
        if result.scalar_one_or_none() is not None:
            return True
        
        # Check if has pending invitation
        result = await self.db.execute(
            select(WorkspaceInvitation).where(
                and_(
                    WorkspaceInvitation.workspace_id == workspace_id,
                    WorkspaceInvitation.user_id == user_id,
                    WorkspaceInvitation.status == "pending"
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
