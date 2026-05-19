"""
Volume management service with quota enforcement.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
import uuid

from app.models.volume import Volume
from app.models.server import Server
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.workspace_volume import WorkspaceVolume
from app.docker.client import get_docker_client
from app.config import settings


class VolumeService:
    """Docker volume management with database tracking"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_volume_storage_paths(self, name: str, mountpoint: Optional[str] = None) -> List[str]:
        """Build a list of possible volume storage paths to try."""
        import os

        paths = []

        if settings.volume_storage_path:
            paths.append(os.path.join(settings.volume_storage_path, name, "_data"))

        if mountpoint:
            paths.append(mountpoint)

        paths.append(f'/var/lib/docker/volumes/{name}/_data')
        paths.append(f'/var/lib/containers/storage/volumes/{name}/_data')
        paths.append(f'{os.path.expanduser("~")}/.local/share/containers/storage/volumes/{name}/_data')

        return paths

    async def create_volume(
        self,
        name: str,
        display_name: str,
        owner_id: str,
        max_size_bytes: Optional[int] = None,
        description: Optional[str] = None,
        visibility: str = "private"
    ) -> Volume:
        """Create a new volume record and Docker volume"""
        docker = await get_docker_client()

        # Create Docker volume
        await docker.client.volumes.create({
            "Name": name,
            "Labels": {
                "nukelab.managed": "true",
                "nukelab.user.id": owner_id,
            }
        })

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
        return volume

    async def get_volume(self, volume_id: str) -> Optional[Volume]:
        """Get volume by ID"""
        from sqlalchemy.orm import selectinload
        result = await self.db.execute(
            select(Volume)
            .options(selectinload(Volume.server_mounts))
            .options(selectinload(Volume.owner))
            .where(Volume.id == volume_id)
        )
        return result.scalar_one_or_none()

    async def get_volume_by_name(self, name: str) -> Optional[Volume]:
        """Get volume by Docker name"""
        result = await self.db.execute(
            select(Volume).where(Volume.name == name)
        )
        return result.scalar_one_or_none()

    async def list_volumes(
        self,
        user_id: str,
        include_workspace_volumes: bool = True
    ) -> List[Volume]:
        """List volumes accessible to user (owned or in workspaces)"""
        conditions = [Volume.owner_id == user_id]

        if include_workspace_volumes:
            # Also include volumes from workspaces the user is a member of
            workspace_volume_query = select(WorkspaceVolume.volume_id).join(
                SharedWorkspace, WorkspaceVolume.workspace_id == SharedWorkspace.id
            ).join(
                WorkspaceMember, WorkspaceMember.workspace_id == SharedWorkspace.id
            ).where(
                or_(
                    WorkspaceMember.user_id == user_id,
                    SharedWorkspace.owner_id == user_id
                )
            )

            result = await self.db.execute(workspace_volume_query)
            workspace_volume_ids = [row[0] for row in result.all()]

            if workspace_volume_ids:
                conditions.append(Volume.id.in_(workspace_volume_ids))

        # Also include public volumes
        conditions.append(Volume.visibility == "public")

        query = select(Volume).options(
            selectinload(Volume.workspace_associations),
            selectinload(Volume.server_mounts),
            selectinload(Volume.owner),
        ).where(or_(*conditions))
        result = await self.db.execute(query)
        return result.scalars().all()

    async def update_volume(
        self,
        volume_id: str,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        visibility: Optional[str] = None,
        max_size_bytes: Optional[int] = None,
        status: Optional[str] = None
    ) -> Optional[Volume]:
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

        if volume.server_count > 0:
            raise ValueError(f"Volume is still mounted by {volume.server_count} server(s)")

        # Delete Docker volume
        docker = await get_docker_client()
        try:
            vol = await docker.client.volumes.get(volume.name)
            await vol.delete()
        except Exception:
            pass

        # Delete database record
        await self.db.delete(volume)
        await self.db.commit()
        return True

    async def update_volume_size(self, volume_id: str) -> Optional[int]:
        """Update volume size from filesystem"""
        volume = await self.get_volume(volume_id)
        if not volume:
            return None

        size_bytes = await self.get_volume_size(volume.name)
        if size_bytes is not None:
            volume.size_bytes = size_bytes
            await self.db.commit()
        return size_bytes

    async def get_volume_size(self, name: str, mountpoint: Optional[str] = None) -> Optional[int]:
        """Get volume size in bytes (requires du command)"""
        import subprocess
        import os

        paths_to_try = self._get_volume_storage_paths(name, mountpoint)

        for path in paths_to_try:
            if os.path.exists(path):
                try:
                    result = subprocess.run(
                        ['du', '-sb', path],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        return int(result.stdout.split()[0])
                except Exception:
                    continue

        return None

    async def check_quota(
        self,
        volume_id: str,
        plan_disk_limit: str
    ) -> Dict[str, Any]:
        """Check if volume size is within plan limit"""
        volume = await self.get_volume(volume_id)
        if not volume:
            return {"allowed": False, "reason": "Volume not found"}

        # Update size before checking
        await self.update_volume_size(volume_id)
        await self.db.refresh(volume)

        # Parse plan limit
        plan_bytes = self._parse_memory(plan_disk_limit)

        if volume.size_bytes > plan_bytes:
            over_by = volume.size_bytes - plan_bytes
            return {
                "allowed": False,
                "reason": (
                    f"Volume size ({self._human_size(volume.size_bytes)}) exceeds "
                    f"plan limit ({plan_disk_limit}). "
                    f"Free up {self._human_size(over_by)} or upgrade your plan."
                ),
                "volume_size": volume.size_bytes,
                "plan_limit": plan_bytes,
                "over_by": over_by,
            }

        return {"allowed": True}

    async def increment_server_count(self, volume_id: str):
        """Increment server count when a server mounts this volume"""
        volume = await self.get_volume(volume_id)
        if volume:
            volume.server_count += 1
            volume.last_mounted_at = datetime.utcnow()
            await self.db.commit()

    async def decrement_server_count(self, volume_id: str):
        """Decrement server count when a server unmounts this volume"""
        volume = await self.get_volume(volume_id)
        if volume:
            volume.server_count = max(0, volume.server_count - 1)
            await self.db.commit()

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
            'b': 1,
            'k': 1024,
            'm': 1024**2,
            'g': 1024**3,
            't': 1024**4,
        }

        for suffix, multiplier in multipliers.items():
            if memory_str.endswith(suffix):
                return int(float(memory_str[:-1]) * multiplier)

        return int(memory_str)

    def _human_size(self, size_bytes: int) -> str:
        """Convert bytes to human readable string"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"
