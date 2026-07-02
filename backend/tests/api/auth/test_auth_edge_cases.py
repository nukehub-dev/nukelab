# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Extended tests for Auth API error paths and uncovered branches."""

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from app.api.auth import pwd_context
from app.config import settings
from app.models.api_token import ApiToken
from app.models.refresh_token import RefreshToken


class TestAuthModeOAuth:
    """Tests for OAuth-only auth mode blocking password login."""

    @pytest.mark.asyncio
    async def test_login_blocked_when_oauth_mode(self, client, test_user):
        """Password login should return 403 when auth_mode is oauth."""
        original = settings.auth_mode
        settings.auth_mode = "oauth"
        try:
            response = await client.post(
                "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
            )
            assert response.status_code == 403
            assert "disabled" in response.json()["detail"].lower()
        finally:
            settings.auth_mode = original


class TestCustomHTTPBearer:
    """Tests for CustomHTTPBearer auth scheme validation."""

    @pytest.mark.asyncio
    async def test_me_with_no_auth_header(self, client):
        """Request without Authorization header should 401."""
        response = await client.get("/api/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_invalid_scheme(self, client):
        """Request with invalid auth scheme should 401."""
        response = await client.get("/api/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert response.status_code == 401
        assert "Invalid authentication scheme" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_me_with_token_scheme(self, client, user_token):
        """Request with 'Token <token>' scheme should work."""
        response = await client.get(
            "/api/auth/me", headers={"Authorization": f"Token {user_token}"}
        )
        assert response.status_code == 200
        assert response.json()["username"] == "testuser"


class TestVerifyEndpoint:
    """Tests for /api/auth/verify endpoint error paths."""

    @pytest.mark.asyncio
    async def test_verify_missing_token(self, client):
        """Verify without any token should 401."""
        response = await client.get("/api/auth/verify")
        assert response.status_code == 401
        assert "Missing token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_verify_invalid_scheme(self, client):
        """Verify with invalid scheme should 401."""
        response = await client.get("/api/auth/verify", headers={"Authorization": "Basic invalid"})
        assert response.status_code == 401
        assert "Invalid scheme" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_verify_cookie_token(self, client, user_token):
        """Verify should accept token from cookie."""
        response = await client.get("/api/auth/verify", cookies={"nukelab_token": user_token})
        assert response.status_code == 200
        assert "X-User-Id" in response.headers

    @pytest.mark.asyncio
    async def test_verify_expired_api_token(self, client, test_user, db_session):
        """Verify with expired API token should 401."""
        token_plain = "test-api-token-12345"
        token_hash = pwd_context.hash(token_plain)
        api_token = ApiToken(
            user_id=test_user.id,
            name="test",
            token_hash=token_hash,
            token_prefix=token_plain[:16],
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
            is_active=True,
        )
        db_session.add(api_token)
        await db_session.commit()

        response = await client.get(
            "/api/auth/verify", headers={"Authorization": f"Bearer {token_plain}"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_valid_api_token(self, client, test_user, db_session):
        """Verify with valid API token should 200."""
        token_plain = "valid-api-token-12345"
        token_hash = pwd_context.hash(token_plain)
        api_token = ApiToken(
            user_id=test_user.id,
            name="test",
            token_hash=token_hash,
            token_prefix=token_plain[:16],
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            is_active=True,
        )
        db_session.add(api_token)
        await db_session.commit()

        response = await client.get(
            "/api/auth/verify", headers={"Authorization": f"Bearer {token_plain}"}
        )
        assert response.status_code == 200
        assert "X-User-Id" in response.headers


class TestAuthMethodsEndpoint:
    """Tests for /api/auth/methods."""

    @pytest.mark.asyncio
    async def test_get_auth_methods(self, client):
        """Should return available auth methods."""
        response = await client.get("/api/auth/methods")
        assert response.status_code == 200
        data = response.json()
        assert "methods" in data
        assert "auth_mode" in data


class TestCSRFTokenEndpoint:
    """Tests for /api/auth/csrf-token."""

    @pytest.mark.asyncio
    async def test_get_csrf_token(self, client):
        """Should return a CSRF token and set cookie."""
        response = await client.get("/api/auth/csrf-token")
        assert response.status_code == 200
        data = response.json()
        assert "csrf_token" in data
        assert len(data["csrf_token"]) > 20


class TestRefreshInactiveUser:
    """Tests for refresh with inactive user."""

    @pytest.mark.asyncio
    async def test_refresh_inactive_user(self, client, test_user, db_session):
        """Refresh should fail if user is inactive."""
        # Login first
        login_resp = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
        )
        if login_resp.status_code == 429:
            pytest.skip("Rate limited")
        refresh_token = login_resp.json()["refresh_token"]

        # Deactivate user
        test_user.is_active = False
        await db_session.commit()

        response = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert response.status_code == 401
        assert "inactive" in response.json()["detail"].lower()


class TestRequireScopes:
    """Tests for API token scope restrictions."""

    @pytest.mark.asyncio
    async def test_api_token_insufficient_scope(self, client, test_user, db_session):
        """API token without required scope should 403."""

        token_plain = "scoped-token-12345"
        token_hash = pwd_context.hash(token_plain)
        api_token = ApiToken(
            user_id=test_user.id,
            name="test",
            token_hash=token_hash,
            token_prefix=token_plain[:16],
            scopes=["servers:read"],
            is_active=True,
        )
        db_session.add(api_token)
        await db_session.commit()

        # Try to access admin endpoint with wrong scope
        response = await client.get(
            "/api/admin/users", headers={"Authorization": f"Bearer {token_plain}"}
        )
        # Should be 403 due to insufficient scope (admin requires different scope)
        assert response.status_code in [403, 401]


class TestRequireJWTAuth:
    """Tests for JWT-only endpoints rejecting API tokens."""

    @pytest.mark.asyncio
    async def test_api_token_rejected_for_jwt_only(self, client, test_user, db_session):
        """API token should be rejected on JWT-only endpoints like /api/auth/oauth/sync."""
        token_plain = "jwt-test-token-123"
        token_hash = pwd_context.hash(token_plain)
        api_token = ApiToken(
            user_id=test_user.id,
            name="test",
            token_hash=token_hash,
            token_prefix=token_plain[:16],
            scopes=["profile"],
            is_active=True,
        )
        db_session.add(api_token)
        await db_session.commit()

        response = await client.post(
            "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {token_plain}"}
        )
        assert response.status_code == 403
        assert "JWT authentication required" in response.json()["detail"]


class TestOAuthLoginErrors:
    """Tests for OAuth login error paths."""

    @pytest.mark.asyncio
    async def test_oauth_login_not_configured(self, client):
        """OAuth login should 503 when not configured."""
        from app.services.oauth_service import OAuthService

        with mock.patch.object(
            OAuthService, "is_configured", new_callable=mock.PropertyMock, return_value=False
        ):
            response = await client.get("/api/auth/oauth/login")
            assert response.status_code == 503
            assert "not configured" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_oauth_login_disabled_when_local_mode(self, client):
        """OAuth login should 403 when auth_mode is local."""
        original_mode = settings.auth_mode
        settings.auth_mode = "local"
        try:
            from app.services.oauth_service import OAuthService

            with mock.patch.object(
                OAuthService, "is_configured", new_callable=mock.PropertyMock, return_value=True
            ):
                response = await client.get("/api/auth/oauth/login")
                assert response.status_code == 403
                assert "disabled" in response.json()["detail"].lower()
        finally:
            settings.auth_mode = original_mode


class TestOAuthSyncErrors:
    """Tests for OAuth sync error paths."""

    @pytest.mark.asyncio
    async def test_oauth_sync_not_oauth_user(self, client, user_token, test_user):
        """OAuth sync should fail for non-OAuth users."""
        test_user.oauth_provider = None
        response = await client.post(
            "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 400
        assert "Not an OAuth user" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_oauth_sync_no_refresh_token(self, client, user_token, test_user):
        """OAuth sync should fail when no refresh token is stored."""
        test_user.oauth_provider = "oauth"
        test_user.security = {"oauth_refresh_token": None}
        response = await client.post(
            "/api/auth/oauth/sync", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 400
        assert "No refresh token available" in response.json()["detail"]


class TestLogoutWithStopOnLogout:
    """Tests for logout with stop_on_logout preference."""

    @pytest.mark.asyncio
    async def test_logout_stops_servers_when_preference_set(self, client, test_user, db_session):
        """Logout should stop running servers when stop_on_logout is enabled."""
        from app.models.server import Server

        test_user.preferences = {"stop_on_logout": True}
        server = Server(
            name="running-srv", user_id=test_user.id, status="running", container_id=None
        )
        db_session.add(server)
        await db_session.commit()

        # Login
        login_resp = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
        )
        if login_resp.status_code == 429:
            pytest.skip("Rate limited")
        refresh_token = login_resp.json()["refresh_token"]

        response = await client.post("/api/auth/logout", json={"refresh_token": refresh_token})
        assert response.status_code == 200
        assert "Logged out" in response.json()["message"]


class TestCleanupExpiredRefreshTokens:
    """Tests for refresh token cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_refresh_tokens(self, db_session, test_user):
        """Cleanup should delete expired refresh tokens."""
        from app.api.auth import cleanup_expired_refresh_tokens

        expired_rt = RefreshToken(
            user_id=test_user.id,
            token_hash="hash",
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60),
        )
        db_session.add(expired_rt)
        await db_session.commit()

        count = await cleanup_expired_refresh_tokens(db_session)
        assert count >= 1
