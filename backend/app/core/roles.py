"""
Role-Permission Matrix
Defines which permissions each role has.
"""

from app.core.permissions import Permission


# Role to permissions mapping
ROLE_PERMISSIONS = {
    "super_admin": [Permission.ALL],
    
    "admin": [
        Permission.USERS_READ,
        Permission.USERS_CREATE,
        Permission.USERS_UPDATE,
        Permission.USERS_DELETE,
        Permission.SERVERS_READ_ALL,
        Permission.SERVERS_MANAGE,
        Permission.RESOURCES_READ_ALL,
        Permission.ENVIRONMENTS_MANAGE,
        Permission.PLANS_MANAGE,
        Permission.CREDITS_READ,
        Permission.CREDITS_GRANT,
        Permission.CREDITS_DEDUCT,
        Permission.AUDIT_READ,
        Permission.ADMIN_ACCESS,
    ],
    
    "moderator": [
        Permission.USERS_READ,
        Permission.USERS_CREATE,
        Permission.USERS_UPDATE,
        Permission.SERVERS_READ_ALL,
        Permission.RESOURCES_READ_ALL,
        Permission.CREDITS_READ,
    ],
    
    "support": [
        Permission.USERS_READ,
        Permission.SERVERS_READ_ALL,
        Permission.SERVERS_START,
        Permission.SERVERS_STOP,
        Permission.RESOURCES_READ_ALL,
        Permission.CREDITS_READ,
    ],
    
    "user": [
        Permission.SERVERS_READ_OWN,
        Permission.SERVERS_START,
        Permission.SERVERS_STOP,
        Permission.SERVERS_DELETE,
        Permission.RESOURCES_READ_OWN,
        Permission.CREDITS_READ,
    ],
    
    "guest": [
        Permission.SERVERS_READ_OWN,
    ],
}


# Valid roles
VALID_ROLES = list(ROLE_PERMISSIONS.keys())


def get_role_permissions(role: str) -> list:
    """Get permissions for a role"""
    return ROLE_PERMISSIONS.get(role, [])


def is_valid_role(role: str) -> bool:
    """Check if role is valid"""
    return role in VALID_ROLES
