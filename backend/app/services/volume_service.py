# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Volume management service with quota enforcement.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.container.client import get_container_client
from app.core.logging import get_logger
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.volume import Volume
from app.models.workspace_volume import WorkspaceVolume
from app.services.xfs_quota_service import xfs_quota_service

logger = get_logger(__name__)


class VolumeService:
    """Docker volume management with database tracking"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_volume_storage_paths(self, name: str, mountpoint: str | None = None) -> list[str]:
        """Build a list of possible volume storage paths to try."""
        import os

        paths = []

        if settings.volume_storage_path:
            paths.append(os.path.join(settings.volume_storage_path, name, "_data"))

        if mountpoint:
            paths.append(mountpoint)

        paths.append(f"/var/lib/docker/volumes/{name}/_data")
        paths.append(f"/var/lib/containers/storage/volumes/{name}/_data")
        paths.append(
            f"{os.path.expanduser('~')}/.local/share/containers/storage/volumes/{name}/_data"
        )

        return paths

    async def create_volume(
        self,
        name: str,
        display_name: str,
        owner_id: str,
        max_size_bytes: int | None = None,
        description: str | None = None,
        visibility: str = "private",
    ) -> Volume:
        """Create a new volume record and Docker volume"""
        container_client = await get_container_client()

        # Create Docker volume
        await container_client.client.volumes.create(
            {
                "Name": name,
                "Labels": {
                    "nukelab.managed": "true",
                    "nukelab.user.id": owner_id,
                },
            }
        )

        # Create database record
        volume = Volume(
            name=name,
            display_name=display_name,
            owner_id=owner_id,
            max_size_bytes=max_size_bytes,
            description=description,
            visibility=visibility,
            status="active",
        )
        self.db.add(volume)
        await self.db.commit()
        await self.db.refresh(volume)

        # Set XFS project quota if enabled and limit specified
        if max_size_bytes:
            quota_ok = xfs_quota_service.set_quota(name, max_size_bytes)
            if not quota_ok and settings.xfs_quota_enabled:
                logger.warning(
                    "XFS quota could not be set for volume %s; "
                    "falling back to periodic du-based enforcement",
                    name,
                )

        return volume

    async def get_volume(self, volume_id: str) -> Volume | None:
        """Get volume by ID"""
        from sqlalchemy.orm import selectinload

        result = await self.db.execute(
            select(Volume)
            .options(selectinload(Volume.server_mounts))
            .options(selectinload(Volume.owner))
            .where(Volume.id == volume_id)
        )
        return result.scalar_one_or_none()

    async def get_volume_by_name(self, name: str) -> Volume | None:
        """Get volume by Docker name"""
        result = await self.db.execute(select(Volume).where(Volume.name == name))
        return result.scalar_one_or_none()

    async def list_volumes(
        self, user_id: str, include_workspace_volumes: bool = True
    ) -> list[Volume]:
        """List volumes accessible to user (owned or in workspaces)"""
        conditions = [Volume.owner_id == user_id]

        if include_workspace_volumes:
            # Also include volumes from workspaces the user is a member of
            workspace_volume_query = (
                select(WorkspaceVolume.volume_id)
                .join(SharedWorkspace, WorkspaceVolume.workspace_id == SharedWorkspace.id)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == SharedWorkspace.id)
                .where(or_(WorkspaceMember.user_id == user_id, SharedWorkspace.owner_id == user_id))
            )

            result = await self.db.execute(workspace_volume_query)
            workspace_volume_ids = [row[0] for row in result.all()]

            if workspace_volume_ids:
                conditions.append(Volume.id.in_(workspace_volume_ids))

        # Also include public volumes
        conditions.append(Volume.visibility == "public")

        query = (
            select(Volume)
            .options(
                selectinload(Volume.workspace_associations),
                selectinload(Volume.server_mounts),
                selectinload(Volume.owner),
            )
            .where(or_(*conditions))
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def list_all_volumes(
        self,
        page: int = 1,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        search: str | None = None,
        status: str | None = None,
        visibility: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        """List ALL volumes (admin view) with pagination, sorting, and filtering."""
        from app.models.user import User

        query = select(Volume).options(
            selectinload(Volume.owner),
            selectinload(Volume.workspace_associations),
        )

        count_query = select(func.count()).select_from(Volume)

        # Apply status filter
        if status:
            query = query.where(Volume.status == status)
            count_query = count_query.where(Volume.status == status)

        # Apply visibility filter
        if visibility:
            query = query.where(Volume.visibility == visibility)
            count_query = count_query.where(Volume.visibility == visibility)

        # Apply owner filter
        if owner_id:
            query = query.where(Volume.owner_id == owner_id)
            count_query = count_query.where(Volume.owner_id == owner_id)

        # Apply search (volume name/display_name or owner username)
        if search:
            search_pattern = f"%{search}%"
            search_filter = or_(
                Volume.name.ilike(search_pattern),
                Volume.display_name.ilike(search_pattern),
                User.username.ilike(search_pattern),
            )
            query = query.join(User, Volume.owner_id == User.id).where(search_filter)
            count_query = count_query.join(User, Volume.owner_id == User.id).where(search_filter)
        else:
            # Still join User for sorting by username
            query = query.join(User, Volume.owner_id == User.id)

        # Get total count
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Apply sorting
        sort_column_map = {
            "name": Volume.name,
            "display_name": Volume.display_name,
            "created_at": Volume.created_at,
            "size_bytes": Volume.size_bytes,
            "username": User.username,
        }
        sort_column = sort_column_map.get(sort_by, Volume.created_at)

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

    def validate_max_size(self, volume: Volume, max_size_bytes: int | None) -> None:
        """Validate that max_size_bytes is not below the volume's current size.

        Raises ValueError with a descriptive message if the limit would be
        set below the actual used bytes.
        """
        if max_size_bytes is not None and volume.size_bytes is not None:
            if max_size_bytes < volume.size_bytes:
                raise ValueError(
                    f"Cannot set volume limit ({max_size_bytes} bytes) "
                    f"below current volume size ({volume.size_bytes} bytes). "
                    f"Free up {volume.size_bytes - max_size_bytes} bytes first."
                )

    async def update_volume(
        self,
        volume_id: str,
        display_name: str | None = None,
        description: str | None = None,
        visibility: str | None = None,
        max_size_bytes: int | None = None,
        status: str | None = None,
    ) -> Volume | None:
        """Update volume metadata"""
        volume = await self.get_volume(volume_id)
        if not volume:
            return None

        if display_name is not None:
            volume.display_name = display_name
        if description is not None:
            volume.description = description
        if visibility is not None:
            volume.visibility = visibility
        if max_size_bytes is not None:
            volume.max_size_bytes = max_size_bytes
            # Update XFS project quota if enabled
            xfs_quota_service.update_quota(volume.name, max_size_bytes)
        if status is not None:
            volume.status = status

        await self.db.commit()
        await self.db.refresh(volume)
        return volume

    async def delete_volume(self, volume_id: str) -> bool:
        """Delete a volume (only if not mounted by any server)"""
        volume = await self.get_volume(volume_id)
        if not volume:
            return False

        from app.models.server_volume import ServerVolume

        mount_count = await self.db.execute(
            select(func.count()).where(ServerVolume.volume_id == volume.id)
        )
        mount_count_value = mount_count.scalar()
        if mount_count_value > 0:
            raise ValueError(f"Volume is still mounted by {mount_count_value} server(s)")

        # Remove XFS project quota (best-effort, do before Docker delete)
        xfs_quota_service.remove_quota(volume.name)

        # Delete Docker volume
        container_client = await get_container_client()
        try:
            vol = await container_client.client.volumes.get(volume.name)
            await vol.delete()
        except Exception:
            pass

        # Delete database record
        await self.db.delete(volume)
        await self.db.commit()
        return True

    async def update_volume_size(self, volume_id: str) -> int | None:
        """Update volume size from filesystem"""
        volume = await self.get_volume(volume_id)
        if not volume:
            return None

        size_bytes = await self.get_volume_size(volume.name)
        if size_bytes is not None:
            volume.size_bytes = size_bytes
            await self.db.commit()

            # Warn if volume is near limit (90%)
            if volume.max_size_bytes and volume.max_size_bytes > 0:
                usage_pct = int((size_bytes / volume.max_size_bytes) * 100)
                if usage_pct >= 90:
                    from app.services.notification_service import NotificationService

                    notif_service = NotificationService(self.db)
                    await notif_service.volume_near_limit(
                        user_id=volume.owner_id,
                        volume_name=volume.display_name or volume.name,
                        usage_pct=usage_pct,
                    )
        return size_bytes

    async def get_volume_size(self, name: str, mountpoint: str | None = None) -> int | None:
        """Get volume size in bytes (requires du command)"""
        import os
        import subprocess

        paths_to_try = self._get_volume_storage_paths(name, mountpoint)

        for path in paths_to_try:
            if os.path.exists(path):
                try:
                    result = subprocess.run(
                        ["du", "-sb", path], capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        return int(result.stdout.split()[0])
                except Exception:
                    continue

        return None

    async def check_volumes_quota(
        self, volume_ids: list[str], plan_disk_limit: str
    ) -> dict[str, Any]:
        """Batch quota check: fetches all volumes once, updates sizes once,
        and performs both per-volume and aggregate checks in-memory.

        This eliminates the N+1 pattern of calling check_quota() and
        check_aggregate_quota() separately for the same volumes.
        """
        # 1. Batch fetch all volumes
        result = await self.db.execute(select(Volume).where(Volume.id.in_(volume_ids)))
        volumes = {str(v.id): v for v in result.scalars().all()}

        if missing := set(volume_ids) - set(volumes):
            return {
                "allowed": False,
                "reason": f"Volume(s) not found: {', '.join(sorted(missing))}",
            }

        # 2. Update sizes once per volume on the ORM objects
        # (caller is responsible for committing the session)
        for vid in volume_ids:
            volume = volumes[vid]
            size_bytes = await self.get_volume_size(volume.name)
            if size_bytes is not None and volume.size_bytes != size_bytes:
                volume.size_bytes = size_bytes

        # 3. Parse plan limit once
        plan_bytes = self._parse_memory(plan_disk_limit)

        # 4. Per-volume checks
        for vid in volume_ids:
            volume = volumes[vid]
            if volume.size_bytes and volume.size_bytes > plan_bytes:
                over_by = volume.size_bytes - plan_bytes
                return {
                    "allowed": False,
                    "reason": (
                        f"Volume '{volume.display_name or volume.name}' "
                        f"({self._human_size(volume.size_bytes)}) exceeds plan limit "
                        f"({plan_disk_limit}). Free up {self._human_size(over_by)} or upgrade your plan."
                    ),
                }

        # 5. Aggregate check
        total_bytes = sum(
            v.max_size_bytes if v.max_size_bytes is not None else (v.size_bytes or 0)
            for v in volumes.values()
        )

        if total_bytes > plan_bytes:
            over_by = total_bytes - plan_bytes
            return {
                "allowed": False,
                "reason": (
                    f"Total mounted volume capacity ({self._human_size(total_bytes)}) exceeds "
                    f"plan limit ({plan_disk_limit}). "
                    f"Free up {self._human_size(over_by)} or upgrade your plan."
                ),
                "total_size": total_bytes,
                "plan_limit": plan_bytes,
                "over_by": over_by,
            }

        return {"allowed": True}

    async def record_mount(self, volume_id: str):
        """Update last_mounted_at when a server mounts this volume"""
        volume = await self.get_volume(volume_id)
        if volume:
            volume.last_mounted_at = datetime.now(UTC).replace(tzinfo=None)

    async def mark_home_volume(self, volume_id: str):
        """Persistently mark a volume as having been used as a home directory.
        This flag survives server deletion so users are always warned before sharing."""
        volume = await self.get_volume(volume_id)
        if volume:
            if not volume.labels:
                volume.labels = {}
            if not volume.labels.get("was_home_volume"):
                volume.labels["was_home_volume"] = True
                await self.db.commit()

    def _parse_memory(self, memory_str: str) -> int:
        """Parse memory string to bytes"""
        memory_str = memory_str.lower()
        multipliers = {
            "b": 1,
            "k": 1024,
            "m": 1024**2,
            "g": 1024**3,
            "t": 1024**4,
        }

        for suffix, multiplier in multipliers.items():
            if memory_str.endswith(suffix):
                return int(float(memory_str[:-1]) * multiplier)

        return int(memory_str)

    def _human_size(self, size_bytes: int) -> str:
        """Convert bytes to human readable string"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"
