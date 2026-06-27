"""Tests for Credits API endpoints."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.server import Server


class TestCreditsBalance:
    """Credits balance endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_own_balance(self, client, user_token, test_user):
        """User should see their own balance."""
        response = await client.get(
            "/api/credits/", headers={"Authorization": f"Bearer {user_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "balance" in data
        assert data["balance"] == test_user.nuke_balance


class TestCreditsAdmin:
    """Admin credit management tests."""

    @pytest.mark.asyncio
    async def test_update_user_daily_allowance(self, client, admin_token, test_user):
        """Admin should update a user's daily allowance."""
        response = await client.put(
            f"/api/credits/users/{test_user.id}/daily-allowance",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"amount": 2000},
        )
        assert response.status_code == 200
        assert response.json()["user"]["daily_allowance"] == 2000

    @pytest.mark.asyncio
    async def test_grant_credits_to_user(self, client, admin_token, test_user):
        """Admin should grant credits to a user."""
        response = await client.post(
            f"/api/credits/users/{test_user.id}/grant",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"amount": 100, "reason": "Bonus"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_grant_credits_requires_admin(self, client, user_token):
        """Non-admin should not grant credits."""
        response = await client.post(
            "/api/credits/users/some-user-id/grant",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"amount": 100},
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
            user_id=str(test_user.id), amount=10, description="Test consumption"
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
            user_id=str(test_user.id), amount=amount, description="E2E test consumption"
        )

        assert tx.amount == -amount
        assert tx.balance_after == initial - amount

        new_balance = await service.get_balance(str(test_user.id))
        assert new_balance == initial - amount

        grant_tx = await service.grant_credits(
            user_id=str(test_user.id),
            amount=amount,
            actor_id=str(test_user.id),
            reason="E2E test cleanup",
        )

        assert grant_tx.amount == amount
        final_balance = await service.get_balance(str(test_user.id))
        assert final_balance == initial


class TestServerBillingReconciliation:
    """Server billing reconciliation tests."""

    @pytest.mark.asyncio
    async def test_reconcile_exact_billing_short_run(self, db_session, test_user):
        """Server stopped after short run should bill exact duration."""
        import uuid as uuid_mod

        from app.services.credit_service import CreditService

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
        import uuid as uuid_mod

        from app.services.credit_service import CreditService

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
        import uuid as uuid_mod

        from app.services.credit_service import CreditService

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
        import uuid as uuid_mod

        from app.services.credit_service import CreditService

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
            "/api/credits/history", headers={"Authorization": f"Bearer {user_token}"}
        )

        assert response.status_code == 200


"""Extended tests for small API modules — coverage gap closure."""

import uuid as uuid_mod
from unittest import mock

import pytest

from app.config import settings
from app.models.server_plan import ServerPlan


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


class TestCreditsExtended:
    """Tests for credits endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_get_credit_history(self, client, user_token):
        """Should get credit transaction history."""
        response = await client.get(
            "/api/credits/history",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_user_credit_history_admin(self, client, admin_token, test_user):
        """Admin should get any user's credit history."""
        response = await client.get(
            f"/api/credits/users/{test_user.id}/history",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_deduct_credits(self, client, admin_token, test_user, db_session):
        """Admin should be able to deduct credits."""
        test_user.nuke_balance = 100
        await db_session.commit()

        with mock.patch("app.api.credits.CreditService") as mock_credit:
            mock_tx = mock.Mock()
            mock_tx.balance_after = 50
            mock_tx.to_dict.return_value = {"id": str(uuid_mod.uuid4()), "amount": -50}
            mock_credit.return_value.deduct_credits = mock.AsyncMock(return_value=mock_tx)
            with mock.patch("app.api.credits.NotificationService") as mock_notif:
                mock_notif.return_value.credits_deducted = mock.AsyncMock()
                response = await client.post(
                    f"/api/credits/users/{test_user.id}/deduct",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"amount": 50, "reason": "test deduction"},
                )
        assert response.status_code == 200
        assert "deducted" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_get_low_balance_users(self, client, admin_token):
        """Admin should get low balance users."""
        response = await client.get(
            "/api/credits/low-balance",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert "users" in response.json()


# ─────────────────────────────────────────────────────────────
# System API
# ─────────────────────────────────────────────────────────────


class TestBulkCreditActions:
    """Bulk grant + bulk allowance admin endpoints."""

    @pytest.mark.asyncio
    async def test_bulk_grant_credits(self, client, admin_token, test_user, admin_user):
        """Admin should grant credits to multiple users at once."""
        response = await client.post(
            "/api/admin/credits/grant-bulk",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"user_ids": [str(test_user.id)], "amount": 100, "reason": "Bulk bonus"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["success"][0]["user_id"] == str(test_user.id)
        assert data["results"]["success"][0]["granted_amount"] == 100
        assert data["results"]["success"][0]["capped"] is False

    @pytest.mark.asyncio
    async def test_bulk_grant_reports_missing_user(self, client, admin_token):
        """Bulk grant should report missing users in the failed list, not 500."""
        response = await client.post(
            "/api/admin/credits/grant-bulk",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "user_ids": ["00000000-0000-0000-0000-000000000000"],
                "amount": 50,
                "reason": "Test",
            },
        )
        assert response.status_code == 200
        assert len(response.json()["results"]["failed"]) == 1

    @pytest.mark.asyncio
    async def test_bulk_grant_requires_credits_grant(self, client, user_token, test_user):
        """Non-grant users should be forbidden from bulk grant."""
        response = await client.post(
            "/api/admin/credits/grant-bulk",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"user_ids": [str(test_user.id)], "amount": 100, "reason": "Bulk bonus"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_bulk_set_daily_allowance(self, client, admin_token, test_user):
        """Admin should set the daily allowance for multiple users at once."""
        response = await client.post(
            "/api/admin/credits/bulk-allowance",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"user_ids": [str(test_user.id)], "amount": 1500},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["success"][0]["daily_allowance"] == 1500

    @pytest.mark.asyncio
    async def test_bulk_set_daily_allowance_reports_missing(self, client, admin_token):
        """Bulk allowance should report missing users, not 500."""
        response = await client.post(
            "/api/admin/credits/bulk-allowance",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"user_ids": ["00000000-0000-0000-0000-000000000000"], "amount": 100},
        )
        assert response.status_code == 200
        assert len(response.json()["results"]["failed"]) == 1

    @pytest.mark.asyncio
    async def test_bulk_set_daily_allowance_requires_credits_grant(
        self, client, user_token, test_user
    ):
        """Non-grant users should be forbidden from bulk allowance."""
        response = await client.post(
            "/api/admin/credits/bulk-allowance",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"user_ids": [str(test_user.id)], "amount": 1500},
        )
        assert response.status_code == 403
