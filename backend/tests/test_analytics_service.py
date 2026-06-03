"""Tests for AnalyticsService."""

import pytest
import uuid
from datetime import datetime, timedelta
from unittest import mock

from app.services.analytics_service import AnalyticsService
from app.models.server import Server
from app.models.server_metric import ServerMetric
from app.models.daily_server_metric import DailyServerMetric
from app.models.credit_transaction import CreditTransaction
from app.models.user import User
from app.models.volume import Volume
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.login_event import LoginEvent
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan


@pytest.fixture
def analytics_service(db_session):
    return AnalyticsService(db_session)


class TestParseDateRange:
    """Tests for _parse_date_range helper."""

    def test_default_30_days(self, analytics_service):
        since, until = analytics_service._parse_date_range()
        assert (until - since).days == 30

    def test_explicit_days(self, analytics_service):
        since, until = analytics_service._parse_date_range(days=7)
        assert (until - since).days == 7

    def test_from_to_dates(self, analytics_service):
        from_dt = datetime(2024, 1, 1)
        to_dt = datetime(2024, 1, 5)
        since, until = analytics_service._parse_date_range(from_date=from_dt, to_date=to_dt)
        assert since == from_dt
        assert until.hour == 23
        assert until.minute == 59


class TestShouldUseRollups:
    """Tests for _should_use_rollups helper."""

    def test_short_window_no_rollups(self, analytics_service):
        since = datetime(2024, 1, 1)
        until = datetime(2024, 1, 5)
        assert analytics_service._should_use_rollups(since, until) is False

    def test_long_window_uses_rollups(self, analytics_service):
        since = datetime(2024, 1, 1)
        until = datetime(2024, 1, 15)
        assert analytics_service._should_use_rollups(since, until) is True


class TestGetUserUsage:
    """Tests for get_user_usage method."""

    @pytest.mark.asyncio
    async def test_user_usage_raw_window(self, db_session, analytics_service, test_user):
        """Should return usage data from raw metrics for short windows."""
        server = Server(name="srv1", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        metric = ServerMetric(
            server_id=server.id,
            container_id="cid1",
            cpu_percent=50.0,
            memory_percent=60.0,
            collected_at=datetime.utcnow() - timedelta(days=1),
        )
        db_session.add(metric)
        await db_session.commit()

        result = await analytics_service.get_user_usage(str(test_user.id), days=7)
        assert result["user_id"] == str(test_user.id)
        assert "daily_usage" in result
        assert "peak_stats" in result
        assert "server_breakdown" in result
        assert result["period_days"] == 7

    @pytest.mark.asyncio
    async def test_user_usage_rollup_window(self, db_session, analytics_service, test_user):
        """Should return usage data from rollups for long windows."""
        server = Server(name="srv2", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        rollup = DailyServerMetric(
            server_id=server.id,
            date=(datetime.utcnow() - timedelta(days=10)).date(),
            avg_cpu=40.0,
            peak_cpu=80.0,
            avg_memory=50.0,
            peak_memory=90.0,
            data_points=100,
        )
        db_session.add(rollup)
        await db_session.commit()

        result = await analytics_service.get_user_usage(str(test_user.id), days=30)
        assert result["user_id"] == str(test_user.id)
        assert "daily_usage" in result

    @pytest.mark.asyncio
    async def test_user_usage_with_costs(self, db_session, analytics_service, test_user):
        """Should include credit transaction costs."""
        server = Server(name="srv3", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        tx = CreditTransaction(
            user_id=test_user.id,
            server_id=server.id,
            amount=-100,
            balance_after=900,
            type="server_usage",
            created_at=datetime.utcnow() - timedelta(days=1),
        )
        db_session.add(tx)
        await db_session.commit()

        result = await analytics_service.get_user_usage(str(test_user.id), days=7)
        assert result["total_cost"] == 100
        assert len(result["server_breakdown"]) == 1

    @pytest.mark.asyncio
    async def test_user_usage_empty(self, analytics_service, test_user):
        """Should handle users with no activity gracefully."""
        result = await analytics_service.get_user_usage(str(test_user.id), days=7)
        assert result["user_id"] == str(test_user.id)
        assert result["daily_usage"] == []
        assert result["total_cost"] == 0
        assert result["peak_stats"]["peak_cpu"] == 0


class TestGetGlobalUsage:
    """Tests for get_global_usage method."""

    @pytest.mark.asyncio
    async def test_global_usage(self, db_session, analytics_service, test_user):
        server = Server(name="gsrv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        result = await analytics_service.get_global_usage(days=7)
        assert "total_users" in result
        assert "total_servers" in result
        assert "running_servers" in result
        assert "server_status_breakdown" in result
        assert result["period_days"] == 7

    @pytest.mark.asyncio
    async def test_global_usage_with_transactions(self, db_session, analytics_service, test_user):
        tx = CreditTransaction(user_id=test_user.id, amount=-50, balance_after=950, type="server_usage", created_at=datetime.utcnow() - timedelta(days=1))
        db_session.add(tx)
        await db_session.commit()

        result = await analytics_service.get_global_usage(days=7)
        assert result["total_credits_consumed"] == 50


class TestGetTopConsumers:
    """Tests for get_top_consumers method."""

    @pytest.mark.asyncio
    async def test_top_consumers(self, db_session, analytics_service, test_user):
        tx = CreditTransaction(
            user_id=test_user.id,
            amount=-200,
            balance_after=800,
            type="server_usage",
            created_at=datetime.utcnow() - timedelta(days=1),
        )
        db_session.add(tx)
        await db_session.commit()

        result = await analytics_service.get_top_consumers(days=7, limit=5)
        assert len(result) == 1
        assert result[0]["user_id"] == str(test_user.id)
        assert result[0]["credits_consumed"] == 200

    @pytest.mark.asyncio
    async def test_top_consumers_empty(self, analytics_service):
        result = await analytics_service.get_top_consumers(days=7)
        assert result == []


class TestGetCreditFlow:
    """Tests for get_credit_flow method."""

    @pytest.mark.asyncio
    async def test_credit_flow(self, db_session, analytics_service, test_user):
        tx1 = CreditTransaction(user_id=test_user.id, amount=-50, balance_after=950, type="server_usage", created_at=datetime.utcnow() - timedelta(days=1))
        tx2 = CreditTransaction(user_id=test_user.id, amount=100, balance_after=1050, type="grant", created_at=datetime.utcnow() - timedelta(days=1))
        db_session.add_all([tx1, tx2])
        await db_session.commit()

        result = await analytics_service.get_credit_flow(days=7)
        assert len(result) >= 1
        assert result[0]["credits_consumed"] == 50
        assert result[0]["credits_granted"] == 100

    @pytest.mark.asyncio
    async def test_credit_flow_empty(self, analytics_service):
        result = await analytics_service.get_credit_flow(days=7)
        assert result == []


class TestGetUserGrowth:
    """Tests for get_user_growth method."""

    @pytest.mark.asyncio
    async def test_user_growth(self, db_session, analytics_service):
        user = User(username="growthuser", email="g@test.com", role="user")
        user.created_at = datetime.utcnow() - timedelta(days=1)
        db_session.add(user)
        await db_session.commit()

        result = await analytics_service.get_user_growth(days=7)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_user_growth_empty(self, analytics_service):
        result = await analytics_service.get_user_growth(days=7)
        # May be empty if no users created recently
        assert isinstance(result, list)


class TestGetDailyLogins:
    """Tests for get_daily_logins method."""

    @pytest.mark.asyncio
    async def test_daily_logins(self, db_session, analytics_service, test_user):
        event = LoginEvent(user_id=test_user.id, timestamp=datetime.utcnow() - timedelta(days=1))
        db_session.add(event)
        await db_session.commit()

        result = await analytics_service.get_daily_logins(days=7)
        assert len(result) >= 1
        assert result[0]["count"] >= 1

    @pytest.mark.asyncio
    async def test_daily_logins_empty(self, analytics_service):
        result = await analytics_service.get_daily_logins(days=7)
        assert result == []


class TestGetPlatformMetrics:
    """Tests for get_platform_metrics method."""

    @pytest.mark.asyncio
    async def test_platform_metrics_raw(self, db_session, analytics_service, test_user):
        server = Server(name="pmsrv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        metric = ServerMetric(
            server_id=server.id,
            container_id="cid2",
            cpu_percent=45.0,
            memory_percent=55.0,
            collected_at=datetime.utcnow() - timedelta(days=1),
        )
        db_session.add(metric)
        await db_session.commit()

        result = await analytics_service.get_platform_metrics(days=7)
        assert len(result) >= 1
        assert "avg_cpu" in result[0]
        assert "peak_cpu" in result[0]

    @pytest.mark.asyncio
    async def test_platform_metrics_rollups(self, db_session, analytics_service, test_user):
        server = Server(name="pmsrv2", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        rollup = DailyServerMetric(
            server_id=server.id,
            date=(datetime.utcnow() - timedelta(days=10)).date(),
            avg_cpu=40.0,
            peak_cpu=80.0,
            avg_memory=50.0,
            peak_memory=90.0,
            data_points=100,
        )
        db_session.add(rollup)
        await db_session.commit()

        result = await analytics_service.get_platform_metrics(days=30)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_platform_metrics_empty(self, analytics_service):
        result = await analytics_service.get_platform_metrics(days=7)
        assert result == []


class TestGetVolumeAnalytics:
    """Tests for get_volume_analytics method."""

    @pytest.mark.asyncio
    async def test_volume_analytics(self, db_session, analytics_service, test_user):
        vol = Volume(name="vol1", display_name="Volume 1", owner_id=test_user.id, size_bytes=1024**3, max_size_bytes=10 * 1024**3, visibility="private", status="active")
        db_session.add(vol)
        await db_session.commit()

        result = await analytics_service.get_volume_analytics()
        assert result["total_volumes"] == 1
        assert result["total_storage_used_gb"] == 1.0
        assert result["total_storage_capacity_gb"] == 10.0
        assert result["storage_utilization_percent"] == 10.0
        assert len(result["volumes_by_visibility"]) == 1
        assert len(result["volumes_by_status"]) == 1

    @pytest.mark.asyncio
    async def test_volume_analytics_empty(self, analytics_service):
        result = await analytics_service.get_volume_analytics()
        assert result["total_volumes"] == 0
        assert result["storage_utilization_percent"] == 0


class TestGetWorkspaceAnalytics:
    """Tests for get_workspace_analytics method."""

    @pytest.mark.asyncio
    async def test_workspace_analytics(self, db_session, analytics_service, test_user):
        ws = SharedWorkspace(name="ws1", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="owner")
        db_session.add(member)
        await db_session.commit()

        result = await analytics_service.get_workspace_analytics()
        assert result["total_workspaces"] == 1
        assert result["total_members"] == 1
        assert result["avg_members_per_workspace"] == 1.0
        assert result["unique_workspace_users"] == 1

    @pytest.mark.asyncio
    async def test_workspace_analytics_empty(self, analytics_service):
        result = await analytics_service.get_workspace_analytics()
        assert result["total_workspaces"] == 0
        assert result["total_members"] == 0
        assert result["avg_members_per_workspace"] == 0


class TestGetEnvironmentUsage:
    """Tests for get_environment_usage method."""

    @pytest.mark.asyncio
    async def test_environment_usage(self, db_session, analytics_service, test_user):
        env = EnvironmentTemplate(name="test-env", slug="test-env", image="test")
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        server = Server(name="esrv", user_id=test_user.id, environment_id=env.id, status="running")
        db_session.add(server)
        await db_session.commit()

        result = await analytics_service.get_environment_usage()
        assert len(result) >= 1
        assert result[0]["server_count"] == 1

    @pytest.mark.asyncio
    async def test_environment_usage_empty(self, analytics_service):
        result = await analytics_service.get_environment_usage()
        # Should still return environments with 0 count
        assert isinstance(result, list)


class TestGetPlanUsage:
    """Tests for get_plan_usage method."""

    @pytest.mark.asyncio
    async def test_plan_usage(self, db_session, analytics_service, test_user):
        plan = ServerPlan(name="test-plan", slug="test-plan", cpu_limit=1.0, memory_limit="1g", disk_limit="10g", cost_per_hour=0, max_runtime="1h")
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        server = Server(name="psrv", user_id=test_user.id, plan_id=plan.id, status="running")
        db_session.add(server)
        await db_session.commit()

        result = await analytics_service.get_plan_usage()
        assert len(result) >= 1
        assert result[0]["server_count"] == 1

    @pytest.mark.asyncio
    async def test_plan_usage_empty(self, analytics_service):
        result = await analytics_service.get_plan_usage()
        assert isinstance(result, list)
