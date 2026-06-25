"""Tests for the precomputed expanded permission cache in roles.py."""

from app.core.permissions import Permission
from app.core.roles import (
    ROLE_PERMISSIONS,
    _rebuild_expansion_cache,
    get_expanded_role_permissions,
)


class TestExpandedRolePermissions:
    """Tests for the O(1) expanded permission lookup."""

    def test_super_admin_has_all_permissions(self):
        perms = get_expanded_role_permissions("super_admin")
        assert Permission.ALL in perms
        # ALL implies every other permission
        assert Permission.SERVERS_READ_OWN in perms
        assert Permission.SERVERS_WRITE_ALL in perms
        assert Permission.ADMIN_ACCESS in perms

    def test_admin_has_server_write_all_and_implied(self):
        perms = get_expanded_role_permissions("admin")
        assert Permission.SERVERS_WRITE_ALL in perms
        # SERVERS_WRITE_ALL implies SERVERS_WRITE_OWN, SERVERS_READ_ALL, SERVERS_READ_OWN
        assert Permission.SERVERS_WRITE_OWN in perms
        assert Permission.SERVERS_READ_ALL in perms
        assert Permission.SERVERS_READ_OWN in perms

    def test_user_has_own_permissions_only(self):
        perms = get_expanded_role_permissions("user")
        assert Permission.SERVERS_READ_OWN in perms
        assert Permission.SERVERS_WRITE_OWN in perms
        assert Permission.SERVERS_READ_ALL not in perms
        assert Permission.ADMIN_ACCESS not in perms

    def test_unknown_role_returns_empty_set(self):
        perms = get_expanded_role_permissions("nonexistent")
        assert perms == set()

    def test_returns_frozenset(self):
        perms = get_expanded_role_permissions("user")
        assert isinstance(perms, frozenset)


class TestRebuildExpansionCache:
    """Tests for _rebuild_expansion_cache."""

    def test_rebuild_reflects_role_permission_changes(self):
        # Temporarily add a permission to the guest role
        original = list(ROLE_PERMISSIONS["guest"])
        ROLE_PERMISSIONS["guest"].append(Permission.ADMIN_ACCESS)

        try:
            _rebuild_expansion_cache()
            perms = get_expanded_role_permissions("guest")
            assert Permission.ADMIN_ACCESS in perms
        finally:
            ROLE_PERMISSIONS["guest"] = original
            _rebuild_expansion_cache()

    def test_rebuild_restores_defaults(self):
        # Mutate and restore
        original = list(ROLE_PERMISSIONS["guest"])
        ROLE_PERMISSIONS["guest"].append(Permission.ADMIN_ACCESS)
        _rebuild_expansion_cache()
        assert Permission.ADMIN_ACCESS in get_expanded_role_permissions("guest")

        ROLE_PERMISSIONS["guest"] = original
        _rebuild_expansion_cache()
        assert Permission.ADMIN_ACCESS not in get_expanded_role_permissions("guest")
