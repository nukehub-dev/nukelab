"""
Analytics API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
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
    db: AsyncSession = Depends(get_db)
):
    """Get top credit consumers. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    return await service.get_top_consumers(days, limit)


@router.get("/environments")
async def get_environment_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get usage by environment. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    return await service.get_environment_usage()


@router.get("/plans")
async def get_plan_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get usage by plan. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    service = AnalyticsService(db)
    return await service.get_plan_usage()
