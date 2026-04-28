"""
Resource quota service for business logic.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from fastapi import HTTPException, status

from app.models.resource_quota import ResourceQuota
from app.models.server import Server
from app.models.server_plan import ServerPlan


class QuotaService:
    """Resource quota business logic"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_quota(self, user_id: str) -> Optional[ResourceQuota]:
        """Get quota for a user"""
        result = await self.db.execute(
            select(ResourceQuota).where(ResourceQuota.user_id == uuid.UUID(user_id))
        )
        return result.scalar_one_or_none()
    
    async def get_or_create_user_quota(self, user_id: str) -> ResourceQuota:
        """Get or create quota for a user"""
        quota = await self.get_user_quota(user_id)
        if not quota:
            quota = ResourceQuota(user_id=uuid.UUID(user_id))
            self.db.add(quota)
            await self.db.commit()
            await self.db.refresh(quota)
        return quota
    
    async def get_role_quota(self, role: str) -> Optional[ResourceQuota]:
        """Get quota for a role"""
        result = await self.db.execute(
            select(ResourceQuota).where(ResourceQuota.role == role)
        )
        return result.scalar_one_or_none()
    
    async def update_user_quota(
        self,
        user_id: str,
        max_cpu_total: Optional[float] = None,
        max_memory_total: Optional[str] = None,
        max_disk_total: Optional[str] = None,
        max_gpu_total: Optional[int] = None,
        max_servers_total: Optional[int] = None
    ) -> ResourceQuota:
        """Update user's quota limits"""
        
        quota = await self.get_or_create_user_quota(user_id)
        
        if max_cpu_total is not None:
            quota.max_cpu_total = max_cpu_total
        if max_memory_total is not None:
            quota.max_memory_total = max_memory_total
        if max_disk_total is not None:
            quota.max_disk_total = max_disk_total
        if max_gpu_total is not None:
            quota.max_gpu_total = max_gpu_total
        if max_servers_total is not None:
            quota.max_servers_total = max_servers_total
        
        quota.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(quota)
        
        return quota
    
    async def recalculate_usage(self, user_id: str) -> ResourceQuota:
        """Recalculate current usage from active servers"""
        
        quota = await self.get_or_create_user_quota(user_id)
        
        # Get all active servers for user
        result = await self.db.execute(
            select(Server).where(
                and_(
                    Server.user_id == uuid.UUID(user_id),
                    Server.status.in_(["running", "starting"])
                )
            )
        )
        servers = result.scalars().all()
        
        # Calculate totals
        total_cpu = sum(s.allocated_cpu for s in servers)
        total_memory_mb = sum(self._parse_memory(s.allocated_memory) for s in servers)
        total_disk_mb = sum(self._parse_memory(s.allocated_disk) for s in servers)
        total_gpu = sum(s.allocated_gpu for s in servers)
        total_servers = len(servers)
        
        quota.usage_cpu = total_cpu
        quota.usage_memory_mb = total_memory_mb
        quota.usage_disk_mb = total_disk_mb
        quota.usage_gpu = total_gpu
        quota.usage_servers = total_servers
        quota.updated_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(quota)
        
        return quota
    
    def _parse_memory(self, mem_str: str) -> int:
        """Parse memory string to MB"""
        if not mem_str:
            return 0
        
        mem_str = str(mem_str).lower().strip()
        
        if mem_str.endswith('g'):
            return int(float(mem_str[:-1]) * 1024)
        elif mem_str.endswith('gb'):
            return int(float(mem_str[:-2]) * 1024)
        elif mem_str.endswith('m'):
            return int(float(mem_str[:-1]))
        elif mem_str.endswith('mb'):
            return int(float(mem_str[:-2]))
        elif mem_str.endswith('t'):
            return int(float(mem_str[:-1]) * 1024 * 1024)
        elif mem_str.endswith('tb'):
            return int(float(mem_str[:-2]) * 1024 * 1024)
        else:
            return int(float(mem_str))
    
    async def check_spawn_allowed(
        self,
        user_id: str,
        plan_id: str
    ) -> Dict[str, Any]:
        """Check if user can spawn a server with given plan"""
        
        quota = await self.recalculate_usage(user_id)
        
        # Get plan details
        result = await self.db.execute(
            select(ServerPlan).where(ServerPlan.id == uuid.UUID(plan_id))
        )
        plan = result.scalar_one_or_none()
        
        if not plan:
            return {
                "allowed": False,
                "reason": "Plan not found"
            }
        
        # Check server count limit
        if quota.usage_servers >= quota.max_servers_total:
            return {
                "allowed": False,
                "reason": f"Maximum server limit reached ({quota.max_servers_total})"
            }
        
        # Check plan-specific server limit
        result = await self.db.execute(
            select(func.count()).where(
                and_(
                    Server.user_id == uuid.UUID(user_id),
                    Server.plan_id == uuid.UUID(plan_id),
                    Server.status.in_(["running", "starting"])
                )
            )
        )
        plan_server_count = result.scalar()
        
        if plan_server_count >= plan.max_servers_per_user:
            return {
                "allowed": False,
                "reason": f"Plan limit reached for {plan.name} (max {plan.max_servers_per_user})"
            }
        
        # Check CPU limit
        if quota.usage_cpu + plan.cpu_limit > quota.max_cpu_total:
            return {
                "allowed": False,
                "reason": f"CPU quota exceeded (using {quota.usage_cpu}/{quota.max_cpu_total} cores)"
            }
        
        # Check memory limit
        plan_memory_mb = self._parse_memory(plan.memory_limit)
        if quota.usage_memory_mb + plan_memory_mb > self._parse_memory(quota.max_memory_total):
            return {
                "allowed": False,
                "reason": f"Memory quota exceeded"
            }
        
        # Check disk limit
        plan_disk_mb = self._parse_memory(plan.disk_limit)
        if quota.usage_disk_mb + plan_disk_mb > self._parse_memory(quota.max_disk_total):
            return {
                "allowed": False,
                "reason": f"Disk quota exceeded"
            }
        
        # Check GPU limit
        if quota.usage_gpu + plan.gpu_limit > quota.max_gpu_total:
            return {
                "allowed": False,
                "reason": f"GPU quota exceeded"
            }
        
        return {
            "allowed": True,
            "reason": None,
            "estimated_cost_per_hour": plan.cost_per_hour
        }
    
    async def increment_usage(self, user_id: str, plan_id: str) -> ResourceQuota:
        """Increment usage when server starts"""
        
        quota = await self.get_or_create_user_quota(user_id)
        
        result = await self.db.execute(
            select(ServerPlan).where(ServerPlan.id == uuid.UUID(plan_id))
        )
        plan = result.scalar_one_or_none()
        
        if plan:
            quota.usage_cpu += plan.cpu_limit
            quota.usage_memory_mb += self._parse_memory(plan.memory_limit)
            quota.usage_disk_mb += self._parse_memory(plan.disk_limit)
            quota.usage_gpu += plan.gpu_limit
            quota.usage_servers += 1
            quota.updated_at = datetime.utcnow()
            
            await self.db.commit()
            await self.db.refresh(quota)
        
        return quota
    
    async def decrement_usage(self, user_id: str, plan_id: str) -> ResourceQuota:
        """Decrement usage when server stops"""
        
        quota = await self.get_or_create_user_quota(user_id)
        
        result = await self.db.execute(
            select(ServerPlan).where(ServerPlan.id == uuid.UUID(plan_id))
        )
        plan = result.scalar_one_or_none()
        
        if plan:
            quota.usage_cpu = max(0, quota.usage_cpu - plan.cpu_limit)
            quota.usage_memory_mb = max(0, quota.usage_memory_mb - self._parse_memory(plan.memory_limit))
            quota.usage_disk_mb = max(0, quota.usage_disk_mb - self._parse_memory(plan.disk_limit))
            quota.usage_gpu = max(0, quota.usage_gpu - plan.gpu_limit)
            quota.usage_servers = max(0, quota.usage_servers - 1)
            quota.updated_at = datetime.utcnow()
            
            await self.db.commit()
            await self.db.refresh(quota)
        
        return quota
