# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Environment Template API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_jwt_auth
from app.core.permissions import Permission
from app.core.security import has_permission
from app.db.session import get_db
from app.dependencies import get_current_user, require_permissions
from app.services.environment_service import EnvironmentService

router = APIRouter(tags=["environments"])


@router.get("/")
async def list_environments(
    category: str | None = None,
    is_active: bool | None = Query(None),
    search: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List environment templates.

    Admins see all environments.
    Other authenticated users only see public, active environments.
    """
    is_admin = has_permission(current_user, Permission.ADMIN_ACCESS) or has_permission(
        current_user, Permission.ALL
    )
    service = EnvironmentService(db)
    result = await service.list_environments(
        category=category,
        is_active=is_active if is_admin else True,
        search=search,
        user_role=current_user.role,
        page=page,
        limit=limit,
    )

    return {"success": True, "data": result}


@router.get("/{env_id}")
async def get_environment(
    env_id: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Get environment template details.

    Admins can view any environment.
    Other authenticated users can only view public, active environments.
    """
    service = EnvironmentService(db)
    env = await service.get_by_id(env_id)
    if not env:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")

    env_dict = env.to_dict()
    is_admin = has_permission(current_user, Permission.ADMIN_ACCESS) or has_permission(
        current_user, Permission.ALL
    )

    if not is_admin and (not env.is_public or not env.is_active):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return {"success": True, "data": env_dict}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_environment(
    data: dict,
    current_user=Depends(require_permissions(Permission.ENVIRONMENT_CREATE)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Create new environment template"""
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
        created_by=str(current_user.id),
    )
    return {"success": True, "data": env.to_dict(), "message": "Environment created"}


@router.put("/{env_id}")
async def update_environment(
    env_id: str,
    data: dict,
    current_user=Depends(require_permissions(Permission.ENVIRONMENT_UPDATE)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update environment template"""
    service = EnvironmentService(db)
    env = await service.update_environment(env_id, **data)
    return {"success": True, "data": env.to_dict(), "message": "Environment updated"}


@router.delete("/{env_id}")
async def deactivate_environment(
    env_id: str,
    current_user=Depends(require_permissions(Permission.ENVIRONMENT_DELETE)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate environment template"""
    service = EnvironmentService(db)
    env = await service.deactivate_environment(env_id)
    return {"success": True, "data": env.to_dict(), "message": "Environment deactivated"}


@router.delete("/{env_id}/permanent")
async def delete_environment(
    env_id: str,
    current_user=Depends(require_permissions(Permission.ENVIRONMENT_DELETE)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete environment template"""
    service = EnvironmentService(db)
    await service.delete_environment(env_id)
    return {"success": True, "message": "Environment permanently deleted"}


@router.post("/{env_id}/activate")
async def activate_environment(
    env_id: str,
    current_user=Depends(require_permissions(Permission.ENVIRONMENT_UPDATE)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Activate environment template"""
    service = EnvironmentService(db)
    env = await service.activate_environment(env_id)
    return {"success": True, "data": env.to_dict(), "message": "Environment activated"}


@router.post("/{env_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_environment(
    env_id: str,
    data: dict,
    current_user=Depends(require_permissions(Permission.ENVIRONMENT_CREATE)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Clone environment template"""
    service = EnvironmentService(db)
    env = await service.clone_environment(
        env_id=env_id, new_name=data["name"], new_slug=data["slug"]
    )
    return {"success": True, "data": env.to_dict(), "message": "Environment cloned"}
