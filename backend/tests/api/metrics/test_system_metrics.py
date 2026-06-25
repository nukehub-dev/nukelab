"""Extended tests for System and Metrics API endpoints."""

import pytest


class TestMetricsAPI:
    """Tests for metrics endpoints."""

    @pytest.mark.asyncio
    async def test_get_server_metrics_not_found(self, client, admin_token):
        """Getting metrics for non-existent server should 404."""
        response = await client.get(
            "/api/metrics/servers/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_latest_server_metrics_not_found(self, client, admin_token):
        """Getting latest metrics for non-existent server should 404."""
        response = await client.get(
            "/api/metrics/servers/00000000-0000-0000-0000-000000000000/latest",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_system_metrics(self, client, admin_token):
        """Should get system metrics."""
        response = await client.get(
            "/api/metrics/system", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_latest_system_metrics(self, client, admin_token):
        """Should get latest system metrics."""
        response = await client.get(
            "/api/metrics/system/latest", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_alert_rules(self, client, admin_token):
        """Should list alert rules."""
        response = await client.get(
            "/api/metrics/alerts/rules", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_alert_rule_not_found(self, client, admin_token):
        """Getting non-existent alert rule should 404."""
        response = await client.get(
            "/api/metrics/alerts/rules/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_alert_rule_not_found(self, client, admin_token):
        """Updating non-existent alert rule should 404."""
        response = await client.put(
            "/api/metrics/alerts/rules/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Updated"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_alert_rule_not_found(self, client, admin_token):
        """Deleting non-existent alert rule should 404."""
        response = await client.delete(
            "/api/metrics/alerts/rules/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_alert_history(self, client, admin_token):
        """Should list alert history."""
        response = await client.get(
            "/api/metrics/alerts/history", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_acknowledge_alert_not_found(self, client, admin_token):
        """Acknowledging non-existent alert."""
        response = await client.post(
            "/api/metrics/alerts/history/00000000-0000-0000-0000-000000000000/acknowledge",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # May 404 or 422 depending on body requirements
        assert response.status_code in [404, 422]

    @pytest.mark.asyncio
    async def test_resolve_alert_not_found(self, client, admin_token):
        """Resolving non-existent alert should 404."""
        response = await client.post(
            "/api/metrics/alerts/history/00000000-0000-0000-0000-000000000000/resolve",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_server_health_not_found(self, client, admin_token):
        """Getting health for non-existent server should 404."""
        response = await client.get(
            "/api/metrics/health/servers/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_health_summary(self, client, admin_token):
        """Should get health summary."""
        response = await client.get(
            "/api/metrics/health/summary", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
