"""Tests for Credits API endpoints."""

import pytest


class TestCreditsBalance:
    """Credits balance endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_own_balance(self, client, user_token, test_user):
        """User should see their own balance."""
        response = await client.get(
            "/api/credits/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "balance" in data
        assert data["balance"] == test_user.nuke_balance


class TestCreditsAdmin:
    """Admin credit management tests."""

    @pytest.mark.asyncio
    async def test_grant_credits_to_user(self, client, admin_token, test_user):
        """Admin should grant credits to a user."""
        response = await client.post(
            f"/api/credits/users/{test_user.id}/grant",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"amount": 100, "reason": "Bonus"}
        )
        
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_grant_credits_requires_admin(self, client, user_token):
        """Non-admin should not grant credits."""
        response = await client.post(
            "/api/credits/users/some-user-id/grant",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 100}
        )
        
        assert response.status_code == 403


class TestTransactions:
    """Credit transaction tests."""

    @pytest.mark.asyncio
    async def test_view_transaction_history(self, client, user_token):
        """User should view their transaction history."""
        response = await client.get(
            "/api/credits/history",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        
        assert response.status_code == 200