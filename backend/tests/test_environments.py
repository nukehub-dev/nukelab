"""Tests for Environments API endpoints."""

import pytest


class TestEnvironmentsList:
    """Environments listing endpoint tests."""

    @pytest.mark.asyncio
    async def test_list_environments(self, client, user_token):
        """User should list environments."""
        response = await client.get(
            "/api/environments/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200


class TestEnvironmentCRUD:
    """Environment CRUD endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_environment_as_admin(self, client, admin_token):
        """Admin should create environment."""
        response = await client.post(
            "/api/environments/",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "Test Environment",
                "slug": "test-env",
                "description": "A test environment",
                "image": "nukelab/test:latest",
                "packages": ["python", "numpy"],
                "environment_variables": {"DEBUG": "true"},
                "ports": [3000],
                "volumes": ["/data:/data"],
                "icon": "🧪",
                "color": "#3B82F6",
                "category": "test",
                "is_public": True
            }
        )
        
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_environment_as_user_forbidden(self, client, user_token):
        """User should not create environments."""
        response = await client.post(
            "/api/environments/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "Hack Env",
                "slug": "hack-env",
                "image": "evil:latest"
            }
        )
        
        assert response.status_code == 403


class TestEnvironmentActivation:
    """Environment activation tests."""

    @pytest.mark.asyncio
    async def test_activate_environment(self, client, admin_token, db_session):
        """Admin should activate/deactivate environment."""
        from app.models.environment_template import EnvironmentTemplate
        
        env = EnvironmentTemplate(
            name="Active Test",
            slug="active-test",
            image="test:latest",
            is_active=False
        )
        db_session.add(env)
        await db_session.commit()
        
        response = await client.post(
            f"/api/environments/{env.id}/activate",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200