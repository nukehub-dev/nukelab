"""Tests for app.core.security and app.api.auth security primitives."""

import pytest
from unittest import mock
from datetime import datetime, timedelta

from app.core.security import (
    _expand_permissions,
    get_user_permissions,
    has_permission,
    has_any_permission,
    has_all_permissions,
    check_permission,
    check_any_permission,
)
from app.core.permissions import Permission
from app.models.user import User


class TestExpandPermissions:
    def test_expand_empty(self):
        assert _expand_permissions([]) == set()

    def test_expand_single_no_implications(self):
        result = _expand_permissions([Permission.USERS_READ])
        assert result == {Permission.USERS_READ}

    def test_expand_servers_write_all_implies_read(self):
        result = _expand_permissions([Permission.SERVERS_WRITE_ALL])
        assert Permission.SERVERS_READ_ALL in result
        assert Permission.SERVERS_READ_OWN in result
        assert Permission.SERVERS_WRITE_OWN in result
        assert Permission.SERVERS_WRITE_ALL in result

    def test_expand_all_implies_everything(self):
        result = _expand_permissions([Permission.ALL])
        assert Permission.ADMIN_ACCESS in result
        assert Permission.SERVERS_WRITE_ALL in result
        assert Permission.VOLUMES_WRITE_ALL in result

    def test_expand_multiple(self):
        result = _expand_permissions([Permission.SERVERS_READ_ALL, Permission.VOLUMES_READ_ALL])
        assert Permission.SERVERS_READ_OWN in result
        assert Permission.VOLUMES_READ_OWN in result

    def test_expand_chained(self):
        # SERVERS_WRITE_ALL -> SERVERS_READ_ALL -> SERVERS_READ_OWN
        result = _expand_permissions([Permission.SERVERS_WRITE_ALL])
        assert Permission.SERVERS_READ_OWN in result


class TestGetUserPermissions:
    def test_get_user_permissions_normal(self):
        user = User(id=mock.Mock(), username="u", email="u@test.com", role="user")
        perms = get_user_permissions(user)
        assert isinstance(perms, list)

    def test_get_user_permissions_none_user(self):
        assert get_user_permissions(None) == []

    def test_get_user_permissions_none_role(self):
        user = User(id=mock.Mock(), username="u", email="u@test.com", role=None)
        assert get_user_permissions(user) == []


class TestHasPermission:
    def test_has_permission_true(self):
        user = User(id=mock.Mock(), username="admin", email="a@test.com", role="admin", is_active=True)
        assert has_permission(user, Permission.ADMIN_ACCESS) is True

    def test_has_permission_false(self):
        user = User(id=mock.Mock(), username="u", email="u@test.com", role="user", is_active=True)
        assert has_permission(user, Permission.ADMIN_ACCESS) is False

    def test_has_permission_inactive_user(self):
        user = User(id=mock.Mock(), username="u", email="u@test.com", role="admin", is_active=False)
        assert has_permission(user, Permission.ADMIN_ACCESS) is False

    def test_has_permission_none_user(self):
        assert has_permission(None, Permission.ADMIN_ACCESS) is False

    def test_has_permission_implied(self):
        # admin role has SERVERS_WRITE_ALL which implies SERVERS_READ_OWN
        user = User(id=mock.Mock(), username="admin", email="a@test.com", role="admin", is_active=True)
        assert has_permission(user, Permission.SERVERS_READ_OWN) is True


class TestHasAnyPermission:
    def test_has_any_permission_true(self):
        user = User(id=mock.Mock(), username="admin", email="a@test.com", role="admin", is_active=True)
        assert has_any_permission(user, [Permission.ADMIN_ACCESS, "FAKE"]) is True

    def test_has_any_permission_false(self):
        user = User(id=mock.Mock(), username="u", email="u@test.com", role="user", is_active=True)
        assert has_any_permission(user, [Permission.ADMIN_ACCESS, "FAKE"]) is False

    def test_has_any_permission_inactive(self):
        user = User(id=mock.Mock(), username="u", email="u@test.com", role="admin", is_active=False)
        assert has_any_permission(user, [Permission.ADMIN_ACCESS]) is False


class TestHasAllPermissions:
    def test_has_all_permissions_true(self):
        user = User(id=mock.Mock(), username="admin", email="a@test.com", role="admin", is_active=True)
        assert has_all_permissions(user, [Permission.ADMIN_ACCESS]) is True

    def test_has_all_permissions_false(self):
        user = User(id=mock.Mock(), username="u", email="u@test.com", role="user", is_active=True)
        assert has_all_permissions(user, [Permission.ADMIN_ACCESS, Permission.USERS_READ]) is False

    def test_has_all_permissions_inactive(self):
        user = User(id=mock.Mock(), username="u", email="u@test.com", role="admin", is_active=False)
        assert has_all_permissions(user, [Permission.ADMIN_ACCESS]) is False


class TestCheckPermission:
    def test_check_permission_passes(self):
        user = User(id=mock.Mock(), username="admin", email="a@test.com", role="admin", is_active=True)
        check_permission(user, Permission.ADMIN_ACCESS)  # should not raise

    def test_check_permission_raises(self):
        from fastapi import HTTPException
        user = User(id=mock.Mock(), username="u", email="u@test.com", role="user", is_active=True)
        with pytest.raises(HTTPException) as exc_info:
            check_permission(user, Permission.ADMIN_ACCESS)
        assert exc_info.value.status_code == 403


class TestCheckAnyPermission:
    def test_check_any_permission_passes(self):
        user = User(id=mock.Mock(), username="admin", email="a@test.com", role="admin", is_active=True)
        check_any_permission(user, [Permission.ADMIN_ACCESS])  # should not raise

    def test_check_any_permission_raises(self):
        from fastapi import HTTPException
        user = User(id=mock.Mock(), username="u", email="u@test.com", role="user", is_active=True)
        with pytest.raises(HTTPException) as exc_info:
            check_any_permission(user, [Permission.ADMIN_ACCESS])
        assert exc_info.value.status_code == 403


# ===== app.api.auth primitives =====

class TestAuthPasswordUtils:
    def test_get_password_hash(self):
        from app.api.auth import get_password_hash, verify_password
        hashed = get_password_hash("password123")
        assert hashed != "password123"
        assert verify_password("password123", hashed) is True

    def test_verify_password_wrong(self):
        from app.api.auth import get_password_hash, verify_password
        hashed = get_password_hash("password123")
        assert verify_password("wrong", hashed) is False


class TestCreateAccessToken:
    def test_create_access_token(self):
        from app.api.auth import create_access_token
        from jose import jwt
        from app.config import settings

        token = create_access_token(data={"sub": "testuser"})
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == "testuser"
        assert "exp" in payload

    def test_create_access_token_custom_expiry(self):
        from app.api.auth import create_access_token
        from jose import jwt
        from app.config import settings

        future = timedelta(minutes=60)
        token = create_access_token(data={"sub": "testuser"}, expires_delta=future)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == "testuser"


class TestCustomHTTPBearer:
    @pytest.mark.asyncio
    async def test_bearer_scheme(self):
        from app.api.auth import CustomHTTPBearer
        from fastapi import Request

        req = mock.Mock(spec=Request)
        req.headers = {"Authorization": "Bearer mytoken"}
        bearer = CustomHTTPBearer(auto_error=True)
        result = await bearer(req)
        assert result == "mytoken"

    @pytest.mark.asyncio
    async def test_token_scheme(self):
        from app.api.auth import CustomHTTPBearer
        from fastapi import Request

        req = mock.Mock(spec=Request)
        req.headers = {"Authorization": "Token mytoken"}
        bearer = CustomHTTPBearer(auto_error=True)
        result = await bearer(req)
        assert result == "mytoken"

    @pytest.mark.asyncio
    async def test_invalid_scheme(self):
        from app.api.auth import CustomHTTPBearer
        from fastapi import Request, HTTPException

        req = mock.Mock(spec=Request)
        req.headers = {"Authorization": "Basic abc"}
        bearer = CustomHTTPBearer(auto_error=True)
        with pytest.raises(HTTPException) as exc_info:
            await bearer(req)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_header(self):
        from app.api.auth import CustomHTTPBearer
        from fastapi import Request, HTTPException

        req = mock.Mock(spec=Request)
        req.headers = {}
        bearer = CustomHTTPBearer(auto_error=True)
        with pytest.raises(HTTPException) as exc_info:
            await bearer(req)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_header_no_auto_error(self):
        from app.api.auth import CustomHTTPBearer
        from fastapi import Request

        req = mock.Mock(spec=Request)
        req.headers = {}
        bearer = CustomHTTPBearer(auto_error=False)
        result = await bearer(req)
        assert result is None


class TestRequireScopes:
    def test_require_scopes_jwt_bypass(self):
        from app.api.auth import require_scopes
        from fastapi import Request

        checker = require_scopes("servers:read")
        req = mock.Mock(spec=Request)
        req.state.auth_context = mock.Mock(auth_method="jwt", token_scopes=[])
        user = mock.Mock()
        # Should not raise
        import asyncio
        asyncio.get_event_loop().run_until_complete(checker(req, user))

    def test_require_scopes_api_token_match(self):
        from app.api.auth import require_scopes
        from fastapi import Request, HTTPException

        checker = require_scopes("servers:read")
        req = mock.Mock(spec=Request)
        req.state.auth_context = mock.Mock(auth_method="api_token", token_scopes=["servers:read"])
        user = mock.Mock()
        import asyncio
        asyncio.get_event_loop().run_until_complete(checker(req, user))

    def test_require_scopes_api_token_no_match(self):
        from app.api.auth import require_scopes
        from fastapi import Request, HTTPException

        checker = require_scopes("servers:write")
        req = mock.Mock(spec=Request)
        req.state.auth_context = mock.Mock(auth_method="api_token", token_scopes=["servers:read"])
        user = mock.Mock()
        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(checker(req, user))
        assert exc_info.value.status_code == 403

    def test_require_scopes_wildcard(self):
        from app.api.auth import require_scopes
        from fastapi import Request

        checker = require_scopes("servers:write")
        req = mock.Mock(spec=Request)
        req.state.auth_context = mock.Mock(auth_method="api_token", token_scopes=["servers:*"])
        user = mock.Mock()
        import asyncio
        asyncio.get_event_loop().run_until_complete(checker(req, user))

    def test_require_scopes_no_auth_context(self):
        from app.api.auth import require_scopes
        from fastapi import Request, HTTPException

        checker = require_scopes("servers:read")
        req = mock.Mock(spec=Request)
        req.state.auth_context = None
        user = mock.Mock()
        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(checker(req, user))
        assert exc_info.value.status_code == 401


class TestRequireJWTAuth:
    def test_require_jwt_auth_pass(self):
        from app.api.auth import require_jwt_auth
        from fastapi import Request

        checker = require_jwt_auth()
        req = mock.Mock(spec=Request)
        req.state.auth_context = mock.Mock(auth_method="jwt")
        user = mock.Mock()
        import asyncio
        asyncio.get_event_loop().run_until_complete(checker(req, user))

    def test_require_jwt_auth_rejects_api_token(self):
        from app.api.auth import require_jwt_auth
        from fastapi import Request, HTTPException

        checker = require_jwt_auth()
        req = mock.Mock(spec=Request)
        req.state.auth_context = mock.Mock(auth_method="api_token")
        user = mock.Mock()
        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(checker(req, user))
        assert exc_info.value.status_code == 403
        assert "JWT" in exc_info.value.detail

    def test_require_jwt_auth_no_context(self):
        from app.api.auth import require_jwt_auth
        from fastapi import Request, HTTPException

        checker = require_jwt_auth()
        req = mock.Mock(spec=Request)
        req.state.auth_context = None
        user = mock.Mock()
        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(checker(req, user))
        assert exc_info.value.status_code == 401


class TestRefreshTokenUtils:
    @pytest.mark.asyncio
    async def test_create_refresh_token(self, db_session, test_user):
        from app.api.auth import create_refresh_token_for_user

        token = await create_refresh_token_for_user(str(test_user.id), db_session)
        assert isinstance(token, str)
        assert len(token) > 20

    @pytest.mark.asyncio
    async def test_verify_refresh_token_valid(self, db_session, test_user):
        from app.api.auth import create_refresh_token_for_user, verify_refresh_token

        plaintext = await create_refresh_token_for_user(str(test_user.id), db_session)
        rt = await verify_refresh_token(plaintext, db_session)
        assert rt is not None
        assert str(rt.user_id) == str(test_user.id)

    @pytest.mark.asyncio
    async def test_verify_refresh_token_invalid(self, db_session):
        from app.api.auth import verify_refresh_token

        rt = await verify_refresh_token("invalid-token", db_session)
        assert rt is None

    @pytest.mark.asyncio
    async def test_revoke_refresh_token(self, db_session, test_user):
        from app.api.auth import create_refresh_token_for_user, verify_refresh_token, revoke_refresh_token

        plaintext = await create_refresh_token_for_user(str(test_user.id), db_session)
        rt = await verify_refresh_token(plaintext, db_session)
        result = await revoke_refresh_token(rt=rt, db=db_session)
        assert result is True

        # After revoke, verify should fail
        rt2 = await verify_refresh_token(plaintext, db_session)
        assert rt2 is None

    @pytest.mark.asyncio
    async def test_revoke_refresh_token_invalid_plaintext(self, db_session):
        from app.api.auth import revoke_refresh_token

        result = await revoke_refresh_token(plaintext="bogus", db=db_session)
        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_refresh_token_value_error(self, db_session):
        from app.api.auth import revoke_refresh_token

        with pytest.raises(ValueError):
            await revoke_refresh_token()

    @pytest.mark.asyncio
    async def test_refresh_token_enforcement_limit(self, db_session, test_user):
        from app.api.auth import create_refresh_token_for_user, verify_refresh_token
        from app.api.auth import MAX_REFRESH_TOKENS_PER_USER

        # Reduce limit to avoid connection exhaustion in tests
        with mock.patch("app.api.auth.MAX_REFRESH_TOKENS_PER_USER", 3):
            tokens = []
            for _ in range(5):
                t = await create_refresh_token_for_user(str(test_user.id), db_session)
                tokens.append(t)

            # Oldest should be revoked
            oldest = await verify_refresh_token(tokens[0], db_session)
            assert oldest is None

            # Newest should still be valid
            newest = await verify_refresh_token(tokens[-1], db_session)
            assert newest is not None

    @pytest.mark.asyncio
    async def test_cleanup_expired_refresh_tokens(self, db_session, test_user):
        from app.api.auth import create_refresh_token_for_user, cleanup_expired_refresh_tokens
        from app.models.refresh_token import RefreshToken
        from sqlalchemy import select

        # Create an expired token by backdating
        plaintext = await create_refresh_token_for_user(str(test_user.id), db_session)

        # Manually expire it
        result = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == test_user.id))
        rt = result.scalars().first()
        rt.expires_at = datetime.utcnow() - timedelta(days=1)
        await db_session.commit()

        deleted = await cleanup_expired_refresh_tokens(db_session)
        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_run_periodic_cleanup_runs(self, db_session):
        from app.api.auth import run_periodic_refresh_token_cleanup
        import asyncio

        call_count = 0
        async def fake_sleep(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise SystemExit("stop")

        with mock.patch("app.api.auth.asyncio.sleep", side_effect=fake_sleep):
            with mock.patch("app.api.auth.cleanup_expired_refresh_tokens", new_callable=mock.AsyncMock) as mock_cleanup:
                with pytest.raises(SystemExit):
                    await run_periodic_refresh_token_cleanup()
                mock_cleanup.assert_called_once()
