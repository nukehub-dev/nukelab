"""
Permission checking functions and decorators.
"""

from fastapi import HTTPException, status

from app.core.roles import get_expanded_role_permissions, get_role_permissions
from app.models.user import User


def get_user_permissions(user: User) -> list:
    """Get all raw (unexpanded) permissions for a user based on their role.

    Kept for backward compatibility with callers that expect a list.
    """
    if not user or not user.role:
        return []
    permissions = get_role_permissions(user.role)
    return permissions if permissions else []


def has_permission(user: User, permission: str) -> bool:
    """Check if user has a specific permission (including implied permissions).

    Uses the precomputed expanded-permission cache in ``roles.py`` for O(1)
    lookup instead of re-running the implication-expansion loop on every call.
    """
    if not user or not user.is_active:
        return False
    user_perms = get_expanded_role_permissions(user.role)
    return permission in user_perms


def has_any_permission(user: User, permissions: list[str]) -> bool:
    """Check if user has any of the specified permissions (including implied)"""
    if not user or not user.is_active:
        return False
    user_perms = get_expanded_role_permissions(user.role)
    return any(perm in user_perms for perm in permissions)


def has_all_permissions(user: User, permissions: list[str]) -> bool:
    """Check if user has all specified permissions (including implied)"""
    if not user or not user.is_active:
        return False
    user_perms = get_expanded_role_permissions(user.role)
    return all(perm in user_perms for perm in permissions)


def check_permission(user: User, permission: str):
    """Check permission and raise 403 if not allowed"""
    if not has_permission(user, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )


def check_any_permission(user: User, permissions: list[str]):
    """Check any permission and raise 403 if none allowed"""
    if not has_any_permission(user, permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
