"""Tests for Analytics service and API."""

import pytest
import uuid as uuid_mod
from datetime import datetime, timedelta, UTC
from httpx import AsyncClient
from sqlalchemy import select

from app.models.server import Server
from app.models.server_metric import ServerMetric
from app.models.daily_server_metric import DailyServerMetric
from app.models.credit_transaction import CreditTransaction
from app.models.server_plan import ServerPlan
from app.models.volume import Volume
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.services.analytics_service import AnalyticsService
from app.services.retention_service import RetentionService


"""Tests for Analytics service and API."""


class TestAnalyticsService:
    """Analytics service tests."""

    @pytest.mark.asyncio
    async def test_analytics_service_instantiation(self, db_session):
        """Analytics service should be instantiable."""
        service = AnalyticsService(db_session)
        assert service is not None

    @pytest.mark.asyncio
    async def test_get_user_usage_empty(self, db_session, test_user):
        """get_user_usage should return empty data when no metrics exist."""
        service = AnalyticsService(db_session)
        result = await service.get_user_usage(str(test_user.id), days=7)

        assert result["user_id"] == str(test_user.id)
        assert result["period_days"] == 7
        assert result["daily_usage"] == []
        assert result["total_cost"] == 0
        assert result["active_days"] == 0
        assert result["server_breakdown"] == []

    @pytest.mark.asyncio
    async def test_get_user_usage_with_data(self, db_session, test_user):
        """get_user_usage should aggregate metrics correctly."""
        # Create a server plan
        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name="Test Plan",
            slug="test-plan",
            cost_per_hour=10,
        )
        db_session.add(plan)

        # Create a server
        server = Server(
            id=uuid_mod.uuid4(),
            name="test-server",
            user_id=test_user.id,
            plan_id=plan.id,
            status="running",
            container_id="test-container",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2),
        )
        db_session.add(server)
        await db_session.flush()

        # Create metrics for 2 days
        for day_offset in range(2):
            for hour in range(24):
                metric = ServerMetric(
                    id=uuid_mod.uuid4(),
                    server_id=server.id,
                    container_id=server.container_id,
                    cpu_percent=30.0 + hour,
                    memory_percent=50.0 + hour,
                    network_rx_bytes=1000000,
                    network_tx_bytes=500000,
                    disk_read_bytes=100000,
                    disk_write_bytes=50000,
                    collected_at=datetime.now(UTC).replace(tzinfo=None)
                    - timedelta(days=day_offset, hours=hour),
                )
                db_session.add(metric)

        # Create a credit transaction
        tx = CreditTransaction(
            id=uuid_mod.uuid4(),
            user_id=test_user.id,
            amount=-50,
            balance_after=50,
            type="server_usage",
            description="Test charge",
            server_id=server.id,
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(tx)
        await db_session.commit()

        service = AnalyticsService(db_session)
        result = await service.get_user_usage(str(test_user.id), days=7)

        assert result["user_id"] == str(test_user.id)
        assert result["total_cost"] == 50
        assert result["active_days"] >= 1
        assert len(result["daily_usage"]) >= 1
        assert len(result["server_breakdown"]) == 1
        assert result["server_breakdown"][0]["server_name"] == "test-server"
        assert result["server_breakdown"][0]["cost"] == 50

        # Check peak stats
        assert result["peak_stats"]["peak_cpu"] > 0
        assert result["peak_stats"]["peak_memory"] > 0

        # Check first day has correct aggregation
        first_day = result["daily_usage"][0]
        assert "avg_cpu" in first_day
        assert "peak_cpu" in first_day
        assert "avg_memory" in first_day
        assert "peak_memory" in first_day
        assert "data_points" in first_day

    @pytest.mark.asyncio
    async def test_get_user_usage_period_filtering(self, db_session, test_user):
        """get_user_usage should only return data within the specified period."""
        # Create server
        server = Server(
            id=uuid_mod.uuid4(),
            name="old-server",
            user_id=test_user.id,
            status="running",
            container_id="old-container",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10),
        )
        db_session.add(server)
        await db_session.flush()

        # Create metric from 10 days ago (outside 7-day window)
        old_metric = ServerMetric(
            id=uuid_mod.uuid4(),
            server_id=server.id,
            container_id=server.container_id,
            cpu_percent=50.0,
            memory_percent=60.0,
            collected_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10),
        )
        db_session.add(old_metric)

        # Create metric from 1 day ago (inside 7-day window)
        new_metric = ServerMetric(
            id=uuid_mod.uuid4(),
            server_id=server.id,
            container_id=server.container_id,
            cpu_percent=70.0,
            memory_percent=80.0,
            collected_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(new_metric)
        await db_session.commit()

        service = AnalyticsService(db_session)
        result = await service.get_user_usage(str(test_user.id), days=7)

        # Should only have the recent metric
        assert len(result["daily_usage"]) == 1
        # The old metric should be excluded
        assert result["daily_usage"][0]["avg_cpu"] == 70.0

    @pytest.mark.asyncio
    async def test_get_user_usage_cost_trend(self, db_session, test_user):
        """get_user_usage should calculate cost trend correctly."""
        server = Server(
            id=uuid_mod.uuid4(),
            name="test-server",
            user_id=test_user.id,
            status="running",
            container_id="test-container",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=20),
        )
        db_session.add(server)
        await db_session.flush()

        # Transaction in previous period (8-14 days ago)
        tx_prev = CreditTransaction(
            id=uuid_mod.uuid4(),
            user_id=test_user.id,
            amount=-100,
            balance_after=900,
            type="server_usage",
            server_id=server.id,
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10),
        )
        db_session.add(tx_prev)

        # Transaction in current period (last 7 days)
        tx_curr = CreditTransaction(
            id=uuid_mod.uuid4(),
            user_id=test_user.id,
            amount=-150,
            balance_after=750,
            type="server_usage",
            server_id=server.id,
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2),
        )
        db_session.add(tx_curr)
        await db_session.commit()

        service = AnalyticsService(db_session)
        result = await service.get_user_usage(str(test_user.id), days=7)

        assert result["total_cost"] == 150
        assert result["prev_cost"] == 100
        assert result["cost_trend"] == 50.0

    @pytest.mark.asyncio
    async def test_get_global_usage(self, db_session, test_user):
        """get_global_usage should return platform-wide stats with new fields."""
        server = Server(
            id=uuid_mod.uuid4(),
            name="global-test-server",
            user_id=test_user.id,
            status="running",
            container_id="test-container",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
            started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(server)
        await db_session.commit()

        service = AnalyticsService(db_session)
        result = await service.get_global_usage(days=7)

        assert result["period_days"] == 7
        assert result["active_users"] >= 1
        assert len(result["server_creation_by_day"]) >= 1
        # New fields
        assert "total_users" in result
        assert "new_users" in result
        assert "total_servers" in result
        assert "running_servers" in result
        assert "server_status_breakdown" in result
        assert "avg_platform_cpu" in result
        assert "avg_platform_memory" in result
        assert "total_runtime_hours" in result
        assert result["total_servers"] >= 1
        assert result["running_servers"] >= 1

    @pytest.mark.asyncio
    async def test_get_top_consumers(self, db_session, test_user):
        """get_top_consumers should return users ordered by consumption."""
        server = Server(
            id=uuid_mod.uuid4(),
            name="consumer-server",
            user_id=test_user.id,
            status="running",
            container_id="test-container",
        )
        db_session.add(server)
        await db_session.flush()

        tx = CreditTransaction(
            id=uuid_mod.uuid4(),
            user_id=test_user.id,
            amount=-200,
            balance_after=800,
            type="server_usage",
            server_id=server.id,
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(tx)
        await db_session.commit()

        service = AnalyticsService(db_session)
        result = await service.get_top_consumers(days=7, limit=10)

        assert len(result) >= 1
        assert result[0]["user_id"] == str(test_user.id)
        assert result[0]["username"] == test_user.username
        assert result[0]["credits_consumed"] == 200

    @pytest.mark.asyncio
    async def test_get_credit_flow(self, db_session, test_user):
        """get_credit_flow should return daily consumed vs granted."""
        # Consumed transaction
        tx1 = CreditTransaction(
            id=uuid_mod.uuid4(),
            user_id=test_user.id,
            amount=-100,
            balance_after=900,
            type="server_usage",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(tx1)

        # Granted transaction
        tx2 = CreditTransaction(
            id=uuid_mod.uuid4(),
            user_id=test_user.id,
            amount=50,
            balance_after=950,
            type="grant",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(tx2)
        await db_session.commit()

        service = AnalyticsService(db_session)
        result = await service.get_credit_flow(days=7)

        assert len(result) >= 1
        day_data = result[-1]
        assert "date" in day_data
        assert "credits_consumed" in day_data
        assert "credits_granted" in day_data
        assert day_data["credits_consumed"] == 100
        assert day_data["credits_granted"] == 50

    @pytest.mark.asyncio
    async def test_get_user_growth(self, db_session, test_user):
        """get_user_growth should return daily new signups."""
        service = AnalyticsService(db_session)
        result = await service.get_user_growth(days=7)

        # test_user was created recently so should appear
        assert len(result) >= 1
        day_data = result[-1]
        assert "date" in day_data
        assert "count" in day_data
        assert day_data["count"] >= 1

    @pytest.mark.asyncio
    async def test_get_platform_metrics(self, db_session, test_user):
        """get_platform_metrics should return daily aggregated resource usage."""
        server = Server(
            id=uuid_mod.uuid4(),
            name="metrics-server",
            user_id=test_user.id,
            status="running",
            container_id="metrics-container",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(server)
        await db_session.flush()

        metric = ServerMetric(
            id=uuid_mod.uuid4(),
            server_id=server.id,
            container_id=server.container_id,
            cpu_percent=45.5,
            memory_percent=60.0,
            network_rx_bytes=1000000,
            network_tx_bytes=500000,
            disk_read_bytes=100000,
            disk_write_bytes=50000,
            collected_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(metric)
        await db_session.commit()

        service = AnalyticsService(db_session)
        result = await service.get_platform_metrics(days=7)

        assert len(result) >= 1
        day_data = result[-1]
        assert "date" in day_data
        assert "avg_cpu" in day_data
        assert "peak_cpu" in day_data
        assert "avg_memory" in day_data
        assert "peak_memory" in day_data
        assert day_data["avg_cpu"] == 45.5
        assert day_data["avg_memory"] == 60.0

    @pytest.mark.asyncio
    async def test_get_volume_analytics(self, db_session, test_user):
        """get_volume_analytics should return storage stats."""
        volume = Volume(
            id=uuid_mod.uuid4(),
            name="test-vol",
            display_name="Test Volume",
            owner_id=test_user.id,
            size_bytes=1073741824,  # 1 GB
            max_size_bytes=2147483648,  # 2 GB
            status="active",
            visibility="private",
        )
        db_session.add(volume)
        await db_session.commit()

        service = AnalyticsService(db_session)
        result = await service.get_volume_analytics()

        assert result["total_volumes"] == 1
        assert result["total_storage_used_gb"] == 1.0
        assert result["total_storage_capacity_gb"] == 2.0
        assert result["storage_utilization_percent"] == 50.0
        assert len(result["volumes_by_visibility"]) >= 1
        assert len(result["volumes_by_status"]) >= 1

    @pytest.mark.asyncio
    async def test_get_workspace_analytics(self, db_session, test_user, admin_user):
        """get_workspace_analytics should return workspace stats."""
        workspace = SharedWorkspace(
            id=uuid_mod.uuid4(),
            name="Test Workspace",
            owner_id=test_user.id,
            is_active=True,
        )
        db_session.add(workspace)
        await db_session.flush()

        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=admin_user.id,
            role="read_write",
        )
        db_session.add(member)
        await db_session.commit()

        service = AnalyticsService(db_session)
        result = await service.get_workspace_analytics()

        assert result["total_workspaces"] == 1
        assert result["total_members"] == 1
        assert result["avg_members_per_workspace"] == 1.0
        assert result["unique_workspace_users"] >= 1
        assert result["total_users"] >= 2
        assert result["workspace_adoption_rate"] > 0


class TestAnalyticsAPI:
    """Analytics API endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_user_usage_api(self, client: AsyncClient, test_user, user_token):
        """User should be able to view their own usage."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get(
            f"/api/analytics/users/{test_user.id}/usage?days=7", headers=headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(test_user.id)
        assert data["period_days"] == 7
        assert "daily_usage" in data
        assert "total_cost" in data

    @pytest.mark.asyncio
    async def test_user_cannot_view_other_usage(
        self, client: AsyncClient, test_user, user_token, admin_user
    ):
        """User should not be able to view another user's usage."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get(
            f"/api/analytics/users/{admin_user.id}/usage?days=7", headers=headers
        )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_view_any_usage(self, client: AsyncClient, test_user, admin_token):
        """Admin should be able to view any user's usage."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            f"/api/analytics/users/{test_user.id}/usage?days=7", headers=headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(test_user.id)

    @pytest.mark.asyncio
    async def test_global_usage_requires_admin(self, client: AsyncClient, test_user, user_token):
        """Global usage should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/global?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_global_usage_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view global usage."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/global?days=7", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["period_days"] == 7
        assert "active_users" in data
        assert "total_credits_consumed" in data
        assert "total_users" in data
        assert "total_servers" in data
        assert "server_status_breakdown" in data

    @pytest.mark.asyncio
    async def test_top_consumers_requires_admin(self, client: AsyncClient, user_token):
        """Top consumers should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/top-consumers?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_top_consumers_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view top consumers."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/top-consumers?days=7&limit=5", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "consumers" in data
        assert isinstance(data["consumers"], list)

    @pytest.mark.asyncio
    async def test_credit_flow_requires_admin(self, client: AsyncClient, user_token):
        """Credit flow should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/credit-flow?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_credit_flow_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view credit flow."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/credit-flow?days=7", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "credit_flow" in data
        assert isinstance(data["credit_flow"], list)

    @pytest.mark.asyncio
    async def test_user_growth_requires_admin(self, client: AsyncClient, user_token):
        """User growth should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/user-growth?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_user_growth_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view user growth."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/user-growth?days=7", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "user_growth" in data
        assert isinstance(data["user_growth"], list)

    @pytest.mark.asyncio
    async def test_platform_metrics_requires_admin(self, client: AsyncClient, user_token):
        """Platform metrics should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/platform-metrics?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_platform_metrics_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view platform metrics."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/platform-metrics?days=7", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert isinstance(data["metrics"], list)

    @pytest.mark.asyncio
    async def test_volume_analytics_requires_admin(self, client: AsyncClient, user_token):
        """Volume analytics should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/volumes", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_volume_analytics_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view volume analytics."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/volumes", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "total_volumes" in data
        assert "total_storage_used_gb" in data
        assert "storage_utilization_percent" in data

    @pytest.mark.asyncio
    async def test_workspace_analytics_requires_admin(self, client: AsyncClient, user_token):
        """Workspace analytics should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/workspaces", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_workspace_analytics_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view workspace analytics."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/workspaces", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "total_workspaces" in data
        assert "total_members" in data
        assert "workspace_adoption_rate" in data

    @pytest.mark.asyncio
    async def test_environments_requires_admin(self, client: AsyncClient, user_token):
        """Environment usage should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/environments", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_plans_requires_admin(self, client: AsyncClient, user_token):
        """Plan usage should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/plans", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_date_range_params(self, client: AsyncClient, admin_token):
        """Analytics endpoints should accept from/to date parameters."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        from_date = "2024-01-01T00:00:00"
        to_date = "2024-01-31T23:59:59"

        resp = await client.get(
            f"/api/analytics/platform-metrics?from={from_date}&to={to_date}", headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data

    @pytest.mark.asyncio
    async def test_invalid_date_range(self, client: AsyncClient, admin_token):
        """Invalid date ranges should return 422."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # to_date before from_date
        resp = await client.get(
            "/api/analytics/platform-metrics?from=2024-02-01&to=2024-01-01", headers=headers
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_export_endpoint(self, client: AsyncClient, admin_token):
        """Export endpoint should return data for admin."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        payload = {
            "metric": "user-growth",
            "format": "json",
            "from": "2024-01-01T00:00:00",
            "to": "2024-01-31T23:59:59",
        }
        resp = await client.post("/api/analytics/export", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data

    @pytest.mark.asyncio
    async def test_export_requires_admin(self, client: AsyncClient, user_token):
        """Export endpoint should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        payload = {"metric": "platform-metrics", "format": "json"}
        resp = await client.post("/api/analytics/export", json=payload, headers=headers)
        assert resp.status_code == 403


class TestDailyServerMetricRollups:
    """Tests for DailyServerMetric rollup functionality."""

    @pytest.mark.asyncio
    async def test_rollup_fallback_to_raw(self, db_session, test_user):
        """Short windows should use raw metrics, not rollups."""
        server = Server(
            id=uuid_mod.uuid4(),
            name="rollup-test-server",
            user_id=test_user.id,
            status="running",
            container_id="rollup-container",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(server)
        await db_session.flush()

        metric = ServerMetric(
            id=uuid_mod.uuid4(),
            server_id=server.id,
            container_id=server.container_id,
            cpu_percent=50.0,
            memory_percent=60.0,
            collected_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(metric)
        await db_session.commit()

        service = AnalyticsService(db_session)
        # 7-day window should use raw metrics
        result = await service.get_platform_metrics(days=7)
        assert len(result) >= 1
        assert result[0]["avg_cpu"] == 50.0

    @pytest.mark.asyncio
    async def test_rollup_usage_long_window(self, db_session, test_user):
        """Long windows should use rollups when available."""
        server = Server(
            id=uuid_mod.uuid4(),
            name="rollup-long-server",
            user_id=test_user.id,
            status="running",
            container_id="rollup-long-container",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10),
        )
        db_session.add(server)
        await db_session.flush()

        rollup = DailyServerMetric(
            id=uuid_mod.uuid4(),
            server_id=server.id,
            date=(datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)).date(),
            avg_cpu=42.0,
            peak_cpu=80.0,
            avg_memory=55.0,
            peak_memory=90.0,
            avg_network_rx=1000000,
            avg_network_tx=500000,
            avg_disk_read=100000,
            avg_disk_write=50000,
            data_points=100,
        )
        db_session.add(rollup)
        await db_session.commit()

        service = AnalyticsService(db_session)
        # 30-day window should use rollups
        result = await service.get_platform_metrics(days=30)
        assert len(result) >= 1
        # Should get the rollup value
        day_result = [r for r in result if r["avg_cpu"] == 42.0]
        assert len(day_result) >= 1


class TestRetentionService:
    """Tests for RetentionService."""

    @pytest.mark.asyncio
    async def test_get_default_policy(self, db_session):
        """RetentionService should return default policy when DB is empty."""
        service = RetentionService(db_session)
        policy = await service.get_policy()
        assert "metrics_retention_days" in policy
        assert policy["metrics_retention_days"] == 30
        assert "cleanup_enabled" in policy
        assert policy["cleanup_enabled"] is True

    @pytest.mark.asyncio
    async def test_set_and_get_policy(self, db_session):
        """RetentionService should persist and return updated policy."""
        service = RetentionService(db_session)
        await service.set_policy({"metrics_retention_days": 60})
        policy = await service.get_policy()
        assert policy["metrics_retention_days"] == 60

    @pytest.mark.asyncio
    async def test_set_invalid_policy(self, db_session):
        """RetentionService should reject invalid values."""
        service = RetentionService(db_session)
        with pytest.raises(ValueError):
            await service.set_policy({"metrics_retention_days": 3})  # Below minimum


class TestAnalyticsAPIExtended:
    """Analytics API endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_user_usage_api(self, client: AsyncClient, test_user, user_token):
        """User should be able to view their own usage."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get(
            f"/api/analytics/users/{test_user.id}/usage?days=7", headers=headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(test_user.id)
        assert data["period_days"] == 7
        assert "daily_usage" in data
        assert "total_cost" in data

    @pytest.mark.asyncio
    async def test_user_cannot_view_other_usage(
        self, client: AsyncClient, test_user, user_token, admin_user
    ):
        """User should not be able to view another user's usage."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get(
            f"/api/analytics/users/{admin_user.id}/usage?days=7", headers=headers
        )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_view_any_usage(self, client: AsyncClient, test_user, admin_token):
        """Admin should be able to view any user's usage."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(
            f"/api/analytics/users/{test_user.id}/usage?days=7", headers=headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(test_user.id)

    @pytest.mark.asyncio
    async def test_global_usage_requires_admin(self, client: AsyncClient, test_user, user_token):
        """Global usage should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/global?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_global_usage_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view global usage."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/global?days=7", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["period_days"] == 7
        assert "active_users" in data
        assert "total_credits_consumed" in data
        assert "total_users" in data
        assert "total_servers" in data
        assert "server_status_breakdown" in data

    @pytest.mark.asyncio
    async def test_top_consumers_requires_admin(self, client: AsyncClient, user_token):
        """Top consumers should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/top-consumers?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_top_consumers_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view top consumers."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/top-consumers?days=7&limit=5", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "consumers" in data
        assert isinstance(data["consumers"], list)

    @pytest.mark.asyncio
    async def test_credit_flow_requires_admin(self, client: AsyncClient, user_token):
        """Credit flow should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/credit-flow?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_credit_flow_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view credit flow."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/credit-flow?days=7", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "credit_flow" in data
        assert isinstance(data["credit_flow"], list)

    @pytest.mark.asyncio
    async def test_user_growth_requires_admin(self, client: AsyncClient, user_token):
        """User growth should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/user-growth?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_user_growth_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view user growth."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/user-growth?days=7", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "user_growth" in data
        assert isinstance(data["user_growth"], list)

    @pytest.mark.asyncio
    async def test_platform_metrics_requires_admin(self, client: AsyncClient, user_token):
        """Platform metrics should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/platform-metrics?days=7", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_platform_metrics_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view platform metrics."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/platform-metrics?days=7", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert isinstance(data["metrics"], list)

    @pytest.mark.asyncio
    async def test_volume_analytics_requires_admin(self, client: AsyncClient, user_token):
        """Volume analytics should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/volumes", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_volume_analytics_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view volume analytics."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/volumes", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "total_volumes" in data
        assert "total_storage_used_gb" in data
        assert "storage_utilization_percent" in data

    @pytest.mark.asyncio
    async def test_workspace_analytics_requires_admin(self, client: AsyncClient, user_token):
        """Workspace analytics should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/workspaces", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_workspace_analytics_admin(self, client: AsyncClient, admin_token):
        """Admin should be able to view workspace analytics."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get("/api/analytics/workspaces", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "total_workspaces" in data
        assert "total_members" in data
        assert "workspace_adoption_rate" in data

    @pytest.mark.asyncio
    async def test_environments_requires_admin(self, client: AsyncClient, user_token):
        """Environment usage should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/environments", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_plans_requires_admin(self, client: AsyncClient, user_token):
        """Plan usage should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get("/api/analytics/plans", headers=headers)

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_date_range_params(self, client: AsyncClient, admin_token):
        """Analytics endpoints should accept from/to date parameters."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        from_date = "2024-01-01T00:00:00"
        to_date = "2024-01-31T23:59:59"

        resp = await client.get(
            f"/api/analytics/platform-metrics?from={from_date}&to={to_date}", headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data

    @pytest.mark.asyncio
    async def test_invalid_date_range(self, client: AsyncClient, admin_token):
        """Invalid date ranges should return 422."""
        headers = {"Authorization": f"Bearer {admin_token}"}

        # to_date before from_date
        resp = await client.get(
            "/api/analytics/platform-metrics?from=2024-02-01&to=2024-01-01", headers=headers
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_export_endpoint(self, client: AsyncClient, admin_token):
        """Export endpoint should return data for admin."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        payload = {
            "metric": "user-growth",
            "format": "json",
            "from": "2024-01-01T00:00:00",
            "to": "2024-01-31T23:59:59",
        }
        resp = await client.post("/api/analytics/export", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data

    @pytest.mark.asyncio
    async def test_export_requires_admin(self, client: AsyncClient, user_token):
        """Export endpoint should be admin-only."""
        headers = {"Authorization": f"Bearer {user_token}"}
        payload = {"metric": "platform-metrics", "format": "json"}
        resp = await client.post("/api/analytics/export", json=payload, headers=headers)
        assert resp.status_code == 403


"""Extended tests for small API modules — coverage gap closure."""

import pytest
from unittest import mock
from datetime import datetime, timedelta, UTC
import uuid as uuid_mod

from app.config import settings
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate
from app.models.notification import Notification
from app.models.activity_log import ActivityLog
from app.models.credit_transaction import CreditTransaction


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


class TestAnalyticsExtended:
    """Tests for analytics endpoint coverage gaps."""

    @pytest.mark.asyncio
    async def test_analytics_environments(self, client, admin_token):
        """Admin should get environment usage analytics."""
        with mock.patch("app.api.analytics.AnalyticsService") as mock_svc:
            mock_svc.return_value.get_environment_usage = mock.AsyncMock(return_value=[])
            response = await client.get(
                "/api/analytics/environments",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200
        assert "environments" in response.json()

    @pytest.mark.asyncio
    async def test_analytics_plans(self, client, admin_token):
        """Admin should get plan usage analytics."""
        with mock.patch("app.api.analytics.AnalyticsService") as mock_svc:
            mock_svc.return_value.get_plan_usage = mock.AsyncMock(return_value=[])
            response = await client.get(
                "/api/analytics/plans",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert response.status_code == 200
        assert "plans" in response.json()

    @pytest.mark.asyncio
    async def test_analytics_export_csv(self, client, admin_token):
        """Admin should export analytics as CSV."""
        with mock.patch("app.api.analytics.AnalyticsService") as mock_svc:
            mock_svc.return_value.get_platform_metrics = mock.AsyncMock(
                return_value=[{"day": "2024-01-01", "users": 5}]
            )
            response = await client.post(
                "/api/analytics/export",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"metric": "platform-metrics", "format": "csv"},
            )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_analytics_export_invalid_metric(self, client, admin_token):
        """Invalid metric should return 400."""
        response = await client.post(
            "/api/analytics/export",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"metric": "invalid-metric", "format": "json"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_analytics_date_validation(self, client, admin_token):
        """Invalid date range should return 422."""
        response = await client.get(
            "/api/analytics/global?from=2024-01-15T00:00:00&to=2024-01-10T00:00:00",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analytics_date_range_too_large(self, client, admin_token):
        """Date range > 365 days should return 422."""
        response = await client.get(
            "/api/analytics/global?from=2023-01-01T00:00:00&to=2024-01-15T00:00:00",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422
