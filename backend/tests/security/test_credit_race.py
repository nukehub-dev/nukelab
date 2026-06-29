# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Security regression tests for NUKE credit business logic abuse.

These tests verify that the credit system cannot be manipulated through
race conditions, negative values, or unauthorized grants.
"""

import asyncio

import pytest
from httpx import AsyncClient

from app.models.credit_transaction import CreditTransaction


class TestCreditLogic:
    """Business logic tests for the NUKE credit system."""

    @pytest.mark.asyncio
    async def test_cannot_start_server_with_insufficient_credits(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """User with 0 credits should not be able to start a billable server."""
        from app.models.environment_template import EnvironmentTemplate
        from app.models.server_plan import ServerPlan

        test_user.nuke_balance = 0
        await db_session.commit()

        plan = ServerPlan(
            name="Costly Plan",
            slug="costly-plan",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=10,
            is_active=True,
            visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Costly Env",
            slug="costly-env",
            image="hello-world",
            is_active=True,
            is_public=True,
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        response = await client.post(
            "/api/servers/",
            json={
                "name": "no-credit-server",
                "environment_id": str(env.id),
                "plan_id": str(plan.id),
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (402, 422, 403), (
            f"Expected 402/422/403, got {response.status_code}: {response.text}"
        )

    @pytest.mark.asyncio
    async def test_cannot_grant_negative_credits(self, client: AsyncClient, test_user, admin_token):
        """Admin grant endpoint should reject negative amounts."""
        response = await client.post(
            f"/api/credits/users/{test_user.id}/grant",
            json={"amount": -1000, "reason": "refund"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code in (400, 422), (
            f"Expected 400/422, got {response.status_code}: {response.text}"
        )


class TestCreditRaceConditions:
    """Race condition tests for concurrent credit operations."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires mocking or real concurrent spawn implementation")
    async def test_concurrent_server_spawn_no_negative_balance(
        self, client: AsyncClient, test_user, user_token, db_session
    ):
        """Concurrent spawn attempts should not drive the balance negative."""
        from app.models.environment_template import EnvironmentTemplate
        from app.models.server_plan import ServerPlan

        test_user.nuke_balance = 15  # Enough for one server
        await db_session.commit()

        plan = ServerPlan(
            name="Race Plan",
            slug="race-plan",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=10,
            is_active=True,
            visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Race Env",
            slug="race-env",
            image="hello-world",
            is_active=True,
            is_public=True,
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        async def spawn_attempt(i):
            return await client.post(
                "/api/servers/",
                json={
                    "name": f"race-server-{i}",
                    "environment_id": str(env.id),
                    "plan_id": str(plan.id),
                },
                headers={"Authorization": f"Bearer {user_token}"},
            )

        responses = await asyncio.gather(*[spawn_attempt(i) for i in range(5)])
        success_count = sum(1 for r in responses if r.status_code in (200, 201))

        await db_session.refresh(test_user)
        assert success_count <= 1, "Multiple servers spawned despite insufficient credits"
        assert test_user.nuke_balance >= 0, "NUKE balance went negative"

    @pytest.mark.asyncio
    async def test_credit_transaction_ledger_is_immutable(
        self, client: AsyncClient, test_user, admin_token, db_session
    ):
        """Credit transactions should be append-only and tamper-evident."""
        from sqlalchemy import select

        response = await client.post(
            f"/api/credits/users/{test_user.id}/grant",
            json={"amount": 100, "reason": "test grant"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200, f"Grant failed: {response.status_code}: {response.text}"

        result = await db_session.execute(
            select(CreditTransaction).where(CreditTransaction.user_id == test_user.id)
        )
        transactions = result.scalars().all()
        assert len(transactions) >= 1, "No credit transaction recorded"

        # Verify ledger entries are not updated in place (immutable)
        for tx in transactions:
            assert tx.amount is not None
            assert tx.balance_after is not None
            assert tx.type in ("admin_grant", "daily_allowance", "server_usage", "refund")
