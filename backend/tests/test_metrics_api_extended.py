"""Extended tests for Metrics API: alert history and health checks."""

import pytest
import uuid
from datetime import datetime, UTC

from app.models.alert_rule import AlertRule
from app.models.alert_history import AlertHistory
from app.models.health_check import HealthCheck
from app.models.server import Server


class TestAlertHistory:
    """Tests for /api/metrics/alerts/history endpoints."""

    @pytest.mark.asyncio
    async def test_list_alert_history_admin_sees_all(self, client, admin_token, test_user, db_session):
        """Admin should see all alert history."""
        alert = AlertHistory(
            metric_value=90.0, threshold=80.0, status="fired",
            user_id=test_user.id, fired_at=datetime.now(UTC).replace(tzinfo=None)
        )
        db_session.add(alert)
        await db_session.commit()

        response = await client.get(
            "/api/metrics/alerts/history",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["alerts"]) == 1

    @pytest.mark.asyncio
    async def test_list_alert_history_user_forbidden(self, client, user_token, test_user, db_session):
        """Regular user (no ANALYTICS_READ) should get 403."""
        response = await client.get(
            "/api/metrics/alerts/history",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_alert_history_non_admin_filtered(self, client, support_token, support_user, db_session):
        """Non-admin with ANALYTICS_READ should only see their own alerts."""
        alert = AlertHistory(
            metric_value=90.0, threshold=80.0, status="fired",
            user_id=support_user.id, fired_at=datetime.now(UTC).replace(tzinfo=None)
        )
        db_session.add(alert)
        await db_session.commit()

        response = await client.get(
            "/api/metrics/alerts/history",
            headers={"Authorization": f"Bearer {support_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["alerts"]) == 1

    @pytest.mark.asyncio
    async def test_list_alert_history_status_filter(self, client, admin_token, test_user, db_session):
        """Should filter alerts by status."""
        db_session.add(AlertHistory(metric_value=90.0, threshold=80.0, status="fired", user_id=test_user.id))
        db_session.add(AlertHistory(metric_value=70.0, threshold=80.0, status="resolved", user_id=test_user.id))
        await db_session.commit()

        response = await client.get(
            "/api/metrics/alerts/history?status=resolved",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self, client, user_token, test_user, db_session):
        """Should acknowledge an alert."""
        alert = AlertHistory(
            metric_value=90.0, threshold=80.0, status="fired",
            user_id=test_user.id, fired_at=datetime.now(UTC).replace(tzinfo=None)
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)

        response = await client.post(
            f"/api/metrics/alerts/history/{alert.id}/acknowledge",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"notes": "Looking into it"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "acknowledged"
        assert data["acknowledged"] is True
        assert "acknowledged_at" in data

    @pytest.mark.asyncio
    async def test_acknowledge_alert_not_found(self, client, user_token):
        """Should 404 for nonexistent alert."""
        response = await client.post(
            f"/api/metrics/alerts/history/{uuid.uuid4()}/acknowledge",
            headers={"Authorization": f"Bearer {user_token}"},
            json={}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_resolve_alert(self, client, admin_token, test_user, db_session):
        """Admin should resolve an alert."""
        alert = AlertHistory(
            metric_value=90.0, threshold=80.0, status="fired",
            user_id=test_user.id, fired_at=datetime.now(UTC).replace(tzinfo=None)
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)

        response = await client.post(
            f"/api/metrics/alerts/history/{alert.id}/resolve",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"
        assert "resolved_at" in data

    @pytest.mark.asyncio
    async def test_resolve_alert_not_found(self, client, admin_token):
        """Should 404 for nonexistent alert."""
        response = await client.post(
            f"/api/metrics/alerts/history/{uuid.uuid4()}/resolve",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404


class TestHealthChecks:
    """Tests for /api/metrics/health/* endpoints."""

    @pytest.mark.asyncio
    async def test_server_health_checks(self, client, support_token, support_user, db_session):
        """Should return health checks for a server."""
        server = Server(name="hc-srv", user_id=support_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        for i in range(3):
            hc = HealthCheck(
                server_id=server.id, container_id="hc1",
                status="healthy", consecutive_failures=0,
                checked_at=datetime.now(UTC).replace(tzinfo=None)
            )
            db_session.add(hc)
        await db_session.commit()

        response = await client.get(
            f"/api/metrics/health/servers/{server.id}",
            headers={"Authorization": f"Bearer {support_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["checks"]) == 3
        assert data["latest"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_server_health_checks_not_found(self, client, support_token):
        """Should 404 for nonexistent server."""
        response = await client.get(
            f"/api/metrics/health/servers/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {support_token}"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_health_summary(self, client, admin_token, test_user, db_session):
        """Admin should get health summary."""
        server = Server(name="hs-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        db_session.add(HealthCheck(server_id=server.id, container_id="c1", status="healthy", checked_at=datetime.now(UTC).replace(tzinfo=None)))
        db_session.add(HealthCheck(server_id=server.id, container_id="c1", status="unhealthy", checked_at=datetime.now(UTC).replace(tzinfo=None)))
        await db_session.commit()

        response = await client.get(
            "/api/metrics/health/summary",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "status_counts" in data
        assert "unhealthy_count" in data
        assert "latest_checks" in data

    @pytest.mark.asyncio
    async def test_health_summary_forbidden_for_user(self, client, user_token):
        """Regular user should not access health summary."""
        response = await client.get(
            "/api/metrics/health/summary",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403
