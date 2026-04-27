import asyncio
from typing import Optional
import aiodocker
from app.config import settings

class DockerClient:
    def __init__(self):
        self.client: Optional[aiodocker.Docker] = None
    
    async def connect(self):
        """Connect to Docker/Podman socket"""
        self.client = aiodocker.Docker(url=f"unix://{settings.docker_socket}")
    
    async def close(self):
        """Close connection"""
        if self.client:
            await self.client.close()
    
    async def pull_image(self, image: str):
        """Pull Docker image"""
        await self.client.images.pull(image)
    
    async def create_container(
        self,
        name: str,
        image: str,
        command: Optional[str] = None,
        ports: Optional[dict] = None,
        volumes: Optional[dict] = None,
        env: Optional[dict] = None,
        labels: Optional[dict] = None,
        network: Optional[str] = None,
        cpu_limit: Optional[float] = None,
        memory_limit: Optional[str] = None,
    ):
        """Create a new container"""
        config = {
            "Image": image,
            "Cmd": command.split() if command else None,
            "Labels": labels or {},
            "Env": [f"{k}={v}" for k, v in (env or {}).items()],
            "HostConfig": {
                "NetworkMode": network or settings.docker_network,
                "PublishAllPorts": False,
            }
        }
        
        if ports:
            config["ExposedPorts"] = {f"{k}/tcp": {} for k in ports.keys()}
            config["HostConfig"]["PortBindings"] = {
                f"{k}/tcp": [{"HostPort": str(v)}] for k, v in ports.items()
            }
        
        if volumes:
            config["HostConfig"]["Binds"] = [
                f"{host}:{container}" for host, container in volumes.items()
            ]
        
        if cpu_limit:
            config["HostConfig"]["NanoCpus"] = int(cpu_limit * 1e9)
        
        if memory_limit:
            # Parse memory limit (e.g., "512m", "1g")
            memory_bytes = self._parse_memory(memory_limit)
            config["HostConfig"]["Memory"] = memory_bytes
        
        container = await self.client.containers.create(config, name=name)
        return container
    
    async def start_container(self, container_id: str):
        """Start a container"""
        container = await self.client.containers.get(container_id)
        await container.start()
    
    async def stop_container(self, container_id: str, timeout: int = 30):
        """Stop a container"""
        try:
            container = await self.client.containers.get(container_id)
            await container.stop(timeout=timeout)
        except Exception:
            pass
    
    async def delete_container(self, container_id: str, force: bool = True):
        """Delete a container"""
        try:
            container = await self.client.containers.get(container_id)
            await container.delete(force=force)
        except Exception:
            pass
    
    async def get_container_info(self, container_id: str):
        """Get container info"""
        container = await self.client.containers.get(container_id)
        return await container.show()
    
    async def list_containers(self, filters: Optional[dict] = None):
        """List containers"""
        return await self.client.containers.list(filters=filters)
    
    def _parse_memory(self, memory_str: str) -> int:
        """Parse memory string to bytes"""
        memory_str = memory_str.lower()
        multipliers = {
            'b': 1,
            'k': 1024,
            'm': 1024**2,
            'g': 1024**3,
        }
        
        for suffix, multiplier in multipliers.items():
            if memory_str.endswith(suffix):
                return int(float(memory_str[:-1]) * multiplier)
        
        return int(memory_str)

# Singleton instance
docker_client = DockerClient()

async def get_docker_client():
    """Get initialized Docker client"""
    if not docker_client.client:
        await docker_client.connect()
    return docker_client
