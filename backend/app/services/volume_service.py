"""
Volume management service for Docker volumes.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.docker.client import get_docker_client
from app.config import settings


class VolumeService:
    """Docker volume management"""

    def _get_volume_storage_paths(self, name: str, mountpoint: Optional[str] = None) -> List[str]:
        """Build a list of possible volume storage paths to try."""
        import os

        paths = []

        # 1. Configured path from environment (most explicit)
        if settings.volume_storage_path:
            paths.append(os.path.join(settings.volume_storage_path, name, "_data"))

        # 2. Mountpoint from Docker/Podman API (if accessible)
        if mountpoint:
            paths.append(mountpoint)

        # 3. Common Docker path
        paths.append(f'/var/lib/docker/volumes/{name}/_data')

        # 4. Common Podman rootful path
        paths.append(f'/var/lib/containers/storage/volumes/{name}/_data')

        # 5. Common Podman rootless path
        paths.append(f'{os.path.expanduser("~")}/.local/share/containers/storage/volumes/{name}/_data')

        return paths

    async def list_volumes(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List volumes managed by NukeLab"""
        docker = await get_docker_client()

        volumes = await docker.client.volumes.list()
        result = []

        for vol in volumes.get('Volumes', []):
            labels = vol.get('Labels', {}) or {}

            # Only show nukelab-managed volumes
            if labels.get('nukelab.managed') != 'true':
                continue

            # Filter by user if specified
            if user_id and labels.get('nukelab.user.id') != user_id:
                continue

            # Try to get size
            size_bytes = await self.get_volume_size(vol.get('Name'), vol.get('Mountpoint'))

            result.append({
                "name": vol.get('Name'),
                "driver": vol.get('Driver'),
                "mountpoint": vol.get('Mountpoint'),
                "created_at": vol.get('CreatedAt'),
                "labels": labels,
                "size": size_bytes,
            })

        return result

    async def get_volume(self, name: str) -> Optional[Dict[str, Any]]:
        """Get volume details"""
        docker = await get_docker_client()

        try:
            vol = await docker.client.volumes.get(name)
            info = await vol.show()

            labels = info.get('Labels', {}) or {}

            # Get volume size
            size_bytes = await self.get_volume_size(name, info.get('Mountpoint'))

            return {
                "name": info.get('Name'),
                "driver": info.get('Driver'),
                "mountpoint": info.get('Mountpoint'),
                "created_at": info.get('CreatedAt'),
                "labels": labels,
                "size": size_bytes,
            }
        except Exception:
            return None

    async def delete_volume(self, name: str) -> bool:
        """Delete a volume"""
        docker = await get_docker_client()

        try:
            vol = await docker.client.volumes.get(name)
            await vol.delete()
            return True
        except Exception:
            return False

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
