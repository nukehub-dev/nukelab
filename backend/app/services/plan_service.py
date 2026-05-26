"""
Server plan service for business logic.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status

from app.models.server_plan import ServerPlan
from app.models.plan_access import UserPlanAccess, WorkspacePlanAccess
from app.models.shared_workspace import WorkspaceMember
from app.core.permissions import Permission
from app.core.roles import get_role_permissions


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
        user_id: Optional[str] = None,
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
        
        if filters:
            query = query.where(and_(*filters))
        
        # Count total (before visibility filtering)
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()
        
        # Sort by priority desc, then name
        query = query.order_by(ServerPlan.priority.desc(), ServerPlan.name)
        query = query.offset((page - 1) * limit).limit(limit)
        
        result = await self.db.execute(query)
        plans = list(result.scalars().all())
        
        # If no user context, return all (e.g., admin view)
        if not user_role and not user_id:
            return {
                "items": [plan.to_dict() for plan in plans],
                "total": total,
                "page": page,
                "limit": limit,
                "pages": (total + limit - 1) // limit
            }
        
        # Gather visibility data in bulk
        plan_ids = [plan.id for plan in plans]
        user_plan_ids = set()
        workspace_plan_ids = set()
        
        if user_id and plan_ids:
            # Direct user access
            user_access_result = await self.db.execute(
                select(UserPlanAccess.plan_id).where(
                    UserPlanAccess.user_id == uuid.UUID(user_id),
                    UserPlanAccess.plan_id.in_(plan_ids)
                )
            )
            user_plan_ids = {row[0] for row in user_access_result.all()}
            
            # Workspace-based access: find workspaces the user is in
            # that have access to any of these plans
            workspace_access_result = await self.db.execute(
                select(WorkspacePlanAccess.plan_id).where(
                    WorkspacePlanAccess.plan_id.in_(plan_ids),
                    WorkspacePlanAccess.workspace_id.in_(
                        select(WorkspaceMember.workspace_id).where(
                            WorkspaceMember.user_id == uuid.UUID(user_id)
                        )
                    )
                )
            )
            workspace_plan_ids = {row[0] for row in workspace_access_result.all()}
        
        # Filter plans by visibility
        visible_plans = []
        for plan in plans:
            # Public plans are visible to all
            public_visible = plan.is_public
            # Admin/super_admin always have access
            user_perms = get_role_permissions(user_role) if user_role else []
            admin_visible = Permission.ADMIN_ACCESS in user_perms or Permission.ALL in user_perms
            # Role-based visibility
            role_visible = (
                user_role and plan.visible_to_roles
                and user_role in plan.visible_to_roles
            )
            # Direct user access
            user_visible = plan.id in user_plan_ids
            # Workspace access
            workspace_visible = plan.id in workspace_plan_ids
            
            if public_visible or admin_visible or role_visible or user_visible or workspace_visible:
                visible_plans.append(plan)
        
        return {
            "items": [plan.to_dict() for plan in visible_plans],
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
        is_public: bool = False,
        visible_to_roles: Optional[List[str]] = None,
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
            is_public=is_public,
            visible_to_roles=visible_to_roles or [],
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
    
    async def can_user_use_plan(self, plan_id: str, user_role: str, user_id: Optional[str] = None) -> bool:
        """Check if a user can use a plan"""
        plan = await self.get_by_id(plan_id)
        if not plan or not plan.is_active:
            return False
        
        # Admin/super_admin always have access
        user_perms = get_role_permissions(user_role) if user_role else []
        if Permission.ADMIN_ACCESS in user_perms or Permission.ALL in user_perms:
            return True
        
        # Public plans are usable by all
        if plan.is_public:
            return True
        
        # Role-based check
        if plan.visible_to_roles and user_role in plan.visible_to_roles:
            return True
        
        # Direct user access
        if user_id:
            access = await self.db.execute(
                select(UserPlanAccess).where(
                    UserPlanAccess.plan_id == uuid.UUID(plan_id),
                    UserPlanAccess.user_id == uuid.UUID(user_id)
                )
            )
            if access.scalar_one_or_none():
                return True
            
            # Workspace-based access
            workspace_access = await self.db.execute(
                select(WorkspacePlanAccess).where(
                    WorkspacePlanAccess.plan_id == uuid.UUID(plan_id),
                    WorkspacePlanAccess.workspace_id.in_(
                        select(WorkspaceMember.workspace_id).where(
                            WorkspaceMember.user_id == uuid.UUID(user_id)
                        )
                    )
                )
            )
            if workspace_access.scalar_one_or_none():
                return True
        
        return False
    
    # ─── User Plan Access ───
    
    async def list_plan_users(self, plan_id: str) -> List[Dict[str, Any]]:
        """List users with direct access to a plan"""
        result = await self.db.execute(
            select(UserPlanAccess)
            .where(UserPlanAccess.plan_id == uuid.UUID(plan_id))
            .options(
                selectinload(UserPlanAccess.user),
                selectinload(UserPlanAccess.granted_by_user)
            )
        )
        accesses = result.scalars().all()
        data = []
        for access in accesses:
            item = access.to_dict()
            if access.user:
                item["username"] = access.user.username
                item["display_name"] = access.user.display_name
            if access.granted_by_user:
                item["granted_by_username"] = access.granted_by_user.username
            data.append(item)
        return data
    
    async def grant_user_access(self, plan_id: str, user_id: str, granted_by: Optional[str] = None) -> UserPlanAccess:
        """Grant a user access to a plan"""
        plan = await self.get_by_id(plan_id)
        if not plan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
        
        # Check if already exists
        existing = await self.db.execute(
            select(UserPlanAccess).where(
                UserPlanAccess.plan_id == uuid.UUID(plan_id),
                UserPlanAccess.user_id == uuid.UUID(user_id)
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already has access to this plan")
        
        access = UserPlanAccess(
            plan_id=uuid.UUID(plan_id),
            user_id=uuid.UUID(user_id),
            granted_by=uuid.UUID(granted_by) if granted_by else None,
            granted_at=datetime.utcnow()
        )
        self.db.add(access)
        await self.db.commit()
        await self.db.refresh(access)
        return access
    
    async def revoke_user_access(self, plan_id: str, user_id: str) -> None:
        """Revoke a user's access to a plan"""
        result = await self.db.execute(
            select(UserPlanAccess).where(
                UserPlanAccess.plan_id == uuid.UUID(plan_id),
                UserPlanAccess.user_id == uuid.UUID(user_id)
            )
        )
        access = result.scalar_one_or_none()
        if access:
            await self.db.delete(access)
            await self.db.commit()
    
    # ─── Workspace Plan Access ───
    
    async def list_plan_workspaces(self, plan_id: str) -> List[Dict[str, Any]]:
        """List workspaces with access to a plan"""
        from app.models.shared_workspace import SharedWorkspace
        result = await self.db.execute(
            select(WorkspacePlanAccess)
            .where(WorkspacePlanAccess.plan_id == uuid.UUID(plan_id))
            .options(
                selectinload(WorkspacePlanAccess.workspace).selectinload(SharedWorkspace.owner),
                selectinload(WorkspacePlanAccess.granted_by_user)
            )
        )
        accesses = result.scalars().all()
        data = []
        for access in accesses:
            item = access.to_dict()
            if access.workspace:
                item["workspace_name"] = access.workspace.name
                if access.workspace.owner:
                    item["owner_name"] = access.workspace.owner.display_name or access.workspace.owner.username
                    item["owner_username"] = access.workspace.owner.username
            if access.granted_by_user:
                item["granted_by_username"] = access.granted_by_user.username
            data.append(item)
        return data
    
    async def grant_workspace_access(self, plan_id: str, workspace_id: str, granted_by: Optional[str] = None) -> WorkspacePlanAccess:
        """Grant a workspace access to a plan"""
        plan = await self.get_by_id(plan_id)
        if not plan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
        
        # Check if already exists
        existing = await self.db.execute(
            select(WorkspacePlanAccess).where(
                WorkspacePlanAccess.plan_id == uuid.UUID(plan_id),
                WorkspacePlanAccess.workspace_id == uuid.UUID(workspace_id)
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workspace already has access to this plan")
        
        access = WorkspacePlanAccess(
            plan_id=uuid.UUID(plan_id),
            workspace_id=uuid.UUID(workspace_id),
            granted_by=uuid.UUID(granted_by) if granted_by else None,
            granted_at=datetime.utcnow()
        )
        self.db.add(access)
        await self.db.commit()
        await self.db.refresh(access)
        return access
    
    async def revoke_workspace_access(self, plan_id: str, workspace_id: str) -> None:
        """Revoke a workspace's access to a plan"""
        result = await self.db.execute(
            select(WorkspacePlanAccess).where(
                WorkspacePlanAccess.plan_id == uuid.UUID(plan_id),
                WorkspacePlanAccess.workspace_id == uuid.UUID(workspace_id)
            )
        )
        access = result.scalar_one_or_none()
        if access:
            await self.db.delete(access)
            await self.db.commit()
