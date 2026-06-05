"""Extended tests for Environments, Notifications, and Health API endpoints."""

import pytest
import uuid

from app.models.environment_template import EnvironmentTemplate
from app.models.notification import Notification
from app.models.health_check import HealthCheck
from app.models.server import Server

class TestNotificationsAPI:
    """Tests for notification endpoints."""

    @pytest.mark.asyncio
    async def test_list_notifications(self, client, user_token):
        """Should list user notifications."""
        response = await client.get(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data
        assert "unread_count" in data

    @pytest.mark.asyncio
    async def test_unread_count(self, client, user_token):
        """Should get unread notification count."""
        response = await client.get(
            "/api/notifications/unread-count",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "unread_count" in data

    @pytest.mark.asyncio
    async def test_mark_notification_read_not_found(self, client, user_token):
        """Marking non-existent notification as read should 404."""
        response = await client.put(
            "/api/notifications/00000000-0000-0000-0000-000000000000/read",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_mark_all_read(self, client, user_token):
        """Should mark all notifications as read."""
        response = await client.put(
            "/api/notifications/read-all",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200



