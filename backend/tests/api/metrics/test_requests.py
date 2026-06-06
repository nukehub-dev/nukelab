"""Tests for request metrics API endpoint."""

import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import patch

from app.models.request_metric import RequestMetric


class TestRequestMetricsEndpoint:
    """GET /metrics/requests endpoint tests."""

    @pytest.fixture
    async def seed_metrics(self, db_session):
        """Create sample request metrics."""
        metrics = [
            RequestMetric(
                method="GET",
                path="/api/users",
                status_code=200,
                duration_ms=15.0,
                ip_address="127.0.0.1",
                user_agent="test",
            ),
            RequestMetric(
                method="POST",
                path="/api/users",
                status_code=201,
                duration_ms=45.0,
                ip_address="127.0.0.1",
                user_agent="test",
            ),
            RequestMetric(
                method="GET",
                path="/api/users",
                status_code=500,
                duration_ms=250.0,
                ip_address="127.0.0.1",
                user_agent="test",
            ),
        ]
        for m in metrics:
            db_session.add(m)
        await db_session.commit()
        return metrics

    @pytest.mark.asyncio
    async def test_admin_can_access(self, client, admin_token):
        """Admin should be able to access request metrics."""
        response = await client.get(
            "/metrics/requests",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "endpoints" in data
        assert "summary" in data
        assert "recent" in data

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, client, user_token):
        """Non-admin should be forbidden."""
        response = await client.get(
            "/metrics/requests",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_filter_by_path(self, client, admin_token, seed_metrics):
        """Should filter metrics by path."""
        response = await client.get(
            "/metrics/requests?path=/api/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert all(e["path"] == "/api/users" for e in data["endpoints"])

    @pytest.mark.asyncio
    async def test_filter_by_status_code(self, client, admin_token, seed_metrics):
        """Should filter metrics by status code."""
        response = await client.get(
            "/metrics/requests?status_code=200",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        # Raw recent should be filtered too
        assert all(r["status_code"] == 200 for r in data["recent"])

    @pytest.mark.asyncio
    async def test_summary_computed(self, client, admin_token, seed_metrics):
        """Summary should include totals and error rate."""
        response = await client.get(
            "/metrics/requests",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        summary = data["summary"]
        assert summary["total_requests"] == 3
        assert summary["total_errors"] == 1
        assert summary["error_rate"] > 0

    @pytest.mark.asyncio
    async def test_endpoints_aggregated(self, client, admin_token, seed_metrics):
        """Endpoints should show aggregated stats per path+method."""
        response = await client.get(
            "/metrics/requests",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        endpoints = data["endpoints"]

        # Should have GET /api/users and POST /api/users
        get_ep = next((e for e in endpoints if e["method"] == "GET"), None)
        assert get_ep is not None
        assert get_ep["count"] == 2  # one 200, one 500
        assert get_ep["error_count"] == 1
        assert get_ep["error_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_limit_parameter(self, client, admin_token, seed_metrics):
        """Should respect limit parameter for recent metrics."""
        response = await client.get(
            "/metrics/requests?limit=1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["recent"]) <= 1
