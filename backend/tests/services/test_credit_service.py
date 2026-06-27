"""Extended tests for CreditService business logic."""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.credit_transaction import CreditTransaction
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.services.credit_service import CreditService


class TestCreditServiceBalance:
    """Tests for get_balance and related methods."""

    @pytest.mark.asyncio
    async def test_get_balance_returns_zero_for_missing_user(self, db_session):
        """get_balance should return 0 for non-existent user."""
        service = CreditService(db_session)
        balance = await service.get_balance(str(uuid_mod.uuid4()))
        assert balance == 0

    @pytest.mark.asyncio
    async def test_get_balance_for_existing_user(self, db_session, test_user):
        """get_balance should return user's nuke_balance."""
        service = CreditService(db_session)
        balance = await service.get_balance(str(test_user.id))
        assert balance == test_user.nuke_balance


class TestCreditServiceTransactions:
    """Tests for transaction history and creation."""

    @pytest.mark.asyncio
    async def test_get_transaction_history_empty(self, db_session, test_user):
        """Transaction history should be empty for new user."""
        service = CreditService(db_session)
        result = await service.get_transaction_history(str(test_user.id))
        assert result["transactions"] == []
        assert result["pagination"]["total"] == 0

    @pytest.mark.asyncio
    async def test_get_transaction_history_with_pagination(self, db_session, test_user):
        """Transaction history should respect pagination."""
        service = CreditService(db_session)

        # Create multiple transactions
        for i in range(5):
            tx = CreditTransaction(
                user_id=test_user.id,
                amount=i + 1,
                balance_after=100 + i + 1,
                type="admin_grant",
                description=f"Grant {i}",
            )
            db_session.add(tx)
        await db_session.commit()

        result = await service.get_transaction_history(str(test_user.id), page=1, limit=2)
        assert len(result["transactions"]) == 2
        assert result["pagination"]["total"] == 5
        assert result["pagination"]["total_pages"] == 3

    @pytest.mark.asyncio
    async def test_get_transaction_history_filter_by_type(self, db_session, test_user):
        """Transaction history should filter by type."""
        service = CreditService(db_session)

        tx1 = CreditTransaction(
            user_id=test_user.id,
            amount=10,
            balance_after=110,
            type="admin_grant",
            description="Grant",
        )
        tx2 = CreditTransaction(
            user_id=test_user.id,
            amount=-5,
            balance_after=105,
            type="server_usage",
            description="Usage",
        )
        db_session.add_all([tx1, tx2])
        await db_session.commit()

        result = await service.get_transaction_history(
            str(test_user.id), transaction_type="server_usage"
        )
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["type"] == "server_usage"

    @pytest.mark.asyncio
    async def test_get_transaction_history_sort_ascending(self, db_session, test_user):
        """Transaction history should support ascending sort."""
        service = CreditService(db_session)

        tx1 = CreditTransaction(
            user_id=test_user.id,
            amount=10,
            balance_after=110,
            type="admin_grant",
            description="First",
        )
        tx2 = CreditTransaction(
            user_id=test_user.id,
            amount=20,
            balance_after=120,
            type="admin_grant",
            description="Second",
        )
        db_session.add_all([tx1, tx2])
        await db_session.commit()

        result = await service.get_transaction_history(
            str(test_user.id), sort_by="amount", sort_order="asc"
        )
        amounts = [t["amount"] for t in result["transactions"]]
        assert amounts == [10, 20]

    @pytest.mark.asyncio
    async def test_create_transaction_insufficient_credits(self, db_session, test_user):
        """_create_transaction should raise when balance goes negative."""
        service = CreditService(db_session)
        test_user.nuke_balance = 5
        await db_session.commit()

        with pytest.raises(Exception) as exc_info:
            await service._create_transaction(
                user_id=str(test_user.id),
                amount=-10,
                transaction_type="server_usage",
                description="Overdraft",
            )
        assert "Insufficient credits" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_transaction_with_actor_and_meta(self, db_session, test_user, admin_user):
        """_create_transaction should record actor_id and metadata."""
        service = CreditService(db_session)

        tx = await service._create_transaction(
            user_id=str(test_user.id),
            amount=50,
            transaction_type="admin_grant",
            description="Test grant",
            actor_id=str(admin_user.id),
            meta={"reason": "testing"},
        )

        assert tx.actor_id == admin_user.id
        assert tx.meta == {"reason": "testing"}
        # balance_after reflects the actual transaction
        new_balance = await service.get_balance(str(test_user.id))
        assert tx.balance_after == new_balance


class TestCreditServiceDailyAllowance:
    """Tests for daily allowance functionality."""

    @pytest.mark.asyncio
    async def test_grant_daily_allowance_success(self, db_session, test_user):
        """grant_daily_allowance should add credits once per day."""
        service = CreditService(db_session)
        initial = test_user.nuke_balance

        with patch.object(service, "_create_transaction", wraps=service._create_transaction):
            tx = await service.grant_daily_allowance(str(test_user.id))
            assert tx.amount == test_user.daily_allowance

        balance = await service.get_balance(str(test_user.id))
        assert balance == initial + test_user.daily_allowance

    @pytest.mark.asyncio
    async def test_grant_daily_allowance_inactive_user(self, db_session):
        """grant_daily_allowance should fail for inactive user."""
        user = User(
            username="inactive",
            email="inactive@test.com",
            password_hash="hash",
            role="user",
            is_active=False,
            nuke_balance=0,
        )
        db_session.add(user)
        await db_session.commit()

        service = CreditService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.grant_daily_allowance(str(user.id))
        assert "not found or inactive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_grant_daily_allowance_already_granted(self, db_session, test_user):
        """grant_daily_allowance should fail if already granted today."""
        service = CreditService(db_session)

        # First grant
        await service.grant_daily_allowance(str(test_user.id))

        # Second grant should fail
        with pytest.raises(Exception) as exc_info:
            await service.grant_daily_allowance(str(test_user.id))
        assert "already granted" in str(exc_info.value)


class TestCreditServiceGrantDeduct:
    """Tests for grant_credits and deduct_credits."""

    @pytest.mark.asyncio
    async def test_grant_credits(self, db_session, test_user, admin_user):
        """grant_credits should add credits and record actor."""
        service = CreditService(db_session)
        initial = test_user.nuke_balance

        tx = await service.grant_credits(
            user_id=str(test_user.id), amount=100, actor_id=str(admin_user.id), reason="Bonus"
        )

        assert tx.amount == 100
        assert tx.type == "admin_grant"
        assert "Bonus" in tx.description
        assert await service.get_balance(str(test_user.id)) == initial + 100

    @pytest.mark.asyncio
    async def test_deduct_credits(self, db_session, test_user, admin_user):
        """deduct_credits should remove credits and record actor."""
        service = CreditService(db_session)
        test_user.nuke_balance = 200
        await db_session.commit()

        tx = await service.deduct_credits(
            user_id=str(test_user.id), amount=50, actor_id=str(admin_user.id), reason="Penalty"
        )

        assert tx.amount == -50
        assert tx.type == "admin_deduct"
        assert "Penalty" in tx.description
        assert await service.get_balance(str(test_user.id)) == 150


class TestCreditServiceChecks:
    """Tests for check_sufficient_credits and summaries."""

    @pytest.mark.asyncio
    async def test_check_sufficient_credits_true(self, db_session, test_user):
        """check_sufficient_credits should return True when enough."""
        service = CreditService(db_session)
        test_user.nuke_balance = 100
        await db_session.commit()

        assert await service.check_sufficient_credits(str(test_user.id), 50) is True

    @pytest.mark.asyncio
    async def test_check_sufficient_credits_false(self, db_session, test_user):
        """check_sufficient_credits should return False when insufficient."""
        service = CreditService(db_session)
        test_user.nuke_balance = 10
        await db_session.commit()

        assert await service.check_sufficient_credits(str(test_user.id), 50) is False

    @pytest.mark.asyncio
    async def test_get_low_credit_users(self, db_session):
        """get_low_credit_users should return users below threshold."""
        service = CreditService(db_session)

        user1 = User(
            username="low1",
            email="low1@test.com",
            password_hash="hash",
            role="user",
            is_active=True,
            nuke_balance=50,
        )
        user2 = User(
            username="high1",
            email="high1@test.com",
            password_hash="hash",
            role="user",
            is_active=True,
            nuke_balance=500,
        )
        db_session.add_all([user1, user2])
        await db_session.commit()

        result = await service.get_low_credit_users(threshold=100)
        usernames = [u["username"] for u in result["users"]]
        assert "low1" in usernames
        assert "high1" not in usernames
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_get_credit_summary(self, db_session, test_user):
        """get_credit_summary should return aggregated stats."""
        service = CreditService(db_session)
        test_user.nuke_balance = 1000
        await db_session.commit()

        # Add some transactions
        tx1 = CreditTransaction(
            user_id=test_user.id,
            amount=500,
            balance_after=1500,
            type="daily_allowance",
            description="Daily",
        )
        tx2 = CreditTransaction(
            user_id=test_user.id,
            amount=-200,
            balance_after=1300,
            type="server_usage",
            description="Usage",
        )
        db_session.add_all([tx1, tx2])
        await db_session.commit()

        summary = await service.get_credit_summary(str(test_user.id))
        assert summary["current_balance"] == 1000
        assert summary["total_earned"] == 500
        assert summary["total_consumed"] == 200


class TestCreditServiceFormatDuration:
    """Tests for _format_duration helper."""

    @pytest.mark.asyncio
    async def test_format_duration_hours(self, db_session):
        """Should format hours, minutes, seconds."""
        service = CreditService(db_session)
        assert service._format_duration(3661) == "1h 1m 1s"

    @pytest.mark.asyncio
    async def test_format_duration_minutes_only(self, db_session):
        """Should format minutes and seconds."""
        service = CreditService(db_session)
        assert service._format_duration(125) == "2m 5s"

    @pytest.mark.asyncio
    async def test_format_duration_seconds_only(self, db_session):
        """Should format seconds only."""
        service = CreditService(db_session)
        assert service._format_duration(45) == "45s"


class TestCreditServiceReconcile:
    """Additional tests for reconcile_server_billing."""

    @pytest.mark.asyncio
    async def test_reconcile_insufficient_balance_partial_charge(self, db_session, test_user):
        """Should charge what it can when balance is insufficient."""
        from app.services.credit_service import CreditService

        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name="Test Plan",
            slug="test-plan",
            cost_per_hour=60,
        )
        db_session.add(plan)
        await db_session.flush()

        test_user.nuke_balance = 2
        await db_session.commit()

        server = Server(
            id=uuid_mod.uuid4(),
            name="test-server",
            user_id=test_user.id,
            plan_id=plan.id,
            status="stopped",
            started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10),
            stopped_at=datetime.now(UTC).replace(tzinfo=None),
            total_cost=0,
        )
        db_session.add(server)
        await db_session.commit()

        service = CreditService(db_session)
        additional = await service.reconcile_server_billing(server, plan)

        # Should charge the 2 available credits
        assert additional == 2
        assert server.total_cost == 2

    @pytest.mark.asyncio
    async def test_reconcile_no_timestamps(self, db_session, test_user):
        """Should return 0 when server has no timestamps."""
        service = CreditService(db_session)
        server = Server(
            id=uuid_mod.uuid4(),
            name="test-server",
            user_id=test_user.id,
            status="stopped",
        )
        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name="Test Plan",
            slug="test-plan",
            cost_per_hour=10,
        )
        db_session.add_all([server, plan])
        await db_session.commit()

        assert await service.reconcile_server_billing(server, plan) == 0

    @pytest.mark.asyncio
    async def test_reconcile_negative_duration(self, db_session, test_user):
        """Should return 0 when stopped before started."""
        service = CreditService(db_session)
        server = Server(
            id=uuid_mod.uuid4(),
            name="test-server",
            user_id=test_user.id,
            status="stopped",
            started_at=datetime.now(UTC).replace(tzinfo=None),
            stopped_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5),
            total_cost=0,
        )
        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name="Test Plan",
            slug="test-plan",
            cost_per_hour=10,
        )
        db_session.add_all([server, plan])
        await db_session.commit()

        assert await service.reconcile_server_billing(server, plan) == 0


class TestGrantDailyAllowanceRaceResolution:
    """Tests for the cross-process / concurrent-grant resolution path."""

    @pytest.mark.asyncio
    async def test_grant_daily_allowance_maps_integrity_error_to_400(self, db_session, test_user):
        """If the unique index fires (concurrent insert won), surface 400 not 500."""
        from sqlalchemy.exc import IntegrityError

        service = CreditService(db_session)

        async def _raise_integrity_error(*_args, **_kwargs):
            raise IntegrityError("simulated", {}, Exception("unique violation"))

        with patch.object(service, "_create_transaction", side_effect=_raise_integrity_error):
            # Pre-check finds nothing, so we proceed to _create_transaction
            # which raises IntegrityError (simulating the unique index).
            with pytest.raises(Exception) as exc_info:
                await service.grant_daily_allowance(str(test_user.id))

        # Should be an HTTPException with 400, not a raw IntegrityError
        assert "already granted" in str(exc_info.value.detail).lower()
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_transaction_locks_user_row(self, db_session, test_user):
        """_create_transaction should use SELECT...FOR UPDATE on the user row."""
        service = CreditService(db_session)

        # Spy on execute() to verify with_for_update is applied to the user lock query
        original_execute = db_session.execute
        lock_calls = []

        async def _spy_execute(statement, *args, **kwargs):
            compiled = str(statement)
            if "FROM users" in compiled and "FOR UPDATE" in str(
                statement.compile(compile_kwargs={"literal_binds": True})
            ):
                lock_calls.append(True)
            return await original_execute(statement, *args, **kwargs)

        with patch.object(db_session, "execute", _spy_execute):
            await service.grant_credits(
                user_id=str(test_user.id),
                amount=50,
                actor_id=str(test_user.id),
                reason="unit test grant",
            )

        assert lock_calls, "Expected _create_transaction to issue SELECT...FOR UPDATE on users"
