import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.container.client import ContainerClient, get_container_client
from app.core.logging import get_logger
from app.models.server import Server

logger = get_logger(__name__)


class ServerSpawner:
    def __init__(self):
        self.container_client: ContainerClient | None = None

    async def _get_container_client(self):
        if not self.container_client:
            self.container_client = await get_container_client()
        return self.container_client

    async def _ensure_volume(self, volume_name: str):
        """Create a named Docker volume if it doesn't exist."""
        container_client = await self._get_container_client()
        try:
            await container_client.client.volumes.get(volume_name)
        except Exception:
            await container_client.client.volumes.create(
                {
                    "Name": volume_name,
                    "Labels": {
                        "nukelab.managed": "true",
                    },
                }
            )
            logger.info("Created volume: %s", volume_name)

    async def spawn(
        self,
        user_id: str,
        username: str,
        server_name: str,
        environment: str = "dev",
        environment_id: str | None = None,
        image: str | None = None,
        cpu: float = 1.0,
        memory: str = "2g",
        disk: str = "10g",
        env_vars: dict | None = None,
        volume_mounts: list[dict[str, Any]] | None = None,
        server_id: str | None = None,
    ) -> Server:
        """Spawn a new server container with persistent volume(s)

        Args:
            volume_mounts: List of dicts with keys: volume_id, mount_path, mode
        """
        container_client = await self._get_container_client()

        # Use existing server ID or generate new one
        server_id = server_id or str(uuid.uuid4())
        container_name = f"nukelab-server-{username}-{server_name}"

        # If a container with this name already exists (e.g., an orphaned container
        # from a previous failed stop/start/restart), remove it before attempting to
        # create a new one. This keeps the database and runtime state consistent and
        # prevents DockerError(500, "name already in use").
        try:
            existing = await container_client.client.containers.get(container_name)
            logger.warning("Found existing container %s before spawn; removing it", container_name)
            await existing.delete(force=True)
            # Wait briefly for container to release the name.
            await asyncio.sleep(0.5)
        except Exception:
            pass

        # Build Docker volumes dict from multiple mounts
        volumes = {}

        # Default username/path used for the home directory; overridden in
        # hardened mode to match the fixed container user.
        container_username = username
        home_mount_path = f"/home/{username}"

        if volume_mounts:
            for mount in volume_mounts:
                vol_id = mount.get("volume_id")
                mount_path = mount.get("mount_path", "/data")
                mode = mount.get("mode", "read_write")

                # In hardened mode the container runs as a fixed non-root user.
                # Remount any /home/{username} path to the container user's home
                # so the named volume inherits the correct ownership from the image.
                if settings.container_hardening_enabled and mount_path == f"/home/{username}":
                    container_username = settings.container_user
                    mount_path = f"/home/{settings.container_user}"

                # Get volume name from database
                if vol_id:
                    from sqlalchemy import select

                    from app.db.session import async_session
                    from app.models.volume import Volume

                    async with async_session() as db:
                        result = await db.execute(select(Volume).where(Volume.id == vol_id))
                        volume = result.scalar_one_or_none()
                        if volume:
                            volume_name = volume.name
                        else:
                            # Fallback: generate name from id
                            volume_name = f"nukelab-vol-{vol_id[:8]}"
                else:
                    volume_name = f"nukelab-server-{username}-{server_name}-data"

                await self._ensure_volume(volume_name)

                mount_mode = "ro" if mode == "read_only" else "rw"
                volumes[volume_name] = {"bind": mount_path, "mode": mount_mode}
        else:
            # In hardened mode the container runs as a fixed non-root user
            # (nukelab) and the home volume must be mounted at that user's home
            # directory so the named volume inherits the correct ownership from
            # the image.
            if settings.container_hardening_enabled:
                container_username = settings.container_user
                home_mount_path = f"/home/{settings.container_user}"

            # Default single volume for backward compatibility
            volume_name = f"nukelab-server-{username}-{server_name}-data"
            await self._ensure_volume(volume_name)
            volumes[volume_name] = {"bind": home_mount_path, "mode": "rw"}

        # Determine image - use provided image or default to naming convention
        if not image:
            image = f"nukelab-environments-{environment}:latest"

        # Traefik labels for dynamic routing
        route_prefix = f"/user/{username}/{server_name}"
        public_url = getattr(settings, "public_url", "http://localhost:8080").rstrip("/")
        labels = {
            "traefik.enable": "true",
            f"traefik.http.routers.server-{server_id}.rule": f"PathPrefix(`{route_prefix}`)",
            f"traefik.http.routers.server-{server_id}.service": f"server-{server_id}",
            f"traefik.http.routers.server-{server_id}.middlewares": f"server-{server_id}-strip@docker",
            f"traefik.http.middlewares.server-{server_id}-strip.stripprefix.prefixes": route_prefix,
            "nukelab.server.id": server_id,
            "nukelab.user.id": user_id,
            "nukelab.user.name": username,
        }

        # Internal port exposed by hardened dev/nginx images (unprivileged 8080).
        # Images that already run their service on a different port must be matched
        # by an environment-specific port override in future work.
        labels[f"traefik.http.services.server-{server_id}.loadbalancer.server.port"] = "8080"

        # Environment variables
        # Note: We do NOT pass JWT_SECRET to containers anymore.
        # Containers validate server access tokens using the public key only.
        environment = {
            "NUKELAB_USER_ID": user_id,
            "NUKELAB_USERNAME": container_username,
            "NUKELAB_SERVER_ID": server_id,
            "NUKELAB_SERVER_NAME": server_name,
            # Auth sidecar configuration
            "NUKELAB_AUTH_ENABLED": "true" if settings.server_auth_enabled else "false",
            "NUKELAB_AUTH_PUBLIC_KEY_PATH": "/etc/nukelab/auth/server-auth-public.pem",
            "NUKELAB_AUTH_ALGORITHM": settings.server_auth_key_algorithm,
            "NUKELAB_AUTH_SERVER_ID": server_id,
            **(env_vars or {}),
        }

        # Mount public key for auth validation if server auth is enabled
        if settings.server_auth_enabled and settings.server_auth_public_key_path:
            from app.services.server_auth_service import server_auth_service

            # Ensure keys exist (generates them if needed)
            server_auth_service._ensure_keys_exist()
            # Mount the same server-secrets named volume the backend uses so the
            # auth sidecar validates tokens against the current public key. The
            # volume is mounted read-only at /etc/nukelab/auth.
            volumes["nukelab-server-secrets"] = {"bind": "/etc/nukelab/auth", "mode": "ro"}

        try:
            # Check if image exists locally first, then try to pull
            try:
                # Try to inspect image locally
                await container_client.client.images.get(image)
            except Exception:
                # Try to pull if not found locally
                try:
                    await container_client.pull_image(image)
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
                    bind_str = f"{host}:{container}" if ":" in container else f"{host}:{container}"
                else:
                    bind_str = f"{host}:{container}"
                binds.append(bind_str)

            # Create container
            container = await container_client.create_container(
                name=container_name,
                image=image,
                env=environment,
                labels=labels,
                network=settings.docker_network,
                cpu_limit=cpu,
                memory_limit=memory,
                disk_limit=disk,
                volumes=volumes,
            )

            # Start container
            await container_client.start_container(container.id)

            # Wait for the container's /health endpoint to be reachable before
            # reporting the server as running. This avoids the UI showing "ready"
            # while the auth sidecar/ttyd/nginx are still starting inside the
            # container.
            health_url = f"http://{container_name}:8080/health"
            ready = await container_client.wait_for_container_ready(container_name, health_url)
            if not ready:
                logger.warning(
                    "Container %s started but did not become ready within timeout; "
                    "continuing with status=running",
                    container_name,
                )

            # Fix volume permissions inside the container.
            # Rootless Podman maps the host UID to container root, so named volumes
            # appear as root-owned. We make the mount point itself world-writable
            # (non-recursive) so the container user can read/write. This avoids:
            #   - Slow recursive chown on large volumes (50GB / 100k files)
            #   - Ownership fights when a volume is shared across multiple users
            #     (each container would otherwise chown to its own user)
            # /home/{username} is already handled by the container's /start.sh.
            for mount in volume_mounts or []:
                mount_path = mount.get("mount_path", "/data")
                # Skip the home directory — /start.sh manages that
                if mount_path == f"/home/{username}":
                    continue
                try:
                    exec_instance = await container.exec(["chmod", "777", mount_path])
                    await exec_instance.start(detach=True)
                    await asyncio.sleep(0.2)
                except Exception as e:
                    logger.warning(
                        f"Could not fix permissions for {mount_path} in container "
                        f"{container_name}: {e}"
                    )

            # Determine primary volume_id from volume_mounts if provided
            primary_volume_id = None
            if volume_mounts:
                # Find primary mount or use first mount
                primary = next((m for m in volume_mounts if m.get("is_primary")), volume_mounts[0])
                primary_volume_id = primary.get("volume_id")

            # Create server record
            server = Server(
                id=uuid.UUID(server_id),
                name=server_name,
                user_id=uuid.UUID(user_id),
                environment_id=uuid.UUID(environment_id) if environment_id else None,
                container_id=container.id,
                image=image,
                volume_id=uuid.UUID(primary_volume_id) if primary_volume_id else None,
                status="running",
                allocated_cpu=cpu,
                allocated_memory=memory,
                allocated_disk=disk,
                external_url=f"{public_url}{route_prefix}",
                started_at=datetime.now(UTC).replace(tzinfo=None),
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )

            return server

        except Exception as e:
            # Cleanup on failure
            try:
                container = await container_client.client.containers.get(container_name)
                await container.delete(force=True)
            except Exception:
                pass
            raise Exception(f"Failed to spawn server: {str(e)}")

    async def start(self, container_id: str) -> bool:
        """Start a server container"""
        container_client = await self._get_container_client()
        try:
            await container_client.start_container(container_id)
            return True
        except Exception:
            logger.exception("Error starting container")
            return False

    async def stop(self, container_id: str) -> bool:
        """Stop a server container"""
        container_client = await self._get_container_client()
        try:
            await container_client.stop_container(container_id)
            return True
        except Exception:
            logger.exception("Error stopping container")
            return False

    async def delete(self, container_id: str) -> bool:
        """Delete a server container"""
        container_client = await self._get_container_client()
        try:
            await container_client.delete_container(container_id, force=True)
            return True
        except Exception:
            logger.exception("Error deleting container")
            return False

    async def get_status(self, container_id: str) -> str:
        """Get container status"""
        container_client = await self._get_container_client()
        try:
            info = await container_client.get_container_info(container_id)
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
