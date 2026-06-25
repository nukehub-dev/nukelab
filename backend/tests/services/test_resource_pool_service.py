"""Tests for ResourcePoolService business logic."""

import pytest
import uuid as uuid_mod

from app.services.resource_pool_service import ResourcePoolService
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue


class TestResourcePoolServiceParseMemory:
    """Tests for _parse_memory."""

    def test_parse_memory_gb(self):
        """Should parse GB values."""
        assert ResourcePoolService._parse_memory("4g") == 4096
        assert ResourcePoolService._parse_memory("4GB") == 4096

    def test_parse_memory_mb(self):
        """Should parse MB values."""
        assert ResourcePoolService._parse_memory("512m") == 512
        assert ResourcePoolService._parse_memory("512MB") == 512

    def test_parse_memory_tb(self):
        """Should parse TB values."""
        assert ResourcePoolService._parse_memory("2t") == 2 * 1024 * 1024
        assert ResourcePoolService._parse_memory("2TB") == 2 * 1024 * 1024

    def test_parse_memory_raw(self):
        """Should parse raw numbers."""
        assert ResourcePoolService._parse_memory("1024") == 1024

    def test_parse_memory_empty(self):
        """Should return 0 for empty."""
        assert ResourcePoolService._parse_memory("") == 0
        assert ResourcePoolService._parse_memory(None) == 0


class TestResourcePoolServiceGetAvailable:
    """Tests for get_available_resources."""

    @pytest.mark.asyncio
    async def test_get_available_no_servers(self, db_session):
        """Should return full resources when no servers running."""
        service = ResourcePoolService(db_session)
        result = await service.get_available_resources()
        assert result["cpu"]["total"] == 34.0
        assert result["cpu"]["allocated"] == 0
        assert result["cpu"]["available"] == 34.0

    @pytest.mark.asyncio
    async def test_get_available_with_servers(self, db_session, test_user):
        """Should subtract running server resources."""
        server = Server(
            name="srv",
            user_id=test_user.id,
            status="running",
            allocated_cpu=4,
            allocated_memory="8g",
            allocated_disk="50g",
        )
        db_session.add(server)
        await db_session.commit()

        service = ResourcePoolService(db_session)
        result = await service.get_available_resources()
        assert result["cpu"]["allocated"] == 4
        assert result["cpu"]["available"] == 30.0
        assert result["memory_mb"]["allocated"] == 8192

    @pytest.mark.asyncio
    async def test_get_available_ignores_stopped(self, db_session, test_user):
        """Should not count stopped servers."""
        server = Server(
            name="srv",
            user_id=test_user.id,
            status="stopped",
            allocated_cpu=8,
            allocated_memory="16g",
        )
        db_session.add(server)
        await db_session.commit()

        service = ResourcePoolService(db_session)
        result = await service.get_available_resources()
        assert result["cpu"]["allocated"] == 0


class TestResourcePoolServiceCanFit:
    """Tests for can_fit."""

    @pytest.mark.asyncio
    async def test_can_fit_yes(self, db_session):
        """Should return True when plan fits."""
        plan = ServerPlan(
            name="Small", slug="small", cpu_limit=1, memory_limit="1g", disk_limit="10g"
        )
        db_session.add(plan)
        await db_session.commit()

        service = ResourcePoolService(db_session)
        assert await service.can_fit(str(plan.id)) is True

    @pytest.mark.asyncio
    async def test_can_fit_no(self, db_session, test_user):
        """Should return False when plan exceeds resources."""
        plan = ServerPlan(
            name="Huge", slug="huge", cpu_limit=100, memory_limit="100g", disk_limit="1000g"
        )
        db_session.add(plan)
        await db_session.commit()

        service = ResourcePoolService(db_session)
        assert await service.can_fit(str(plan.id)) is False

    @pytest.mark.asyncio
    async def test_can_fit_plan_not_found(self, db_session):
        """Should return False when plan not found."""
        service = ResourcePoolService(db_session)
        assert await service.can_fit(str(uuid_mod.uuid4())) is False

    @pytest.mark.asyncio
    async def test_can_fit_resources_direct(self, db_session):
        """Should check specific resources."""
        service = ResourcePoolService(db_session)
        assert await service.can_fit_resources(1, "1g", "10g") is True
        assert await service.can_fit_resources(100, "100g", "1000g") is False


class TestResourcePoolServiceQueue:
    """Tests for queue methods."""

    @pytest.mark.asyncio
    async def test_get_queue_position(self, db_session, test_user):
        """Should return position in queue."""
        plan = ServerPlan(name="Test", slug="q-test", cpu_limit=1)
        db_session.add(plan)
        await db_session.flush()

        from app.models.environment_template import EnvironmentTemplate

        env = EnvironmentTemplate(name="Env", slug="q-env", image="img")
        db_session.add(env)
        await db_session.flush()

        q1 = ServerQueue(
            user_id=test_user.id,
            environment_id=env.id,
            plan_id=plan.id,
            status="pending",
            server_name="srv1",
            requested_cpu=1,
            requested_memory="1g",
            requested_disk="10g",
        )
        db_session.add(q1)
        await db_session.commit()

        service = ResourcePoolService(db_session)
        # Position of q1 among pending items excluding itself
        pos = await service.get_queue_position(str(q1.id))
        assert pos == 0

    @pytest.mark.asyncio
    async def test_get_next_in_queue_empty(self, db_session):
        """Should return None when queue is empty."""
        service = ResourcePoolService(db_session)
        result = await service.get_next_in_queue()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_next_in_queue_returns_entry(self, db_session, test_user):
        """Should return next queue entry that fits."""
        plan = ServerPlan(
            name="Test", slug="q-next", cpu_limit=1, memory_limit="1g", disk_limit="10g"
        )
        db_session.add(plan)
        await db_session.flush()

        from app.models.environment_template import EnvironmentTemplate

        env = EnvironmentTemplate(name="Env", slug="q-env2", image="img")
        db_session.add(env)
        await db_session.flush()

        q = ServerQueue(
            user_id=test_user.id,
            environment_id=env.id,
            plan_id=plan.id,
            status="pending",
            server_name="srv1",
            requested_cpu=1,
            requested_memory="1g",
            requested_disk="10g",
        )
        db_session.add(q)
        await db_session.commit()

        service = ResourcePoolService(db_session)
        result = await service.get_next_in_queue()
        assert result is not None
        assert result.id == q.id
