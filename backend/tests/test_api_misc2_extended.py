"""Extended tests for Environments, Notifications, and Health API endpoints."""

import pytest
import uuid

from app.models.environment_template import EnvironmentTemplate
from app.models.notification import Notification
from app.models.health_check import HealthCheck
from app.models.server import Server


class TestEnvironmentsAPI:
    """Tests for environment endpoints."""

    @pytest.mark.asyncio
    async def test_list_environments(self, client, user_token):
        """Should list environments."""
        response = await client.get(
            "/api/environments/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data

    @pytest.mark.asyncio
    async def test_get_environment_not_found(self, client, user_token):
        """Getting non-existent environment should 404."""
        response = await client.get(
            "/api/environments/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_environment_not_found(self, client, user_token):
        """Getting non-existent environment should 404."""
        response = await client.get(
            "/api/environments/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_non_admin_cannot_create_environment(self, client, user_token):
        """Regular user should not create environments."""
        response = await client.post(
            "/api/environments/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "Test", "slug": "test", "image": "test:latest"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_environment(self, client, user_token):
        """Regular user should not update environments."""
        response = await client.put(
            "/api/environments/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "Updated"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_delete_environment(self, client, user_token):
        """Regular user should not delete environments."""
        response = await client.delete(
            "/api/environments/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_clone_environment(self, client, user_token):
        """Regular user should not clone environments."""
        response = await client.post(
            "/api/environments/00000000-0000-0000-0000-000000000000/clone",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "Cloned", "slug": "cloned"}
        )
        assert response.status_code in [403, 404]


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


class TestHealthAPI:
    """Tests for health endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Health check should be public."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    @pytest.mark.asyncio
    async def test_health_status(self, client):
        """Status check should be public."""
        response = await client.get("/api/health/status")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_detailed(self, client, admin_token):
        """Detailed health check may require admin."""
        response = await client.get(
            "/api/health/detailed",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "resources" in data
