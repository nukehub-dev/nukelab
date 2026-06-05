"""Extended tests for System and Metrics API endpoints."""

import pytest

class TestSystemAPI:
    """Tests for system endpoints."""

    @pytest.mark.asyncio
    async def test_system_health(self, client):
        """System health should be public."""
        response = await client.get("/api/system/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_system_config(self, client, admin_token):
        """System config requires admin."""
        response = await client.get(
            "/api/system/config",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_system_stats(self, client, admin_token):
        """System stats requires admin."""
        response = await client.get(
            "/api/system/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_maintenance_windows(self, client, admin_token):
        """Maintenance windows requires admin."""
        response = await client.get(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_non_admin_cannot_update_config(self, client, user_token):
        """Regular user should not update system config."""
        response = await client.put(
            "/api/system/config",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"key": "value"}
        )
        assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_non_admin_cannot_create_maintenance_window(self, client, user_token):
        """Regular user should not create maintenance windows."""
        response = await client.post(
            "/api/system/maintenance-windows",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"title": "Test", "message": "test", "start_at": "2025-01-01T00:00:00", "end_at": "2025-01-02T00:00:00"}
        )
        assert response.status_code in [403, 404]



