"""
Bulk Operations API endpoints.
"""

from typing import List, Dict
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.auth import get_current_user, require_scopes
from app.core.permissions import Permission
from app.core.security import has_permission
from app.dependencies import require_permissions
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server

router = APIRouter()


class BulkServerActionRequest(BaseModel):
    action: str  # start, stop, restart, delete
    server_ids: List[str]


class BulkActionResponse(BaseModel):
    succeeded: List[str]
    failed: List[Dict[str, str]]
    total: int
    success_count: int
    failure_count: int


@router.post("/servers/bulk-action", response_model=BulkActionResponse)
async def bulk_server_action(
    request: BulkServerActionRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("bulk:execute")),
    db: AsyncSession = Depends(get_db)
):
    """Perform bulk action on servers"""
    
    # Validate action
    valid_actions = ["start", "stop", "restart", "delete"]
    if request.action not in valid_actions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action. Must be one of: {', '.join(valid_actions)}"
        )
    
    # Check permission based on action
    if request.action == "start":
        PermissionChecker = require_permissions(Permission.SERVERS_START)
    elif request.action == "stop":
        PermissionChecker = require_permissions(Permission.SERVERS_STOP)
    elif request.action == "restart":
        PermissionChecker = require_permissions(Permission.SERVERS_MANAGE)
    elif request.action == "delete":
        PermissionChecker = require_permissions(Permission.SERVERS_DELETE)
    
    succeeded = []
    failed = []
    
    for server_id in request.server_ids:
        try:
            # Get server
            result = await db.execute(
                select(Server).where(Server.id == server_id)
            )
            server = result.scalar_one_or_none()
            
            if not server:
                failed.append({"server_id": server_id, "error": "Server not found"})
                continue
            
            # Check ownership
            if str(server.user_id) != str(current_user.id):
                # Need permission to manage other users' servers
                if not has_permission(current_user, Permission.SERVERS_MANAGE):
                    failed.append({"server_id": server_id, "error": "Permission denied"})
                    continue
            
            # Perform action
            if request.action == "start":
                if server.status == "running":
                    failed.append({"server_id": server_id, "error": "Server already running"})
                    continue
                # TODO: Implement actual start logic
                server.status = "running"
                
            elif request.action == "stop":
                if server.status == "stopped":
                    failed.append({"server_id": server_id, "error": "Server already stopped"})
                    continue
                # TODO: Implement actual stop logic
                server.status = "stopped"
                
            elif request.action == "restart":
                # TODO: Implement actual restart logic
                server.status = "running"
                
            elif request.action == "delete":
                await db.delete(server)
                await db.commit()
                succeeded.append(server_id)
                continue
            
            await db.commit()
            succeeded.append(server_id)
            
        except Exception as e:
            failed.append({"server_id": server_id, "error": str(e)})
    
    return {
        "succeeded": succeeded,
        "failed": failed,
        "total": len(request.server_ids),
        "success_count": len(succeeded),
        "failure_count": len(failed)
    }