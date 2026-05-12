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
    
    async def _ensure_volume(self, volume_name: str):
        """Create a named Docker volume if it doesn't exist."""
        docker = await self._get_docker()
        try:
            await docker.client.volumes.get(volume_name)
        except Exception:
            await docker.client.volumes.create({
                "Name": volume_name,
                "Labels": {
                    "nukelab.managed": "true",
                }
            })
            print(f"Created volume: {volume_name}")

    async def spawn(
        self,
        user_id: str,
        username: str,
        server_name: str,
        environment: str = "dev",
        environment_id: Optional[str] = None,
        image: Optional[str] = None,
        cpu: float = 1.0,
        memory: str = "2g",
        disk: str = "10g",
        env_vars: Optional[dict] = None,
        volume_id: Optional[str] = None,
        volume_mode: Optional[str] = "read_write",
        server_id: Optional[str] = None,
    ) -> Server:
        """Spawn a new server container with persistent volume"""
        docker = await self._get_docker()
        
        # Use existing server ID or generate new one
        server_id = server_id or str(uuid.uuid4())
        container_name = f"nukelab-server-{username}-{server_name}"
        
        # Get volume name from database if volume_id provided
        volume_name = None
        if volume_id:
            from app.db.session import async_session
            from sqlalchemy import select
            from app.models.volume import Volume
            
            async with async_session() as db:
                result = await db.execute(select(Volume).where(Volume.id == volume_id))
                volume = result.scalar_one_or_none()
                if volume:
                    volume_name = volume.name
        
        # Create or reuse persistent volume
        if not volume_name:
            volume_name = f"nukelab-server-{username}-{server_name}-data"
        await self._ensure_volume(volume_name)
        
        # Determine image - use provided image or default to naming convention
        if not image:
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
        # Note: We do NOT pass JWT_SECRET to containers anymore.
        # Containers validate server access tokens using the public key only.
        environment = {
            "NUKELAB_USER_ID": user_id,
            "NUKELAB_USERNAME": username,
            "NUKELAB_SERVER_ID": server_id,
            # Auth sidecar configuration
            "NUKELAB_AUTH_ENABLED": "true" if settings.server_auth_enabled else "false",
            "NUKELAB_AUTH_PUBLIC_KEY_PATH": "/etc/nukelab/auth/server-auth-public.pem",
            "NUKELAB_AUTH_ALGORITHM": settings.server_auth_key_algorithm,
            "NUKELAB_AUTH_SERVER_ID": server_id,
            **(env_vars or {}),
        }
        
        # Mount volume to user's home directory with mode
        mount_mode = "ro" if volume_mode == "read_only" else "rw"
        volumes = {
            volume_name: {"bind": f"/home/{username}", "mode": mount_mode}
        }
        
        # Mount public key for auth validation if server auth is enabled
        if settings.server_auth_enabled and settings.server_auth_public_key_path:
            from app.services.server_auth_service import server_auth_service
            # Ensure keys exist (generates them if needed)
            server_auth_service._ensure_keys_exist()
            # Share the nukelab-secrets named volume with spawned containers.
            # The volume is mounted read-only at /etc/nukelab/auth.
            volumes["nukelab-secrets"] = {"bind": "/etc/nukelab/auth", "mode": "ro"}
        
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
            
            # Convert volumes dict to Docker bind mounts format
            # Handle both simple string format and dict format
            binds = []
            for host, container in volumes.items():
                if isinstance(container, dict):
                    bind_str = f"{host}:{container['bind']}:{container['mode']}"
                elif isinstance(container, str):
                    if ":" in container:
                        bind_str = f"{host}:{container}"
                    else:
                        bind_str = f"{host}:{container}"
                else:
                    bind_str = f"{host}:{container}"
                binds.append(bind_str)
            
            # Create container
            container = await docker.create_container(
                name=container_name,
                image=image,
                env=environment,
                labels=labels,
                network=settings.docker_network,
                cpu_limit=cpu,
                memory_limit=memory,
                disk_limit=disk,
                volumes={k: v if isinstance(v, str) else v['bind'] for k, v in volumes.items()},
            )
            
            # Start container
            await docker.start_container(container.id)
            
            # Create server record
            server = Server(
                id=uuid.UUID(server_id),
                name=server_name,
                user_id=uuid.UUID(user_id),
                environment_id=uuid.UUID(environment_id) if environment_id else None,
                container_id=container.id,
                image=image,
                volume_id=uuid.UUID(volume_id) if volume_id else None,
                volume_mode=volume_mode,
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
    
    async def start(self, container_id: str) -> bool:
        """Start a server container"""
        docker = await self._get_docker()
        try:
            await docker.start_container(container_id)
            return True
        except Exception as e:
            print(f"Error starting container: {e}")
            return False
    
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
