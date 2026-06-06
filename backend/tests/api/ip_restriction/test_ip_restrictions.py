"""Tests for IP allowlist/blocklist middleware and admin API."""

import pytest
import pytest_asyncio
import ipaddress
from unittest.mock import patch, AsyncMock
from sqlalchemy import text

from app.middleware.ip_restriction import (
    _ip_matches,
    _get_client_ip,
    _invalidate_cache,
)
from app.models.ip_restriction import IPRestriction


@pytest.fixture(autouse=True)
def clear_ip_cache():
    """Invalidate the IP restriction cache before and after each test."""
    _invalidate_cache()
    yield
    _invalidate_cache()


class TestIPMatching:
    """Unit tests for CIDR matching logic."""

    def test_single_ip_match(self):
        assert _ip_matches("192.168.1.1", "192.168.1.1") is True
        assert _ip_matches("192.168.1.2", "192.168.1.1") is False

    def test_cidr_match(self):
        assert _ip_matches("192.168.1.50", "192.168.1.0/24") is True
        assert _ip_matches("192.168.2.1", "192.168.1.0/24") is False

    def test_ipv6_match(self):
        assert _ip_matches("::1", "::1/128") is True
        assert _ip_matches("2001:db8::1", "2001:db8::/32") is True

    def test_invalid_pattern(self):
        assert _ip_matches("192.168.1.1", "not-an-ip") is False


class TestIPRestrictionMiddleware:
    """Integration tests for the IP restriction middleware."""

    @pytest.mark.asyncio
    async def test_no_restrictions_allow_all(self, client):
        """When no restrictions exist, all traffic is allowed."""
        response = await client.get("/api/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_blocklist_blocks_matching_ip(self, client, admin_token):
        with patch(
            "app.middleware.ip_restriction._get_restrictions",
            return_value=[
                {"ip_range": "1.2.3.4/32", "restriction_type": "block"}
            ],
        ):
            with patch(
                "app.middleware.ip_restriction._get_client_ip",
                return_value="1.2.3.4",
            ):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                assert response.status_code == 403
                assert "blocked" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_blocklist_allows_non_matching_ip(self, client, admin_token):
        with patch(
            "app.middleware.ip_restriction._get_restrictions",
            return_value=[
                {"ip_range": "1.2.3.4/32", "restriction_type": "block"}
            ],
        ):
            response = await client.get(
                "/api/servers/",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert response.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_allowlist_blocks_non_matching_ip(self, client, admin_token):
        with patch(
            "app.middleware.ip_restriction._get_restrictions",
            return_value=[
                {"ip_range": "10.0.0.0/8", "restriction_type": "allow"}
            ],
        ):
            with patch(
                "app.middleware.ip_restriction._get_client_ip",
                return_value="8.8.8.8",
            ):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                assert response.status_code == 403
                assert "allowlist" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_allowlist_allows_matching_ip(self, client, admin_token):
        with patch(
            "app.middleware.ip_restriction._get_restrictions",
            return_value=[
                {"ip_range": "10.0.0.0/8", "restriction_type": "allow"}
            ],
        ):
            with patch(
                "app.middleware.ip_restriction._get_client_ip",
                return_value="10.1.2.3",
            ):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                assert response.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_exempt_paths_always_allowed(self, client):
        with patch(
            "app.middleware.ip_restriction._get_restrictions",
            return_value=[
                {"ip_range": "0.0.0.0/0", "restriction_type": "block"}
            ],
        ):
            with patch(
                "app.middleware.ip_restriction._get_client_ip",
                return_value="1.2.3.4",
            ):
                # Health check should still work
                response = await client.get("/api/health")
                assert response.status_code == 200

                # Auth should still work
                response = await client.get("/api/auth/me")
                assert response.status_code in (200, 401)

    @pytest.mark.asyncio
    async def test_inactive_restriction_ignored(self, client, admin_token):
        with patch(
            "app.middleware.ip_restriction._get_restrictions",
            return_value=[
                {"ip_range": "1.2.3.4/32", "restriction_type": "block"}
            ],
        ):
            with patch(
                "app.middleware.ip_restriction._get_client_ip",
                return_value="1.2.3.4",
            ):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                assert response.status_code == 403

        # Now simulate inactive (empty list = no active restrictions)
        with patch(
            "app.middleware.ip_restriction._get_restrictions",
            return_value=[],
        ):
            with patch(
                "app.middleware.ip_restriction._get_client_ip",
                return_value="1.2.3.4",
            ):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                assert response.status_code in (200, 404)


class TestIPRestrictionAPI:
    """Admin API tests for CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_blocklist_entry(self, client, superadmin_token):
        response = await client.post(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {superadmin_token}"},
            json={
                "ip_range": "192.168.1.0/24",
                "restriction_type": "block",
                "note": "Test block",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["ip_range"] == "192.168.1.0/24"
        assert data["restriction_type"] == "block"
        assert data["note"] == "Test block"

    @pytest.mark.asyncio
    async def test_create_invalid_ip_rejected(self, client, superadmin_token):
        response = await client.post(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {superadmin_token}"},
            json={
                "ip_range": "not-an-ip",
                "restriction_type": "block",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_invalid_type_rejected(self, client, superadmin_token):
        response = await client.post(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {superadmin_token}"},
            json={
                "ip_range": "192.168.1.0/24",
                "restriction_type": "deny",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_list_ip_restrictions(self, client, superadmin_token):
        # Create one first
        await client.post(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {superadmin_token}"},
            json={"ip_range": "10.0.0.0/8", "restriction_type": "allow"},
        )

        response = await client.get(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {superadmin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(r["ip_range"] == "10.0.0.0/8" for r in data)

    @pytest.mark.asyncio
    async def test_delete_ip_restriction(self, client, superadmin_token):
        # Create
        create_resp = await client.post(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {superadmin_token}"},
            json={"ip_range": "172.16.0.0/12", "restriction_type": "block"},
        )
        rid = create_resp.json()["id"]

        # Delete
        del_resp = await client.delete(
            f"/api/admin/ip-restrictions/{rid}",
            headers={"Authorization": f"Bearer {superadmin_token}"},
        )
        assert del_resp.status_code == 204

        # Verify gone
        list_resp = await client.get(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {superadmin_token}"},
        )
        data = list_resp.json()
        assert not any(r["id"] == rid for r in data)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, client, superadmin_token):
        response = await client.delete(
            "/api/admin/ip-restrictions/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {superadmin_token}"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_non_admin_cannot_create(self, client, user_token):
        response = await client.post(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"ip_range": "1.2.3.4", "restriction_type": "block"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_allowlist_entry(self, client, superadmin_token):
        response = await client.post(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {superadmin_token}"},
            json={
                "ip_range": "10.0.0.0/8",
                "restriction_type": "allow",
                "note": "Office VPN",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["ip_range"] == "10.0.0.0/8"
        assert data["restriction_type"] == "allow"
        assert data["note"] == "Office VPN"

    @pytest.mark.asyncio
    async def test_self_block_prevented(self, client, superadmin_token):
        """Admin cannot create a blocklist entry that covers their own IP."""
        response = await client.post(
            "/api/admin/ip-restrictions",
            headers={
                "Authorization": f"Bearer {superadmin_token}",
                "X-Forwarded-For": "203.0.113.50",
            },
            json={
                "ip_range": "203.0.113.0/24",
                "restriction_type": "block",
                "note": "Should fail",
            },
        )
        assert response.status_code == 422
        assert "cannot block your own ip" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_my_ip_endpoint(self, client):
        """My-IP endpoint returns caller's IP and is exempt from restrictions."""
        response = await client.get(
            "/api/admin/ip-restrictions/my-ip",
            headers={"X-Forwarded-For": "198.51.100.42"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ip"] == "198.51.100.42"
        assert "note" in data

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list(self, client, user_token):
        response = await client.get(
            "/api/admin/ip-restrictions",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403


class TestIPRestrictionMiddlewareModes:
    """Tests for allowlist/blocklist interaction and precedence."""

    @pytest.mark.asyncio
    async def test_mixed_allow_and_block_uses_allowlist_mode(self, client, admin_token):
        """When both allow and block entries exist, allowlist takes precedence.

        A non-matching IP should be blocked even if it doesn't match any block entry.
        """
        with patch(
            "app.middleware.ip_restriction._get_restrictions",
            return_value=[
                {"ip_range": "10.0.0.0/8", "restriction_type": "allow"},
                {"ip_range": "1.2.3.4/32", "restriction_type": "block"},
            ],
        ):
            # IP that matches neither allow nor block — should be blocked (allowlist mode)
            with patch(
                "app.middleware.ip_restriction._get_client_ip",
                return_value="8.8.8.8",
            ):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                assert response.status_code == 403
                assert "allowlist" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_ip_matching_allow_overrides_block(self, client, admin_token):
        """An IP that matches both allow and block should be allowed."""
        with patch(
            "app.middleware.ip_restriction._get_restrictions",
            return_value=[
                {"ip_range": "10.0.0.0/8", "restriction_type": "allow"},
                {"ip_range": "10.1.2.3/32", "restriction_type": "block"},
            ],
        ):
            # IP is in allowlist range and also in blocklist — allow wins
            with patch(
                "app.middleware.ip_restriction._get_client_ip",
                return_value="10.1.2.3",
            ):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )
                assert response.status_code in (200, 404)

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

