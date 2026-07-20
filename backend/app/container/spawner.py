# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import aiodocker
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.config import settings
from app.container.client import ContainerClient, get_container_client
from app.core.logging import get_logger
from app.models.server import Server
from app.services.volume_service import make_docker_resource_name

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
        gpu: int = 0,
        env_vars: dict | None = None,
        volume_mounts: list[dict[str, Any]] | None = None,
        server_id: str | None = None,
    ) -> Server:
        """Spawn a new server container with persistent volume(s)

        Args:
            volume_mounts: List of dicts with keys: volume_id, mount_path, mode
        """
        if gpu > 0 and not settings.gpu_enabled:
            raise Exception(
                "GPU requested but GPU support is disabled. "
                "Set GPU_ENABLED=true on the backend to enable NVIDIA GPU support."
            )

        container_client = await self._get_container_client()

        # Use existing server ID or generate new one
        server_id = server_id or str(uuid.uuid4())
        container_name = make_docker_resource_name(
            prefix="nukelab-server",
            user_identifier=user_id,
            server_name=server_name,
            suffix=None,
            max_len=240,
        )

        # Short DNS-safe alias for the backend health probe. Container names can
        # exceed the 63-byte DNS label limit, so resolving the full name fails.
        health_alias = f"srv-{server_id[:8]}"

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

        # Mount the home directory at /home/{username}. The container runtime
        # creates the directory with ownership matching the parent (/home is
        # owned by the container UID in the image), so this works in both
        # hardened (non-root) and non-hardened modes.
        home_mount_path = f"/home/{username}"

        if volume_mounts:
            for mount in volume_mounts:
                vol_id = mount.get("volume_id")
                mount_path = mount.get("mount_path", "/data")
                mode = mount.get("mode", "read_write")

                # Home directory volumes should use /home/{username} so the
                # user sees their own name instead of the fixed system user.
                if (
                    mount_path == f"/home/{username}"
                    or mount_path == f"/home/{settings.container_user}"
                ):
                    mount_path = home_mount_path

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
                    volume_name = make_docker_resource_name(
                        prefix="nukelab-server",
                        user_identifier=user_id,
                        server_name=server_name,
                        suffix="data",
                    )

                await self._ensure_volume(volume_name)

                mount_mode = "ro" if mode == "read_only" else "rw"
                volumes[volume_name] = {"bind": mount_path, "mode": mount_mode}
        else:
            # Default single volume mounted at the user's home directory
            volume_name = make_docker_resource_name(
                prefix="nukelab-server",
                user_identifier=user_id,
                server_name=server_name,
                suffix="data",
            )
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
            # Redirect prefix without trailing slash to prefix/ so relative
            # asset URLs in the IDE index resolve under the strip prefix.
            # Use a relative Location header so the redirect stays on whatever
            # scheme/port the browser used. This avoids scheme downgrade issues
            # when Traefik sits behind an external SSL-terminating reverse proxy.
            f"traefik.http.routers.server-{server_id}.middlewares": f"server-{server_id}-slash@docker,server-{server_id}-strip@docker",
            f"traefik.http.middlewares.server-{server_id}-slash.redirectregex.regex": f"^https?://[^/]+({re.escape(route_prefix)})($|\\?.*$)",
            f"traefik.http.middlewares.server-{server_id}-slash.redirectregex.replacement": "$1/$2",
            f"traefik.http.middlewares.server-{server_id}-slash.redirectregex.permanent": "true",
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
            "NUKELAB_USERNAME": username,
            "NUKELAB_CONTAINER_USER": settings.container_user,
            "NUKELAB_SERVER_ID": server_id,
            "NUKELAB_SERVER_NAME": server_name,
            "HOME": home_mount_path,
            "USER": username,
            # Auth sidecar configuration
            "NUKELAB_AUTH_ENABLED": "true" if settings.server_auth_enabled else "false",
            "NUKELAB_AUTH_PUBLIC_KEY_PATH": "/etc/nukelab/auth/server-auth-public.pem",
            "NUKELAB_AUTH_ALGORITHM": settings.server_auth_key_algorithm,
            "NUKELAB_AUTH_SERVER_ID": server_id,
            # nss-wrapper: every process, including Theia terminals, should see
            # the human username in whoami/id/ls instead of the fixed nukelab
            # account. start.sh creates the passwd/group files and then sets
            # LD_PRELOAD itself, so we only pass the target paths here.
            "NSS_WRAPPER_PASSWD": "/tmp/nukelab-passwd",
            "NSS_WRAPPER_GROUP": "/tmp/nukelab-group",
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
                    # Fallback to base image if specific env not built
                    # (nukelab-base has nginx and stays running)
                    image = "nukelab-base:latest"

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
                command="/start.sh",
                env=environment,
                labels=labels,
                network=settings.docker_network,
                cpu_limit=cpu,
                memory_limit=memory,
                disk_limit=disk,
                gpu_limit=gpu,
                volumes=volumes,
                hostname="NukeLab",
                network_aliases=[health_alias],
            )

            # Start container
            await container_client.start_container(container.id)

            # Fix volume permissions inside the container.
            # Rootless Podman maps the host UID to container root, so named volumes
            # appear as root-owned. We make the mount point itself world-writable
            # (non-recursive) so the container user can read/write. This avoids:
            #   - Slow recursive chown on large volumes (50GB / 100k files)
            #   - Ownership fights when a volume is shared across multiple users
            #     (each container would otherwise chown to its own user)
            # The home directory also needs this in hardened mode because /start.sh
            # runs as the non-root container user and cannot chmod it itself.
            # This MUST run before waiting for the health endpoint: /start.sh
            # aborts if /home/{username} is not writable within ~10s, so nginx
            # never starts and the health probe never succeeds in time.
            mount_paths_to_fix = [home_mount_path]
            for mount in volume_mounts or []:
                mount_path = mount.get("mount_path", "/data")
                if mount_path and mount_path not in mount_paths_to_fix:
                    mount_paths_to_fix.append(mount_path)

            for mount_path in mount_paths_to_fix:
                try:
                    # Run as root so this works in hardened mode, where the
                    # container user is 65532 and cannot chmod a root-owned
                    # named volume that was initialized by an earlier run.
                    exec_instance = await container.exec(["chmod", "777", mount_path], user="root")
                    # Start the chmod in the background; /start.sh polls for up to
                    # ~10s, so the short delay below is enough for the runtime to
                    # schedule the exec while avoiding an unawaitable Stream object
                    # that aiodocker returns with detach=False.
                    await exec_instance.start(detach=True)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(
                        f"Could not fix permissions for {mount_path} in container "
                        f"{container_name}: {e}"
                    )

            # Wait for the container's /health endpoint to be reachable before
            # reporting the server as running. This avoids the UI showing "ready"
            # while the auth sidecar/ttyd/nginx are still starting inside the
            # container. Use the short DNS alias instead of the long container
            # name so the probe hostname stays within the DNS label limit.
            health_url = f"http://{health_alias}:8080/health"
            ready = await container_client.wait_for_container_ready(health_alias, health_url)
            if not ready:
                logger.warning(
                    "Container %s started but did not become ready within timeout; "
                    "continuing with status=running",
                    container_name,
                )

            # Determine primary volume_id from volume_mounts if provided
            primary_volume_id = None
            if volume_mounts:
                # Find primary mount or use first mount
                primary = next((m for m in volume_mounts if m.get("is_primary")), volume_mounts[0])
                primary_volume_id = primary.get("volume_id")

            # Create server record. Reflect the result of the readiness probe in
            # health_status so the API shows an accurate initial state instead of
            # the model default "unknown".
            server = Server(
                id=uuid.UUID(server_id),
                name=server_name,
                user_id=uuid.UUID(user_id),
                environment_id=uuid.UUID(environment_id) if environment_id else None,
                container_id=container.id,
                image=image,
                volume_id=uuid.UUID(primary_volume_id) if primary_volume_id else None,
                status="running",
                health_status="healthy" if ready else "unhealthy",
                allocated_cpu=cpu,
                allocated_memory=memory,
                allocated_disk=disk,
                allocated_gpu=gpu,
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
        """Get container status.

        Returns "unknown" when the runtime lookup fails. Errors are logged and
        emitted to Sentry/tracing/metrics so operators can distinguish a
        transient API failure from a genuinely missing container.
        """
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
        except aiodocker.DockerError as exc:
            reason = "not_found" if exc.status == 404 else "api_error"
            if reason == "not_found":
                logger.debug("Container %s not found during status lookup", container_id)
            else:
                logger.warning(
                    "Container runtime API error looking up status of %s: %s %s",
                    container_id,
                    exc.status,
                    exc.message,
                    exc_info=exc,
                )
                self._record_status_lookup_failure(container_id, exc, reason)
            return "unknown"
        except Exception as exc:
            logger.warning(
                "Unexpected error looking up status of container %s: %s",
                container_id,
                exc,
                exc_info=exc,
            )
            self._record_status_lookup_failure(container_id, exc, "error")
            return "unknown"

    def _record_status_lookup_failure(self, container_id: str, exc: Exception, reason: str) -> None:
        """Emit diagnostics for a container status lookup failure.

        Sends the exception to Sentry (when configured), records it on the
        current OpenTelemetry span, and increments a Prometheus counter that
        can drive Alertmanager notifications.
        """
        from app.core.prometheus_metrics import CONTAINER_STATUS_LOOKUP_FAILURES_TOTAL

        if settings.prometheus_enabled:
            CONTAINER_STATUS_LOOKUP_FAILURES_TOTAL.labels(reason=reason).inc()

        if settings.sentry_dsn:
            import sentry_sdk

            sentry_sdk.set_tag("container_id", container_id)
            sentry_sdk.set_tag("failure_reason", reason)
            sentry_sdk.capture_exception(exc)

        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("container.id", container_id)
            span.set_attribute("failure_reason", reason)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, "container status lookup failed"))


# Singleton instance
spawner = ServerSpawner()
