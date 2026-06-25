"""Tests for QuotaService business logic."""

import uuid as uuid_mod

import pytest

from app.models.resource_quota import ResourceQuota
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.services.quota_service import QuotaService


class TestQuotaServiceGet:
    """Tests for get_user_quota and get_or_create_user_quota."""

    @pytest.mark.asyncio
    async def test_get_user_quota_not_found(self, db_session):
        """get_user_quota should return None for new user."""
        service = QuotaService(db_session)
        result = await service.get_user_quota(str(uuid_mod.uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_quota_found(self, db_session, test_user):
        """get_user_quota should return existing quota."""
        quota = ResourceQuota(user_id=test_user.id, max_cpu_total=16)
        db_session.add(quota)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.get_user_quota(str(test_user.id))
        assert result is not None
        assert result.max_cpu_total == 16

    @pytest.mark.asyncio
    async def test_get_or_create_user_quota_creates(self, db_session, test_user):
        """get_or_create_user_quota should create if missing."""
        service = QuotaService(db_session)
        result = await service.get_or_create_user_quota(str(test_user.id))
        assert result is not None
        assert result.user_id == test_user.id

    @pytest.mark.asyncio
    async def test_get_or_create_user_quota_returns_existing(self, db_session, test_user):
        """get_or_create_user_quota should return existing."""
        quota = ResourceQuota(user_id=test_user.id, max_cpu_total=32)
        db_session.add(quota)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.get_or_create_user_quota(str(test_user.id))
        assert result.max_cpu_total == 32

    @pytest.mark.asyncio
    async def test_get_role_quota(self, db_session):
        """get_role_quota should return quota by role."""
        quota = ResourceQuota(role="admin", max_cpu_total=64)
        db_session.add(quota)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.get_role_quota("admin")
        assert result is not None
        assert result.max_cpu_total == 64


class TestQuotaServiceList:
    """Tests for list_quotas."""

    @pytest.mark.asyncio
    async def test_list_quotas_basic(self, db_session, test_user, admin_user):
        """list_quotas should return all active users."""
        service = QuotaService(db_session)
        result = await service.list_quotas()
        assert result["total"] >= 2
        user_ids = [i["user_id"] for i in result["items"]]
        assert str(test_user.id) in user_ids
        assert str(admin_user.id) in user_ids

    @pytest.mark.asyncio
    async def test_list_quotas_search(self, db_session, test_user):
        """list_quotas should search by username."""
        service = QuotaService(db_session)
        result = await service.list_quotas(search=test_user.username)
        assert len(result["items"]) >= 1
        assert result["items"][0]["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_list_quotas_pagination(self, db_session, test_user, admin_user):
        """list_quotas should respect pagination."""
        service = QuotaService(db_session)
        result = await service.list_quotas(page=1, limit=1)
        assert len(result["items"]) == 1


class TestQuotaServiceUpdate:
    """Tests for update_user_quota."""

    @pytest.mark.asyncio
    async def test_update_user_quota_creates_new(self, db_session, test_user):
        """update_user_quota should create quota if missing."""
        service = QuotaService(db_session)
        result = await service.update_user_quota(
            str(test_user.id), max_cpu_total=16, max_memory_total="32g", max_servers_total=10
        )
        assert result.max_cpu_total == 16
        assert result.max_memory_total == "32g"
        assert result.max_servers_total == 10

    @pytest.mark.asyncio
    async def test_update_user_quota_updates_existing(self, db_session, test_user):
        """update_user_quota should update existing quota."""
        quota = ResourceQuota(user_id=test_user.id, max_cpu_total=4)
        db_session.add(quota)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.update_user_quota(str(test_user.id), max_cpu_total=8)
        assert result.max_cpu_total == 8


class TestQuotaServiceMemoryParsing:
    """Tests for _parse_memory and _format_memory."""

    @pytest.mark.asyncio
    async def test_parse_memory_gb(self, db_session):
        """Should parse GB values."""
        service = QuotaService(db_session)
        assert service._parse_memory("4g") == 4096
        assert service._parse_memory("4GB") == 4096

    @pytest.mark.asyncio
    async def test_parse_memory_mb(self, db_session):
        """Should parse MB values."""
        service = QuotaService(db_session)
        assert service._parse_memory("512m") == 512
        assert service._parse_memory("512MB") == 512

    @pytest.mark.asyncio
    async def test_parse_memory_tb(self, db_session):
        """Should parse TB values."""
        service = QuotaService(db_session)
        assert service._parse_memory("2t") == 2 * 1024 * 1024
        assert service._parse_memory("2TB") == 2 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_parse_memory_raw_number(self, db_session):
        """Should parse raw numbers as MB."""
        service = QuotaService(db_session)
        assert service._parse_memory("1024") == 1024

    @pytest.mark.asyncio
    async def test_parse_memory_empty(self, db_session):
        """Should return 0 for empty string."""
        service = QuotaService(db_session)
        assert service._parse_memory("") == 0
        assert service._parse_memory(None) == 0

    @pytest.mark.asyncio
    async def test_format_memory_tb(self, db_session):
        """Should format TB values."""
        service = QuotaService(db_session)
        assert "TB" in service._format_memory(1024 * 1024 * 2)

    @pytest.mark.asyncio
    async def test_format_memory_gb(self, db_session):
        """Should format GB values."""
        service = QuotaService(db_session)
        assert "GB" in service._format_memory(4096)

    @pytest.mark.asyncio
    async def test_format_memory_mb(self, db_session):
        """Should format MB values."""
        service = QuotaService(db_session)
        assert service._format_memory(512) == "512 MB"


class TestQuotaServiceRecalculate:
    """Tests for recalculate_usage."""

    @pytest.mark.asyncio
    async def test_recalculate_usage_no_servers(self, db_session, test_user):
        """Should return zero usage with no servers."""
        service = QuotaService(db_session)
        quota = await service.recalculate_usage(str(test_user.id))
        assert quota.usage_cpu == 0
        assert quota.usage_servers == 0

    @pytest.mark.asyncio
    async def test_recalculate_usage_with_servers(self, db_session, test_user):
        """Should sum running server resources."""
        plan = ServerPlan(
            name="Test", slug="test", cpu_limit=2, memory_limit="4g", disk_limit="20g"
        )
        db_session.add(plan)
        await db_session.flush()

        server = Server(
            name="srv1",
            user_id=test_user.id,
            plan_id=plan.id,
            status="running",
            allocated_cpu=2,
            allocated_memory="4g",
            allocated_disk="20g",
        )
        db_session.add(server)
        await db_session.commit()

        service = QuotaService(db_session)
        quota = await service.recalculate_usage(str(test_user.id))
        assert quota.usage_cpu == 2
        assert quota.usage_memory_mb == 4096
        assert quota.usage_disk_mb == 20480
        assert quota.usage_servers == 1

    @pytest.mark.asyncio
    async def test_recalculate_usage_excludes_stopped(self, db_session, test_user):
        """Should not count stopped servers."""
        server = Server(
            name="srv1",
            user_id=test_user.id,
            status="stopped",
            allocated_cpu=8,
        )
        db_session.add(server)
        await db_session.commit()

        service = QuotaService(db_session)
        quota = await service.recalculate_usage(str(test_user.id))
        assert quota.usage_cpu == 0

    @pytest.mark.asyncio
    async def test_recalculate_usage_excludes_server(self, db_session, test_user):
        """Should exclude specified server ID."""
        server = Server(
            name="srv1",
            user_id=test_user.id,
            status="running",
            allocated_cpu=4,
        )
        db_session.add(server)
        await db_session.commit()

        service = QuotaService(db_session)
        quota = await service.recalculate_usage(str(test_user.id), exclude_server_id=str(server.id))
        assert quota.usage_cpu == 0


class TestQuotaServiceCheckSpawn:
    """Tests for check_spawn_allowed."""

    @pytest.mark.asyncio
    async def test_check_spawn_allowed(self, db_session, test_user):
        """Should allow spawn when under limits."""
        plan = ServerPlan(
            name="Test",
            slug="spawn-test",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            gpu_limit=0,
            max_servers_per_user=5,
            cost_per_hour=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.check_spawn_allowed(str(test_user.id), str(plan.id))
        assert result["allowed"] is True
        assert result["estimated_cost_per_hour"] == 1

    @pytest.mark.asyncio
    async def test_check_spawn_plan_not_found(self, db_session, test_user):
        """Should reject when plan not found."""
        service = QuotaService(db_session)
        result = await service.check_spawn_allowed(str(test_user.id), str(uuid_mod.uuid4()))
        assert result["allowed"] is False
        assert "Plan not found" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_spawn_server_limit_reached(self, db_session, test_user):
        """Should reject when server limit reached."""
        plan = ServerPlan(
            name="Test",
            slug="limit-test",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=1,
            cost_per_hour=1,
        )
        db_session.add(plan)
        await db_session.flush()

        server = Server(
            name="srv1", user_id=test_user.id, plan_id=plan.id, status="running", allocated_cpu=1
        )
        db_session.add(server)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.check_spawn_allowed(str(test_user.id), str(plan.id))
        assert result["allowed"] is False
        assert "Plan limit reached" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_spawn_cpu_limit(self, db_session, test_user):
        """Should reject when CPU limit exceeded."""
        quota = ResourceQuota(
            user_id=test_user.id,
            max_cpu_total=1,
            max_memory_total="16g",
            max_disk_total="100g",
            max_gpu_total=0,
            max_servers_total=5,
        )
        db_session.add(quota)
        await db_session.flush()

        plan = ServerPlan(
            name="Test",
            slug="cpu-test",
            cpu_limit=4,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.check_spawn_allowed(str(test_user.id), str(plan.id))
        assert result["allowed"] is False
        assert "CPU limit exceeded" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_spawn_memory_limit(self, db_session, test_user):
        """Should reject when memory limit exceeded."""
        quota = ResourceQuota(
            user_id=test_user.id,
            max_cpu_total=16,
            max_memory_total="1g",
            max_disk_total="100g",
            max_gpu_total=0,
            max_servers_total=5,
        )
        db_session.add(quota)
        await db_session.flush()

        plan = ServerPlan(
            name="Test",
            slug="mem-test",
            cpu_limit=1,
            memory_limit="4g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.check_spawn_allowed(str(test_user.id), str(plan.id))
        assert result["allowed"] is False
        assert "Memory limit exceeded" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_spawn_disk_limit(self, db_session, test_user):
        """Should reject when disk limit exceeded."""
        quota = ResourceQuota(
            user_id=test_user.id,
            max_cpu_total=16,
            max_memory_total="16g",
            max_disk_total="1g",
            max_gpu_total=0,
            max_servers_total=5,
        )
        db_session.add(quota)
        await db_session.flush()

        plan = ServerPlan(
            name="Test",
            slug="disk-test",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.check_spawn_allowed(str(test_user.id), str(plan.id))
        assert result["allowed"] is False
        assert "Disk limit exceeded" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_spawn_gpu_limit(self, db_session, test_user):
        """Should reject when GPU limit exceeded."""
        quota = ResourceQuota(
            user_id=test_user.id,
            max_cpu_total=16,
            max_memory_total="16g",
            max_disk_total="100g",
            max_gpu_total=0,
            max_servers_total=5,
        )
        db_session.add(quota)
        await db_session.flush()

        plan = ServerPlan(
            name="Test",
            slug="gpu-test",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            gpu_limit=1,
            max_servers_per_user=5,
            cost_per_hour=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.check_spawn_allowed(str(test_user.id), str(plan.id))
        assert result["allowed"] is False
        assert "GPU limit exceeded" in result["reason"]


class TestQuotaServiceVolumeCheck:
    """Tests for check_volume_creation_allowed."""

    @pytest.mark.asyncio
    async def test_check_volume_allowed(self, db_session, test_user):
        """Should allow volume creation when under quota."""
        service = QuotaService(db_session)
        result = await service.check_volume_creation_allowed(
            str(test_user.id), requested_size_bytes=1024 * 1024 * 1024
        )
        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_check_volume_denied(self, db_session, test_user):
        """Should deny volume creation when over quota."""
        quota = ResourceQuota(user_id=test_user.id, max_disk_total="1g")
        db_session.add(quota)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.check_volume_creation_allowed(
            str(test_user.id), requested_size_bytes=1024 * 1024 * 1024 * 2
        )
        assert result["allowed"] is False
        assert "Disk quota exceeded" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_volume_default_size(self, db_session, test_user):
        """Should use default size when not specified."""
        service = QuotaService(db_session)
        result = await service.check_volume_creation_allowed(str(test_user.id))
        assert result["allowed"] is True


class TestQuotaServiceIncrementDecrement:
    """Tests for increment_usage and decrement_usage."""

    @pytest.mark.asyncio
    async def test_increment_usage(self, db_session, test_user):
        """increment_usage should add plan resources."""
        plan = ServerPlan(
            name="Test",
            slug="inc-test",
            cpu_limit=2,
            memory_limit="4g",
            disk_limit="20g",
            gpu_limit=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = QuotaService(db_session)
        quota = await service.increment_usage(str(test_user.id), str(plan.id))
        assert quota.usage_cpu == 2
        assert quota.usage_memory_mb == 4096
        assert quota.usage_disk_mb == 20480
        assert quota.usage_gpu == 1
        assert quota.usage_servers == 1

    @pytest.mark.asyncio
    async def test_decrement_usage(self, db_session, test_user):
        """decrement_usage should subtract plan resources."""
        plan = ServerPlan(
            name="Test",
            slug="dec-test",
            cpu_limit=2,
            memory_limit="4g",
            disk_limit="20g",
            gpu_limit=1,
        )
        db_session.add(plan)
        await db_session.flush()

        quota = ResourceQuota(
            user_id=test_user.id,
            usage_cpu=2,
            usage_memory_mb=4096,
            usage_disk_mb=20480,
            usage_gpu=1,
            usage_servers=1,
        )
        db_session.add(quota)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.decrement_usage(str(test_user.id), str(plan.id))
        assert result.usage_cpu == 0
        assert result.usage_memory_mb == 0
        assert result.usage_disk_mb == 0
        assert result.usage_gpu == 0
        assert result.usage_servers == 0

    @pytest.mark.asyncio
    async def test_decrement_usage_never_negative(self, db_session, test_user):
        """decrement_usage should not go below zero."""
        plan = ServerPlan(
            name="Test",
            slug="dec-zero",
            cpu_limit=2,
            memory_limit="4g",
            disk_limit="20g",
            gpu_limit=1,
        )
        db_session.add(plan)
        await db_session.commit()

        service = QuotaService(db_session)
        result = await service.decrement_usage(str(test_user.id), str(plan.id))
        assert result.usage_cpu == 0
        assert result.usage_memory_mb == 0
        assert result.usage_servers == 0
