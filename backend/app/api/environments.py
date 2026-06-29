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

    Users with 'environment:read' permission see all environments.
    Other authenticated users only see public, active environments.
    """
    can_read_all = has_permission(current_user, Permission.ENVIRONMENT_READ)
    service = EnvironmentService(db)
    result = await service.list_environments(
        category=category,
        is_active=is_active if can_read_all else True,
        search=search,
        page=page,
        limit=limit,
    )

    # Filter to public-only for non-admin users
    if not can_read_all:
        items = result.get("items", [])
        result["items"] = [
            env for env in items if env.get("is_public") and env.get("is_active", True)
        ]
        result["total"] = len(result["items"])

    return {"success": True, "data": result}


@router.get("/{env_id}")
async def get_environment(
    env_id: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Get environment template details.

    Users with 'environment:read' permission can view any environment.
    Other authenticated users can only view public, active environments.
    """
    service = EnvironmentService(db)
    env = await service.get_by_id(env_id)
    if not env:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")

    env_dict = env.to_dict()
    can_read_all = has_permission(current_user, Permission.ENVIRONMENT_READ)

    if not can_read_all and (not env_dict.get("is_public") or not env_dict.get("is_active", True)):
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
