# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage tests for remaining auth.py gaps (helpers, logout cleanup, admin verify)."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest import mock

import jwt
import pytest
from fastapi import HTTPException

from app.api import auth
from app.models.api_token import ApiToken
from app.models.user import User


class _FakeSessionCtx:
    """Mimics ``async with AsyncSessionLocal() as db``."""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *args):
        return False


class _MockAiohttpResponse:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status = status

    async def json(self):
        return self._json

    def raise_for_status(self):
        if self.status >= 400:
            raise Exception(f"HTTP {self.status}")


class _MockAiohttpResponseContext:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        pass


class _MockAiohttpSession:
    def __init__(self, response_json, status=200):
        self._response = _MockAiohttpResponse(response_json, status)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, *args, **kwargs):
        return _MockAiohttpResponseContext(self._response)


class _MockAiohttpClientSession:
    def __init__(self, response_json, status=200):
        self._session = _MockAiohttpSession(response_json, status)

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


def _make_oauth_mock():
    """Create a mock OAuthService that appears configured."""
    m = mock.MagicMock()
    m.is_configured = True
    m.generate_state = mock.Mock(return_value="state123")
    m.generate_pkce = mock.Mock(return_value=("verifier", "challenge"))
    m.get_authorize_url = mock.AsyncMock(return_value="http://oauth/authorize")
    m.exchange_code = mock.AsyncMock(return_value={"access_token": "at"})
    m.get_user_info = mock.AsyncMock(return_value={"sub": "oauth123", "email": "test@example.com"})
    m.extract_user_data = mock.Mock(
        return_value={
            "oauth_id": "oauth123",
            "username": "oauthuser",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "extra_profile": {},
        }
    )
    return m


def _make_request(headers=None, query_params=None, cookies=None):
    request = mock.MagicMock()
    request.headers = headers or {}
    request.query_params = query_params or {}
    request.cookies = cookies or {}
    return request


class TestConditionalLimiter:
    """_ConditionalLimiter delegates to slowapi when rate limiting is enabled."""

    def test_limit_enabled_returns_real_decorator(self):
        with mock.patch("app.api.auth.settings.rate_limit_enabled", True):
            decorator = auth.limiter.limit("5/minute")
            assert callable(decorator)

            def dummy(request):
                return request

            wrapped = decorator(dummy)
            assert callable(wrapped)

    def test_limit_disabled_returns_identity(self):
        with mock.patch("app.api.auth.settings.rate_limit_enabled", False):
            decorator = auth.limiter.limit("5/minute")

            def dummy():
                return None

            assert decorator(dummy) is dummy


class TestReleaseGpuDevices:
    """_release_gpu_devices happy path and never-raises guarantee."""

    @pytest.mark.asyncio
    async def test_release_success(self):
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_cls:
            mock_cls.return_value.release = mock.AsyncMock()
            await auth._release_gpu_devices(mock.AsyncMock(), "server-1")
            mock_cls.return_value.release.assert_awaited_once_with("server-1")

    @pytest.mark.asyncio
    async def test_release_failure_does_not_raise(self):
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_cls:
            mock_cls.return_value.release = mock.AsyncMock(side_effect=RuntimeError("boom"))
            # Must swallow the exception (logout-driven stops must not be blocked)
            await auth._release_gpu_devices(mock.AsyncMock(), "server-2")


class TestCustomHTTPBearerEdgeCases:
    """CustomHTTPBearer auto_error=False invalid scheme branch."""

    @pytest.mark.asyncio
    async def test_invalid_scheme_auto_error_false_returns_none(self):
        bearer = auth.CustomHTTPBearer(auto_error=False)
        request = _make_request(headers={"Authorization": "Basic abc123"})
        result = await bearer(request)
        assert result is None


class TestRevokeRefreshToken:
    """revoke_refresh_token verify-and-revoke path and negative result."""

    @pytest.mark.asyncio
    async def test_revoke_with_plaintext(self, db_session, test_user):
        plaintext = await auth.create_refresh_token_for_user(str(test_user.id), db_session)
        result = await auth.revoke_refresh_token(plaintext=plaintext, db=db_session)
        assert result is True

    @pytest.mark.asyncio
    async def test_revoke_invalid_plaintext_returns_false(self, db_session):
        result = await auth.revoke_refresh_token(plaintext="bogus-token", db=db_session)
        assert result is False


class TestPeriodicRefreshTokenCleanup:
    """run_periodic_refresh_token_cleanup loop coverage."""

    @pytest.mark.asyncio
    async def test_cleanup_logs_purged_tokens(self):
        db = mock.AsyncMock()
        with (
            mock.patch(
                "app.api.auth.asyncio.sleep",
                new=mock.AsyncMock(side_effect=[None, asyncio.CancelledError()]),
            ),
            mock.patch("app.db.session.AsyncSessionLocal", return_value=_FakeSessionCtx(db)),
            mock.patch(
                "app.api.auth.cleanup_expired_refresh_tokens",
                new=mock.AsyncMock(return_value=7),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await auth.run_periodic_refresh_token_cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_exception_is_logged_and_loop_continues(self):
        db = mock.AsyncMock()
        with (
            mock.patch(
                "app.api.auth.asyncio.sleep",
                new=mock.AsyncMock(side_effect=[None, asyncio.CancelledError()]),
            ),
            mock.patch("app.db.session.AsyncSessionLocal", return_value=_FakeSessionCtx(db)),
            mock.patch(
                "app.api.auth.cleanup_expired_refresh_tokens",
                new=mock.AsyncMock(side_effect=RuntimeError("db down")),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await auth.run_periodic_refresh_token_cleanup()


class TestSignout:
    """GET /auth/signout browser-friendly sign-out."""

    @pytest.mark.asyncio
    async def test_signout_redirects_and_clears(self, client):
        response = await client.get("/api/auth/signout", follow_redirects=False)
        assert response.status_code == 307
        assert "/login?signed_out=1" in response.headers["location"]
        assert "Clear-Site-Data" in response.headers


class TestResolveUserFromToken:
    """_resolve_user_from_token API-token branches."""

    @pytest.mark.asyncio
    async def test_resolve_via_api_token(self, db_session, test_user):
        import secrets

        raw = f"nukelab_{secrets.token_urlsafe(32)}"
        token = ApiToken(
            user_id=test_user.id,
            name="resolve",
            token_hash=auth.get_password_hash(raw),
            token_prefix=raw[:16],
            scopes=["user:read"],
            is_active=True,
        )
        db_session.add(token)
        await db_session.commit()

        with mock.patch.object(
            auth.token_signing,
            "verify_access_token",
            new=mock.AsyncMock(side_effect=jwt.InvalidTokenError("nope")),
        ):
            user = await auth._resolve_user_from_token(raw, db_session)
        assert user is not None
        assert user.id == test_user.id

    @pytest.mark.asyncio
    async def test_resolve_expired_api_token_raises(self, db_session, test_user):
        import secrets

        raw = f"nukelab_{secrets.token_urlsafe(32)}"
        token = ApiToken(
            user_id=test_user.id,
            name="expired",
            token_hash=auth.get_password_hash(raw),
            token_prefix=raw[:16],
            scopes=["user:read"],
            is_active=True,
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
        db_session.add(token)
        await db_session.commit()

        with mock.patch.object(
            auth.token_signing,
            "verify_access_token",
            new=mock.AsyncMock(side_effect=jwt.InvalidTokenError("nope")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth._resolve_user_from_token(raw, db_session)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_resolve_inactive_user_returns_none(self, db_session, test_user):
        import secrets

        test_user.is_active = False
        raw = f"nukelab_{secrets.token_urlsafe(32)}"
        token = ApiToken(
            user_id=test_user.id,
            name="inactive",
            token_hash=auth.get_password_hash(raw),
            token_prefix=raw[:16],
            scopes=["user:read"],
            is_active=True,
        )
        db_session.add(token)
        await db_session.commit()

        with mock.patch.object(
            auth.token_signing,
            "verify_access_token",
            new=mock.AsyncMock(side_effect=jwt.InvalidTokenError("nope")),
        ):
            user = await auth._resolve_user_from_token(raw, db_session)
        assert user is None


class TestExtractTokenFromRequest:
    """_extract_token_from_request(_optional) branch coverage."""

    def test_missing_token_raises_401(self):
        request = _make_request()
        with pytest.raises(HTTPException) as exc_info:
            auth._extract_token_from_request(request)
        assert exc_info.value.status_code == 401

    def test_invalid_scheme_header_returned_verbatim(self):
        request = _make_request(headers={"Authorization": "Basic abc123"})
        assert auth._extract_token_from_request_optional(request) == "Basic abc123"

    def test_query_param_token(self):
        request = _make_request(query_params={"token": "query-token"})
        assert auth._extract_token_from_request_optional(request) == "query-token"


class TestVerifyAdminAuth:
    """GET /auth/verify-admin branch coverage (direct calls)."""

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        request = _make_request(headers={"Authorization": "Bearer x"})
        with mock.patch(
            "app.api.auth._resolve_user_from_token", new=mock.AsyncMock(return_value=None)
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth.verify_admin_auth(request, mock.AsyncMock())
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self):
        request = _make_request(headers={"Authorization": "Bearer x"})
        user = mock.MagicMock(spec=User)
        with (
            mock.patch("app.api.auth._resolve_user_from_token", new=mock.AsyncMock(return_value=user)),
            mock.patch("app.api.auth.has_permission", return_value=False),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth.verify_admin_auth(request, mock.AsyncMock())
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_returns_200_with_headers(self):
        import uuid

        request = _make_request(headers={"Authorization": "Bearer x"})
        user = mock.MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.username = "adminuser"
        with (
            mock.patch("app.api.auth._resolve_user_from_token", new=mock.AsyncMock(return_value=user)),
            mock.patch("app.api.auth.has_permission", return_value=True),
        ):
            response = await auth.verify_admin_auth(request, mock.AsyncMock())
        assert response.status_code == 200
        assert response.headers["X-User-Id"] == str(user.id)
        assert response.headers["X-User-Name"] == "adminuser"
        assert response.headers["X-User-Role"] == "Admin"


class TestKeyEndpoints:
    """GET /auth/jwks.json and /auth/public-key.pem."""

    @pytest.mark.asyncio
    async def test_jwks(self, client):
        response = await client.get("/api/auth/jwks.json")
        assert response.status_code == 200
        assert "keys" in response.json()

    @pytest.mark.asyncio
    async def test_public_key_pem(self, client):
        response = await client.get("/api/auth/public-key.pem")
        assert response.status_code == 200
        assert "PUBLIC KEY" in response.text


class TestOAuthCallbackMoreBranches:
    """OAuth callback branches not covered elsewhere."""

    @pytest.mark.asyncio
    async def test_sync_mode_invalid_state(self, client):
        with mock.patch("app.services.oauth_service.oauth_service", _make_oauth_mock()):
            client.cookies.set("oauth_state", "real_state")
            client.cookies.set("oauth_sync", "1")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=fake_state", follow_redirects=False
            )
            assert response.status_code == 307
            assert "sync=error" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_id_token_decode_failure_redirects(self, client):
        m = _make_oauth_mock()
        m.exchange_code = mock.AsyncMock(
            return_value={"access_token": "at", "id_token": "bad_token"}
        )
        m.get_user_info = mock.AsyncMock(return_value=None)
        with (
            mock.patch("app.services.oauth_service.oauth_service", m),
            mock.patch("app.api.auth.jwt.decode", side_effect=Exception("bad jwt")),
        ):
            client.cookies.set("oauth_state", "test_state")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=test_state", follow_redirects=False
            )
            assert response.status_code == 307
            assert "failed" in response.headers["location"].lower()

    @pytest.mark.asyncio
    async def test_existing_user_extra_profile_merge(self, client, test_user, db_session):
        test_user.oauth_id = None
        test_user.oauth_provider = None
        test_user.profile = {"existing": "keep"}
        await db_session.commit()

        m = _make_oauth_mock()
        m.get_user_info = mock.AsyncMock(
            return_value={
                "sub": "oauth555",
                "email": test_user.email,
                "preferred_username": test_user.username,
            }
        )
        m.extract_user_data = mock.Mock(
            return_value={
                "oauth_id": "oauth555",
                "username": test_user.username,
                "email": test_user.email,
                "first_name": "Merged",
                "last_name": "User",
                "extra_profile": {"org": "TestOrg"},
            }
        )
        with mock.patch("app.services.oauth_service.oauth_service", m):
            client.cookies.set("oauth_state", "test_state")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=test_state", follow_redirects=False
            )
            assert response.status_code == 307
            assert "token=" in response.headers["location"]

        await db_session.refresh(test_user)
        assert test_user.profile["org"] == "TestOrg"
        assert test_user.profile["existing"] == "keep"


async def _setup_oauth_user(test_user, db_session):
    from app.core.token_encryption import encrypt_token

    test_user.oauth_provider = "oauth"
    test_user.security = {"oauth_refresh_token": encrypt_token("rt123")}
    test_user.profile = {}
    await db_session.commit()


class TestOAuthSyncBranches:
    """POST /oauth/sync error and fallback branches."""

    @pytest.mark.asyncio
    async def test_token_url_not_configured(self, client, user_token, test_user, db_session):
        await _setup_oauth_user(test_user, db_session)
        mock_oauth = _make_oauth_mock()
        mock_oauth._load_discovery = mock.AsyncMock()
        mock_oauth._get_endpoint = mock.Mock(return_value=None)
        with mock.patch("app.services.oauth_service.oauth_service", mock_oauth):
            response = await client.post(
                "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 500
        assert "token url not configured" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_provider_rejects_refresh_token(self, client, user_token, test_user, db_session):
        await _setup_oauth_user(test_user, db_session)
        mock_oauth = _make_oauth_mock()
        mock_oauth._load_discovery = mock.AsyncMock()
        mock_oauth._get_endpoint = mock.Mock(return_value="http://test/token")
        mock_session = _MockAiohttpClientSession({}, status=400)
        with (
            mock.patch("app.services.oauth_service.oauth_service", mock_oauth),
            mock.patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            response = await client.post(
                "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 400
        assert "rejected" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_provider_unreachable(self, client, user_token, test_user, db_session):
        import aiohttp

        await _setup_oauth_user(test_user, db_session)
        mock_oauth = _make_oauth_mock()
        mock_oauth._load_discovery = mock.AsyncMock()
        mock_oauth._get_endpoint = mock.Mock(return_value="http://test/token")
        with (
            mock.patch("app.services.oauth_service.oauth_service", mock_oauth),
            mock.patch(
                "aiohttp.ClientSession", side_effect=aiohttp.ClientError("connection failed")
            ),
        ):
            response = await client.post(
                "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 502
        assert "unreachable" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_no_access_token_in_response(self, client, user_token, test_user, db_session):
        await _setup_oauth_user(test_user, db_session)
        mock_oauth = _make_oauth_mock()
        mock_oauth._load_discovery = mock.AsyncMock()
        mock_oauth._get_endpoint = mock.Mock(return_value="http://test/token")
        mock_session = _MockAiohttpClientSession({"refresh_token": "rt_new"}, status=200)
        with (
            mock.patch("app.services.oauth_service.oauth_service", mock_oauth),
            mock.patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            response = await client.post(
                "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 400
        assert "failed to refresh access token" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_userinfo_id_token_fallback(self, client, user_token, test_user, db_session):
        await _setup_oauth_user(test_user, db_session)
        mock_oauth = _make_oauth_mock()
        mock_oauth._load_discovery = mock.AsyncMock()
        mock_oauth._get_endpoint = mock.Mock(return_value="http://test/token")
        mock_oauth.get_user_info = mock.AsyncMock(return_value=None)
        mock_oauth.extract_user_data = mock.Mock(
            return_value={
                "oauth_id": "oauth123",
                "username": test_user.username,
                "email": "fallback@example.com",
                "first_name": "Fallback",
                "last_name": "User",
                "extra_profile": {},
            }
        )
        # A real (unsigned-decodable) JWT so jwt.decode succeeds without patching
        # it globally, which would break this endpoint's own access-token auth.
        id_token = jwt.encode({"sub": "oauth123", "email": "fallback@example.com"}, "secret")
        mock_session = _MockAiohttpClientSession(
            {"access_token": "at_new", "id_token": id_token}, status=200
        )
        with (
            mock.patch("app.services.oauth_service.oauth_service", mock_oauth),
            mock.patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            response = await client.post(
                "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        assert response.json()["email"] == "fallback@example.com"

    @pytest.mark.asyncio
    async def test_no_userinfo_at_all(self, client, user_token, test_user, db_session):
        await _setup_oauth_user(test_user, db_session)
        mock_oauth = _make_oauth_mock()
        mock_oauth._load_discovery = mock.AsyncMock()
        mock_oauth._get_endpoint = mock.Mock(return_value="http://test/token")
        mock_oauth.get_user_info = mock.AsyncMock(return_value=None)
        mock_session = _MockAiohttpClientSession({"access_token": "at_new"}, status=200)
        with (
            mock.patch("app.services.oauth_service.oauth_service", mock_oauth),
            mock.patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            response = await client.post(
                "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 400
        assert "failed to get user information" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_userinfo_id_token_decode_failure(self, client, user_token, test_user, db_session):
        await _setup_oauth_user(test_user, db_session)
        mock_oauth = _make_oauth_mock()
        mock_oauth._load_discovery = mock.AsyncMock()
        mock_oauth._get_endpoint = mock.Mock(return_value="http://test/token")
        mock_oauth.get_user_info = mock.AsyncMock(return_value=None)
        # Undecodable id_token: jwt.decode raises and is swallowed, leaving no userinfo.
        mock_session = _MockAiohttpClientSession(
            {"access_token": "at_new", "id_token": "not-a-jwt"}, status=200
        )
        with (
            mock.patch("app.services.oauth_service.oauth_service", mock_oauth),
            mock.patch("aiohttp.ClientSession", return_value=mock_session),
        ):
            response = await client.post(
                "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 400
        assert "failed to get user information" in response.json()["detail"].lower()
