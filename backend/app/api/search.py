# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Grouped, permission-scoped search API endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.core.security import has_any_permission, has_permission
from app.db.session import get_db
from app.dependencies import PermissionChecker
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.user import User
from app.models.volume import Volume
from app.models.workspace_invitation import WorkspaceInvitation

router = APIRouter()

_SEARCH_GROUPS = ("servers", "volumes", "workspaces", "environments", "users")


@router.get("/")
async def search(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(5, ge=1, le=20),
    group: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search across servers, volumes, workspaces, environments, and users.

    Every authenticated user can search something: groups whose read permission
    the user lacks are omitted from the response instead of returning 403.
    Each group is a case-insensitive substring match ordered by name with at
    most ``limit`` items. Pass ``group`` to search only a single group.
    """
    if group is not None and group not in _SEARCH_GROUPS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid group. Must be one of: {', '.join(_SEARCH_GROUPS)}",
        )

    pattern = f"%{q}%"
    checker = PermissionChecker(current_user)
    groups = {group} if group else set(_SEARCH_GROUPS)
    results: dict[str, list[dict]] = {}

    if "servers" in groups and has_permission(current_user, Permission.SERVERS_READ_OWN):
        query = select(Server).where(Server.name.ilike(pattern))
        if not (
            checker.is_admin() or has_any_permission(current_user, [Permission.SERVERS_READ_ALL])
        ):
            query = query.where(Server.user_id == current_user.id)
        result = await db.execute(query.order_by(Server.name).limit(limit))
        results["servers"] = [
            {"id": str(s.id), "name": s.name, "status": s.status} for s in result.scalars().all()
        ]

    if "volumes" in groups and has_permission(current_user, Permission.VOLUMES_READ_OWN):
        query = select(Volume).where(
            or_(Volume.name.ilike(pattern), Volume.display_name.ilike(pattern))
        )
        if not (
            checker.is_admin() or has_any_permission(current_user, [Permission.VOLUMES_READ_ALL])
        ):
            query = query.where(Volume.owner_id == current_user.id)
        result = await db.execute(query.order_by(Volume.name).limit(limit))
        results["volumes"] = [
            {
                "id": str(v.id),
                "name": v.name,
                "display_name": v.display_name,
                "size_bytes": v.size_bytes or 0,
                "status": v.status,
            }
            for v in result.scalars().all()
        ]

    if "workspaces" in groups and has_permission(current_user, Permission.WORKSPACES_READ_OWN):
        query = select(SharedWorkspace).where(
            SharedWorkspace.is_active.is_(True),
            SharedWorkspace.name.ilike(pattern),
        )
        if not (
            checker.is_admin() or has_any_permission(current_user, [Permission.WORKSPACES_READ_ALL])
        ):
            # Same own/member/invited scoping as the workspaces list endpoint.
            query = query.where(
                or_(
                    SharedWorkspace.owner_id == current_user.id,
                    SharedWorkspace.members.any(WorkspaceMember.user_id == current_user.id),
                    SharedWorkspace.invitations.any(
                        and_(
                            WorkspaceInvitation.user_id == current_user.id,
                            WorkspaceInvitation.status == "pending",
                        )
                    ),
                )
            )
        result = await db.execute(query.order_by(SharedWorkspace.name).limit(limit))
        results["workspaces"] = [{"id": str(w.id), "name": w.name} for w in result.scalars().all()]

    if "environments" in groups and has_permission(current_user, Permission.ENVIRONMENT_READ):
        # Mirrors the environments list: holders of environment:read see all
        # templates, so no is_active/is_public filter is applied here.
        result = await db.execute(
            select(EnvironmentTemplate)
            .where(
                or_(
                    EnvironmentTemplate.name.ilike(pattern),
                    EnvironmentTemplate.slug.ilike(pattern),
                )
            )
            .order_by(EnvironmentTemplate.name)
            .limit(limit)
        )
        results["environments"] = [
            {"id": str(e.id), "name": e.name, "slug": e.slug, "category": e.category}
            for e in result.scalars().all()
        ]

    if "users" in groups and has_permission(current_user, Permission.USERS_READ):
        result = await db.execute(
            select(User)
            .where(
                or_(
                    User.username.ilike(pattern),
                    User.email.ilike(pattern),
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                )
            )
            .order_by(User.username)
            .limit(limit)
        )
        results["users"] = [
            {"id": str(u.id), "username": u.username, "email": u.email}
            for u in result.scalars().all()
        ]

    return results
