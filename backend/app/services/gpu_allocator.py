# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Exclusive GPU device allocator.

When ``settings.gpu_devices`` lists CDI device names, each unit of a plan's
gpu_limit exclusively reserves one physical device for a server for its
lifetime. Allocation rows are guarded by a UNIQUE(device) constraint so
concurrent spawns cannot reserve the same device twice. When the pool is
empty the allocator is disabled and GPU servers share
``settings.gpu_cdi_device`` (legacy behavior).
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server

logger = logging.getLogger(__name__)

# Rows younger than this are never reaped: a create-flow allocation commits
# before its Server row exists (the spawn takes seconds), so reconcile must
# not treat fresh rows as orphans and double-book the device.
_RECONCILE_GRACE = timedelta(minutes=15)


class GpuAllocatorService:
    """Exclusive GPU device pool business logic"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def pool(self) -> list[str]:
        """Configured CDI device names."""
        return settings.gpu_device_list

    def enabled(self) -> bool:
        """The allocator is active only when a device pool is configured."""
        return len(self.pool()) > 0

    async def allocated_devices(self) -> set[str]:
        """Devices currently reserved by any server."""
        result = await self.db.execute(select(GpuAllocation.device))
        return set(result.scalars().all())

    async def available(self) -> list[str]:
        """Pool devices not currently reserved, in pool order."""
        allocated = await self.allocated_devices()
        return [device for device in self.pool() if device not in allocated]

    async def allocate(self, server_id: str, count: int) -> list[str] | None:
        """Reserve the first ``count`` available devices for a server.

        Returns the allocated device list, [] for count <= 0 or when the
        allocator is disabled, or None when the pool is exhausted or a
        concurrent allocation won the race for the same device.
        """
        if count <= 0 or not self.enabled():
            return []

        devices = (await self.available())[:count]
        if len(devices) < count:
            logger.warning(
                "GPU pool exhausted: server %s requested %d device(s), only %d available",
                server_id,
                count,
                len(devices),
            )
            return None

        for device in devices:
            self.db.add(GpuAllocation(server_id=uuid.UUID(server_id), device=device))
        try:
            await self.db.commit()
        except IntegrityError:
            # Lost a concurrent race for the same device (UNIQUE guard).
            await self.db.rollback()
            logger.warning("GPU allocation race lost for server %s", server_id)
            return None

        logger.info("Allocated GPU devices %s to server %s", devices, server_id)
        return devices

    async def devices_for(self, server_id: str) -> list[str]:
        """Devices currently reserved for a server."""
        result = await self.db.execute(
            select(GpuAllocation.device).where(GpuAllocation.server_id == uuid.UUID(server_id))
        )
        return list(result.scalars().all())

    async def release(self, server_id: str) -> None:
        """Release all devices reserved for a server. Idempotent."""
        result = await self.db.execute(
            delete(GpuAllocation).where(GpuAllocation.server_id == uuid.UUID(server_id))
        )
        await self.db.commit()
        if result.rowcount:
            logger.info("Released %d GPU device(s) from server %s", result.rowcount, server_id)

    async def reconcile(self) -> None:
        """Drop allocation rows whose server no longer needs them.

        Safety net for crashed releases: removes rows older than
        _RECONCILE_GRACE whose server is gone, is not running/starting, or
        has allocated_gpu == 0. Fresh rows are kept so in-flight spawns are
        not reaped mid-create.
        """
        result = await self.db.execute(select(GpuAllocation))
        rows = result.scalars().all()
        if not rows:
            return

        cutoff = utc_now() - _RECONCILE_GRACE
        candidates = [row for row in rows if row.created_at and row.created_at < cutoff]
        if not candidates:
            return

        server_ids = {row.server_id for row in candidates}
        result = await self.db.execute(
            select(Server.id, Server.status, Server.allocated_gpu).where(Server.id.in_(server_ids))
        )
        servers = {row.id: row for row in result.all()}

        stale_ids = [
            row.id
            for row in candidates
            if row.server_id not in servers
            or servers[row.server_id].status not in ("running", "starting")
            or not servers[row.server_id].allocated_gpu
        ]
        if stale_ids:
            await self.db.execute(delete(GpuAllocation).where(GpuAllocation.id.in_(stale_ids)))
            await self.db.commit()
            logger.info("Reconciled %d stale GPU allocation(s)", len(stale_ids))
