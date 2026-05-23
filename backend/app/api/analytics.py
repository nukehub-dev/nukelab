"""
Analytics API endpoints.
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_scopes
from app.core.permissions import Permission
from app.dependencies import PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.services.analytics_service import AnalyticsService

router = APIRouter()

MAX_DATE_RANGE_DAYS = 365


def _parse_date_params(
    days: int = 30,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> tuple:
    """Parse and validate date range parameters."""
    if from_date and to_date:
        if to_date <= from_date:
            raise HTTPException(status_code=422, detail="to_date must be after from_date")
        if (to_date - from_date).days > MAX_DATE_RANGE_DAYS:
            raise HTTPException(
                status_code=422,
                detail=f"Date range cannot exceed {MAX_DATE_RANGE_DAYS} days"
            )
        return days, from_date, to_date
    return days, None, None


@router.get("/users/{user_id}/usage")
async def get_user_usage(
    user_id: str,
    days: int = 30,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get usage trends for a user."""
    # Users can only view their own, admins can view any
    if str(current_user.id) != user_id:
        checker = PermissionChecker(current_user)
        checker.require(Permission.ADMIN_ACCESS)
    
    _, from_date, to_date = _parse_date_params(days, from_date, to_date)
    service = AnalyticsService(db)
    return await service.get_user_usage(user_id, days, from_date, to_date)


@router.get("/global")
async def get_global_usage(
    days: int = 30,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get platform-wide usage statistics. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    _, from_date, to_date = _parse_date_params(days, from_date, to_date)
    service = AnalyticsService(db)
    return await service.get_global_usage(days, from_date, to_date)


@router.get("/top-consumers")
async def get_top_consumers(
    days: int = 30,
    limit: int = 10,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get top credit consumers. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    _, from_date, to_date = _parse_date_params(days, from_date, to_date)
    service = AnalyticsService(db)
    consumers = await service.get_top_consumers(days, limit, from_date, to_date)
    return {"consumers": consumers}


@router.get("/credit-flow")
async def get_credit_flow(
    days: int = 30,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get daily credit flow (consumed vs granted). Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    _, from_date, to_date = _parse_date_params(days, from_date, to_date)
    service = AnalyticsService(db)
    flow = await service.get_credit_flow(days, from_date, to_date)
    return {"credit_flow": flow}


@router.get("/logins")
async def get_login_events(
    days: int = 30,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get daily login counts. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    _, from_date, to_date = _parse_date_params(days, from_date, to_date)
    service = AnalyticsService(db)
    logins = await service.get_daily_logins(days, from_date, to_date)
    return {"login_events": logins}


@router.get("/user-growth")
async def get_user_growth(
    days: int = 30,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get daily new user signups. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    _, from_date, to_date = _parse_date_params(days, from_date, to_date)
    service = AnalyticsService(db)
    growth = await service.get_user_growth(days, from_date, to_date)
    return {"user_growth": growth}


@router.get("/platform-metrics")
async def get_platform_metrics(
    days: int = 30,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get platform-wide resource metrics over time. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    _, from_date, to_date = _parse_date_params(days, from_date, to_date)
    service = AnalyticsService(db)
    metrics = await service.get_platform_metrics(days, from_date, to_date)
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


@router.post("/export")
async def export_analytics(
    request: dict,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("analytics:read")),
    db: AsyncSession = Depends(get_db)
):
    """Export analytics data in CSV or JSON format. Admin only."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)

    metric = request.get("metric", "platform-metrics")
    fmt = request.get("format", "json")
    from_date_str = request.get("from")
    to_date_str = request.get("to")

    from_date = datetime.fromisoformat(from_date_str) if from_date_str else None
    to_date = datetime.fromisoformat(to_date_str) if to_date_str else None

    service = AnalyticsService(db)

    if metric == "platform-metrics":
        data = await service.get_platform_metrics(from_date=from_date, to_date=to_date)
    elif metric == "user-growth":
        data = await service.get_user_growth(from_date=from_date, to_date=to_date)
    elif metric == "credit-flow":
        data = await service.get_credit_flow(from_date=from_date, to_date=to_date)
    elif metric == "global":
        data = await service.get_global_usage(from_date=from_date, to_date=to_date)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported metric: {metric}")

    if fmt == "csv":
        import csv
        import io
        from fastapi.responses import StreamingResponse

        output = io.StringIO()
        if data and isinstance(data, list) and len(data) > 0:
            writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
            writer.writeheader()
            writer.writerows(data)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={metric}.csv"}
        )

    return {"data": data}
