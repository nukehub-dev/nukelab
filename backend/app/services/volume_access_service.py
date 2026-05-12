"""
Volume access control service for permission checking.
"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.models.volume import Volume
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.workspace_volume import WorkspaceVolume


class VolumeAccessService:
    """Centralized volume permission checker"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def can_access_volume(
        self,
        volume_id: str,
        user_id: str,
        mode: str = "read_write"
    ) -> bool:
        """Check if user can access a volume in read_write or read_only mode"""
        volume = await self._get_volume(volume_id)
        if not volume:
            return False

        # Owner always has full access
        if str(volume.owner_id) == user_id:
            return True

        # Check workspace memberships
        if await self._is_workspace_member_with_access(volume_id, user_id, mode):
            return True

        # Check public visibility (read-only only)
        if volume.visibility == "public" and mode == "read_only":
            return True

        return False

    async def can_manage_volume(self, volume_id: str, user_id: str) -> bool:
        """Check if user can manage (delete, update) a volume"""
        volume = await self._get_volume(volume_id)
        if not volume:
            return False
        return str(volume.owner_id) == user_id

    async def _get_volume(self, volume_id: str) -> Optional[Volume]:
        """Get volume by ID"""
        result = await self.db.execute(
            select(Volume).where(Volume.id == volume_id)
        )
        return result.scalar_one_or_none()

    async def _is_workspace_member_with_access(
        self,
        volume_id: str,
        user_id: str,
        mode: str
    ) -> bool:
        """Check if user has access through workspace membership"""
        # Find workspaces that contain this volume
        workspace_query = select(WorkspaceVolume).where(
            WorkspaceVolume.volume_id == volume_id
        )
        result = await self.db.execute(workspace_query)
        workspace_volumes = result.scalars().all()

        for wv in workspace_volumes:
            workspace_id = str(wv.workspace_id)

            # Check if user is owner
            workspace_result = await self.db.execute(
                select(SharedWorkspace).where(
                    and_(
                        SharedWorkspace.id == workspace_id,
                        SharedWorkspace.owner_id == user_id
                    )
                )
            )
            if workspace_result.scalar_one_or_none():
                return True

            # Check if user is member
            member_result = await self.db.execute(
                select(WorkspaceMember).where(
                    and_(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.user_id == user_id
                    )
                )
            )
            member = member_result.scalar_one_or_none()
            if member:
                if mode == "read_only":
                    return True  # Any member can read
                elif mode == "read_write":
                    # Check workspace volume role or member role
                    if wv.role == "read_write":
                        return True
                    if member.role in ("read_write", "admin"):
                        return True

        return False

    async def get_accessible_volume_ids(
        self,
        user_id: str,
        mode: str = "read_write"
    ) -> list:
        """Get list of volume IDs accessible to user"""
        # Owned volumes
        result = await self.db.execute(
            select(Volume.id).where(Volume.owner_id == user_id)
        )
        volume_ids = [str(row[0]) for row in result.all()]

        # Workspace volumes
        workspace_query = select(WorkspaceVolume).join(
            SharedWorkspace, WorkspaceVolume.workspace_id == SharedWorkspace.id
        ).join(
            WorkspaceMember, WorkspaceMember.workspace_id == SharedWorkspace.id
        ).where(
            or_(
                WorkspaceMember.user_id == user_id,
                SharedWorkspace.owner_id == user_id
            )
        )
        result = await self.db.execute(workspace_query)
        for wv in result.scalars().all():
            if str(wv.volume_id) not in volume_ids:
                # Check if user has access with requested mode
                if await self.can_access_volume(str(wv.volume_id), user_id, mode):
                    volume_ids.append(str(wv.volume_id))

        # Public volumes (read-only)
        if mode == "read_only":
            result = await self.db.execute(
                select(Volume.id).where(Volume.visibility == "public")
            )
            for row in result.all():
                vid = str(row[0])
                if vid not in volume_ids:
                    volume_ids.append(vid)

        return volume_ids
