"""Tests for app.core.roles helpers."""

import pytest
from unittest import mock

from app.core.roles import (
    ROLE_PERMISSIONS,
    ROLE_RATE_LIMITS,
    VALID_ROLES,
    ROLE_HIERARCHY,
    get_role_permissions,
    is_valid_role,
    get_role_level,
    has_higher_or_equal_role,
    get_role_rate_limit,
    load_role_permissions_from_db,
    save_role_permissions_to_db,
    _DEFAULT_ROLE_PERMISSIONS,
)
from app.core.permissions import Permission


class TestGetRolePermissions:
    def test_super_admin_has_all(self):
        perms = get_role_permissions("super_admin")
        assert Permission.ALL in perms

    def test_admin_has_admin_access(self):
        perms = get_role_permissions("admin")
        assert Permission.ADMIN_ACCESS in perms

    def test_user_has_own_permissions(self):
        perms = get_role_permissions("user")
        assert Permission.SERVERS_READ_OWN in perms
        assert Permission.ADMIN_ACCESS not in perms

    def test_guest_limited(self):
        perms = get_role_permissions("guest")
        assert len(perms) == 2
        assert Permission.SERVERS_READ_OWN in perms

    def test_invalid_role_returns_empty(self):
        assert get_role_permissions("nonexistent") == []


class TestIsValidRole:
    def test_valid_roles(self):
        for role in VALID_ROLES:
            assert is_valid_role(role) is True

    def test_invalid_role(self):
        assert is_valid_role("hacker") is False


class TestGetRoleLevel:
    def test_hierarchy(self):
        assert get_role_level("super_admin") == 5
        assert get_role_level("admin") == 4
        assert get_role_level("user") == 1
        assert get_role_level("guest") == 0

    def test_invalid_role_returns_negative(self):
        assert get_role_level("unknown") == -1


class TestHasHigherOrEqualRole:
    def test_admin_vs_user(self):
        assert has_higher_or_equal_role("admin", "user") is True

    def test_user_vs_admin(self):
        assert has_higher_or_equal_role("user", "admin") is False

    def test_same_role(self):
        assert has_higher_or_equal_role("moderator", "moderator") is True

    def test_super_admin_vs_all(self):
        for role in VALID_ROLES:
            assert has_higher_or_equal_role("super_admin", role) is True


class TestGetRoleRateLimit:
    def test_known_roles(self):
        assert get_role_rate_limit("guest") == 30
        assert get_role_rate_limit("user") == 120
        assert get_role_rate_limit("admin") == 600
        assert get_role_rate_limit("super_admin") == 3000

    def test_unknown_role_defaults_to_user(self):
        assert get_role_rate_limit("unknown") == 120


class TestLoadRolePermissionsFromDb:
    @pytest.mark.asyncio
    async def test_loads_valid_permissions(self):
        with mock.patch("app.core.roles.ROLE_PERMISSIONS", {k: list(v) for k, v in _DEFAULT_ROLE_PERMISSIONS.items()}):
            stored_json = '{"user": ["servers:read_own", "servers:write_own"]}'
            with mock.patch("app.services.setting_service.SettingService") as MockService:
                mock_service = MockService.return_value
                mock_service.get = mock.AsyncMock(return_value=stored_json)
                await load_role_permissions_from_db()
                assert Permission.SERVERS_READ_OWN in ROLE_PERMISSIONS["user"]

    @pytest.mark.asyncio
    async def test_ignores_invalid_permissions(self):
        with mock.patch("app.core.roles.ROLE_PERMISSIONS", {k: list(v) for k, v in _DEFAULT_ROLE_PERMISSIONS.items()}):
            stored_json = '{"user": ["invalid:permission", "servers:read_own"]}'
            with mock.patch("app.services.setting_service.SettingService") as MockService:
                mock_service = MockService.return_value
                mock_service.get = mock.AsyncMock(return_value=stored_json)
                await load_role_permissions_from_db()
                # Invalid permissions should trigger reset to defaults
                assert ROLE_PERMISSIONS["user"] == _DEFAULT_ROLE_PERMISSIONS["user"]

    @pytest.mark.asyncio
    async def test_no_settings_keeps_defaults(self):
        with mock.patch("app.services.setting_service.SettingService") as MockService:
            mock_service = MockService.return_value
            mock_service.get = mock.AsyncMock(return_value=None)
            await load_role_permissions_from_db()
            # Defaults should remain unchanged

    @pytest.mark.asyncio
    async def test_error_keeps_defaults(self):
        with mock.patch("app.services.setting_service.SettingService", side_effect=Exception("DB down")):
            await load_role_permissions_from_db()


class TestSaveRolePermissionsToDb:
    @pytest.mark.asyncio
    async def test_saves_permissions(self):
        with mock.patch("app.services.setting_service.SettingService") as MockService:
            mock_service = MockService.return_value
            mock_service.set = mock.AsyncMock()
            await save_role_permissions_to_db()
            mock_service.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_handled(self):
        with mock.patch("app.services.setting_service.SettingService", side_effect=Exception("DB down")):
            await save_role_permissions_to_db()
