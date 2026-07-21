# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Health and Status API endpoints."""

import pytest


class TestBasicHealth:
    """Public health endpoint tests."""

    @pytest.mark.asyncio
    async def test_health_returns_healthy(self, client):
        """Basic health check should return healthy status."""
        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestDetailedHealth:
    """Admin-only detailed health check tests."""

    @pytest.mark.asyncio
    async def test_detailed_health_requires_admin(self, client, admin_token):
        """Detailed health should be accessible to admins only."""
        response = await client.get(
            "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "resources" in data
        assert "database" in data["services"]
        assert "redis" in data["services"]

    @pytest.mark.asyncio
    async def test_detailed_health_services_have_status(self, client, admin_token):
        """Each service in detailed health should have a status field."""
        response = await client.get(
            "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        services = response.json()["services"]
        for service_name, service_data in services.items():
            assert "status" in service_data, f"Service {service_name} missing status"


class TestPlatformStatus:
    """Platform feature flags endpoint tests."""

    @pytest.mark.asyncio
    async def test_status_has_version_and_features(self, client):
        """Platform status should expose version and feature flags."""
        response = await client.get("/api/health/status")

        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "features" in data
        assert data["features"]["gravatar_enabled"] is True
        assert data["features"]["themes_enabled"] is True
        assert data["features"]["notifications_enabled"] is True

    @pytest.mark.asyncio
    async def test_status_has_limits(self, client):
        """Platform status should expose rate limits and quotas."""
        response = await client.get("/api/health/status")

        assert response.status_code == 200
        data = response.json()
        assert "limits" in data
        assert "max_servers_per_user" in data["limits"]
        assert "api_rate_limit" in data["limits"]


"""Coverage tests for smaller API modules: health, system, quotas, ip_restriction."""

from unittest import mock

import pytest


class TestHealthEndpoints:
    """app/api/health.py coverage."""

    @pytest.mark.asyncio
    async def test_health_check_basic(self, client):
        response = await client.get("/api/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_health_check_detailed(self, client, admin_token):
        response = await client.get(
            "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "resources" in data
        assert "database" in data["services"]

    @pytest.mark.asyncio
    async def test_platform_status(self, client):
        response = await client.get("/api/health/status")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "features" in data
        assert "limits" in data
        assert "auth_mode" in data["features"]


"""Extended tests for Environments, Notifications, and Health API endpoints."""


import pytest


class TestHealthAPI:
    """Tests for health endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Health check should be public."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    @pytest.mark.asyncio
    async def test_health_status(self, client):
        """Status check should be public."""
        response = await client.get("/api/health/status")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_detailed(self, client, admin_token):
        """Detailed health check may require admin."""
        response = await client.get(
            "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "resources" in data


"""Extended tests for Health API failure paths."""

import pytest


class TestDetailedHealthFailures:
    """Tests for /api/health/detailed failure paths."""

    @pytest.mark.asyncio
    async def test_detailed_health_db_failure(self, client, admin_token, db_session):
        """Database failure should show degraded status."""
        original_execute = db_session.execute

        async def failing_execute(*args, **kwargs):
            query = str(args[0]) if args else ""
            if "SELECT 1" in query:
                raise Exception("DB down")
            return await original_execute(*args, **kwargs)

        db_session.execute = failing_execute
        try:
            response = await client.get(
                "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
            )
        finally:
            db_session.execute = original_execute

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["database"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_detailed_health_redis_failure(self, client, admin_token):
        """Redis failure should show degraded status."""
        with mock.patch("app.api.health.redis.from_url", side_effect=Exception("Redis down")):
            response = await client.get(
                "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["redis"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_detailed_health_container_failure(self, client, admin_token):
        """Container runtime failure should show degraded status."""
        mock_client = mock.AsyncMock()
        mock_client.connect = mock.AsyncMock(side_effect=Exception("No runtime"))

        with mock.patch("app.container.client.container_client", mock_client):
            response = await client.get(
                "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["containers"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_detailed_health_smtp_failure(self, client, admin_token):
        """SMTP failure should show degraded status."""
        mock_email_cls = mock.Mock()
        mock_email = mock_email_cls.return_value
        mock_email.enabled = True
        mock_email.smtp_host = "smtp.test"
        mock_email.smtp_port = 587
        mock_email.use_tls = False
        mock_email.verify_certs = True

        with mock.patch("app.services.email_service.EmailService", mock_email_cls):
            with mock.patch("aiosmtplib.SMTP", side_effect=Exception("SMTP down")):
                response = await client.get(
                    "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
                )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["services"]["smtp"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_detailed_health_smtp_disabled(self, client, admin_token):
        """Disabled SMTP should show disabled status, not degraded."""
        mock_email_cls = mock.Mock()
        mock_email = mock_email_cls.return_value
        mock_email.enabled = False

        # Healthy container runtime (no docker socket in the test container)
        mock_container = mock.AsyncMock()
        mock_container.connect = mock.AsyncMock()
        mock_container.version = mock.AsyncMock(return_value={"Version": "test", "Components": []})

        with mock.patch("app.services.email_service.EmailService", mock_email_cls):
            with mock.patch("app.container.client.container_client", mock_container):
                response = await client.get(
                    "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
                )
        assert response.status_code == 200
        data = response.json()
        assert data["services"]["smtp"]["status"] == "disabled"
        # Overall status should still be healthy since other services work
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_detailed_health_psutil_failure(self, client, admin_token):
        """psutil failure should degrade resources but not overall status."""
        mock_psutil = mock.Mock()
        mock_psutil.disk_usage = mock.Mock(side_effect=Exception("disk err"))

        with mock.patch("app.api.health.psutil", mock_psutil):
            response = await client.get(
                "/api/health/detailed", headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["resources"]["disk"]["percent"] == 0

    @pytest.mark.asyncio
    async def test_detailed_health_requires_admin(self, client, user_token):
        """Non-admin should be forbidden from detailed health."""
        response = await client.get(
            "/api/health/detailed", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_detailed_health_unauthenticated(self, client):
        """Unauthenticated request should be rejected."""
        response = await client.get("/api/health/detailed")
        assert response.status_code == 401
