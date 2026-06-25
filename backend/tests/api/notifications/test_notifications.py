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
                "action_url": "/dashboard/servers",
            },
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
            severity="info",
        )
        db_session.add(notification)
        await db_session.commit()

        response = await client.get(
            "/api/notifications/", headers={"Authorization": f"Bearer {user_token}"}
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
            "/api/notifications/unread-count", headers={"Authorization": f"Bearer {user_token}"}
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
            user_id=test_user.id, type="test", title="Read Test", message="Please mark me as read"
        )
        db_session.add(notification)
        await db_session.commit()
        await db_session.refresh(notification)
        notif_id = str(notification.id)

        response = await client.put(
            f"/api/notifications/{notif_id}/read", headers={"Authorization": f"Bearer {user_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["read"] is True
        assert data["read_at"] is not None


"""Extended tests for Environments, Notifications, and Health API endpoints."""

import uuid

import pytest


class TestNotificationsAPI:
    """Tests for notification endpoints."""

    @pytest.mark.asyncio
    async def test_list_notifications(self, client, user_token):
        """Should list user notifications."""
        response = await client.get(
            "/api/notifications/", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data
        assert "unread_count" in data

    @pytest.mark.asyncio
    async def test_unread_count(self, client, user_token):
        """Should get unread notification count."""
        response = await client.get(
            "/api/notifications/unread-count", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "unread_count" in data

    @pytest.mark.asyncio
    async def test_mark_notification_read_not_found(self, client, user_token):
        """Marking non-existent notification as read should 404."""
        response = await client.put(
            "/api/notifications/00000000-0000-0000-0000-000000000000/read",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_mark_all_read(self, client, user_token):
        """Should mark all notifications as read."""
        response = await client.put(
            "/api/notifications/read-all", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200


"""Extended tests for small API modules — coverage gap closure."""

import uuid as uuid_mod

import pytest

from app.config import settings


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


"""Extended tests for Notifications API endpoints."""

import pytest


class TestNotificationUnreadCount:
    @pytest.mark.asyncio
    async def test_unread_count(self, client, user_token, test_user, db_session):
        n1 = Notification(user_id=test_user.id, type="t", title="T1", message="M", read=False)
        n2 = Notification(user_id=test_user.id, type="t", title="T2", message="M", read=False)
        n3 = Notification(user_id=test_user.id, type="t", title="T3", message="M", read=True)
        db_session.add_all([n1, n2, n3])
        await db_session.commit()

        response = await client.get(
            "/api/notifications/unread-count", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert response.json()["unread_count"] == 2


class TestNotificationFilters:
    @pytest.mark.asyncio
    async def test_unread_only_filter(self, client, user_token, test_user, db_session):
        n1 = Notification(user_id=test_user.id, type="t", title="U", message="M", read=False)
        n2 = Notification(user_id=test_user.id, type="t", title="R", message="M", read=True)
        db_session.add_all([n1, n2])
        await db_session.commit()

        response = await client.get(
            "/api/notifications/?unread_only=true",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["title"] == "U"

    @pytest.mark.asyncio
    async def test_type_filter(self, client, user_token, test_user, db_session):
        n1 = Notification(user_id=test_user.id, type="server", title="S", message="M")
        n2 = Notification(user_id=test_user.id, type="billing", title="B", message="M")
        db_session.add_all([n1, n2])
        await db_session.commit()

        response = await client.get(
            "/api/notifications/?type=server", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["type"] == "server"


class TestMarkAllAsRead:
    @pytest.mark.asyncio
    async def test_mark_all_as_read(self, client, user_token, test_user, db_session):
        n1 = Notification(user_id=test_user.id, type="t", title="T1", message="M", read=False)
        n2 = Notification(user_id=test_user.id, type="t", title="T2", message="M", read=False)
        db_session.add_all([n1, n2])
        await db_session.commit()

        response = await client.put(
            "/api/notifications/read-all", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        assert "2" in response.json()["message"]


class TestDeleteNotification:
    @pytest.mark.asyncio
    async def test_delete_notification(self, client, user_token, test_user, db_session):
        n = Notification(user_id=test_user.id, type="t", title="Del", message="M")
        db_session.add(n)
        await db_session.commit()
        await db_session.refresh(n)

        response = await client.delete(
            f"/api/notifications/{n.id}", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_notification_not_found(self, client, user_token):
        response = await client.delete(
            f"/api/notifications/{uuid.uuid4()}", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404


class TestAdminCreateNotification:
    @pytest.mark.asyncio
    async def test_admin_can_create(self, client, admin_token, test_user):
        response = await client.post(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={
                "user_id": str(test_user.id),
                "type": "system",
                "title": "Admin Alert",
                "message": "Hello",
                "severity": "info",
            },
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_user_cannot_create(self, client, user_token, test_user):
        response = await client.post(
            "/api/notifications/",
            headers={"Authorization": f"Bearer {user_token}"},
            params={
                "user_id": str(test_user.id),
                "type": "system",
                "title": "Hack",
                "message": "Bad",
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_mark_read_not_found(self, client, user_token):
        response = await client.put(
            f"/api/notifications/{uuid.uuid4()}/read",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
