"""
Role-Permission Matrix
Defines which permissions each role has.

Hierarchy (most to least privileges):
  super_admin > admin > moderator > support > user > guest

Design principles:
1. Each role has all permissions of roles below it (with some exceptions)
2. Moderators are junior admins - can manage users and servers but not system settings
3. Support staff handle day-to-day server operations and can view users
4. Users only manage their own resources
"""

from app.core.permissions import Permission


# Role to permissions mapping
ROLE_PERMISSIONS = {
    "super_admin": [Permission.ALL],
    
    "admin": [
        # User management (full)
        Permission.USERS_READ,
        Permission.USERS_CREATE,
        Permission.USERS_UPDATE,
        Permission.USERS_DELETE,
        Permission.USERS_IMPERSONATE,
        # Server management (full)
        Permission.SERVERS_READ_ALL,
        Permission.SERVERS_START,
        Permission.SERVERS_STOP,
        Permission.SERVERS_DELETE,
        Permission.SERVERS_MANAGE,
        # Resources (full)
        Permission.RESOURCES_READ_ALL,
        # Environment management
        Permission.ENVIRONMENT_CREATE,
        Permission.ENVIRONMENT_READ,
        Permission.ENVIRONMENT_UPDATE,
        Permission.ENVIRONMENT_DELETE,
        # Plan management
        Permission.PLAN_CREATE,
        Permission.PLAN_READ,
        Permission.PLAN_UPDATE,
        Permission.PLAN_DELETE,
        # Quota management
        Permission.QUOTA_READ,
        Permission.QUOTA_UPDATE,
        # Credit management
        Permission.CREDITS_READ,
        Permission.CREDITS_GRANT,
        Permission.CREDITS_DEDUCT,
        # Audit
        Permission.AUDIT_READ,
        # Admin dashboard
        Permission.ADMIN_ACCESS,
    ],
    
    "moderator": [
        # User management (can create/update but not delete/impersonate)
        Permission.USERS_READ,
        Permission.USERS_CREATE,
        Permission.USERS_UPDATE,
        # Server management (full - can manage all servers)
        Permission.SERVERS_READ_ALL,
        Permission.SERVERS_START,
        Permission.SERVERS_STOP,
        Permission.SERVERS_DELETE,
        Permission.SERVERS_MANAGE,
        # Resources (full)
        Permission.RESOURCES_READ_ALL,
        # Environment (read only)
        Permission.ENVIRONMENT_READ,
        # Plan (read only)
        Permission.PLAN_READ,
        # Credits (view only)
        Permission.CREDITS_READ,
    ],
    
    "support": [
        # User management (view only)
        Permission.USERS_READ,
        # Server management (start/stop/restart but not delete)
        Permission.SERVERS_READ_ALL,
        Permission.SERVERS_START,
        Permission.SERVERS_STOP,
        # Resources (read all)
        Permission.RESOURCES_READ_ALL,
        # Credits (view only)
        Permission.CREDITS_READ,
    ],
    
    "user": [
        # Own servers only
        Permission.SERVERS_READ_OWN,
        Permission.SERVERS_START,
        Permission.SERVERS_STOP,
        Permission.SERVERS_DELETE,
        # Own resources
        Permission.RESOURCES_READ_OWN,
        # Credits (view own)
        Permission.CREDITS_READ,
    ],
    
    "guest": [
        # Read-only access to own resources
        Permission.SERVERS_READ_OWN,
        Permission.RESOURCES_READ_OWN,
    ],
}


# Valid roles ordered by privilege level
VALID_ROLES = list(ROLE_PERMISSIONS.keys())


# Role hierarchy for inheritance checks
ROLE_HIERARCHY = {
    'super_admin': 5,
    'admin': 4,
    'moderator': 3,
    'support': 2,
    'user': 1,
    'guest': 0,
}


def get_role_permissions(role: str) -> list:
    """Get permissions for a role"""
    return ROLE_PERMISSIONS.get(role, [])


def is_valid_role(role: str) -> bool:
    """Check if role is valid"""
    return role in VALID_ROLES


def get_role_level(role: str) -> int:
    """Get privilege level of a role (higher = more privileges)"""
    return ROLE_HIERARCHY.get(role, -1)


def has_higher_or_equal_role(user_role: str, required_role: str) -> bool:
    """Check if user_role has equal or higher privileges than required_role"""
    return get_role_level(user_role) >= get_role_level(required_role)
