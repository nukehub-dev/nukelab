"""Tests for metrics API endpoints."""

import pytest
from datetime import datetime, timedelta

from app.models.server import Server
from app.models.server_metric import ServerMetric
from app.models.system_metric import SystemMetric
from app.models.alert_rule import AlertRule


class TestServerMetrics:
    """Tests for GET /api/metrics/servers/{id} (admin only)."""

    @pytest.mark.asyncio
    async def test_get_server_metrics_not_found(self, client, admin_token, db_session):
        """Should 404 for non-existent server."""
        response = await client.get(
            "/api/metrics/servers/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_server_metrics_empty(self, client, admin_token, test_user, db_session):
        """Should return empty metrics list."""
        server = Server(name="metric-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/servers/{server.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["metrics"] == []
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_get_server_metrics_with_data(self, client, admin_token, test_user, db_session):
        """Should return metrics for server."""
        server = Server(name="metric-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        metric = ServerMetric(
            server_id=server.id,
            container_id="cid",
            cpu_percent=50.0,
            memory_percent=60.0,
            collected_at=datetime.utcnow(),
        )
        db_session.add(metric)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/servers/{server.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["metrics"]) == 1

    @pytest.mark.asyncio
    async def test_get_server_latest_metrics(self, client, admin_token, test_user, db_session):
        """Should return latest metric."""
        server = Server(name="metric-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        metric = ServerMetric(
            server_id=server.id,
            container_id="cid",
            cpu_percent=50.0,
            collected_at=datetime.utcnow(),
        )
        db_session.add(metric)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/servers/{server.id}/latest",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["metric"]["cpu"]["percent"] == 50.0

    @pytest.mark.asyncio
    async def test_get_server_metrics_user_denied(self, client, user_token, test_user, db_session):
        """Regular user should be denied."""
        server = Server(name="metric-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/servers/{server.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403


class TestSystemMetrics:
    """Tests for system metrics endpoints (admin only)."""

    @pytest.mark.asyncio
    async def test_system_metrics_admin(self, client, admin_token, db_session):
        """Admin should access system metrics."""
        response = await client.get(
            "/api/metrics/system",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data

    @pytest.mark.asyncio
    async def test_system_metrics_user_denied(self, client, user_token, db_session):
        """Regular user should be denied."""
        response = await client.get(
            "/api/metrics/system",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_latest_system_metrics_admin(self, client, admin_token, db_session):
        """Admin should access latest system metrics."""
        response = await client.get(
            "/api/metrics/system/latest",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200


class TestAlertRules:
    """Tests for alert rule endpoints (admin only)."""

    @pytest.mark.asyncio
    async def test_list_alert_rules_admin(self, client, admin_token, db_session):
        """Admin should list alert rules."""
        response = await client.get(
            "/api/metrics/alerts/rules",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "rules" in data

    @pytest.mark.asyncio
    async def test_list_alert_rules_user_denied(self, client, user_token, db_session):
        """Regular user should be denied."""
        response = await client.get(
            "/api/metrics/alerts/rules",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_alert_rule(self, client, admin_token, db_session):
        """Admin should create alert rule."""
        response = await client.post(
            "/api/metrics/alerts/rules",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "High CPU",
                "metric_type": "cpu",
                "operator": ">",
                "threshold": 90.0,
                "scope": "global",
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "High CPU"

    @pytest.mark.asyncio
    async def test_get_alert_rule(self, client, admin_token, db_session):
        """Admin should get alert rule details."""
        rule = AlertRule(
            name="Test Rule",
            metric_type="cpu",
            operator=">",
            threshold=50.0,
            scope="global",
        )
        db_session.add(rule)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/alerts/rules/{rule.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Rule"

    @pytest.mark.asyncio
    async def test_get_alert_rule_not_found(self, client, admin_token, db_session):
        """Should 404 for missing rule."""
        response = await client.get(
            "/api/metrics/alerts/rules/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404
