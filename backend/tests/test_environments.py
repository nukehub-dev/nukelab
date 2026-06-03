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

    @pytest.mark.asyncio
    async def test_update_environment(self, client, admin_token, db_session):
        """Admin should update an environment."""
        from app.models.environment_template import EnvironmentTemplate
        env = EnvironmentTemplate(name="Updatable", slug="updatable", image="test:latest")
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        response = await client.put(
            f"/api/environments/{env.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Updated Name", "description": "New desc"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_deactivate_environment(self, client, admin_token, db_session):
        """Admin should deactivate an environment."""
        from app.models.environment_template import EnvironmentTemplate
        env = EnvironmentTemplate(name="Deact", slug="deact", image="test:latest", is_active=True)
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        response = await client.delete(
            f"/api/environments/{env.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert "deactivated" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_permanently_delete_environment(self, client, admin_token, db_session):
        """Admin should permanently delete an environment."""
        from app.models.environment_template import EnvironmentTemplate
        env = EnvironmentTemplate(name="PermDel", slug="permdel", image="test:latest")
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        response = await client.delete(
            f"/api/environments/{env.id}/permanent",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert "permanently deleted" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_clone_environment(self, client, admin_token, db_session):
        """Admin should clone an environment."""
        from app.models.environment_template import EnvironmentTemplate
        env = EnvironmentTemplate(name="Original", slug="original", image="test:latest")
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        response = await client.post(
            f"/api/environments/{env.id}/clone",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Cloned Env", "slug": "cloned-env"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["data"]["name"] == "Cloned Env"
        assert data["data"]["slug"] == "cloned-env"

    @pytest.mark.asyncio
    async def test_clone_environment_not_found(self, client, admin_token):
        """Cloning nonexistent environment should 404."""
        import uuid
        response = await client.post(
            f"/api/environments/{uuid.uuid4()}/clone",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Clone", "slug": "clone"}
        )
        assert response.status_code == 404


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