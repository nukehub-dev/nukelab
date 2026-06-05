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

class TestBulkExtended:
    """Tests for bulk endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_bulk_invalid_action(self, client, user_token):
        """Invalid action should return 400."""
        response = await client.post(
            "/api/bulk/servers/bulk-action",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"action": "invalid", "server_ids": [str(uuid_mod.uuid4())]},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_bulk_permission_denied(self, client, user_token):
        """User without permission should get 403."""
        with mock.patch("app.api.bulk.has_permission", return_value=False):
            response = await client.post(
                "/api/bulk/servers/bulk-action",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"action": "start", "server_ids": [str(uuid_mod.uuid4())]},
            )
        assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Dashboard API
# ─────────────────────────────────────────────────────────────


