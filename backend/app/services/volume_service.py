"""
Volume management service for Docker volumes.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.docker.client import get_docker_client


class VolumeService:
    """Docker volume management"""
    
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
            
            result.append({
                "name": vol.get('Name'),
                "driver": vol.get('Driver'),
                "mountpoint": vol.get('Mountpoint'),
                "created_at": vol.get('CreatedAt'),
                "labels": labels,
                "size": None,  # Would need du command
            })
        
        return result
    
    async def get_volume(self, name: str) -> Optional[Dict[str, Any]]:
        """Get volume details"""
        docker = await get_docker_client()
        
        try:
            vol = await docker.client.volumes.get(name)
            info = await vol.show()
            
            labels = info.get('Labels', {}) or {}
            
            return {
                "name": info.get('Name'),
                "driver": info.get('Driver'),
                "mountpoint": info.get('Mountpoint'),
                "created_at": info.get('CreatedAt'),
                "labels": labels,
                "size": None,
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
    
    async def get_volume_size(self, name: str) -> Optional[int]:
        """Get volume size in bytes (requires du command)"""
        import subprocess
        try:
            result = subprocess.run(
                ['du', '-sb', f'/var/lib/docker/volumes/{name}/_data'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return int(result.stdout.split()[0])
        except Exception:
            pass
        return None
