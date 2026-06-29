# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Volume access control service for permission checking.

Permission Model A (Workspace Role Ceiling):
- Effective access = MIN(personal_access, most_restrictive_workspace_access)
- If volume is NOT in any workspace: owner = RW, non-owner = none (or public RO)
- If volume IS in workspace(s): workspace role is a hard ceiling
  - Owner + shared as RO → effective RO
  - Admin/Editor member + volume role RW → effective RW
  - Viewer member + any volume role → effective RO
"""

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.volume import Volume
from app.models.workspace_volume import WorkspaceVolume


class VolumeAccessService:
    """Centralized volume permission checker implementing Model A."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def can_access_volume(
        self, volume_id: str, user_id: str, mode: str = "read_write"
    ) -> bool:
        """Check if user can access a volume in read_write or read_only mode.

        Model A: Workspace role is a hard ceiling. Owner access is capped by
        the most restrictive workspace role across all workspaces the volume
        is shared in where the user has membership.
        """
        volume = await self._get_volume(volume_id)
        if not volume:
            return False

        # Compute personal_access: RW if owner, else none
        personal_access = "read_write" if str(volume.owner_id) == user_id else None

        # Find all workspace memberships for this user+volume combo
        workspace_access = await self._get_workspace_access(volume_id, user_id)

        # Compute effective access
        effective = self._compute_effective_access(personal_access, workspace_access)

        # If no effective access, fall back to public visibility
        if effective is None:
            return bool(volume.visibility == "public" and mode == "read_only")

        # Check if effective access satisfies requested mode
        if mode == "read_only":
            return effective in ("read_only", "read_write")
        elif mode == "read_write":
            return effective == "read_write"
        return False

    async def can_manage_volume(self, volume_id: str, user_id: str) -> bool:
        """Check if user can manage (delete, update) a volume"""
        volume = await self._get_volume(volume_id)
        if not volume:
            return False
        return str(volume.owner_id) == user_id

    async def _get_volume(self, volume_id: str) -> Volume | None:
        """Get volume by ID"""
        result = await self.db.execute(select(Volume).where(Volume.id == volume_id))
        return result.scalar_one_or_none()

    async def _get_workspace_access(self, volume_id: str, user_id: str) -> str | None:
        """Get the most restrictive workspace access for user+volume.

        Returns:
            "read_write", "read_only", or None if no workspace access.
        """
        # Find workspaces that contain this volume
        workspace_query = select(WorkspaceVolume).where(WorkspaceVolume.volume_id == volume_id)
        result = await self.db.execute(workspace_query)
        workspace_volumes = result.scalars().all()

        if not workspace_volumes:
            return None

        workspace_access = None

        for wv in workspace_volumes:
            workspace_id = str(wv.workspace_id)
            volume_role = wv.role  # "read_write" or "read_only"

            # Check if user is workspace owner
            workspace_result = await self.db.execute(
                select(SharedWorkspace).where(
                    and_(SharedWorkspace.id == workspace_id, SharedWorkspace.owner_id == user_id)
                )
            )
            ws = workspace_result.scalar_one_or_none()
            if ws:
                # Workspace owner gets the volume's role in that workspace
                workspace_access = self._most_restrictive(workspace_access, volume_role)
                continue

            # Check if user is a member
            member_result = await self.db.execute(
                select(WorkspaceMember).where(
                    and_(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.user_id == user_id,
                    )
                )
            )
            member = member_result.scalar_one_or_none()
            if member:
                if volume_role == "read_only":
                    access = "read_only"
                else:
                    # volume_role is "read_write"
                    if member.role == "read_only":
                        access = "read_only"
                    else:
                        # admin, read_write members get RW
                        access = "read_write"
                workspace_access = self._most_restrictive(workspace_access, access)

        return workspace_access

    @staticmethod
    def _most_restrictive(a: str | None, b: str | None) -> str | None:
        """Return the most restrictive of two access levels.

        read_only is more restrictive than read_write.
        None means no access.
        """
        if a is None:
            return b
        if b is None:
            return a
        if a == "read_only" or b == "read_only":
            return "read_only"
        return "read_write"

    @staticmethod
    def _compute_effective_access(personal: str | None, workspace: str | None) -> str | None:
        """Compute effective access as MIN(personal, workspace).

        If volume is in workspaces and user has workspace access, workspace caps personal.
        If volume is in workspaces but user has no workspace membership,
        personal access applies unchanged.
        If no personal access and no workspace access, no access.
        """
        if personal and workspace:
            return VolumeAccessService._most_restrictive(personal, workspace)
        elif personal:
            return personal
        elif workspace:
            return workspace
        return None

    async def get_accessible_volume_ids(self, user_id: str, mode: str = "read_write") -> list:
        """Get list of volume IDs accessible to user"""
        # Owned volumes
        result = await self.db.execute(select(Volume.id).where(Volume.owner_id == user_id))
        volume_ids = [str(row[0]) for row in result.all()]

        # Workspace volumes
        workspace_query = (
            select(WorkspaceVolume)
            .join(SharedWorkspace, WorkspaceVolume.workspace_id == SharedWorkspace.id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == SharedWorkspace.id)
            .where(or_(WorkspaceMember.user_id == user_id, SharedWorkspace.owner_id == user_id))
        )
        result = await self.db.execute(workspace_query)
        for wv in result.scalars().all():
            if str(wv.volume_id) not in volume_ids:
                # Check if user has access with requested mode
                if await self.can_access_volume(str(wv.volume_id), user_id, mode):
                    volume_ids.append(str(wv.volume_id))

        # Public volumes (read-only)
        if mode == "read_only":
            result = await self.db.execute(select(Volume.id).where(Volume.visibility == "public"))
            for row in result.all():
                vid = str(row[0])
                if vid not in volume_ids:
                    volume_ids.append(vid)

        return volume_ids
