# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for exception-safe security headers middleware and related protections."""

import pytest

from app.config import settings


class TestSecurityHeadersMiddleware:
    """FastAPI ASGI middleware security header tests."""

    @pytest.mark.asyncio
    async def test_health_response_has_security_headers(self, client):
        """Every API response should include defense-in-depth headers."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert response.headers.get("Cross-Origin-Resource-Policy") == "same-origin"
        assert "Permissions-Policy" in response.headers
        assert "accelerometer=()" in response.headers.get("Permissions-Policy", "")

    @pytest.mark.asyncio
    async def test_error_response_has_security_headers(self, client):
        """Headers should be present even on 404 responses."""
        response = await client.get("/api/nonexistent-endpoint")
        assert response.status_code == 404
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert response.headers.get("Cross-Origin-Resource-Policy") == "same-origin"

    @pytest.mark.asyncio
    async def test_hsts_not_set_on_http(self, client):
        """HSTS header must NOT be present on non-TLS requests (dev safety)."""
        response = await client.get("/api/health")
        assert "Strict-Transport-Security" not in response.headers

    @pytest.mark.asyncio
    async def test_middleware_skipped_when_disabled(self, client):
        """When security_headers_enabled=False, no extra headers are added."""
        original = settings.security_headers_enabled
        try:
            settings.security_headers_enabled = False
            response = await client.get("/api/health")
            assert response.status_code == 200
        finally:
            settings.security_headers_enabled = original

    @pytest.mark.asyncio
    async def test_auth_endpoint_has_security_headers(self, client):
        """Auth endpoints (public) should also carry security headers."""
        # Use /auth/me (401 for unauthenticated) instead of /auth/login
        # to avoid slowapi rate-limit conflicts with other tests.
        response = await client.get("/api/auth/me")
        assert response.status_code == 401
        assert response.headers.get("X-Content-Type-Options") == "nosniff"


class TestCacheControl:
    """Cache-Control header tests for sensitive endpoints."""

    @pytest.mark.asyncio
    async def test_auth_login_has_no_store(self, client):
        """Login endpoint must not be cached by browsers or proxies."""
        response = await client.post(
            "/api/auth/login", data={"username": "testuser", "password": "wrongpass"}
        )
        cc = response.headers.get("Cache-Control", "")
        assert "no-store" in cc
        assert response.headers.get("Pragma") == "no-cache"

    @pytest.mark.asyncio
    async def test_auth_me_has_no_store(self, client, user_token):
        """Authenticated user info must not be cached."""
        response = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {user_token}"}
        )
        cc = response.headers.get("Cache-Control", "")
        assert "no-store" in cc

    @pytest.mark.asyncio
    async def test_health_does_not_have_no_store(self, client):
        """Public health endpoint should NOT have no-store (it's cacheable)."""
        response = await client.get("/api/health")
        cc = response.headers.get("Cache-Control", "")
        assert "no-store" not in cc


class TestLogoutClearSiteData:
    """Clear-Site-Data header tests."""

    @pytest.mark.asyncio
    async def test_logout_clears_site_data(self, client):
        """Logout should instruct the browser to wipe cookies, cache, and storage."""
        # Logout does not require authentication — calling it directly avoids
        # slowapi rate-limit conflicts on /auth/login in full-suite runs.
        response = await client.post("/api/auth/logout")
        assert response.status_code == 200
        csd = response.headers.get("Clear-Site-Data", "")
        assert '"cache"' in csd
        assert '"cookies"' in csd
        assert '"storage"' in csd


class TestSecurityHeadersConfiguration:
    """Settings-level security header tests."""

    def test_security_headers_enabled_default(self):
        """security_headers_enabled should default to True."""
        assert getattr(settings, "security_headers_enabled", None) is True
