"""Tests for Analytics service and API."""

import pytest
import uuid as uuid_mod
from datetime import datetime, timedelta
from httpx import AsyncClient
from sqlalchemy import select

from app.models.server import Server
from app.models.server_metric import ServerMetric
from app.models.credit_transaction import CreditTransaction
from app.models.server_plan import ServerPlan
from app.services.analytics_service import AnalyticsService


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
            created_at=datetime.utcnow() - timedelta(days=2),
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
                    collected_at=datetime.utcnow() - timedelta(days=day_offset, hours=hour),
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
            created_at=datetime.utcnow() - timedelta(days=1),
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
            created_at=datetime.utcnow() - timedelta(days=10),
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
            collected_at=datetime.utcnow() - timedelta(days=10),
        )
        db_session.add(old_metric)
        
        # Create metric from 1 day ago (inside 7-day window)
        new_metric = ServerMetric(
            id=uuid_mod.uuid4(),
            server_id=server.id,
            container_id=server.container_id,
            cpu_percent=70.0,
            memory_percent=80.0,
            collected_at=datetime.utcnow() - timedelta(days=1),
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
            created_at=datetime.utcnow() - timedelta(days=20),
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
            created_at=datetime.utcnow() - timedelta(days=10),
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
            created_at=datetime.utcnow() - timedelta(days=2),
        )
        db_session.add(tx_curr)
        await db_session.commit()
        
        service = AnalyticsService(db_session)
        result = await service.get_user_usage(str(test_user.id), days=7)
        
        assert result["total_cost"] == 150
        assert result["prev_cost"] == 100
        assert result["cost_trend"] == 50.0  # (150-100)/100 * 100

    @pytest.mark.asyncio
    async def test_get_global_usage(self, db_session, test_user):
        """get_global_usage should return platform-wide stats."""
        server = Server(
            id=uuid_mod.uuid4(),
            name="global-test-server",
            user_id=test_user.id,
            status="running",
            container_id="test-container",
            created_at=datetime.utcnow() - timedelta(days=1),
        )
        db_session.add(server)
        await db_session.commit()
        
        service = AnalyticsService(db_session)
        result = await service.get_global_usage(days=7)
        
        assert result["period_days"] == 7
        assert result["active_users"] >= 1
        assert len(result["server_creation_by_day"]) >= 1

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
            created_at=datetime.utcnow() - timedelta(days=1),
        )
        db_session.add(tx)
        await db_session.commit()
        
        service = AnalyticsService(db_session)
        result = await service.get_top_consumers(days=7, limit=10)
        
        assert len(result) >= 1
        assert result[0]["user_id"] == str(test_user.id)
        assert result[0]["username"] == test_user.username
        assert result[0]["credits_consumed"] == 200


class TestAnalyticsAPI:
    """Analytics API endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_user_usage_api(self, client: AsyncClient, test_user, user_token):
        """User should be able to view their own usage."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get(f"/api/analytics/users/{test_user.id}/usage?days=7", headers=headers)
        
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(test_user.id)
        assert data["period_days"] == 7
        assert "daily_usage" in data
        assert "total_cost" in data

    @pytest.mark.asyncio
    async def test_user_cannot_view_other_usage(self, client: AsyncClient, test_user, user_token, admin_user):
        """User should not be able to view another user's usage."""
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = await client.get(f"/api/analytics/users/{admin_user.id}/usage?days=7", headers=headers)
        
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_view_any_usage(self, client: AsyncClient, test_user, admin_token):
        """Admin should be able to view any user's usage."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        resp = await client.get(f"/api/analytics/users/{test_user.id}/usage?days=7", headers=headers)
        
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
        assert isinstance(resp.json(), list)

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
