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
    SERVERS_READ_ALL = "servers:read_all"
    SERVERS_START = "servers:start"
    SERVERS_STOP = "servers:stop"
    SERVERS_DELETE = "servers:delete"
    SERVERS_MANAGE = "servers:manage"
    
    # Resources
    RESOURCES_READ_OWN = "resources:read_own"
    RESOURCES_READ_ALL = "resources:read_all"
    
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
    CREDITS_READ = "credits:read"
    CREDITS_GRANT = "credits:grant"
    CREDITS_DEDUCT = "credits:deduct"
    
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
            cls.SERVERS_READ_ALL,
            cls.SERVERS_START,
            cls.SERVERS_STOP,
            cls.SERVERS_DELETE,
            cls.SERVERS_MANAGE,
            cls.RESOURCES_READ_OWN,
            cls.RESOURCES_READ_ALL,
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
            cls.CREDITS_READ,
            cls.CREDITS_GRANT,
            cls.CREDITS_DEDUCT,
            cls.AUDIT_READ,
            cls.ADMIN_ACCESS,
        ]
