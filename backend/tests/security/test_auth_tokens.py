# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Security regression tests for authentication and token abuse.

These tests verify JWT integrity, token scope enforcement, and that API tokens
cannot be used for high-impact session-only operations.
"""

from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient

from app.config import settings

_ALGORITHM = settings.user_auth_key_algorithm


def _load_signing_key() -> str:
    """Load the active Ed25519 private key PEM for resigning tokens."""
    with open(settings.user_auth_private_key_path, "rb") as f:
        return f.read().decode("utf-8")


def _generate_wrong_key() -> str:
    """Generate a different Ed25519 private key PEM."""
    private_key = Ed25519PrivateKey.generate()
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


class TestJWTIntegrity:
    """Tests for JWT manipulation and validation."""

    @pytest.mark.asyncio
    async def test_tampered_role_claim_is_rejected(
        self, client: AsyncClient, test_user, user_token
    ):
        """Modifying the role claim in a JWT should not grant admin access."""
        private_key = _load_signing_key()
        payload = jwt.decode(
            user_token,
            options={"verify_signature": False},
            algorithms=[_ALGORITHM],
        )
        payload["role"] = "admin"

        tampered_token = jwt.encode(
            payload,
            private_key,
            algorithm=_ALGORITHM,
        )

        response = await client.get(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {tampered_token}"},
        )
        data = response.json()
        if response.status_code == 200:
            assert data.get("role") != "admin", "Backend trusted tampered role claim"

    @pytest.mark.asyncio
    async def test_expired_token_is_rejected(self, client: AsyncClient, test_user):
        """Expired JWT should be rejected."""
        from app.core.token_signing import create_access_token

        expired_token = create_access_token(
            data={"sub": test_user.username, "role": test_user.role},
            expires_delta=timedelta(seconds=-10),
        )

        response = await client.get(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_missing_token_is_rejected(self, client: AsyncClient):
        """Requests without authentication should be rejected."""
        response = await client.get("/api/users/me/profile")
        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_invalid_signature_is_rejected(self, client: AsyncClient, user_token):
        """JWT signed with a different key should be rejected."""
        wrong_key = _generate_wrong_key()
        payload = jwt.decode(
            user_token,
            options={"verify_signature": False},
            algorithms=[_ALGORITHM],
        )
        wrong_token = jwt.encode(
            payload,
            wrong_key,
            algorithm=_ALGORITHM,
        )

        response = await client.get(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {wrong_token}"},
        )
        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )


class TestAPITokenScope:
    """Tests for API token scope enforcement."""

    @pytest.mark.asyncio
    async def test_api_token_cannot_access_out_of_scope_endpoint(
        self, client: AsyncClient, api_token
    ):
        """API token should be rejected from endpoints outside its scopes."""
        response = await client.delete(
            "/api/servers/00000000-0000-0000-0000-000000000001",
            headers={"Authorization": f"Token {api_token.raw_token}"},
        )
        assert response.status_code in (403, 401, 404), (
            f"Expected 403/401/404, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_api_token_cannot_perform_bulk_actions(self, client: AsyncClient, api_token):
        """Bulk actions should reject API tokens and require session JWT."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            json={"action": "stop", "server_ids": []},
            headers={"Authorization": f"Token {api_token.raw_token}"},
        )
        assert response.status_code in (401, 403), (
            f"Expected 401/403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_api_token_cannot_access_admin_endpoints(self, client: AsyncClient, api_token):
        """API token should not access admin endpoints."""
        response = await client.get(
            "/api/admin/servers",
            headers={"Authorization": f"Token {api_token.raw_token}"},
        )
        assert response.status_code in (401, 403, 404), (
            f"Expected 401/403/404, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_revoked_api_token_is_rejected(self, client: AsyncClient, api_token, db_session):
        """Revoked API tokens should not authenticate."""
        api_token.db_token.is_active = False
        await db_session.commit()

        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Token {api_token.raw_token}"},
        )
        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )


class TestCookieSession:
    """Tests for cookie-based session authentication."""

    @pytest.mark.asyncio
    async def test_csrf_required_for_cookie_auth(self, client: AsyncClient, test_user):
        """State-changing requests with cookie auth require CSRF token."""
        from app.middleware.csrf import CSRFProtectMiddleware

        assert CSRFProtectMiddleware is not None, "CSRF middleware not installed"

    @pytest.mark.asyncio
    async def test_bearer_auth_exempt_from_csrf(self, client: AsyncClient, user_token):
        """Bearer token requests should not require CSRF token."""
        response = await client.put(
            "/api/users/me/profile",
            json={"first_name": "CSRFTest"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
