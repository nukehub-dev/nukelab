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


class TestCreditService:
    """Credit service business logic tests."""

    @pytest.mark.asyncio
    async def test_consume_credits(self, client, test_user, user_token, db_session):
        """CreditService should consume credits and update balance."""
        from app.services.credit_service import CreditService

        service = CreditService(db_session)

        initial = await service.get_balance(str(test_user.id))
        assert initial > 0

        tx = await service.consume_credits(
            user_id=str(test_user.id),
            amount=10,
            description="Test consumption"
        )

        assert tx.amount == -10
        assert tx.balance_after == initial - 10

        new_balance = await service.get_balance(str(test_user.id))
        assert new_balance == initial - 10

    @pytest.mark.asyncio
    async def test_credit_consumption_flow(self, client, test_user, user_token, db_session):
        """E2E: Credits should be consumed and granted back correctly."""
        from app.services.credit_service import CreditService

        service = CreditService(db_session)

        initial = await service.get_balance(str(test_user.id))
        assert initial > 0

        amount = 5
        tx = await service.consume_credits(
            user_id=str(test_user.id),
            amount=amount,
            description="E2E test consumption"
        )

        assert tx.amount == -amount
        assert tx.balance_after == initial - amount

        new_balance = await service.get_balance(str(test_user.id))
        assert new_balance == initial - amount

        grant_tx = await service.grant_credits(
            user_id=str(test_user.id),
            amount=amount,
            actor_id=str(test_user.id),
            reason="E2E test cleanup"
        )

        assert grant_tx.amount == amount
        final_balance = await service.get_balance(str(test_user.id))
        assert final_balance == initial


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