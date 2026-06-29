# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_jwt_auth
from app.config import settings
from app.core.permissions import Permission
from app.db.session import get_db
from app.dependencies import require_permissions
from app.models.server import Server
from app.models.user import User
from app.services.maintenance_window_service import MaintenanceWindowService
from app.services.setting_service import SettingService

router = APIRouter(tags=["system"])


class SystemConfigUpdate(BaseModel):
    maintenance_mode: bool | None = None
    maintenance_message: str | None = None


@router.get("/health")
async def health_check():
    """Public health check endpoint"""
    if settings.maintenance_mode:
        return JSONResponse(
            status_code=503,
            content={"status": "maintenance", "message": settings.maintenance_message},
        )

    return {"status": "healthy", "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat()}


@router.get("/config")
async def get_system_config(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get system configuration (admin only)"""
    service = SettingService(db)
    maint = await service.get_maintenance()

    return {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "app_debug": settings.app_debug,
        "maintenance_mode": maint["maintenance_mode"],
        "maintenance_message": maint["maintenance_message"],
    }


@router.put("/config")
async def update_system_config(
    config: SystemConfigUpdate,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update system configuration (admin only)"""
    service = SettingService(db)
    updates = {}

    if config.maintenance_mode is not None or config.maintenance_message is not None:
        await service.save_maintenance(
            enabled=config.maintenance_mode
            if config.maintenance_mode is not None
            else settings.maintenance_mode,
            message=config.maintenance_message if config.maintenance_message is not None else None,
        )
        updates["maintenance_mode"] = settings.maintenance_mode
        if config.maintenance_message is not None:
            updates["maintenance_message"] = config.maintenance_message

    return {"success": True, "updates": updates, "message": "Configuration updated"}


@router.post("/maintenance")
async def toggle_maintenance(
    enabled: bool,
    message: str | None = None,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Toggle maintenance mode (admin only)"""
    service = SettingService(db)

    final_message = message or (
        settings.maintenance_message if not enabled else "System under maintenance"
    )
    await service.save_maintenance(enabled=enabled, message=final_message)

    return {
        "success": True,
        "maintenance_mode": settings.maintenance_mode,
        "message": settings.maintenance_message,
    }


@router.get("/stats")
async def get_system_stats(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get system statistics (admin only)"""
    total_users_result = await db.execute(select(func.count()).select_from(User))
    total_users = total_users_result.scalar()

    active_users_result = await db.execute(select(func.count()).where(User.is_active.is_(True)))
    active_users = active_users_result.scalar()

    total_servers_result = await db.execute(select(func.count()).select_from(Server))
    total_servers = total_servers_result.scalar()

    running_servers_result = await db.execute(
        select(func.count()).where(Server.status == "running")
    )
    running_servers = running_servers_result.scalar()

    total_credits_result = await db.execute(
        select(func.sum(User.nuke_balance)).where(User.is_active.is_(True))
    )
    total_credits = total_credits_result.scalar() or 0

    return {
        "users": {"total": total_users, "active": active_users},
        "servers": {"total": total_servers, "running": running_servers},
        "credits": {"total": total_credits},
        "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }


# ─── Maintenance Window Schemas ─────────────────────────────────────────────


class MaintenanceWindowCreate(BaseModel):
    title: str
    message: str
    start_at: datetime
    end_at: datetime
    is_active: bool | None = True
    notify_offsets: list[int] | None = Field(
        default=None,
        description="Notification offsets in minutes before start (e.g. [10080, 1440, 15])",
    )


class MaintenanceWindowUpdate(BaseModel):
    title: str | None = None
    message: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    is_active: bool | None = None
    notify_offsets: list[int] | None = Field(
        default=None, description="Notification offsets in minutes before start"
    )


def _naive_utc(dt: datetime) -> datetime:
    """Convert a timezone-aware datetime to naive UTC."""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


# ─── Maintenance Window Endpoints ───────────────────────────────────────────


@router.get("/maintenance-windows")
async def list_maintenance_windows(
    active_only: bool = False,
    future_only: bool = False,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List scheduled maintenance windows (admin only)"""
    service = MaintenanceWindowService(db)
    windows = await service.list_windows(
        active_only=active_only,
        future_only=future_only,
    )
    return {"windows": windows}


@router.post("/maintenance-windows")
async def create_maintenance_window(
    data: MaintenanceWindowCreate,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Create a new scheduled maintenance window (admin only)"""
    service = MaintenanceWindowService(db)
    try:
        window = await service.create_window(
            title=data.title,
            message=data.message,
            start_at=_naive_utc(data.start_at),
            end_at=_naive_utc(data.end_at),
            created_by=str(current_user.id),
            is_active=data.is_active if data.is_active is not None else True,
            notify_offsets=data.notify_offsets,
        )
        return {"success": True, "window": window.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/maintenance-windows/{window_id}")
async def get_maintenance_window(
    window_id: str,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get a single maintenance window (admin only)"""
    service = MaintenanceWindowService(db)
    window = await service.get_window(window_id)
    if not window:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    return {"window": window.to_dict()}


@router.put("/maintenance-windows/{window_id}")
async def update_maintenance_window(
    window_id: str,
    data: MaintenanceWindowUpdate,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update a maintenance window (admin only)"""
    service = MaintenanceWindowService(db)
    try:
        window = await service.update_window(
            window_id=window_id,
            title=data.title,
            message=data.message,
            start_at=_naive_utc(data.start_at) if data.start_at else None,
            end_at=_naive_utc(data.end_at) if data.end_at else None,
            is_active=data.is_active,
            notify_offsets=data.notify_offsets,
        )
        return {"success": True, "window": window.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/maintenance-windows/{window_id}")
async def delete_maintenance_window(
    window_id: str,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Delete a maintenance window (admin only)"""
    service = MaintenanceWindowService(db)
    deleted = await service.delete_window(window_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    return {"success": True, "message": "Maintenance window deleted"}
