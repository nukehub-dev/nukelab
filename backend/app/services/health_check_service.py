# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import contextlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.factory import get_fresh_driver
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.health_check import HealthCheck
from app.models.server import Server
from app.services.admission_service import acquire_admission_lock
from app.services.server_lifecycle_service import ServerLifecycleService
from app.services.server_operation_service import get_active

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

        server_ids = [server.id for server in servers if server.container_id]
        any_checked = False
        for server_id in server_ids:
            try:
                server = await self.db.get(Server, server_id, populate_existing=True)
                if server is None or server.status != "running" or not server.container_id:
                    continue
                await self._check_container(server)
                any_checked = True
            except Exception:
                logger.exception("Health check failed for %s", server_id)

        if any_checked:
            await _broadcast_health_update()

    async def _clear_read_transaction(self):
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Health observation requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def _sample_current(self, server_id, container_id, expected_version):
        """Caller owns the transaction; observations never adopt another executor."""
        await acquire_admission_lock(self.db)
        current = await self.db.scalar(
            select(Server)
            .where(Server.id == server_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            current is None
            or current.status != "running"
            or current.container_id != container_id
            or current.updated_at != expected_version
            or await get_active(self.db, server_id) is not None
        ):
            return None
        return current

    async def _check_container(self, server: Server):
        """Fence a runtime probe to the sampled container and server version."""
        server_id, container_id, version = server.id, server.container_id, server.updated_at
        await self._clear_read_transaction()
        container_client = None
        try:
            if not container_id:
                raise ValueError("Server container missing")
            container_client = await get_fresh_driver()
            info = await container_client.get_container_info(container_id)
            state = info.get("State", {})
            health = state.get("Health", {})
            health_status = health.get("Status", "unknown")
            if health_status == "unknown":
                health_status = "healthy" if state.get("Running") else "unhealthy"
            log = health.get("Log", [])
            last_check = log[-1] if log else {}
            async with self.db.begin():
                current = await self._sample_current(server_id, container_id, version)
                if current is None:
                    return
                health_check = HealthCheck(
                    server_id=server_id,
                    container_id=container_id,
                    status=health_status,
                    exit_code=last_check.get("ExitCode"),
                    output=(last_check.get("Output", "") or "")[:1000],
                )
                current.health_status = health_status
                current.last_health_check = utc_now()
                if health_status == "unhealthy":
                    last = await self.db.scalar(
                        select(HealthCheck)
                        .where(
                            HealthCheck.server_id == server_id,
                            HealthCheck.container_id == container_id,
                        )
                        .order_by(HealthCheck.checked_at.desc())
                        .limit(1)
                    )
                    health_check.consecutive_failures = (
                        (last.consecutive_failures or 0) + 1
                        if last and last.status == "unhealthy"
                        else 1
                    )
                else:
                    health_check.last_success_at = utc_now()
                self.db.add(health_check)
                await self.db.flush()
                restart = health_check.consecutive_failures >= 3
                restart_version = current.updated_at
            # The global lock and read transaction end before any restart I/O.
            if restart:
                await self._auto_restart(
                    current, expected_version=restart_version, expected_container_id=container_id
                )
        except Exception as error:
            await self.db.rollback()
            async with self.db.begin():
                current = await self._sample_current(server_id, container_id, version)
                if current is None:
                    return
                self.db.add(
                    HealthCheck(
                        server_id=server_id,
                        container_id=container_id or "",
                        status="unknown",
                        output=str(error)[:1000],
                    )
                )
                current.health_status = "unknown"
                current.last_health_check = utc_now()
        finally:
            if container_client is not None:
                with contextlib.suppress(Exception):
                    await container_client.close()

    async def _auto_restart(
        self, server: Server, *, expected_version=None, expected_container_id=None
    ):
        """Reserve a restart only while the sampled runtime remains authoritative."""
        if not settings.server_auto_restart_enabled:
            return
        identity = inspect(server).identity
        server_id = identity[0] if identity else server.id
        await self._clear_read_transaction()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            current = await self.db.get(
                Server, server_id, populate_existing=True, with_for_update=True
            )
            if current is None or current.status != "running":
                return
            if (
                (expected_version is not None and current.updated_at != expected_version)
                or (
                    expected_container_id is not None
                    and current.container_id != expected_container_id
                )
                or await get_active(self.db, server_id) is not None
            ):
                return
            owner_id, server_name, container_id, version = (
                current.user_id,
                current.name,
                current.container_id,
                current.updated_at,
            )
            if not container_id:
                logger.warning("Server %s: no container_id, cannot auto-restart", server_id)
                return
            window_start = utc_now() - timedelta(seconds=settings.server_auto_restart_window)
            restart_count = (
                await self.db.scalar(
                    select(func.count())
                    .select_from(HealthCheck)
                    .where(
                        HealthCheck.server_id == server_id,
                        HealthCheck.checked_at >= window_start,
                        HealthCheck.status == "restarting",
                    )
                )
                or 0
            )
            if restart_count >= settings.server_auto_restart_max_attempts:
                logger.warning("Server %s: auto-restart rate limit exceeded", server_id)
                return
        from app.services.notification_service import NotificationService

        runtime = None
        try:
            runtime = await get_fresh_driver()
            restarted = await ServerLifecycleService(self.db, runtime).restart(
                server_id, owner_id=owner_id, expected_version=version
            )
            restarted_container_id = restarted.container_id or ""
            self.db.add(
                HealthCheck(
                    server_id=server_id,
                    container_id=restarted_container_id,
                    status="restarting",
                    output="Auto-restarted after consecutive health check failures",
                    last_success_at=utc_now(),
                )
            )
            await self.db.commit()
            await NotificationService(self.db).server_restarted(
                user_id=owner_id, server_name=server_name, action_url=f"/servers/{server_id}"
            )
            logger.info("Server %s: auto-restart successful", server_id)
        except Exception as error:
            await self.db.rollback()
            if getattr(error, "code", None) in ("configuration_changed", "launch_in_progress"):
                return
            logger.exception("Server %s: auto-restart failed", server_id)
            async with self.db.begin():
                current = await self._sample_current(server_id, container_id, version)
                if current is None:
                    return
                self.db.add(
                    HealthCheck(
                        server_id=server_id,
                        container_id=container_id,
                        status="restart_failed",
                        output=f"Auto-restart failed: {getattr(error, 'code', 'restart_failed')}",
                    )
                )
        finally:
            if runtime is not None:
                with contextlib.suppress(Exception):
                    await runtime.close()
