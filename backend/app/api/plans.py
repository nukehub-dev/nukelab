"""
Server Plan API endpoints.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user, require_permissions
from app.api.auth import require_scopes
from app.core.permissions import Permission
from app.services.plan_service import PlanService

router = APIRouter(tags=["plans"])


@router.get("/")
async def list_plans(
    category: Optional[str] = None,
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user = Depends(get_current_user),
    _ = Depends(require_scopes("plans:read")),
    db: AsyncSession = Depends(get_db)
):
    """List server plans (filtered by user's role)"""
    service = PlanService(db)
    result = await service.list_plans(
        category=category,
        is_active=is_active,
        user_role=current_user.role,
        page=page,
        limit=limit
    )
    return {"success": True, "data": result}


@router.get("/{plan_id}")
async def get_plan(
    plan_id: str,
    current_user = Depends(get_current_user),
    _ = Depends(require_scopes("plans:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get plan details"""
    service = PlanService(db)
    plan = await service.get_by_id(plan_id)
    if not plan:
        return {"success": False, "error": "Plan not found"}
    return {"success": True, "data": plan.to_dict()}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: dict,
    current_user = Depends(require_permissions(Permission.PLAN_CREATE)),
    _scopes = Depends(require_scopes("admin:write")),
    db: AsyncSession = Depends(get_db)
):
    """Create new server plan (admin only)"""
    service = PlanService(db)
    plan = await service.create_plan(
        name=data["name"],
        slug=data["slug"],
        description=data.get("description"),
        category=data.get("category", "cpu"),
        cpu_limit=data.get("cpu_limit", 1.0),
        memory_limit=data.get("memory_limit", "2g"),
        disk_limit=data.get("disk_limit", "10g"),
        gpu_limit=data.get("gpu_limit", 0),
        max_servers_per_user=data.get("max_servers_per_user", 3),
        cost_per_hour=data.get("cost_per_hour", 10),
        cooldown_seconds=data.get("cooldown_seconds", 0),
        requires_approval=data.get("requires_approval", False),
        allowed_roles=data.get("allowed_roles"),
        priority=data.get("priority", 0)
    )
    return {"success": True, "data": plan.to_dict(), "message": "Plan created"}


@router.put("/{plan_id}")
async def update_plan(
    plan_id: str,
    data: dict,
    current_user = Depends(require_permissions(Permission.PLAN_UPDATE)),
    _scopes = Depends(require_scopes("admin:write")),
    db: AsyncSession = Depends(get_db)
):
    """Update server plan (admin only)"""
    service = PlanService(db)
    plan = await service.update_plan(plan_id, **data)
    return {"success": True, "data": plan.to_dict(), "message": "Plan updated"}


@router.delete("/{plan_id}")
async def deactivate_plan(
    plan_id: str,
    current_user = Depends(require_permissions(Permission.PLAN_DELETE)),
    _scopes = Depends(require_scopes("admin:write")),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate server plan (admin only)"""
    service = PlanService(db)
    plan = await service.deactivate_plan(plan_id)
    return {"success": True, "data": plan.to_dict(), "message": "Plan deactivated"}


@router.delete("/{plan_id}/permanent")
async def delete_plan(
    plan_id: str,
    current_user = Depends(require_permissions(Permission.PLAN_DELETE)),
    _scopes = Depends(require_scopes("admin:write")),
    db: AsyncSession = Depends(get_db)
):
    """Permanently delete server plan (admin only)"""
    service = PlanService(db)
    await service.delete_plan(plan_id)
    return {"success": True, "message": "Plan permanently deleted"}


@router.post("/{plan_id}/activate")
async def activate_plan(
    plan_id: str,
    current_user = Depends(require_permissions(Permission.PLAN_UPDATE)),
    _scopes = Depends(require_scopes("admin:write")),
    db: AsyncSession = Depends(get_db)
):
    """Activate server plan (admin only)"""
    service = PlanService(db)
    plan = await service.activate_plan(plan_id)
    return {"success": True, "data": plan.to_dict(), "message": "Plan activated"}
