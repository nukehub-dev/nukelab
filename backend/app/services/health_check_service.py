# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import contextlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.client import get_fresh_container_client
from app.core.logging import get_logger
from app.models.health_check import HealthCheck
from app.models.server import Server

logger = get_logger(__name__)


async def _broadcast_health_update():
    """Notify admin WebSocket clients that health data has changed."""
    try:
        import redis.asyncio as redis_client

        r = redis_client.from_url(settings.redis_url)
        await r.publish(
            "metrics:system",
            json.dumps(
                {
                    "event": "health:system",
                    "data": {"refreshed_at": datetime.now(UTC).replace(tzinfo=None).isoformat()},
                }
            ),
        )
        await r.aclose()
    except Exception:
        pass


class HealthCheckService:
    """Perform and track container health checks"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_all_containers(self):
        """Check health of all running containers"""
        result = await self.db.execute(select(Server).where(Server.status == "running"))
        servers = result.scalars().all()

        any_checked = False
        for server in servers:
            if not server.container_id:
                continue

            try:
                await self._check_container(server)
                any_checked = True
            except Exception:
                logger.exception("Health check failed for %s", server.id)

        if any_checked:
            await _broadcast_health_update()

    async def _check_container(self, server: Server):
        """Check health of a single container"""
        container_client = None
        try:
            container_client = await get_fresh_container_client()
            container = await container_client.client.containers.get(server.container_id)
            info = await container.show()
            state = info.get("State", {})

            health = state.get("Health", {})
            health_status = health.get("Status", "unknown")

            if health_status == "unknown":
                health_status = "healthy" if state.get("Running") else "unhealthy"

            log = health.get("Log", [])
            last_check = log[-1] if log else {}

            health_check = HealthCheck(
                server_id=server.id,
                container_id=server.container_id,
                status=health_status,
                exit_code=last_check.get("ExitCode"),
                output=(last_check.get("Output", "") or "")[:1000],
            )

            # Track consecutive failures
            if health_status == "unhealthy":
                last_check_result = await self.db.execute(
                    select(HealthCheck)
                    .where(HealthCheck.server_id == server.id)
                    .order_by(HealthCheck.checked_at.desc())
                    .limit(1)
                )
                last = last_check_result.scalar_one_or_none()
                if last and last.status == "unhealthy":
                    health_check.consecutive_failures = last.consecutive_failures + 1
                else:
                    health_check.consecutive_failures = 1
            else:
                health_check.last_success_at = datetime.now(UTC).replace(tzinfo=None)

            self.db.add(health_check)
            await self.db.commit()

            # Auto-restart if too many failures
            if health_check.consecutive_failures >= 3:
                await self._auto_restart(server)

        except Exception as e:
            health_check = HealthCheck(
                server_id=server.id,
                container_id=server.container_id or "",
                status="unknown",
                output=str(e)[:1000],
            )
            self.db.add(health_check)
            await self.db.commit()
        finally:
            if container_client and container_client.client:
                with contextlib.suppress(Exception):
                    await container_client.client.close()

    async def _auto_restart(self, server: Server):
        """Auto-restart a failed container with rate limiting."""
        if not settings.server_auto_restart_enabled:
            return

        # Rate limit: count recent restart attempts within the window
        window_start = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            seconds=settings.server_auto_restart_window
        )
        recent_restarts = await self.db.execute(
            select(func.count())
            .select_from(HealthCheck)
            .where(
                HealthCheck.server_id == server.id,
                HealthCheck.checked_at >= window_start,
                HealthCheck.status == "restarting",
            )
        )
        restart_count = recent_restarts.scalar() or 0

        if restart_count >= settings.server_auto_restart_max_attempts:
            logger.warning(
                "Server %s: auto-restart rate limit exceeded (%s attempts in %ss)",
                server.id,
                restart_count,
                settings.server_auto_restart_window,
            )
            return

        logger.info("Auto-restarting server %s after consecutive failures", server.id)

        from app.container.spawner import spawner
        from app.services.notification_service import NotificationService

        try:
            if server.container_id:
                await spawner.stop(server.container_id)
                await spawner.start(server.container_id)
            else:
                # No container to restart — mark as needing manual attention
                logger.warning("Server %s: no container_id, cannot auto-restart", server.id)
                return

            # Log the restart attempt
            restart_log = HealthCheck(
                server_id=server.id,
                container_id=server.container_id,
                status="restarting",
                output="Auto-restarted after consecutive health check failures",
                last_success_at=datetime.now(UTC).replace(tzinfo=None),
            )
            self.db.add(restart_log)
            await self.db.commit()

            # Notify user
            notif_service = NotificationService(self.db)
            await notif_service.server_restarted(
                user_id=server.user_id, server_name=server.name, action_url=f"/servers/{server.id}"
            )

            logger.info("Server %s: auto-restart successful", server.id)

        except Exception as e:
            logger.exception("Server %s: auto-restart failed", server.id)
            # Log the failure
            fail_log = HealthCheck(
                server_id=server.id,
                container_id=server.container_id or "",
                status="restart_failed",
                output=f"Auto-restart failed: {str(e)[:500]}",
            )
            self.db.add(fail_log)
            await self.db.commit()
