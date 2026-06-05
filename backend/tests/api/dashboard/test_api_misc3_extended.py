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

class TestDashboardExtended:
    """Tests for dashboard endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_dashboard_activity_feed_admin(self, client, admin_token):
        """Admin should access activity feed."""
        response = await client.get(
            "/api/dashboard/activity",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert "activities" in response.json()

    @pytest.mark.asyncio
    async def test_dashboard_activity_feed_non_admin(self, client, user_token):
        """Non-admin should be blocked from activity feed."""
        response = await client.get(
            "/api/dashboard/activity",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Analytics API
# ─────────────────────────────────────────────────────────────


