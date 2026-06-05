"""Extended tests for small API modules — coverage gap closure."""

import pytest
from unittest import mock
from datetime import datetime, timedelta, UTC
import uuid as uuid_mod

from app.config import settings
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate
from app.models.notification import Notification
from app.models.activity_log import ActivityLog
from app.models.credit_transaction import CreditTransaction


@pytest.fixture(autouse=True)
def reset_maintenance_state():
    """Reset global maintenance state before and after each test."""
    settings.maintenance_mode = False
    settings.maintenance_message = "System under maintenance"
    yield
    settings.maintenance_mode = False
    settings.maintenance_message = "System under maintenance"


# ─────────────────────────────────────────────────────────────
# Schedules API
# ─────────────────────────────────────────────────────────────

class TestAnalyticsExtended:
    """Tests for analytics endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_analytics_environments(self, client, admin_token):
        """Admin should get environment usage analytics."""
        with mock.patch("app.api.analytics.AnalyticsService") as mock_svc:
            mock_svc.return_value.get_environment_usage = mock.AsyncMock(return_value=[])
            response = await client.get(
                "/api/analytics/environments",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200
        assert "environments" in response.json()

    @pytest.mark.asyncio
    async def test_analytics_plans(self, client, admin_token):
        """Admin should get plan usage analytics."""
        with mock.patch("app.api.analytics.AnalyticsService") as mock_svc:
            mock_svc.return_value.get_plan_usage = mock.AsyncMock(return_value=[])
            response = await client.get(
                "/api/analytics/plans",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200
        assert "plans" in response.json()

    @pytest.mark.asyncio
    async def test_analytics_export_csv(self, client, admin_token):
        """Admin should export analytics as CSV."""
        with mock.patch("app.api.analytics.AnalyticsService") as mock_svc:
            mock_svc.return_value.get_platform_metrics = mock.AsyncMock(return_value=[{"day": "2024-01-01", "users": 5}])
            response = await client.post(
                "/api/analytics/export",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"metric": "platform-metrics", "format": "csv"},
            )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_analytics_export_invalid_metric(self, client, admin_token):
        """Invalid metric should return 400."""
        response = await client.post(
            "/api/analytics/export",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"metric": "invalid-metric", "format": "json"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_analytics_date_validation(self, client, admin_token):
        """Invalid date range should return 422."""
        response = await client.get(
            "/api/analytics/global?from=2024-01-15T00:00:00&to=2024-01-10T00:00:00",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analytics_date_range_too_large(self, client, admin_token):
        """Date range > 365 days should return 422."""
        response = await client.get(
            "/api/analytics/global?from=2023-01-01T00:00:00&to=2024-01-15T00:00:00",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422

