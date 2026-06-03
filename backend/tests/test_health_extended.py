"""Extended tests for Health API failure paths."""

import pytest
from unittest import mock

from app.main import app
from app.db.session import get_db


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
                "/api/health/detailed",
                headers={"Authorization": f"Bearer {admin_token}"}
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
                "/api/health/detailed",
                headers={"Authorization": f"Bearer {admin_token}"}
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
                "/api/health/detailed",
                headers={"Authorization": f"Bearer {admin_token}"}
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
                    "/api/health/detailed",
                    headers={"Authorization": f"Bearer {admin_token}"}
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

        with mock.patch("app.services.email_service.EmailService", mock_email_cls):
            response = await client.get(
                "/api/health/detailed",
                headers={"Authorization": f"Bearer {admin_token}"}
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
                "/api/health/detailed",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["resources"]["disk"]["percent"] == 0

    @pytest.mark.asyncio
    async def test_detailed_health_requires_admin(self, client, user_token):
        """Non-admin should be forbidden from detailed health."""
        response = await client.get(
            "/api/health/detailed",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_detailed_health_unauthenticated(self, client):
        """Unauthenticated request should be rejected."""
        response = await client.get("/api/health/detailed")
        assert response.status_code == 401
