"""
Bulk Operations API endpoints.
"""

from typing import List, Dict, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.auth import get_current_user, require_jwt_auth, limiter
from app.api.servers import (
    _perform_server_start,
    _perform_server_stop,
    _perform_server_restart,
    _perform_server_delete,
    _audit_cross_user_access,
)
from app.core.permissions import Permission
from app.core.security import has_permission
from app.services.activity_service import ActivityService
from app.services.notification_service import NotificationService
from app.dependencies import require_permissions, PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server

router = APIRouter()


class BulkServerActionRequest(BaseModel):
    action: str  # start, stop, restart, delete
    server_ids: List[str]
    reason: Optional[str] = None


class BulkActionResponse(BaseModel):
    succeeded: List[str]
    failed: List[Dict[str, str]]
    total: int
    success_count: int
    failure_count: int


@router.post("/servers/bulk-action", response_model=BulkActionResponse)
@limiter.limit("20/minute")
async def bulk_server_action(
    body: BulkServerActionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db)
):
    """Perform bulk action on servers"""

    # Validate action
    valid_actions = ["start", "stop", "restart", "delete"]
    if body.action not in valid_actions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        )

    # Check base permission
    base_permissions = {
        "start": Permission.SERVERS_WRITE_OWN,
        "stop": Permission.SERVERS_WRITE_OWN,
        "restart": Permission.SERVERS_WRITE_OWN,
        "delete": Permission.SERVERS_WRITE_OWN,
    }
    if not has_permission(current_user, base_permissions[body.action]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    succeeded = []
    failed = []
    affected_user_ids: set[str] = set()

    for server_id in body.server_ids:
        try:
            # Get server
            result = await db.execute(
                select(Server).where(Server.id == server_id)
            )
            server = result.scalar_one_or_none()

            if not server:
                failed.append({"server_id": server_id, "error": "Server not found"})
                continue

            # Capture owner before any mutation; deleted servers are no longer
            # queryable after the action commits.
            affected_user_ids.add(str(server.user_id))

            # Check ownership and cross-user access requirements
            is_cross_user = str(server.user_id) != str(current_user.id)
            if is_cross_user:
                # Cross-user access requires JWT authentication — API tokens are not allowed
                auth_context = getattr(request.state, "auth_context", None)
                if not auth_context or auth_context.auth_method != "jwt":
                    failed.append({
                        "server_id": server_id,
                        "error": "Cross-user server access requires JWT authentication. Please log in via the web interface."
                    })
                    continue

                if not has_permission(current_user, Permission.SERVERS_ACCESS_OTHERS):
                    failed.append({"server_id": server_id, "error": "Permission denied"})
                    continue

                # Require reason for cross-user access
                if not body.reason or not body.reason.strip():
                    failed.append({"server_id": server_id, "error": "A reason is required for cross-user server access"})
                    continue

                # Audit cross-user bulk action
                activity_service = ActivityService(db)
                await activity_service.log(
                    action=f"server.bulk_{body.action}",
                    target_type="server",
                    target_id=str(server.id),
                    actor_id=str(current_user.id),
                    details={"reason": body.reason, "server_name": server.name},
                )

                notif_service = NotificationService(db)
                await notif_service.create(
                    user_id=server.user_id,
                    title="Server Accessed",
                    message=f"{current_user.username or 'An admin'} performed {body.action} on your server '{server.name}' with reason: {body.reason}",
                    type="server",
                    severity="warning",
                    action_url=f"/servers/{server.id}",
                    event_key="server_accessed",
                )

            # Perform action using shared helpers
            if body.action == "start":
                if server.status == "running":
                    failed.append({"server_id": server_id, "error": "Server already running"})
                    continue
                await _perform_server_start(server, db, current_user, server_id)

            elif body.action == "stop":
                if server.status == "stopped":
                    failed.append({"server_id": server_id, "error": "Server already stopped"})
                    continue
                await _perform_server_stop(server, db, server_id)

            elif body.action == "restart":
                await _perform_server_restart(server, db, current_user, server_id)

            elif body.action == "delete":
                await _perform_server_delete(server, db, server_id)

            succeeded.append(server_id)

        except HTTPException as e:
            failed.append({"server_id": server_id, "error": e.detail})
        except Exception as e:
            failed.append({"server_id": server_id, "error": str(e)})

    # Invalidate server list caches for affected users and admin lists
    if affected_user_ids:
        from app.api.servers import _invalidate_server_list_cache
        for user_id in affected_user_ids:
            await _invalidate_server_list_cache(user_id)

    return {
        "succeeded": succeeded,
        "failed": failed,
        "total": len(body.server_ids),
        "success_count": len(succeeded),
        "failure_count": len(failed)
    }
