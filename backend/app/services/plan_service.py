"""
Server plan service for business logic.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from fastapi import HTTPException, status

from app.models.server_plan import ServerPlan


class PlanService:
    """Server plan business logic"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_id(self, plan_id: str) -> Optional[ServerPlan]:
        """Get plan by ID"""
        result = await self.db.execute(
            select(ServerPlan).where(ServerPlan.id == uuid.UUID(plan_id))
        )
        return result.scalar_one_or_none()
    
    async def get_by_slug(self, slug: str) -> Optional[ServerPlan]:
        """Get plan by slug"""
        result = await self.db.execute(
            select(ServerPlan).where(ServerPlan.slug == slug)
        )
        return result.scalar_one_or_none()
    
    async def list_plans(
        self,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
        user_role: Optional[str] = None,
        page: int = 1,
        limit: int = 50
    ) -> Dict[str, Any]:
        """List plans with filtering and pagination"""
        
        query = select(ServerPlan)
        
        # Apply filters
        filters = []
        if category:
            filters.append(ServerPlan.category == category)
        if is_active is not None:
            filters.append(ServerPlan.is_active == is_active)
        # Note: Role filtering is done in Python due to PostgreSQL JSON comparison limitations
        
        if filters:
            query = query.where(and_(*filters))
        
        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()
        
        # Sort by priority desc, then name
        query = query.order_by(ServerPlan.priority.desc(), ServerPlan.name)
        query = query.offset((page - 1) * limit).limit(limit)
        
        result = await self.db.execute(query)
        plans = result.scalars().all()
        
        # Filter by user role in Python (PostgreSQL JSON comparison limitation)
        if user_role:
            plans = [
                plan for plan in plans
                if not plan.allowed_roles or user_role in plan.allowed_roles
            ]
        
        return {
            "items": [plan.to_dict() for plan in plans],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
    
    async def create_plan(
        self,
        name: str,
        slug: str,
        description: Optional[str] = None,
        category: str = "cpu",
        cpu_limit: float = 1.0,
        memory_limit: str = "2g",
        disk_limit: str = "10g",
        gpu_limit: int = 0,
        max_servers_per_user: int = 3,
        cost_per_hour: int = 10,
        cooldown_seconds: int = 0,
        requires_approval: bool = False,
        allowed_roles: Optional[List[str]] = None,
        priority: int = 0
    ) -> ServerPlan:
        """Create new server plan"""
        
        # Check for duplicate slug
        existing = await self.get_by_slug(slug)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Plan with slug '{slug}' already exists"
            )
        
        plan = ServerPlan(
            name=name,
            slug=slug,
            description=description,
            category=category,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            disk_limit=disk_limit,
            gpu_limit=gpu_limit,
            max_servers_per_user=max_servers_per_user,
            cost_per_hour=cost_per_hour,
            cooldown_seconds=cooldown_seconds,
            requires_approval=requires_approval,
            allowed_roles=allowed_roles or [],
            priority=priority
        )
        
        self.db.add(plan)
        await self.db.commit()
        await self.db.refresh(plan)
        
        return plan
    
    async def update_plan(
        self,
        plan_id: str,
        **updates
    ) -> ServerPlan:
        """Update server plan"""
        
        plan = await self.get_by_id(plan_id)
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan not found"
            )
        
        # Update fields
        for key, value in updates.items():
            if hasattr(plan, key) and value is not None:
                setattr(plan, key, value)
        
        plan.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(plan)
        
        return plan
    
    async def deactivate_plan(self, plan_id: str) -> ServerPlan:
        """Deactivate plan"""
        return await self.update_plan(plan_id, is_active=False)
    
    async def activate_plan(self, plan_id: str) -> ServerPlan:
        """Activate plan"""
        return await self.update_plan(plan_id, is_active=True)
    
    async def delete_plan(self, plan_id: str) -> None:
        """Permanently delete plan"""
        plan = await self.get_by_id(plan_id)
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan not found"
            )
        
        await self.db.delete(plan)
        await self.db.commit()
    
    async def can_user_use_plan(self, plan_id: str, user_role: str) -> bool:
        """Check if a user role can use a plan"""
        plan = await self.get_by_id(plan_id)
        if not plan or not plan.is_active:
            return False
        
        if not plan.allowed_roles:
            return True
        
        return user_role in plan.allowed_roles
