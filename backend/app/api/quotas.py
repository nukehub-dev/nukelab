"""
Resource Quota API endpoints.
"""

from typing import Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user, require_permissions
from app.core.permissions import Permission
from app.services.quota_service import QuotaService

router = APIRouter(tags=["quotas"])


@router.get("/")
async def get_my_quota(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's quota"""
    service = QuotaService(db)
    quota = await service.recalculate_usage(str(current_user.id))
    return {"success": True, "data": quota.to_dict()}


@router.get("/{user_id}")
async def get_user_quota(
    user_id: str,
    current_user = Depends(require_permissions(Permission.QUOTA_READ)),
    db: AsyncSession = Depends(get_db)
):
    """Get specific user's quota (admin/moderator)"""
    service = QuotaService(db)
    quota = await service.recalculate_usage(user_id)
    return {"success": True, "data": quota.to_dict()}


@router.put("/{user_id}")
async def update_user_quota(
    user_id: str,
    data: dict,
    current_user = Depends(require_permissions(Permission.QUOTA_UPDATE)),
    db: AsyncSession = Depends(get_db)
):
    """Update user's quota limits (admin only)"""
    service = QuotaService(db)
    quota = await service.update_user_quota(
        user_id=user_id,
        max_cpu_total=data.get("max_cpu_total"),
        max_memory_total=data.get("max_memory_total"),
        max_disk_total=data.get("max_disk_total"),
        max_gpu_total=data.get("max_gpu_total"),
        max_servers_total=data.get("max_servers_total")
    )
    return {"success": True, "data": quota.to_dict(), "message": "Quota updated"}


@router.post("/check")
async def check_spawn_allowed(
    data: dict,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Check if spawn is allowed with given plan"""
    service = QuotaService(db)
    result = await service.check_spawn_allowed(
        user_id=str(current_user.id),
        plan_id=data["plan_id"]
    )
    return {"success": True, "data": result}
