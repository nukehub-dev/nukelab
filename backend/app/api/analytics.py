"""
Analytics API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_scopes
from app.core.permissions import Permission
from app.dependencies import PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.services.analytics_service import AnalyticsService

router = APIRouter()


@router.get("/users/{user_id}/usage")
async def get_user_usage(
    user_id: str,
    days: int = 30,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get usage trends for a user."""
    # Users can only view their own, admins can view any
    if str(current_user.id) != user_id:
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    return await service.get_user_usage(user_id, days)


@router.get("/global")
async def get_global_usage(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get platform-wide usage statistics. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    return await service.get_global_usage(days)


@router.get("/top-consumers")
async def get_top_consumers(
    days: int = 30,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get top credit consumers. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    consumers = await service.get_top_consumers(days, limit)
    return {"consumers": consumers}


@router.get("/credit-flow")
async def get_credit_flow(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get daily credit flow (consumed vs granted). Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    flow = await service.get_credit_flow(days)
    return {"credit_flow": flow}


@router.get("/user-growth")
async def get_user_growth(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get daily new user signups. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    growth = await service.get_user_growth(days)
    return {"user_growth": growth}


@router.get("/platform-metrics")
async def get_platform_metrics(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get platform-wide resource metrics over time. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    metrics = await service.get_platform_metrics(days)
    return {"metrics": metrics}


@router.get("/volumes")
async def get_volume_analytics(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get storage/volume analytics. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    return await service.get_volume_analytics()


@router.get("/workspaces")
async def get_workspace_analytics(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get workspace collaboration analytics. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    return await service.get_workspace_analytics()


@router.get("/environments")
async def get_environment_usage(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get usage by environment. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    environments = await service.get_environment_usage()
    return {"environments": environments}


@router.get("/plans")
async def get_plan_usage(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get usage by plan. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    plans = await service.get_plan_usage()
    return {"plans": plans}
