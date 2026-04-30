import uuid
from datetime import datetime
from typing import Optional
from app.docker.client import DockerClient, get_docker_client
from app.models.server import Server
from app.config import settings

class ServerSpawner:
    def __init__(self):
        self.docker: Optional[DockerClient] = None
    
    async def _get_docker(self):
        if not self.docker:
            self.docker = await get_docker_client()
        return self.docker
    
    async def spawn(
        self,
        user_id: str,
        username: str,
        server_name: str,
        environment: str = "dev",
        cpu: float = 1.0,
        memory: str = "2g",
        disk: str = "10g",
        env_vars: Optional[dict] = None,
    ) -> Server:
        """Spawn a new server container"""
        docker = await self._get_docker()
        
        # Generate unique IDs
        server_id = str(uuid.uuid4())
        container_name = f"nukelab-server-{username}-{server_name}"
        
        # Determine image
        image = f"nukelab-environments-{environment}:latest"
        
        # Traefik labels for dynamic routing
        route_prefix = f"/user/{username}/{server_name}"
        public_url = getattr(settings, 'public_url', 'http://localhost:8080').rstrip('/')
        labels = {
            "traefik.enable": "true",
            f"traefik.http.routers.server-{server_id}.rule": f"PathPrefix(`{route_prefix}`)",
            f"traefik.http.routers.server-{server_id}.service": f"server-{server_id}",
            f"traefik.http.routers.server-{server_id}.middlewares": f"server-{server_id}-strip@docker",
            f"traefik.http.services.server-{server_id}.loadbalancer.server.port": "80",
            f"traefik.http.middlewares.server-{server_id}-strip.stripprefix.prefixes": route_prefix,
            "nukelab.server.id": server_id,
            "nukelab.user.id": user_id,
            "nukelab.user.name": username,
        }
        
        # Environment variables
        environment = {
            "NUKELAB_USER_ID": user_id,
            "NUKELAB_USERNAME": username,
            "NUKELAB_SERVER_ID": server_id,
            "JWT_SECRET": settings.jwt_secret,
            **(env_vars or {}),
        }
        
        try:
            # Check if image exists locally first, then try to pull
            try:
                # Try to inspect image locally
                await docker.client.images.get(image)
            except Exception:
                # Try to pull if not found locally
                try:
                    await docker.pull_image(image)
                except Exception:
                    # Fallback to dev image if specific env not built
                    # (nukelab-dev has nginx and stays running)
                    image = "nukelab-dev:latest"
            
            # Create container
            container = await docker.create_container(
                name=container_name,
                image=image,
                env=environment,
                labels=labels,
                network=settings.docker_network,
                cpu_limit=cpu,
                memory_limit=memory,
            )
            
            # Start container
            await docker.start_container(container.id)
            
            # Create server record
            server = Server(
                id=uuid.UUID(server_id),
                name=server_name,
                user_id=uuid.UUID(user_id),
                container_id=container.id,
                image=image,
                status="running",
                allocated_cpu=cpu,
                allocated_memory=memory,
                allocated_disk=disk,
                external_url=f"{public_url}{route_prefix}",
                started_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
            )
            
            return server
            
        except Exception as e:
            # Cleanup on failure
            try:
                container = await docker.client.containers.get(container_name)
                await container.delete(force=True)
            except:
                pass
            raise Exception(f"Failed to spawn server: {str(e)}")
    
    async def stop(self, container_id: str) -> bool:
        """Stop a server container"""
        docker = await self._get_docker()
        try:
            await docker.stop_container(container_id)
            return True
        except Exception as e:
            print(f"Error stopping container: {e}")
            return False
    
    async def delete(self, container_id: str) -> bool:
        """Delete a server container"""
        docker = await self._get_docker()
        try:
            await docker.delete_container(container_id, force=True)
            return True
        except Exception as e:
            print(f"Error deleting container: {e}")
            return False
    
    async def get_status(self, container_id: str) -> str:
        """Get container status"""
        docker = await self._get_docker()
        try:
            info = await docker.get_container_info(container_id)
            state = info.get("State", {})
            if state.get("Running"):
                return "running"
            elif state.get("Paused"):
                return "paused"
            else:
                return "stopped"
        except Exception:
            return "unknown"

# Singleton instance
spawner = ServerSpawner()
