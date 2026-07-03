# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Role-Permission Matrix
Defines which permissions each role has.

Hierarchy (most to least privileges):
  super_admin > admin > moderator > support > user > guest

Design principles:
1. Higher permissions imply lower ones (read_all → read_own, write_all → write_own + read_all)
2. Each role has all permissions of roles below it (with some exceptions)
3. Moderators are junior admins - can manage users and servers but not system settings
4. Support staff handle day-to-day server operations and can view users
5. Users only manage their own resources
"""

import json

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
        # Server management (admin level — read_all/write_all imply own)
        Permission.SERVERS_READ_ALL,
        Permission.SERVERS_WRITE_ALL,
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
        Permission.QUOTA_READ,
        Permission.QUOTA_UPDATE,
        # Credit management
        Permission.CREDITS_READ_OWN,
        Permission.CREDITS_READ_ALL,
        Permission.CREDITS_GRANT,
        Permission.CREDITS_DEDUCT,
        # Analytics
        Permission.ANALYTICS_READ_OWN,
        Permission.ANALYTICS_READ,
        # Workspaces (admin level)
        Permission.WORKSPACES_READ_ALL,
        Permission.WORKSPACES_WRITE_ALL,
        # Volumes (admin level)
        Permission.VOLUMES_READ_ALL,
        Permission.VOLUMES_WRITE_ALL,
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
        # Server management (full — read_all/write_all imply own)
        Permission.SERVERS_READ_ALL,
        Permission.SERVERS_WRITE_ALL,
        # Environment (full)
        Permission.ENVIRONMENT_CREATE,
        Permission.ENVIRONMENT_READ,
        Permission.ENVIRONMENT_UPDATE,
        Permission.ENVIRONMENT_DELETE,
        # Plan (full)
        Permission.PLAN_CREATE,
        Permission.PLAN_READ,
        Permission.PLAN_UPDATE,
        Permission.PLAN_DELETE,
        Permission.QUOTA_READ,
        Permission.QUOTA_UPDATE,
        # Credits (view all + grant/deduct)
        Permission.CREDITS_READ_ALL,
        Permission.CREDITS_GRANT,
        Permission.CREDITS_DEDUCT,
        # Workspaces (full)
        Permission.WORKSPACES_READ_ALL,
        Permission.WORKSPACES_WRITE_ALL,
        # Volumes (full)
        Permission.VOLUMES_READ_ALL,
        Permission.VOLUMES_WRITE_ALL,
        # Audit
        Permission.AUDIT_READ,
    ],
    "support": [
        # User management (view only)
        Permission.USERS_READ,
        # Server management (write own + read all)
        Permission.SERVERS_WRITE_OWN,
        Permission.SERVERS_READ_ALL,
        # Environment (read only)
        Permission.ENVIRONMENT_READ,
        # Plan (read only)
        Permission.PLAN_READ,
        Permission.QUOTA_READ,
        # Credits (view own/all + grant)
        Permission.CREDITS_READ_OWN,
        Permission.CREDITS_READ_ALL,
        Permission.CREDITS_GRANT,
        # Analytics
        Permission.ANALYTICS_READ_OWN,
        Permission.ANALYTICS_READ,
        # Workspaces (write own + read all)
        Permission.WORKSPACES_WRITE_OWN,
        Permission.WORKSPACES_READ_ALL,
        # Volumes (write own + read all)
        Permission.VOLUMES_WRITE_OWN,
        Permission.VOLUMES_READ_ALL,
    ],
    "user": [
        # Own resources (full CRUD)
        Permission.SERVERS_READ_OWN,
        Permission.SERVERS_WRITE_OWN,
        Permission.VOLUMES_READ_OWN,
        Permission.VOLUMES_WRITE_OWN,
        Permission.WORKSPACES_READ_OWN,
        Permission.WORKSPACES_WRITE_OWN,
        # Catalogs (view public environments/plans)
        Permission.ENVIRONMENT_READ,
        Permission.PLAN_READ,
        # Credits (view own)
        Permission.CREDITS_READ_OWN,
        # Analytics (view own)
        Permission.ANALYTICS_READ_OWN,
    ],
    "guest": [
        # Read-only access to own servers and volumes
        Permission.SERVERS_READ_OWN,
        Permission.VOLUMES_READ_OWN,
    ],
}


# Rate limits per role (requests per minute, general API)
# Admin/mutation endpoints use strict_multiplier (0.5x)
# WebSocket uses rate_limit_websocket_cpm override
ROLE_RATE_LIMITS = {
    "guest": 30,
    "user": 120,
    "support": 300,
    "moderator": 300,
    "admin": 600,
    "super_admin": 3000,
}


# Valid roles ordered by privilege level
VALID_ROLES = list(ROLE_PERMISSIONS.keys())


# Role hierarchy for inheritance checks
ROLE_HIERARCHY = {
    "super_admin": 5,
    "admin": 4,
    "moderator": 3,
    "support": 2,
    "user": 1,
    "guest": 0,
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


def get_role_rate_limit(role: str) -> int:
    """Get the general API rate limit (RPM) for a role. Defaults to 'user' tier."""
    return ROLE_RATE_LIMITS.get(role, ROLE_RATE_LIMITS["user"])


# ---------------------------------------------------------------------------
# Expanded permission cache — precomputed so has_permission() skips the loop
# ---------------------------------------------------------------------------


def _expand_permissions(permissions: list) -> set:
    """Expand a permission list to include all implied permissions."""
    from app.core.permissions import Permission

    implications = {
        Permission.ALL: set(Permission.all_permissions()),
        Permission.SERVERS_READ_ALL: {Permission.SERVERS_READ_OWN},
        Permission.SERVERS_WRITE_ALL: {
            Permission.SERVERS_WRITE_OWN,
            Permission.SERVERS_READ_ALL,
            Permission.SERVERS_READ_OWN,
        },
        Permission.SERVERS_ACCESS_OTHERS: {
            Permission.SERVERS_READ_ALL,
            Permission.SERVERS_READ_OWN,
        },
        Permission.VOLUMES_READ_ALL: {Permission.VOLUMES_READ_OWN},
        Permission.VOLUMES_WRITE_ALL: {
            Permission.VOLUMES_WRITE_OWN,
            Permission.VOLUMES_READ_ALL,
            Permission.VOLUMES_READ_OWN,
        },
        Permission.WORKSPACES_READ_ALL: {Permission.WORKSPACES_READ_OWN},
        Permission.WORKSPACES_WRITE_ALL: {
            Permission.WORKSPACES_WRITE_OWN,
            Permission.WORKSPACES_READ_ALL,
            Permission.WORKSPACES_READ_OWN,
        },
        Permission.CREDITS_READ_ALL: {Permission.CREDITS_READ_OWN},
    }
    result = set(permissions)
    changed = True
    while changed:
        changed = False
        for perm in list(result):
            implied = implications.get(perm, set())
            for imp in implied:
                if imp not in result:
                    result.add(imp)
                    changed = True
    return result


# Precompute expanded permissions for all roles at module load time.
_EXPANSION_CACHE: dict[str, frozenset] = {}


def _rebuild_expansion_cache() -> None:
    """Rebuild the in-memory expanded-permission cache.

    Called automatically on module load and whenever ``ROLE_PERMISSIONS`` is
    mutated (e.g. admin updates role permissions).
    """
    global _EXPANSION_CACHE
    _EXPANSION_CACHE = {
        role: frozenset(_expand_permissions(perms)) for role, perms in ROLE_PERMISSIONS.items()
    }


_rebuild_expansion_cache()


def get_expanded_role_permissions(role: str) -> frozenset:
    """Return the expanded permission set for a role (O(1) lookup).

    Falls back to an empty set for unknown roles.
    """
    return _EXPANSION_CACHE.get(role, frozenset())


# Deep copy of default permissions for fallback when DB has no overrides
_DEFAULT_ROLE_PERMISSIONS = {role: list(perms) for role, perms in ROLE_PERMISSIONS.items()}


async def load_role_permissions_from_db() -> None:
    """Load custom role permissions from database, falling back to defaults."""
    try:
        from app.core.permissions import Permission
        from app.db.session import AsyncSessionLocal
        from app.services.setting_service import SettingService

        async with AsyncSessionLocal() as db:
            service = SettingService(db)
            raw = await service.get("role_permissions")
            if raw:
                stored = json.loads(raw)
                valid_perms = set(Permission.all_permissions()) | {Permission.ALL}
                for role, perms in stored.items():
                    if role not in ROLE_PERMISSIONS:
                        continue
                    # Validate all stored permissions are still valid
                    invalid = [p for p in perms if p not in valid_perms]
                    if invalid:
                        # Stale permissions detected — reset to defaults
                        ROLE_PERMISSIONS[role] = list(_DEFAULT_ROLE_PERMISSIONS[role])
                    else:
                        ROLE_PERMISSIONS[role] = perms
        _rebuild_expansion_cache()
    except Exception:
        # On any error, keep defaults
        pass


async def save_role_permissions_to_db() -> None:
    """Persist current role permissions to database."""
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.setting_service import SettingService

        async with AsyncSessionLocal() as db:
            service = SettingService(db)
            payload = json.dumps(ROLE_PERMISSIONS)
            await service.set("role_permissions", payload)
    except Exception:
        # Best-effort persistence
        pass
