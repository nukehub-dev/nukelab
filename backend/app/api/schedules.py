"""
Server schedule API endpoints.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.api.auth import get_current_user
from app.api.servers import _audit_cross_user_access, get_server_with_permission_check
from app.core.permissions import Permission
from app.db.session import get_db
from app.dependencies import PermissionChecker, require_permissions
from app.models.user import User
from app.services.schedule_service import ScheduleService

router = APIRouter()


class ScheduleCreateRequest(BaseModel):
    action: str
    cron_expression: str
    timezone: str = "UTC"
    is_active: bool = True
    reason: str | None = None


class ScheduleUpdateRequest(BaseModel):
    action: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    is_active: bool | None = None
    reason: str | None = None


@router.get("/servers/{server_id}/schedules")
async def list_schedules(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """List schedules for a server."""
    await get_server_with_permission_check(server_id, current_user, db, request)

    service = ScheduleService(db)
    schedules = await service.get_schedules_for_server(
        server_id=server_id, user_id=str(current_user.id)
    )

    return {"schedules": schedules}


@router.post("/servers/{server_id}/schedules")
async def create_schedule(
    server_id: str,
    http_request: Request,
    body: ScheduleCreateRequest,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Create a schedule for a server."""
    server = await get_server_with_permission_check(server_id, current_user, db, http_request)

    # Audit cross-user schedule creation
    if str(server.user_id) != str(current_user.id):
        await _audit_cross_user_access(
            server, current_user, db, "server.schedule.create", body.reason
        )

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)

    service = ScheduleService(db)

    try:
        schedule = await service.create_schedule(
            server_id=server_id,
            user_id=str(current_user.id),
            action=body.action,
            cron_expression=body.cron_expression,
            timezone=body.timezone,
            is_active=body.is_active,
        )
        return schedule.to_dict()
    except ValueError:
        logger.exception("Schedule creation failed")
        raise HTTPException(
            status_code=400,
            detail="Failed to create schedule. Please check your input and try again.",
        )
    except Exception:
        logger.exception("Schedule creation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create schedule. Please try again or contact support.",
        )


@router.put("/servers/{server_id}/schedules/{schedule_id}")
async def update_schedule(
    server_id: str,
    schedule_id: str,
    http_request: Request,
    body: ScheduleUpdateRequest,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Update a schedule."""
    server = await get_server_with_permission_check(server_id, current_user, db, http_request)

    # Audit cross-user schedule update
    if str(server.user_id) != str(current_user.id):
        await _audit_cross_user_access(
            server, current_user, db, "server.schedule.update", body.reason
        )

    service = ScheduleService(db)

    try:
        schedule = await service.update_schedule(
            schedule_id=schedule_id,
            user_id=str(current_user.id),
            action=body.action,
            cron_expression=body.cron_expression,
            timezone=body.timezone,
            is_active=body.is_active,
        )
        return schedule.to_dict()
    except ValueError:
        logger.exception("Schedule update failed")
        raise HTTPException(
            status_code=400,
            detail="Failed to update schedule. Please check your input and try again.",
        )
    except Exception:
        logger.exception("Schedule update failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update schedule. Please try again or contact support.",
        )


@router.delete("/servers/{server_id}/schedules/{schedule_id}")
async def delete_schedule(
    server_id: str,
    schedule_id: str,
    request: Request,
    reason: str | None = None,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Delete a schedule."""
    server = await get_server_with_permission_check(server_id, current_user, db, request)

    # Audit cross-user schedule deletion
    if str(server.user_id) != str(current_user.id):
        await _audit_cross_user_access(server, current_user, db, "server.schedule.delete", reason)

    service = ScheduleService(db)

    success = await service.delete_schedule(schedule_id, str(current_user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return {"message": "Schedule deleted", "schedule_id": schedule_id}
