"""Tests for Notifications API endpoints."""

import pytest

from app.models.notification import Notification


class TestNotificationCreate:
    """Notification creation tests."""

    @pytest.mark.asyncio
    async def test_admin_can_create_notification(self, client, test_user, admin_token):
        """Admin should be able to create notifications for users."""
        response = await client.post(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={
                "user_id": str(test_user.id),
                "type": "server",
                "title": "Server Started",
                "message": "Your server has been started successfully",
                "severity": "success",
                "action_url": "/dashboard/servers"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "server"
        assert data["title"] == "Server Started"
        assert data["severity"] == "success"
        assert data["read"] is False


class TestNotificationList:
    """Notification listing and filtering tests."""

    @pytest.mark.asyncio
    async def test_list_user_notifications(self, client, test_user, user_token, db_session):
        """User should see their own notifications with unread count."""
        # Seed a notification directly
        notification = Notification(
            user_id=test_user.id,
            type="system",
            title="Test Notification",
            message="This is a test",
            severity="info"
        )
        db_session.add(notification)
        await db_session.commit()
        
        response = await client.get(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data
        assert "unread_count" in data
        assert len(data["notifications"]) >= 1

    @pytest.mark.asyncio
    async def test_unread_count_endpoint(self, client, user_token):
        """Unread count endpoint should return integer."""
        response = await client.get(
            "/api/notifications/unread-count",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "unread_count" in data
        assert isinstance(data["unread_count"], int)


class TestNotificationActions:
    """Notification state change tests."""

    @pytest.mark.asyncio
    async def test_mark_notification_as_read(self, client, test_user, user_token, db_session):
        """User should be able to mark a notification as read."""
        notification = Notification(
            user_id=test_user.id,
            type="test",
            title="Read Test",
            message="Please mark me as read"
        )
        db_session.add(notification)
        await db_session.commit()
        await db_session.refresh(notification)
        notif_id = str(notification.id)
        
        response = await client.put(
            f"/api/notifications/{notif_id}/read",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["read"] is True
        assert data["read_at"] is not None
