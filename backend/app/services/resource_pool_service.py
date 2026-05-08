"""
Global resource pool service for tracking platform-wide resource availability.
"""

import uuid
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.config import settings


class ResourcePoolService:
    """
    Track global resource availability across the platform.
    
    Platform hardware constraints:
    - Total CPU: 34 cores
    - Total RAM: 68GB
    """
    
    # Platform-wide resource limits
    TOTAL_CPU = 34.0
    TOTAL_MEMORY_MB = 68 * 1024  # 68GB in MB
    TOTAL_DISK_MB = 2000 * 1024  # 2TB in MB (generous)
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_available_resources(self) -> Dict[str, Any]:
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
    
    async def _get_allocated_resources(self) -> Dict[str, float]:
        """Get resources allocated by running servers"""
        result = await self.db.execute(
            select(Server).where(
                Server.status.in_(["running", "starting"])
            )
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
            available["cpu"]["available"] >= plan.cpu_limit and
            available["memory_mb"]["available"] >= plan_memory_mb and
            available["disk_mb"]["available"] >= plan_disk_mb
        )
    
    async def can_fit_resources(
        self,
        cpu: float,
        memory: str,
        disk: str
    ) -> bool:
        """Check if specific resources can fit"""
        available = await self.get_available_resources()
        
        memory_mb = self._parse_memory(memory)
        disk_mb = self._parse_memory(disk)
        
        return (
            available["cpu"]["available"] >= cpu and
            available["memory_mb"]["available"] >= memory_mb and
            available["disk_mb"]["available"] >= disk_mb
        )
    
    @staticmethod
    def _parse_memory(mem_str: str) -> int:
        """Parse memory string to MB"""
        if not mem_str:
            return 0
        
        mem_str = str(mem_str).lower().strip()
        
        if mem_str.endswith('g') or mem_str.endswith('gb'):
            return int(float(mem_str.rstrip('gb').rstrip('g')) * 1024)
        elif mem_str.endswith('m') or mem_str.endswith('mb'):
            return int(float(mem_str.rstrip('mb').rstrip('m')))
        elif mem_str.endswith('t') or mem_str.endswith('tb'):
            return int(float(mem_str.rstrip('tb').rstrip('t')) * 1024 * 1024)
        else:
            return int(float(mem_str))
    
    async def get_queue_position(self, queue_entry_id: str) -> int:
        """Get position in queue for a given queue entry"""
        result = await self.db.execute(
            select(ServerQueue).where(
                and_(
                    ServerQueue.status == "pending",
                    ServerQueue.id != uuid.UUID(queue_entry_id)
                )
            ).order_by(
                ServerQueue.priority.desc(),
                ServerQueue.requested_at.asc()
            )
        )
        entries = result.scalars().all()
        
        # Find position
        for idx, entry in enumerate(entries):
            if str(entry.id) == queue_entry_id:
                return idx + 1
        
        return 0
    
    async def get_next_in_queue(self) -> Optional[ServerQueue]:
        """Get the next queued server that can be started"""
        result = await self.db.execute(
            select(ServerQueue).where(
                ServerQueue.status == "pending"
            ).order_by(
                ServerQueue.priority.desc(),
                ServerQueue.requested_at.asc()
            )
        )
        entries = result.scalars().all()
        
        for entry in entries:
            if await self.can_fit(str(entry.plan_id)):
                return entry
        
        return None
