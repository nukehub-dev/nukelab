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

class TestCreditsExtended:
    """Tests for credits endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_get_credit_history(self, client, user_token):
        """Should get credit transaction history."""
        response = await client.get(
            "/api/credits/history",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_user_credit_history_admin(self, client, admin_token, test_user):
        """Admin should get any user's credit history."""
        response = await client.get(
            f"/api/credits/users/{test_user.id}/history",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_deduct_credits(self, client, admin_token, test_user, db_session):
        """Admin should be able to deduct credits."""
        test_user.nuke_balance = 100
        await db_session.commit()

        with mock.patch("app.api.credits.CreditService") as mock_credit:
            mock_tx = mock.Mock()
            mock_tx.balance_after = 50
            mock_tx.to_dict.return_value = {"id": str(uuid_mod.uuid4()), "amount": -50}
            mock_credit.return_value.deduct_credits = mock.AsyncMock(return_value=mock_tx)
            with mock.patch("app.api.credits.NotificationService") as mock_notif:
                mock_notif.return_value.credits_deducted = mock.AsyncMock()
                response = await client.post(
                    f"/api/credits/users/{test_user.id}/deduct",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"amount": 50, "reason": "test deduction"},
                )
        assert response.status_code == 200
        assert "deducted" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_get_low_balance_users(self, client, admin_token):
        """Admin should get low balance users."""
        response = await client.get(
            "/api/credits/low-balance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert "users" in response.json()


# ─────────────────────────────────────────────────────────────
# System API
# ─────────────────────────────────────────────────────────────


