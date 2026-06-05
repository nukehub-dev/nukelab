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



