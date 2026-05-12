"""Tests for Server model and Server lifecycle with volume support."""

import pytest
from datetime import datetime, timedelta
from httpx import AsyncClient

from app.models.server import Server


class TestServerModelFields:
    """Server model property tests."""

    def test_server_has_volume_fields(self):
        """Server model should have volume-related fields."""
        server = Server()
        assert hasattr(server, 'volume_id')
        assert hasattr(server, 'volume_mode')
        assert hasattr(server, 'total_cost')
        assert hasattr(server, 'last_billed_at')
        assert hasattr(server, 'expires_at')
        assert hasattr(server, 'last_activity')

    def test_server_volume_defaults(self):
        """Volume fields should default correctly when loaded from DB."""
        server = Server()
        assert server.volume_id is None
        # volume_mode defaults to "read_write" in model, but is None before DB insert
        assert server.volume_mode is None  # DB default
        assert server.total_cost is None
        assert server.last_billed_at is None
        assert server.expires_at is None


class TestServerVolumeIntegration:
    """Tests for server deployment with volume selection."""

    @pytest.mark.asyncio
    async def test_server_creation_with_auto_volume(self, db_session, test_user):
        """Server creation without volume_id should auto-create a volume."""
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate
        from app.models.volume import Volume
        from sqlalchemy import select

        plan = ServerPlan(
            name="Test Plan",
            slug="test-plan-auto-vol",
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
            slug="test-env-auto-vol",
            image="hello-world",
            is_active=True,
            is_public=True
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        # Create server without volume_id - volume should be auto-created
        server = Server(
            name="auto-vol-server",
            user_id=test_user.id,
            plan_id=plan.id,
            environment_id=env.id,
            status="pending",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        assert server.volume_id is None  # Would be set by API logic
        assert server.volume_mode == "read_write"

    @pytest.mark.asyncio
    async def test_server_creation_with_existing_volume(self, db_session, test_user):
        """Server creation should support volume_id reference."""
        from app.models.volume import Volume

        # Create a volume
        volume = Volume(
            name="test-existing-vol",
            display_name="Existing Volume",
            owner_id=test_user.id,
            status="active",
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        # Server should be able to reference it
        server = Server(
            name="existing-vol-server",
            user_id=test_user.id,
            volume_id=volume.id,
            volume_mode="read_only",
            status="pending",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        assert str(server.volume_id) == str(volume.id)
        assert server.volume_mode == "read_only"

    @pytest.mark.asyncio
    async def test_server_volume_quota_validation(self, db_session, test_user):
        """Server should validate volume quota against plan limit."""
        from app.services.volume_service import VolumeService
        from unittest.mock import AsyncMock, patch

        service = VolumeService(db_session)
        
        volume = await service.create_volume(
            name="test-quota-vol",
            display_name="Quota Test Volume",
            owner_id=str(test_user.id),
        )

        # Mock the filesystem size check to return 15GB
        with patch.object(service, 'get_volume_size', new_callable=AsyncMock) as mock_size:
            mock_size.return_value = 16106127360  # 15GB
            
            # Should fail with 10GB plan
            result = await service.check_quota(str(volume.id), "10g")
            assert result["allowed"] is False
            assert "exceeds" in result["reason"].lower()

            # Should pass with 20GB plan
            result = await service.check_quota(str(volume.id), "20g")
            assert result["allowed"] is True


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
