"""
Permission constants for RBAC system.
Each permission represents a specific action that can be performed.
"""


class Permission:
    """Permission constants"""
    
    # User management
    USERS_READ = "users:read"
    USERS_CREATE = "users:create"
    USERS_UPDATE = "users:update"
    USERS_DELETE = "users:delete"
    USERS_IMPERSONATE = "users:impersonate"
    
    # Server management
    SERVERS_READ_OWN = "servers:read_own"
    SERVERS_WRITE_OWN = "servers:write_own"
    SERVERS_READ_ALL = "servers:read_all"
    SERVERS_WRITE_ALL = "servers:write_all"
    SERVERS_ACCESS_OTHERS = "servers:access_others"
    
    # Environment management
    ENVIRONMENT_CREATE = "environment:create"
    ENVIRONMENT_READ = "environment:read"
    ENVIRONMENT_UPDATE = "environment:update"
    ENVIRONMENT_DELETE = "environment:delete"
    
    # Plan management
    PLAN_CREATE = "plan:create"
    PLAN_READ = "plan:read"
    PLAN_UPDATE = "plan:update"
    PLAN_DELETE = "plan:delete"
    
    # Quota management
    QUOTA_READ = "quota:read"
    QUOTA_UPDATE = "quota:update"
    
    # Credit management
    CREDITS_READ_OWN = "credits:read_own"
    CREDITS_READ_ALL = "credits:read_all"
    CREDITS_GRANT = "credits:grant"
    CREDITS_DEDUCT = "credits:deduct"
    
    # Analytics
    ANALYTICS_READ_OWN = "analytics:read_own"
    ANALYTICS_READ = "analytics:read"

    # Workspace management
    WORKSPACES_READ_OWN = "workspaces:read_own"
    WORKSPACES_WRITE_OWN = "workspaces:write_own"
    WORKSPACES_READ_ALL = "workspaces:read_all"
    WORKSPACES_WRITE_ALL = "workspaces:write_all"

    # Volume management
    VOLUMES_READ_OWN = "volumes:read_own"
    VOLUMES_WRITE_OWN = "volumes:write_own"
    VOLUMES_READ_ALL = "volumes:read_all"
    VOLUMES_WRITE_ALL = "volumes:write_all"

    # Audit
    AUDIT_READ = "audit:read"

    # Admin dashboard
    ADMIN_ACCESS = "admin:access"

    # Super admin wildcard
    ALL = "*"
    
    @classmethod
    def all_permissions(cls):
        """Return list of all permission strings"""
        return [
            cls.USERS_READ,
            cls.USERS_CREATE,
            cls.USERS_UPDATE,
            cls.USERS_DELETE,
            cls.USERS_IMPERSONATE,
            cls.SERVERS_READ_OWN,
            cls.SERVERS_WRITE_OWN,
            cls.SERVERS_READ_ALL,
            cls.SERVERS_WRITE_ALL,
            cls.SERVERS_ACCESS_OTHERS,
            cls.ENVIRONMENT_CREATE,
            cls.ENVIRONMENT_READ,
            cls.ENVIRONMENT_UPDATE,
            cls.ENVIRONMENT_DELETE,
            cls.PLAN_CREATE,
            cls.PLAN_READ,
            cls.PLAN_UPDATE,
            cls.PLAN_DELETE,
            cls.QUOTA_READ,
            cls.QUOTA_UPDATE,
            cls.CREDITS_READ_OWN,
            cls.CREDITS_READ_ALL,
            cls.CREDITS_GRANT,
            cls.CREDITS_DEDUCT,
            cls.ANALYTICS_READ_OWN,
            cls.ANALYTICS_READ,
            cls.WORKSPACES_READ_OWN,
            cls.WORKSPACES_WRITE_OWN,
            cls.WORKSPACES_READ_ALL,
            cls.WORKSPACES_WRITE_ALL,
            cls.VOLUMES_READ_OWN,
            cls.VOLUMES_WRITE_OWN,
            cls.VOLUMES_READ_ALL,
            cls.VOLUMES_WRITE_ALL,
            cls.AUDIT_READ,
            cls.ADMIN_ACCESS,
        ]
