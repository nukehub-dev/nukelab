from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.dependencies import get_current_user, require_permissions
from app.core.permissions import Permission
from app.models.user import User
from app.models.server import Server
from app.config import settings
from app.api.auth import require_scopes, require_jwt_auth

router = APIRouter(tags=["system"])


class SystemConfigUpdate(BaseModel):
    maintenance_mode: Optional[bool] = None
    maintenance_message: Optional[str] = None
    daily_allowance_default: Optional[int] = None


@router.get("/health")
async def health_check():
    """Public health check endpoint"""
    if settings.maintenance_mode:
        return JSONResponse(
            status_code=503,
            content={
                "status": "maintenance",
                "message": settings.maintenance_message
            }
        )
    
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@router.get("/config")
async def get_system_config(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt = Depends(require_jwt_auth()),
):
    """Get system configuration (admin only)"""
    return {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "app_debug": settings.app_debug,
        "maintenance_mode": settings.maintenance_mode,
        "maintenance_message": settings.maintenance_message,
    }


@router.put("/config")
async def update_system_config(
    config: SystemConfigUpdate,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt = Depends(require_jwt_auth()),
):
    """Update system configuration (admin only)"""
    updates = {}
    
    if config.maintenance_mode is not None:
        settings.maintenance_mode = config.maintenance_mode
        updates["maintenance_mode"] = config.maintenance_mode
    
    if config.maintenance_message is not None:
        settings.maintenance_message = config.maintenance_message
        updates["maintenance_message"] = config.maintenance_message
    
    if config.daily_allowance_default is not None:
        updates["daily_allowance_default"] = config.daily_allowance_default
    
    return {
        "success": True,
        "updates": updates,
        "message": "Configuration updated"
    }


@router.post("/maintenance")
async def toggle_maintenance(
    enabled: bool,
    message: Optional[str] = None,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt = Depends(require_jwt_auth()),
):
    """Toggle maintenance mode (admin only)"""
    settings.maintenance_mode = enabled
    if message:
        settings.maintenance_message = message
    elif enabled:
        settings.maintenance_message = "System under maintenance"
    
    return {
        "success": True,
        "maintenance_mode": settings.maintenance_mode,
        "message": settings.maintenance_message
    }


@router.get("/stats")
async def get_system_stats(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Get system statistics (admin only)"""
    total_users_result = await db.execute(select(func.count()).select_from(User))
    total_users = total_users_result.scalar()
    
    active_users_result = await db.execute(
        select(func.count()).where(User.is_active == True)
    )
    active_users = active_users_result.scalar()
    
    total_servers_result = await db.execute(select(func.count()).select_from(Server))
    total_servers = total_servers_result.scalar()
    
    running_servers_result = await db.execute(
        select(func.count()).where(Server.status == "running")
    )
    running_servers = running_servers_result.scalar()
    
    total_credits_result = await db.execute(
        select(func.sum(User.nuke_balance)).where(User.is_active == True)
    )
    total_credits = total_credits_result.scalar() or 0
    
    return {
        "users": {"total": total_users, "active": active_users},
        "servers": {"total": total_servers, "running": running_servers},
        "credits": {"total": total_credits},
        "timestamp": datetime.utcnow().isoformat()
    }