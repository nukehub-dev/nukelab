"""
Permission checking functions and decorators.
"""

from typing import List, Set
from fastapi import HTTPException, status
from app.core.permissions import Permission
from app.core.roles import get_role_permissions
from app.models.user import User


# Permission implication map: having the key implies you also have the values
PERMISSION_IMPLICATIONS = {
    Permission.ALL: set(Permission.all_permissions()),
    # Servers
    Permission.SERVERS_READ_ALL: {Permission.SERVERS_READ_OWN},
    Permission.SERVERS_WRITE_ALL: {Permission.SERVERS_WRITE_OWN, Permission.SERVERS_READ_ALL, Permission.SERVERS_READ_OWN},
    Permission.SERVERS_ACCESS_OTHERS: {Permission.SERVERS_READ_ALL, Permission.SERVERS_READ_OWN},
    # Volumes
    Permission.VOLUMES_READ_ALL: {Permission.VOLUMES_READ_OWN},
    Permission.VOLUMES_WRITE_ALL: {Permission.VOLUMES_WRITE_OWN, Permission.VOLUMES_READ_ALL, Permission.VOLUMES_READ_OWN},
    # Workspaces
    Permission.WORKSPACES_READ_ALL: {Permission.WORKSPACES_READ_OWN},
    Permission.WORKSPACES_WRITE_ALL: {Permission.WORKSPACES_WRITE_OWN, Permission.WORKSPACES_READ_ALL, Permission.WORKSPACES_READ_OWN},
    # Credits
    Permission.CREDITS_READ_ALL: {Permission.CREDITS_READ_OWN},
}


def _expand_permissions(permissions: List[str]) -> Set[str]:
    """Expand a permission list to include all implied permissions."""
    result = set(permissions)
    changed = True
    while changed:
        changed = False
        for perm in list(result):
            implied = PERMISSION_IMPLICATIONS.get(perm, set())
            for imp in implied:
                if imp not in result:
                    result.add(imp)
                    changed = True
    return result


def get_user_permissions(user: User) -> List[str]:
    """Get all permissions for a user based on their role"""
    if not user or not user.role:
        return []
    
    permissions = get_role_permissions(user.role)
    return permissions if permissions else []


def has_permission(user: User, permission: str) -> bool:
    """Check if user has a specific permission (including implied permissions)"""
    if not user or not user.is_active:
        return False
    
    user_perms = _expand_permissions(get_user_permissions(user))
    return permission in user_perms


def has_any_permission(user: User, permissions: List[str]) -> bool:
    """Check if user has any of the specified permissions (including implied)"""
    if not user or not user.is_active:
        return False
    
    user_perms = _expand_permissions(get_user_permissions(user))
    return any(perm in user_perms for perm in permissions)


def has_all_permissions(user: User, permissions: List[str]) -> bool:
    """Check if user has all specified permissions (including implied)"""
    if not user or not user.is_active:
        return False
    
    user_perms = _expand_permissions(get_user_permissions(user))
    return all(perm in user_perms for perm in permissions)


def check_permission(user: User, permission: str):
    """Check permission and raise 403 if not allowed"""
    if not has_permission(user, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )


def check_any_permission(user: User, permissions: List[str]):
    """Check any permission and raise 403 if none allowed"""
    if not has_any_permission(user, permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
