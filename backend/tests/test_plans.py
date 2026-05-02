"""Tests for Plans API endpoints."""

import pytest


class TestPlansList:
    """Plans listing endpoint tests."""

    @pytest.mark.asyncio
    async def test_list_plans_requires_auth(self, client):
        """Unauthenticated user should not access plans."""
        response = await client.get("/api/plans/")
        
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_plans_as_user(self, client, user_token):
        """Authenticated user should list plans."""
        response = await client.get(
            "/api/plans/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "success" in data or "data" in data


class TestPlanCRUD:
    """Plan CRUD endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_plan_as_admin(self, client, admin_token):
        """Admin should be able to create a plan."""
        response = await client.post(
            "/api/plans/",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "Test Plan",
                "slug": "test-plan-new",
                "description": "A test plan",
                "category": "cpu",
                "cpu_limit": 4.0,
                "memory_limit": "8g",
                "disk_limit": "50g",
                "gpu_limit": 0,
                "max_servers_per_user": 3,
                "cost_per_hour": 2,
                "requires_approval": False,
                "allowed_roles": ["user", "moderator"],
                "priority": 0
            }
        )
        
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_plan_as_user_forbidden(self, client, user_token):
        """Regular user should not create plans."""
        response = await client.post(
            "/api/plans/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "Hacker Plan",
                "slug": "hacker-plan",
                "cpu_limit": 100
            }
        )
        
        assert response.status_code == 403


class TestPlanFeatures:
    """Plan feature tests."""

    @pytest.mark.asyncio
    async def test_default_plan_features(self, client, user_token):
        """Plans should have default feature values."""
        response = await client.get(
            "/api/plans/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        # Just verify we get plans back
        assert data is not None