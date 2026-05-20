"""
Environment Template API endpoints.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user, require_permissions
from app.api.auth import require_scopes, require_jwt_auth
from app.core.permissions import Permission
from app.services.environment_service import EnvironmentService

router = APIRouter(tags=["environments"])


@router.get("/")
async def list_environments(
    category: Optional[str] = None,
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user = Depends(get_current_user),
    _ = Depends(require_scopes("environments:read")),
    db: AsyncSession = Depends(get_db)
):
    """List environment templates"""
    service = EnvironmentService(db)
    result = await service.list_environments(
        category=category,
        is_active=is_active,
        search=search,
        page=page,
        limit=limit
    )
    return {"success": True, "data": result}


@router.get("/{env_id}")
async def get_environment(
    env_id: str,
    current_user = Depends(get_current_user),
    _ = Depends(require_scopes("environments:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get environment template details"""
    service = EnvironmentService(db)
    env = await service.get_by_id(env_id)
    if not env:
        return {"success": False, "error": "Environment not found"}
    return {"success": True, "data": env.to_dict()}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_environment(
    data: dict,
    current_user = Depends(require_permissions(Permission.ENVIRONMENT_CREATE)),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Create new environment template (admin only)"""
    service = EnvironmentService(db)
    env = await service.create_environment(
        name=data["name"],
        slug=data["slug"],
        image=data["image"],
        description=data.get("description"),
        dockerfile=data.get("dockerfile"),
        packages=data.get("packages"),
        environment_variables=data.get("environment_variables"),
        volumes=data.get("volumes"),
        ports=data.get("ports"),
        icon=data.get("icon"),
        color=data.get("color"),
        category=data.get("category"),
        is_public=data.get("is_public", True),
        created_by=str(current_user.id)
    )
    return {"success": True, "data": env.to_dict(), "message": "Environment created"}


@router.put("/{env_id}")
async def update_environment(
    env_id: str,
    data: dict,
    current_user = Depends(require_permissions(Permission.ENVIRONMENT_UPDATE)),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Update environment template (admin only)"""
    service = EnvironmentService(db)
    env = await service.update_environment(env_id, **data)
    return {"success": True, "data": env.to_dict(), "message": "Environment updated"}


@router.delete("/{env_id}")
async def deactivate_environment(
    env_id: str,
    current_user = Depends(require_permissions(Permission.ENVIRONMENT_DELETE)),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate environment template (admin only)"""
    service = EnvironmentService(db)
    env = await service.deactivate_environment(env_id)
    return {"success": True, "data": env.to_dict(), "message": "Environment deactivated"}


@router.delete("/{env_id}/permanent")
async def delete_environment(
    env_id: str,
    current_user = Depends(require_permissions(Permission.ENVIRONMENT_DELETE)),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Permanently delete environment template (admin only)"""
    service = EnvironmentService(db)
    await service.delete_environment(env_id)
    return {"success": True, "message": "Environment permanently deleted"}


@router.post("/{env_id}/activate")
async def activate_environment(
    env_id: str,
    current_user = Depends(require_permissions(Permission.ENVIRONMENT_UPDATE)),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Activate environment template (admin only)"""
    service = EnvironmentService(db)
    env = await service.activate_environment(env_id)
    return {"success": True, "data": env.to_dict(), "message": "Environment activated"}


@router.post("/{env_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_environment(
    env_id: str,
    data: dict,
    current_user = Depends(require_permissions(Permission.ENVIRONMENT_CREATE)),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Clone environment template (admin only)"""
    service = EnvironmentService(db)
    env = await service.clone_environment(
        env_id=env_id,
        new_name=data["name"],
        new_slug=data["slug"]
    )
    return {"success": True, "data": env.to_dict(), "message": "Environment cloned"}
