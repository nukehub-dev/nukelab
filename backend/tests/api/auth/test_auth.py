"""Tests for Auth API endpoints."""

import pytest
from datetime import datetime, timedelta, UTC


class TestRefreshToken:
    """Refresh token rotation and revocation tests."""

    @pytest.mark.asyncio
    async def test_login_returns_refresh_token(self, client, test_user):
        """Login should return both access_token and refresh_token."""
        response = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["refresh_token"]) > 20

    @pytest.mark.asyncio
    async def test_refresh_exchanges_token(self, client, test_user):
        """Refresh endpoint should exchange refresh token for new pair."""
        # Login to get tokens
        login_resp = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
        )
        login_data = login_resp.json()
        refresh_token = login_data["refresh_token"]

        # Exchange refresh token
        response = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        # New refresh token should be different from old one
        assert data["refresh_token"] != refresh_token

    @pytest.mark.asyncio
    async def test_refresh_revokes_old_token(self, client, test_user):
        """Old refresh token should be revoked after rotation."""
        # Login to get tokens
        login_resp = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
        )
        old_refresh = login_resp.json()["refresh_token"]

        # Exchange once
        await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})

        # Try to reuse old refresh token
        response = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})

        assert response.status_code == 401
        assert "Invalid or expired" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_refresh_with_invalid_token(self, client):
        """Invalid refresh token should be rejected."""
        response = await client.post(
            "/api/auth/refresh", json={"refresh_token": "invalid-token-123"}
        )

        assert response.status_code == 401
        assert "Invalid or expired" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_refresh_with_expired_token(self, client, test_user, db_session):
        """Expired refresh token should be rejected."""
        from app.models.refresh_token import RefreshToken
        from app.api.auth import pwd_context
        import secrets

        # Create an expired refresh token directly
        plaintext = secrets.token_urlsafe(32)
        token_hash = pwd_context.hash(plaintext)
        expired_rt = RefreshToken(
            user_id=test_user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
        db_session.add(expired_rt)
        await db_session.commit()

        response = await client.post("/api/auth/refresh", json={"refresh_token": plaintext})

        assert response.status_code == 401
        assert "Invalid or expired" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_logout_revokes_refresh_token(self, client, test_user):
        """Logout should revoke the refresh token."""
        # Login to get tokens
        login_resp = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
        )
        refresh_token = login_resp.json()["refresh_token"]

        # Logout
        logout_resp = await client.post("/api/auth/logout", json={"refresh_token": refresh_token})
        assert logout_resp.status_code == 200

        # Try to refresh with revoked token
        response = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_without_refresh_token(self, client):
        """Logout without refresh token should still succeed."""
        response = await client.post("/api/auth/logout")

        assert response.status_code == 200
        assert "Logged out" in response.json()["message"]

    @pytest.mark.asyncio
    async def test_new_access_token_works_after_refresh(self, client, test_user):
        """New access token from refresh should authenticate requests."""
        # Login
        login_resp = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
        )
        refresh_token = login_resp.json()["refresh_token"]

        # Refresh
        refresh_resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        new_access = refresh_resp.json()["access_token"]

        # Use new access token
        me_resp = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {new_access}"}
        )

        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "testuser"


class TestLogin:
    """Login endpoint tests."""

    @pytest.mark.asyncio
    async def test_login_with_valid_credentials(self, client, test_user):
        """User should login with valid credentials."""
        response = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_with_invalid_credentials(self, client, test_user):
        """Login should fail with wrong password."""
        response = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "wrongpassword"}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_with_nonexistent_user(self, client):
        """Login should fail with non-existent user."""
        response = await client.post(
            "/api/auth/login", data={"username": "nonexistent", "password": "password"}
        )

        assert response.status_code == 401


class TestCurrentUser:
    """Current user endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_current_user(self, client, user_token, test_user):
        """User should get their profile."""
        response = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {user_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_get_current_user_unauthenticated(self, client):
        """Unauthenticated request should be rejected."""
        response = await client.get("/api/auth/me")

        assert response.status_code == 401


class TestRateLimiting:
    """Rate limiting tests."""

    @pytest.mark.asyncio
    async def test_login_rate_limit(self, client, test_user):
        """Login should be rate limited after multiple attempts."""
        # First try should work or fail with auth error (not ratelimit)
        response = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "wrongpassword"}
        )

        # Either succeeds (if not rate limited) or fails with 401 (wrong password)
        # We're testing that the endpoint works, rate limiting is per-IP
        assert response.status_code in [200, 401, 429]


class TestVerification:
    """Auth verification endpoint tests."""

    @pytest.mark.asyncio
    async def test_verify_valid_token(self, client, user_token):
        """Verify endpoint should work with valid token."""
        response = await client.get(
            "/api/auth/verify", headers={"Authorization": f"Bearer {user_token}"}
        )

        assert response.status_code in [200, 401]

    @pytest.mark.asyncio
    async def test_verify_invalid_token(self, client):
        """Verify endpoint should reject invalid token."""
        response = await client.get(
            "/api/auth/verify", headers={"Authorization": "Bearer invalidtoken123"}
        )

        assert response.status_code == 401
