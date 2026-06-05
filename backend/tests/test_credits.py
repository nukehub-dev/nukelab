"""Tests for Credits API endpoints."""

import pytest
from datetime import datetime, timedelta, UTC
from app.models.server import Server


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


class TestServerBillingReconciliation:
    """Server billing reconciliation tests."""

    @pytest.mark.asyncio
    async def test_reconcile_exact_billing_short_run(self, db_session, test_user):
        """Server stopped after short run should bill exact duration."""
        from app.services.credit_service import CreditService
        from app.models.server_plan import ServerPlan
        import uuid as uuid_mod

        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name="Test Plan",
            slug="test-plan",
            cost_per_hour=60,  # 1 NUKE per minute
        )
        db_session.add(plan)
        await db_session.flush()

        server = Server(
            id=uuid_mod.uuid4(),
            name="test-server",
            user_id=test_user.id,
            plan_id=plan.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5),
            stopped_at=datetime.now(UTC).replace(tzinfo=None),
            total_cost=0,
        )
        db_session.add(server)
        await db_session.commit()

        service = CreditService(db_session)
        initial_balance = await service.get_balance(str(test_user.id))
        additional = await service.reconcile_server_billing(server, plan)

        # 5 minutes at 60 NUKE/hr = 5 NUKE
        assert additional == 5
        assert server.total_cost == 5

        balance = await service.get_balance(str(test_user.id))
        assert balance == initial_balance - 5

    @pytest.mark.asyncio
    async def test_reconcile_no_double_billing(self, db_session, test_user):
        """Server already billed via ticks should not double-bill."""
        from app.services.credit_service import CreditService
        from app.models.server_plan import ServerPlan
        import uuid as uuid_mod

        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name="Test Plan",
            slug="test-plan",
            cost_per_hour=60,
        )
        db_session.add(plan)
        await db_session.flush()

        server = Server(
            id=uuid_mod.uuid4(),
            name="test-server",
            user_id=test_user.id,
            plan_id=plan.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30),
            stopped_at=datetime.now(UTC).replace(tzinfo=None),
            total_cost=30,  # Already billed 30 NUKE via ticks
        )
        db_session.add(server)
        await db_session.commit()

        service = CreditService(db_session)
        additional = await service.reconcile_server_billing(server, plan)

        # 30 min at 60 NUKE/hr = 30 NUKE, already billed 30
        assert additional == 0
        assert server.total_cost == 30

    @pytest.mark.asyncio
    async def test_reconcile_partial_under_billing(self, db_session, test_user):
        """Server under-billed via ticks should bill difference."""
        from app.services.credit_service import CreditService
        from app.models.server_plan import ServerPlan
        import uuid as uuid_mod

        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name="Test Plan",
            slug="test-plan",
            cost_per_hour=60,
        )
        db_session.add(plan)
        await db_session.flush()

        server = Server(
            id=uuid_mod.uuid4(),
            name="test-server",
            user_id=test_user.id,
            plan_id=plan.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=20),
            stopped_at=datetime.now(UTC).replace(tzinfo=None),
            total_cost=10,  # Only billed for 10 minutes
        )
        db_session.add(server)
        await db_session.commit()

        service = CreditService(db_session)
        additional = await service.reconcile_server_billing(server, plan)

        # 20 min at 60 NUKE/hr = 20 NUKE, already billed 10
        assert additional == 10
        assert server.total_cost == 20

    @pytest.mark.asyncio
    async def test_reconcile_zero_cost_plan(self, db_session, test_user):
        """Free plan should not bill anything."""
        from app.services.credit_service import CreditService
        from app.models.server_plan import ServerPlan
        import uuid as uuid_mod

        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name="Free Plan",
            slug="free-plan",
            cost_per_hour=0,
        )
        db_session.add(plan)
        await db_session.flush()

        server = Server(
            id=uuid_mod.uuid4(),
            name="test-server",
            user_id=test_user.id,
            plan_id=plan.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
            stopped_at=datetime.now(UTC).replace(tzinfo=None),
            total_cost=0,
        )
        db_session.add(server)
        await db_session.commit()

        service = CreditService(db_session)
        additional = await service.reconcile_server_billing(server, plan)

        assert additional == 0
        assert server.total_cost == 0


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