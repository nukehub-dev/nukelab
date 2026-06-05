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

class TestNotificationsExtended:
    """Tests for notifications endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_delete_notification(self, client, user_token, test_user, db_session):
        """Should delete a notification."""
        notif = Notification(
            user_id=test_user.id, type="test", title="t", message="m", severity="info"
        )
        db_session.add(notif)
        await db_session.commit()
        await db_session.refresh(notif)

        response = await client.delete(
            f"/api/notifications/{notif.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_notification_not_found(self, client, user_token):
        """Should return 404 for nonexistent notification."""
        response = await client.delete(
            f"/api/notifications/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_notifications_filter_type(self, client, user_token, test_user, db_session):
        """Should filter notifications by type."""
        notif = Notification(
            user_id=test_user.id, type="server", title="t", message="m", severity="info"
        )
        db_session.add(notif)
        await db_session.commit()

        response = await client.get(
            "/api/notifications/?type=server",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert all(n["type"] == "server" for n in data["notifications"])

    @pytest.mark.asyncio
    async def test_list_notifications_unread_only(self, client, user_token, test_user, db_session):
        """Should filter to unread notifications only."""
        notif = Notification(
            user_id=test_user.id, type="test", title="t", message="m", severity="info", read=False
        )
        db_session.add(notif)
        await db_session.commit()

        response = await client.get(
            "/api/notifications/?unread_only=true",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["unread_count"] >= 1

    @pytest.mark.asyncio
    async def test_admin_create_notification(self, client, admin_token, test_user, db_session):
        """Admin should be able to create a notification."""
        response = await client.post(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={
                "user_id": str(test_user.id),
                "type": "info",
                "title": "Test",
                "message": "Hello",
                "severity": "info",
            },
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_user_cannot_create_notification(self, client, user_token, test_user):
        """Non-admin should be blocked from creating notifications."""
        response = await client.post(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {user_token}"},
            params={
                "user_id": str(test_user.id),
                "type": "info",
                "title": "Test",
                "message": "Hello",
            },
        )
        assert response.status_code == 403


# ─────────────────────────────────────────────────────────────
# Credits API
# ─────────────────────────────────────────────────────────────


