"""
Permission checking functions and decorators.
"""

from typing import List
from fastapi import HTTPException, status
from app.core.permissions import Permission
from app.core.roles import get_role_permissions
from app.models.user import User


def get_user_permissions(user: User) -> List[str]:
    """Get all permissions for a user based on their role"""
    if not user or not user.role:
        return []
    
    permissions = get_role_permissions(user.role)
    return permissions if permissions else []


def has_permission(user: User, permission: str) -> bool:
    """Check if user has a specific permission"""
    if not user or not user.is_active:
        return False
    
    permissions = get_user_permissions(user)
    
    # Super admin wildcard
    if Permission.ALL in permissions:
        return True
    
    return permission in permissions


def has_any_permission(user: User, permissions: List[str]) -> bool:
    """Check if user has any of the specified permissions"""
    if not user or not user.is_active:
        return False
    
    user_perms = get_user_permissions(user)
    
    # Super admin wildcard
    if Permission.ALL in user_perms:
        return True
    
    return any(perm in user_perms for perm in permissions)


def has_all_permissions(user: User, permissions: List[str]) -> bool:
    """Check if user has all specified permissions"""
    if not user or not user.is_active:
        return False
    
    user_perms = get_user_permissions(user)
    
    # Super admin wildcard
    if Permission.ALL in user_perms:
        return True
    
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
