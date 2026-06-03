"""Extended tests for Notifications API endpoints."""

import pytest
import uuid

from app.models.notification import Notification


class TestNotificationUnreadCount:
    @pytest.mark.asyncio
    async def test_unread_count(self, client, user_token, test_user, db_session):
        n1 = Notification(user_id=test_user.id, type="t", title="T1", message="M", read=False)
        n2 = Notification(user_id=test_user.id, type="t", title="T2", message="M", read=False)
        n3 = Notification(user_id=test_user.id, type="t", title="T3", message="M", read=True)
        db_session.add_all([n1, n2, n3])
        await db_session.commit()

        response = await client.get(
            "/api/notifications/unread-count",
            headers={"Authorization": f"Bearer {user_token}"}
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
            headers={"Authorization": f"Bearer {user_token}"}
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
            "/api/notifications/?type=server",
            headers={"Authorization": f"Bearer {user_token}"}
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
            "/api/notifications/read-all",
            headers={"Authorization": f"Bearer {user_token}"}
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
            f"/api/notifications/{n.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_notification_not_found(self, client, user_token):
        response = await client.delete(
            f"/api/notifications/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"}
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
                "severity": "info"
            }
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
            }
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_mark_read_not_found(self, client, user_token):
        response = await client.put(
            f"/api/notifications/{uuid.uuid4()}/read",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404
