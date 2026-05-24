"""
Server schedule API endpoints.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.api.auth import get_current_user
from app.dependencies import require_permissions
from app.core.permissions import Permission
from app.dependencies import PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server
from app.services.schedule_service import ScheduleService
from app.api.servers import get_server_with_permission_check

router = APIRouter()


class ScheduleCreateRequest(BaseModel):
    action: str
    cron_expression: str
    timezone: str = "UTC"
    is_active: bool = True


class ScheduleUpdateRequest(BaseModel):
    action: Optional[str] = None
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/servers/{server_id}/schedules")
async def list_schedules(
    server_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_READ_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """List schedules for a server."""
    await get_server_with_permission_check(server_id, current_user, db)
    
    service = ScheduleService(db)
    schedules = await service.get_schedules_for_server(
        server_id=server_id,
        user_id=str(current_user.id)
    )
    
    return {"schedules": schedules}


@router.post("/servers/{server_id}/schedules")
async def create_schedule(
    server_id: str,
    request: ScheduleCreateRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_MANAGE)),
    db: AsyncSession = Depends(get_db)
):
    """Create a schedule for a server."""
    server = await get_server_with_permission_check(server_id, current_user, db)
    
    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_START)
    
    service = ScheduleService(db)
    
    try:
        schedule = await service.create_schedule(
            server_id=server_id,
            user_id=str(current_user.id),
            action=request.action,
            cron_expression=request.cron_expression,
            timezone=request.timezone,
            is_active=request.is_active
        )
        return schedule.to_dict()
    except ValueError:
        logger.exception("Schedule creation failed")
        raise HTTPException(status_code=400, detail="Failed to create schedule. Please check your input and try again.")
    except Exception:
        logger.exception("Schedule creation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create schedule. Please try again or contact support."
        )


@router.put("/servers/{server_id}/schedules/{schedule_id}")
async def update_schedule(
    server_id: str,
    schedule_id: str,
    request: ScheduleUpdateRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_MANAGE)),
    db: AsyncSession = Depends(get_db)
):
    """Update a schedule."""
    await get_server_with_permission_check(server_id, current_user, db)
    
    service = ScheduleService(db)
    
    try:
        schedule = await service.update_schedule(
            schedule_id=schedule_id,
            user_id=str(current_user.id),
            action=request.action,
            cron_expression=request.cron_expression,
            timezone=request.timezone,
            is_active=request.is_active
        )
        return schedule.to_dict()
    except ValueError:
        logger.exception("Schedule update failed")
        raise HTTPException(status_code=400, detail="Failed to update schedule. Please check your input and try again.")
    except Exception:
        logger.exception("Schedule update failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update schedule. Please try again or contact support."
        )


@router.delete("/servers/{server_id}/schedules/{schedule_id}")
async def delete_schedule(
    server_id: str,
    schedule_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_MANAGE)),
    db: AsyncSession = Depends(get_db)
):
    """Delete a schedule."""
    await get_server_with_permission_check(server_id, current_user, db)
    
    service = ScheduleService(db)
    
    success = await service.delete_schedule(schedule_id, str(current_user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    return {"message": "Schedule deleted", "schedule_id": schedule_id}
