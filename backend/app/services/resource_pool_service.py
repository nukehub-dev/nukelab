# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Global resource pool service for tracking platform-wide resource availability.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue


class ResourcePoolService:
    """Track configured allocatable budgets, including starting reservations."""

    # Platform-wide resource limits
    TOTAL_CPU = 34.0
    TOTAL_MEMORY_MB = 68 * 1024  # 68GB in MB
    TOTAL_DISK_MB = 2000 * 1024  # 2TB in MB (generous)

    def __init__(self, db: AsyncSession):
        self.db = db
        self.TOTAL_CPU = settings.resource_pool_cpu
        self.TOTAL_MEMORY_MB = settings.resource_pool_memory_mib
        self.TOTAL_DISK_MB = settings.resource_pool_disk_mib

    async def get_available_resources(self) -> dict[str, Any]:
        """Get currently available resources"""
        allocated = await self._get_allocated_resources()

        return {
            "cpu": {
                "total": self.TOTAL_CPU,
                "allocated": allocated["cpu"],
                "available": max(0, self.TOTAL_CPU - allocated["cpu"]),
            },
            "memory_mb": {
                "total": self.TOTAL_MEMORY_MB,
                "allocated": allocated["memory_mb"],
                "available": max(0, self.TOTAL_MEMORY_MB - allocated["memory_mb"]),
            },
            "disk_mb": {
                "total": self.TOTAL_DISK_MB,
                "allocated": allocated["disk_mb"],
                "available": max(0, self.TOTAL_DISK_MB - allocated["disk_mb"]),
            },
        }

    async def _get_allocated_resources(self) -> dict[str, float]:
        """Get resources allocated by running servers"""
        result = await self.db.execute(
            select(Server).where(Server.status.in_(["running", "starting", "stopping"]))
        )
        servers = result.scalars().all()

        total_cpu = sum(s.allocated_cpu for s in servers)
        total_memory_mb = sum(self._parse_memory(s.allocated_memory) for s in servers)
        total_disk_mb = sum(self._parse_memory(s.allocated_disk) for s in servers)

        return {
            "cpu": total_cpu,
            "memory_mb": total_memory_mb,
            "disk_mb": total_disk_mb,
        }

    async def can_fit(self, plan_id: str) -> bool:
        """Check if a plan can fit in the current resource pool"""
        result = await self.db.execute(
            select(ServerPlan).where(ServerPlan.id == uuid.UUID(plan_id))
        )
        plan = result.scalar_one_or_none()

        if not plan:
            return False

        available = await self.get_available_resources()

        plan_memory_mb = self._parse_memory(plan.memory_limit)
        plan_disk_mb = self._parse_memory(plan.disk_limit)

        return (
            available["cpu"]["available"] >= plan.cpu_limit
            and available["memory_mb"]["available"] >= plan_memory_mb
            and available["disk_mb"]["available"] >= plan_disk_mb
        )

    async def can_fit_resources(self, cpu: float, memory: str, disk: str) -> bool:
        """Check if specific resources can fit"""
        available = await self.get_available_resources()

        memory_mb = self._parse_memory(memory)
        disk_mb = self._parse_memory(disk)

        return (
            available["cpu"]["available"] >= cpu
            and available["memory_mb"]["available"] >= memory_mb
            and available["disk_mb"]["available"] >= disk_mb
        )

    @staticmethod
    def _parse_memory(mem_str: str) -> int:
        """Parse memory string to MB"""
        if not mem_str:
            return 0

        mem_str = str(mem_str).lower().strip()

        if mem_str.endswith("g") or mem_str.endswith("gb"):
            return int(float(mem_str.rstrip("gb").rstrip("g")) * 1024)
        elif mem_str.endswith("m") or mem_str.endswith("mb"):
            return int(float(mem_str.rstrip("mb").rstrip("m")))
        elif mem_str.endswith("t") or mem_str.endswith("tb"):
            return int(float(mem_str.rstrip("tb").rstrip("t")) * 1024 * 1024)
        else:
            return int(float(mem_str))

    async def get_queue_position(self, queue_entry_id: str) -> int | None:
        """One-based priority order; missing and terminal requests have no position."""
        entry_id = uuid.UUID(queue_entry_id)
        result = await self.db.execute(
            select(ServerQueue.id)
            .where(ServerQueue.status == "pending")
            .order_by(
                ServerQueue.priority.desc(), ServerQueue.requested_at.asc(), ServerQueue.id.asc()
            )
        )
        for position, candidate_id in enumerate(result.scalars().all(), start=1):
            if candidate_id == entry_id:
                return position
        return None

    async def get_next_in_queue(self) -> ServerQueue | None:
        """Get the next queued server that can be started"""
        result = await self.db.execute(
            select(ServerQueue)
            .where(ServerQueue.status == "pending")
            .order_by(
                ServerQueue.priority.desc(), ServerQueue.requested_at.asc(), ServerQueue.id.asc()
            )
        )
        entries = result.scalars().all()

        for entry in entries:
            if await self.can_fit(str(entry.plan_id)):
                return entry

        return None
