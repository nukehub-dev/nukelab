# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Shared workspace service for managing collaborative workspaces.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.user import User
from app.models.volume import Volume
from app.models.workspace_invitation import WorkspaceInvitation
from app.models.workspace_volume import WorkspaceVolume


class WorkspaceService:
    """Shared workspace management"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_workspace(
        self, name: str, description: str | None, owner_id: str
    ) -> SharedWorkspace:
        """Create a new shared workspace and add owner as admin member."""
        workspace = SharedWorkspace(
            name=name,
            description=description,
            owner_id=owner_id,
        )
        self.db.add(workspace)
        await self.db.commit()
        await self.db.refresh(workspace)

        # Add owner as a member so they appear in the members list
        owner_member = WorkspaceMember(
            workspace_id=str(workspace.id), user_id=owner_id, role="admin"
        )
        self.db.add(owner_member)
        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace

    # ========== Paginated Lists ==========

    async def list_workspace_members(
        self,
        workspace_id: str,
        page: int = 1,
        limit: int = 20,
        sort_by: str = "joined_at",
        sort_order: str = "desc",
        search: str | None = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        """List workspace members with pagination, sorting, and filtering."""
        # Build base query with user joined for sorting/searching
        query = (
            select(WorkspaceMember)
            .options(selectinload(WorkspaceMember.user))
            .join(User, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )

        count_query = (
            select(func.count())
            .select_from(WorkspaceMember)
            .join(User, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )

        # Apply role filter
        if role:
            query = query.where(WorkspaceMember.role == role)
            count_query = count_query.where(WorkspaceMember.role == role)

        # Apply search
        if search:
            search_pattern = f"%{search}%"
            search_filter = or_(
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern),
            )
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        # Get total count
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Apply sorting
        sort_column_map = {
            "username": User.username,
            "role": WorkspaceMember.role,
            "joined_at": WorkspaceMember.joined_at,
        }
        sort_column = sort_column_map.get(sort_by, WorkspaceMember.joined_at)

        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Apply pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        members = result.scalars().all()

        return {
            "members": [m.to_dict() for m in members],
            "total": total,
            "page": page,
            "limit": limit,
        }

    async def list_workspace_volumes(
        self,
        workspace_id: str,
        page: int = 1,
        limit: int = 20,
        sort_by: str = "added_at",
        sort_order: str = "desc",
        search: str | None = None,
    ) -> dict[str, Any]:
        """List workspace volumes with pagination, sorting, and filtering."""
        # Build base query with volume joined for sorting/searching
        query = (
            select(WorkspaceVolume)
            .options(
                selectinload(WorkspaceVolume.volume).selectinload(Volume.owner),
                selectinload(WorkspaceVolume.added_by_user),
            )
            .join(Volume, WorkspaceVolume.volume_id == Volume.id)
            .where(WorkspaceVolume.workspace_id == workspace_id)
        )

        count_query = (
            select(func.count())
            .select_from(WorkspaceVolume)
            .join(Volume, WorkspaceVolume.volume_id == Volume.id)
            .where(WorkspaceVolume.workspace_id == workspace_id)
        )

        # Apply search
        if search:
            search_pattern = f"%{search}%"
            search_filter = Volume.display_name.ilike(search_pattern)
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        # Get total count
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Apply sorting
        sort_column_map = {
            "display_name": Volume.display_name,
            "added_at": WorkspaceVolume.added_at,
            "role": WorkspaceVolume.role,
        }
        sort_column = sort_column_map.get(sort_by, WorkspaceVolume.added_at)

        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Apply pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        volumes = result.scalars().all()

        return {
            "volumes": [v.to_dict() for v in volumes],
            "total": total,
            "page": page,
            "limit": limit,
        }

    async def get_workspace(self, workspace_id: str) -> SharedWorkspace | None:
        """Get workspace by ID with members, volumes, and invitations loaded"""
        result = await self.db.execute(
            select(SharedWorkspace)
            .options(
                selectinload(SharedWorkspace.owner),
                selectinload(SharedWorkspace.members).selectinload(WorkspaceMember.user),
                selectinload(SharedWorkspace.volume_associations).selectinload(
                    WorkspaceVolume.volume
                ),
                selectinload(SharedWorkspace.invitations).selectinload(WorkspaceInvitation.user),
                selectinload(SharedWorkspace.invitations).selectinload(WorkspaceInvitation.inviter),
            )
            .where(SharedWorkspace.id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def list_workspaces(
        self, user_id: str, include_memberships: bool = True
    ) -> list[SharedWorkspace]:
        """List workspaces accessible to user (owned, member of, or invited to)"""
        query = select(SharedWorkspace).options(
            selectinload(SharedWorkspace.owner),
            selectinload(SharedWorkspace.members).selectinload(WorkspaceMember.user),
            selectinload(SharedWorkspace.invitations),
        )

        if include_memberships:
            query = query.where(
                or_(
                    SharedWorkspace.owner_id == user_id,
                    SharedWorkspace.members.any(WorkspaceMember.user_id == user_id),
                    SharedWorkspace.invitations.any(
                        and_(
                            WorkspaceInvitation.user_id == user_id,
                            WorkspaceInvitation.status == "pending",
                        )
                    ),
                )
            )
        else:
            query = query.where(SharedWorkspace.owner_id == user_id)

        query = query.where(SharedWorkspace.is_active.is_(True))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def list_all_workspaces(
        self,
        page: int = 1,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        search: str | None = None,
        status: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        """List ALL workspaces (admin view) with pagination, sorting, and filtering."""
        query = select(SharedWorkspace).options(
            selectinload(SharedWorkspace.owner),
            selectinload(SharedWorkspace.members),
            selectinload(SharedWorkspace.volume_associations),
        )

        count_query = select(func.count()).select_from(SharedWorkspace)

        # Apply status filter
        if status is not None:
            is_active = status.lower() == "active"
            query = query.where(SharedWorkspace.is_active == is_active)
            count_query = count_query.where(SharedWorkspace.is_active == is_active)

        # Apply owner filter
        if owner_id:
            query = query.where(SharedWorkspace.owner_id == owner_id)
            count_query = count_query.where(SharedWorkspace.owner_id == owner_id)

        # Apply search (workspace name or owner username)
        if search:
            search_pattern = f"%{search}%"
            search_filter = or_(
                SharedWorkspace.name.ilike(search_pattern),
                User.username.ilike(search_pattern),
            )
            query = query.join(User, SharedWorkspace.owner_id == User.id).where(search_filter)
            count_query = count_query.join(User, SharedWorkspace.owner_id == User.id).where(
                search_filter
            )
        else:
            # Still join User for sorting by username
            query = query.join(User, SharedWorkspace.owner_id == User.id)

        # Get total count
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Apply sorting
        sort_column_map = {
            "name": SharedWorkspace.name,
            "created_at": SharedWorkspace.created_at,
            "updated_at": SharedWorkspace.updated_at,
            "username": User.username,
        }
        sort_column = sort_column_map.get(sort_by, SharedWorkspace.created_at)

        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Apply pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        workspaces = result.scalars().all()

        return {
            "workspaces": [w.to_dict() for w in workspaces],
            "total": total,
            "page": page,
            "limit": limit,
        }

    async def update_workspace(
        self,
        workspace_id: str,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
    ) -> SharedWorkspace | None:
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
        added_by: str | None = None,
    ) -> WorkspaceVolume:
        """Add a volume to a workspace"""
        workspace_volume = WorkspaceVolume(
            workspace_id=workspace_id, volume_id=volume_id, role=role, added_by=added_by
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
                    WorkspaceVolume.volume_id == volume_id,
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
        self, workspace_id: str, volume_id: str, role: str
    ) -> WorkspaceVolume | None:
        """Update a volume's role in a workspace"""
        result = await self.db.execute(
            select(WorkspaceVolume).where(
                and_(
                    WorkspaceVolume.workspace_id == workspace_id,
                    WorkspaceVolume.volume_id == volume_id,
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
        self, workspace_id: str, user_id: str, role: str = "read_write"
    ) -> WorkspaceMember:
        """Add a member to a workspace"""
        # Check if member already exists (eagerly load user to avoid lazy load issues in async)
        result = await self.db.execute(
            select(WorkspaceMember)
            .options(selectinload(WorkspaceMember.user))
            .where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(member, attribute_names=["user"])
        return member

    async def remove_member(self, workspace_id: str, user_id: str) -> bool:
        """Remove a member from a workspace. Owner cannot be removed."""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            raise ValueError("Workspace not found")

        if str(workspace.owner_id) == user_id:
            raise ValueError(
                "Cannot remove the owner from the workspace. Transfer ownership first."
            )

        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
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
        self, workspace_id: str, user_id: str, role: str
    ) -> WorkspaceMember | None:
        """Update a member's role. Owner's role cannot be changed."""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            raise ValueError("Workspace not found")

        if str(workspace.owner_id) == user_id:
            raise ValueError("Cannot change the owner's role. Transfer ownership first.")

        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
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
        self, workspace_id: str, user_id: str, invited_by: str, role: str = "read_write"
    ) -> WorkspaceInvitation:
        """Send a workspace invitation to a user."""
        # Check if already a member
        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
                )
            )
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError("User is already a member of this workspace")

        # Check if invitation already exists (any status)
        result = await self.db.execute(
            select(WorkspaceInvitation).where(
                and_(
                    WorkspaceInvitation.workspace_id == workspace_id,
                    WorkspaceInvitation.user_id == user_id,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            if existing.status == "pending":
                return existing
            # Re-invite: reset a rejected/expired/accepted invitation back to pending
            existing.status = "pending"
            existing.role = role
            existing.invited_by = invited_by
            existing.expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7)
            await self.db.commit()
            await self.db.refresh(existing, attribute_names=["user", "inviter", "workspace"])
            return existing

        invitation = WorkspaceInvitation(
            workspace_id=workspace_id, user_id=user_id, invited_by=invited_by, role=role
        )
        self.db.add(invitation)
        await self.db.commit()
        await self.db.refresh(invitation, attribute_names=["user", "inviter", "workspace"])
        return invitation

    async def accept_invitation(self, invitation_id: str, user_id: str) -> WorkspaceMember:
        """Accept a workspace invitation."""
        from uuid import UUID

        result = await self.db.execute(
            select(WorkspaceInvitation)
            .options(selectinload(WorkspaceInvitation.workspace))
            .where(
                and_(
                    WorkspaceInvitation.id == UUID(invitation_id),
                    WorkspaceInvitation.user_id == user_id,
                    WorkspaceInvitation.status == "pending",
                )
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise ValueError("Invitation not found or already processed")

        # Check expiration
        if invitation.expires_at and invitation.expires_at < datetime.now(UTC).replace(tzinfo=None):
            invitation.status = "expired"
            await self.db.commit()
            raise ValueError("Invitation has expired")

        # Create workspace member
        member = WorkspaceMember(
            workspace_id=invitation.workspace_id, user_id=user_id, role=invitation.role
        )
        self.db.add(member)

        # Update invitation status
        invitation.status = "accepted"
        await self.db.commit()
        await self.db.refresh(member, attribute_names=["user"])
        return member

    async def reject_invitation(self, invitation_id: str, user_id: str) -> None:
        """Reject a workspace invitation."""
        from uuid import UUID

        result = await self.db.execute(
            select(WorkspaceInvitation).where(
                and_(
                    WorkspaceInvitation.id == UUID(invitation_id),
                    WorkspaceInvitation.user_id == user_id,
                    WorkspaceInvitation.status == "pending",
                )
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise ValueError("Invitation not found or already processed")

        invitation.status = "rejected"
        await self.db.commit()

    async def cancel_invitation(self, invitation_id: str, cancelled_by: str) -> bool:
        """Cancel a workspace invitation (by inviter or admin)."""
        from uuid import UUID

        result = await self.db.execute(
            select(WorkspaceInvitation)
            .options(selectinload(WorkspaceInvitation.workspace))
            .where(
                and_(
                    WorkspaceInvitation.id == UUID(invitation_id),
                    WorkspaceInvitation.status == "pending",
                )
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            return False

        # Check permission: only inviter or workspace owner can cancel
        if (
            str(invitation.invited_by) != cancelled_by
            and str(invitation.workspace.owner_id) != cancelled_by
        ):
            raise PermissionError("Only the inviter or workspace owner can cancel this invitation")

        await self.db.delete(invitation)
        await self.db.commit()
        return True

    async def get_invitation(self, invitation_id: str) -> WorkspaceInvitation | None:
        """Get invitation by ID with user loaded"""
        from uuid import UUID

        result = await self.db.execute(
            select(WorkspaceInvitation)
            .options(selectinload(WorkspaceInvitation.user))
            .where(WorkspaceInvitation.id == UUID(invitation_id))
        )
        return result.scalar_one_or_none()

    async def is_workspace_member(self, workspace_id: str, user_id: str) -> bool:
        """Check if user is a member or owner of workspace"""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            return False

        if str(workspace.owner_id) == user_id:
            return True

        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def can_view_workspace(self, workspace_id: str, user_id: str) -> bool:
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
                    WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
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
                    WorkspaceInvitation.status == "pending",
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def can_manage_workspace(self, workspace_id: str, user_id: str) -> bool:
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
                    WorkspaceMember.role == "admin",
                )
            )
        )
        return result.scalar_one_or_none() is not None

    # ========== Leave & Transfer ==========

    async def leave_workspace(self, workspace_id: str, user_id: str) -> bool:
        """Allow a member (non-owner) to leave a workspace."""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            raise ValueError("Workspace not found")

        if str(workspace.owner_id) == user_id:
            raise ValueError("Owner must transfer ownership before leaving")

        return await self.remove_member(workspace_id, user_id)

    async def transfer_ownership(
        self, workspace_id: str, current_owner_id: str, new_owner_id: str
    ) -> SharedWorkspace | None:
        """Transfer workspace ownership to another member."""
        workspace = await self.get_workspace(workspace_id)
        if not workspace:
            return None

        if str(workspace.owner_id) != current_owner_id:
            raise PermissionError("Only the owner can transfer ownership")

        if current_owner_id == new_owner_id:
            raise ValueError("Cannot transfer ownership to yourself")

        # Verify new owner is a member
        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == new_owner_id,
                )
            )
        )
        new_owner_member = result.scalar_one_or_none()
        if not new_owner_member:
            raise ValueError("Target user must be a workspace member")

        # Update old owner's membership to admin (create if not exists)
        result = await self.db.execute(
            select(WorkspaceMember).where(
                and_(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == current_owner_id,
                )
            )
        )
        old_owner_member = result.scalar_one_or_none()
        if old_owner_member:
            old_owner_member.role = "admin"
        else:
            old_owner_member = WorkspaceMember(
                workspace_id=workspace_id, user_id=current_owner_id, role="admin"
            )
            self.db.add(old_owner_member)

        # Transfer ownership
        workspace.owner_id = new_owner_id

        # Update new owner's role to admin just in case
        new_owner_member.role = "admin"

        await self.db.commit()
        await self.db.refresh(workspace)
        return workspace
