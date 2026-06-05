"""Coverage tests for smaller API modules: health, system, quotas, ip_restriction."""

import pytest
from unittest import mock
from datetime import datetime, timedelta, UTC

class TestIpRestrictionEndpoints:
    """app/api/ip_restriction.py coverage."""

    @pytest.mark.asyncio
    async def test_get_my_ip(self, client):
        response = await client.get("/api/admin/ip-restrictions/my-ip")
        assert response.status_code == 200
        data = response.json()
        assert "ip" in data
        assert "note" in data

    @pytest.mark.asyncio
    async def test_list_ip_restrictions_admin(self, client, admin_token):
        response = await client.get(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_ip_restriction_invalid_ip(self, client, admin_token):
        response = await client.post(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"ip_range": "not-an-ip", "restriction_type": "block"}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_ip_restriction_invalid_id(self, client, admin_token):
        response = await client.delete(
            "/api/admin/ip-restrictions/not-a-uuid",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_ip_restriction_not_found(self, client, admin_token):
        import uuid
        response = await client.delete(
            f"/api/admin/ip-restrictions/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404

