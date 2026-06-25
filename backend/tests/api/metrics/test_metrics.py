"""Extended coverage tests for metrics API endpoints."""

import pytest
from datetime import datetime, timedelta, UTC
from unittest import mock

from app.models.server import Server
from app.models.server_metric import ServerMetric
from app.models.system_metric import SystemMetric
from app.models.alert_rule import AlertRule
from app.models.alert_history import AlertHistory
from app.models.health_check import HealthCheck


class TestServerMetrics:
    """Tests for /metrics/servers/{server_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_server_metrics_not_owner_admin_can_access(
        self, client, admin_token, db_session, test_user
    ):
        """Admin should be able to access another user's server metrics."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        metric = ServerMetric(
            server_id=server.id,
            container_id="c1",
            cpu_percent=50.0,
        )
        db_session.add(metric)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/servers/{server.id}", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data

    @pytest.mark.asyncio
    async def test_get_server_metrics_default_dates(
        self, client, admin_token, db_session, test_user
    ):
        """Should use default date range when not provided."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        metric = ServerMetric(
            server_id=server.id,
            container_id="c1",
            cpu_percent=50.0,
        )
        db_session.add(metric)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/servers/{server.id}", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "from" in data
        assert "to" in data

    @pytest.mark.asyncio
    async def test_get_server_metrics_subsample(self, client, admin_token, db_session, test_user):
        """Should subsample when metrics exceed limit."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        for i in range(10):
            metric = ServerMetric(
                server_id=server.id,
                container_id=f"c{i}",
                cpu_percent=float(i),
            )
            db_session.add(metric)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/servers/{server.id}?limit=5",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] <= 5

    @pytest.mark.asyncio
    async def test_get_server_latest_metrics_no_metric(
        self, client, admin_token, db_session, test_user
    ):
        """Should return None when no metrics exist."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.get(
            f"/api/metrics/servers/{server.id}/latest",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["metric"] is None

    @pytest.mark.asyncio
    async def test_get_server_latest_metrics_not_owner(
        self, client, admin_token, db_session, test_user
    ):
        """Admin should access latest metrics for other user's server."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        metric = ServerMetric(
            server_id=server.id,
            container_id="c1",
            cpu_percent=50.0,
        )
        db_session.add(metric)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/servers/{server.id}/latest",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["metric"] is not None


class TestSystemMetrics:
    """Tests for /metrics/system endpoint."""

    @pytest.mark.asyncio
    async def test_get_system_metrics_default_dates(self, client, admin_token, db_session):
        """Should use default date range when not provided."""
        response = await client.get(
            "/api/metrics/system", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data

    @pytest.mark.asyncio
    async def test_get_system_metrics_subsample(self, client, admin_token, db_session):
        """Should subsample when metrics exceed limit."""
        for i in range(10):
            metric = SystemMetric(
                host="localhost",
                cpu_percent=float(i),
            )
            db_session.add(metric)
        await db_session.commit()

        response = await client.get(
            "/api/metrics/system?limit=5", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] <= 5

    @pytest.mark.asyncio
    async def test_get_latest_system_metrics_no_metric(self, client, admin_token):
        """Should return None when no system metrics exist."""
        response = await client.get(
            "/api/metrics/system/latest", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert response.json()["metric"] is None


class TestAlertRules:
    """Tests for alert rules endpoints."""

    @pytest.mark.asyncio
    async def test_create_alert_rule_with_target_id(
        self, client, admin_token, db_session, test_user
    ):
        """Should create alert rule with target_id."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        response = await client.post(
            "/api/metrics/alerts/rules",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "name": "Test Rule",
                "metric_type": "cpu",
                "operator": "gt",
                "threshold": 80.0,
                "scope": "server",
                "target_id": str(server.id),
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["name"] == "Test Rule"
        assert data["scope"] == "server"

    @pytest.mark.asyncio
    async def test_get_alert_rule_not_found(self, client, admin_token):
        """Should return 404 for missing rule."""
        import uuid

        response = await client.get(
            f"/api/metrics/alerts/rules/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_alert_rule_not_found(self, client, admin_token):
        """Should return 404 when updating missing rule."""
        import uuid

        response = await client.put(
            f"/api/metrics/alerts/rules/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Updated"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_alert_rule_target_id_conversion(self, client, admin_token, db_session):
        """Should convert target_id string to UUID during update."""
        rule = AlertRule(
            name="Test",
            metric_type="cpu",
            operator="gt",
            threshold=80.0,
            scope="server",
            target_id=None,
            is_active=True,
        )
        db_session.add(rule)
        await db_session.commit()
        await db_session.refresh(rule)

        response = await client.put(
            f"/api/metrics/alerts/rules/{rule.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"target_id": "550e8400-e29b-41d4-a716-446655440000"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_alert_rule_not_found(self, client, admin_token):
        """Should return 404 when deleting missing rule."""
        import uuid

        response = await client.delete(
            f"/api/metrics/alerts/rules/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404


class TestHealthChecks:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_get_server_health_checks_not_owner_admin(
        self, client, admin_token, db_session, test_user
    ):
        """Admin should access health checks for other user's server."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        check = HealthCheck(
            server_id=server.id,
            container_id="c1",
            status="healthy",
        )
        db_session.add(check)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/health/servers/{server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "checks" in data

    @pytest.mark.asyncio
    async def test_get_server_health_checks_latest(
        self, client, admin_token, db_session, test_user
    ):
        """Should include latest check."""
        server = Server(name="srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        check = HealthCheck(
            server_id=server.id,
            container_id="c1",
            status="healthy",
        )
        db_session.add(check)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/health/servers/{server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["latest"] is not None
