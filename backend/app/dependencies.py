"""
FastAPI dependencies for authentication and authorization.
"""

from typing import List
from fastapi import Depends, HTTPException, status, Response
from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.core.security import has_permission, has_any_permission
from app.models.user import User


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Get current user and verify they are active"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    return current_user


async def _permission_checker(*permissions: str, current_user: User = Depends(get_current_active_user)):
    """Base permission checker"""
    if not has_any_permission(current_user, list(permissions)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Required: {', '.join(permissions)}"
        )
    return current_user


def require_permissions(*permissions: str):
    """
    Dependency factory to require specific permissions.
    
    Usage:
        @router.get("/users")
        async def list_users(
            current_user: User = Depends(require_permissions(Permission.USERS_READ))
        ):
            ...
    """
    async def checker(current_user: User = Depends(get_current_active_user)):
        if not has_any_permission(current_user, list(permissions)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {', '.join(permissions)}"
            )
        return current_user
    
    return checker


def require_admin(current_user: User = Depends(get_current_active_user)):
    """Require admin access"""
    if not has_permission(current_user, Permission.ADMIN_ACCESS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


class PermissionChecker:
    """
    Class-based permission checker for more complex scenarios.
    
    Usage:
        @router.get("/servers/{server_id}")
        async def get_server(
            server_id: str,
            current_user: User = Depends(get_current_active_user)
        ):
            checker = PermissionChecker(current_user)
            checker.require_any([Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL])
            ...
    """
    
    def __init__(self, user: User):
        self.user = user
    
    def require(self, permission: str):
        """Require a specific permission"""
        if not has_permission(self.user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}"
            )
    
    def require_any(self, permissions: List[str]):
        """Require any of the specified permissions"""
        if not has_any_permission(self.user, permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of these permissions required: {', '.join(permissions)}"
            )
    
    def require_all(self, permissions: List[str]):
        """Require all specified permissions"""
        if not has_all_permissions(self.user, permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"All of these permissions required: {', '.join(permissions)}"
            )
    
    def is_admin(self) -> bool:
        """Check if user is admin"""
        return has_permission(self.user, Permission.ADMIN_ACCESS)
    
    def can_access_resource(self, resource_owner_id: str) -> bool:
        """
        Check if user can access a resource.
        Users can access their own resources, admins can access all.
        """
        if self.is_admin():
            return True
        return str(self.user.id) == str(resource_owner_id)


# Convenience aliases
require_user_read = require_permissions(Permission.USERS_READ)
require_user_create = require_permissions(Permission.USERS_CREATE)
require_user_update = require_permissions(Permission.USERS_UPDATE)
require_user_delete = require_permissions(Permission.USERS_DELETE)
require_server_read = require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)
require_server_write_own = require_permissions(Permission.SERVERS_WRITE_OWN)
require_server_write_all = require_permissions(Permission.SERVERS_WRITE_ALL)
require_volume_read = require_permissions(Permission.VOLUMES_READ_OWN, Permission.VOLUMES_READ_ALL)
require_volume_write_own = require_permissions(Permission.VOLUMES_WRITE_OWN)
require_volume_write_all = require_permissions(Permission.VOLUMES_WRITE_ALL)
require_workspace_read = require_permissions(Permission.WORKSPACES_READ_OWN, Permission.WORKSPACES_READ_ALL)
require_workspace_write_own = require_permissions(Permission.WORKSPACES_WRITE_OWN)
require_workspace_write_all = require_permissions(Permission.WORKSPACES_WRITE_ALL)
require_credit_read_own = require_permissions(Permission.CREDITS_READ_OWN)
require_credit_read_all = require_permissions(Permission.CREDITS_READ_ALL)
require_credit_grant = require_permissions(Permission.CREDITS_GRANT)
require_credit_deduct = require_permissions(Permission.CREDITS_DEDUCT)
require_admin_access = require_permissions(Permission.ADMIN_ACCESS)


def no_store_cache(response: Response) -> None:
    """Add Cache-Control: no-store headers to prevent sensitive data caching.

    Should be applied to auth endpoints, admin endpoints, and any route
    that returns tokens, credentials, or personal data.
    """
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, proxy-revalidate"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
