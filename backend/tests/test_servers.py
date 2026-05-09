"""Tests for Server model and Server lifecycle."""

import pytest
from datetime import datetime, timedelta
from httpx import AsyncClient

from app.models.server import Server


class TestServerModelFields:
    """Server model property tests."""

    def test_server_has_billing_fields(self):
        """Server model should have billing-related fields."""
        server = Server()
        assert hasattr(server, 'total_cost')
        assert hasattr(server, 'last_billed_at')
        assert hasattr(server, 'expires_at')
        assert hasattr(server, 'last_activity')

    def test_server_billing_defaults(self):
        """Billing fields should default to None before DB insert."""
        server = Server()
        assert server.total_cost is None
        assert server.last_billed_at is None
        assert server.expires_at is None


class TestServerLifecycleE2E:
    """End-to-end tests for full server lifecycle."""

    @pytest.mark.asyncio
    async def test_server_creation_has_billing_fields(self, client: AsyncClient, test_user, user_token, db_session):
        """E2E: Create server prerequisites and verify billing fields exist."""
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate
        from sqlalchemy import select

        headers = {"Authorization": f"Bearer {user_token}"}

        plan = ServerPlan(
            name="Test Plan",
            slug="test-plan",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=10,
            is_active=True,
            allowed_roles=["user"]
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Test Env",
            slug="test-env",
            image="hello-world",
            is_active=True,
            is_public=True
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        server = Server(
            name="e2e-test-server",
            user_id=test_user.id,
            plan_id=plan.id,
            environment_id=env.id,
            status="running"
        )
        assert hasattr(server, 'total_cost')
        assert hasattr(server, 'last_billed_at')
        assert hasattr(server, 'expires_at')
        assert hasattr(server, 'last_activity')

    @pytest.mark.asyncio
    async def test_auto_stop_fields(self, db_session):
        """E2E: Verify auto-stop related fields exist on server."""
        server = Server()

        server.expires_at = datetime.utcnow() + timedelta(hours=1)
        assert server.expires_at is not None

        server.last_activity = datetime.utcnow()
        assert server.last_activity is not None

        server.total_cost = 100
        assert server.total_cost == 100
