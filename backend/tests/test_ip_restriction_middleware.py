"""Tests for IP restriction middleware."""

import pytest
from unittest import mock
from fastapi import Request, FastAPI
from starlette.testclient import TestClient

from app.middleware.ip_restriction import (
    _get_client_ip,
    _ip_matches,
    _get_restrictions,
    _invalidate_cache,
    _forbidden_response,
    IPRestrictionMiddleware,
)


class TestGetClientIp:
    def test_x_forwarded_for(self):
        scope = {"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")]}
        assert _get_client_ip(Request(scope)) == "1.2.3.4"

    def test_x_real_ip(self):
        scope = {"type": "http", "headers": [(b"x-real-ip", b"2.3.4.5")]}
        assert _get_client_ip(Request(scope)) == "2.3.4.5"

    def test_request_client(self):
        scope = {"type": "http", "headers": [], "client": ("3.4.5.6", 12345)}
        assert _get_client_ip(Request(scope)) == "3.4.5.6"

    def test_unknown_when_no_info(self):
        scope = {"type": "http", "headers": []}
        assert _get_client_ip(Request(scope)) == "unknown"


class TestIpMatches:
    def test_single_ip_match(self):
        assert _ip_matches("192.168.1.1", "192.168.1.1") is True

    def test_single_ip_no_match(self):
        assert _ip_matches("192.168.1.1", "192.168.1.2") is False

    def test_cidr_match(self):
        assert _ip_matches("192.168.1.50", "192.168.1.0/24") is True

    def test_cidr_no_match(self):
        assert _ip_matches("10.0.0.1", "192.168.1.0/24") is False

    def test_invalid_pattern(self):
        assert _ip_matches("192.168.1.1", "not-a-network") is False

    def test_invalid_client_ip(self):
        assert _ip_matches("not-an-ip", "192.168.1.0/24") is False


class TestCacheInvalidation:
    def test_invalidate_clears_cache(self):
        # Set cache directly
        from app.middleware import ip_restriction as mod
        mod._cache = ([{"id": "1", "ip_range": "1.1.1.1", "restriction_type": "block"}], 0)
        _invalidate_cache()
        assert mod._cache is None


class TestForbiddenResponse:
    def test_status_and_content(self):
        resp = _forbidden_response("Access denied")
        assert resp.status_code == 403
        body = resp.body.decode()
        assert "Access denied" in body


class TestGetRestrictions:
    @pytest.mark.asyncio
    async def test_db_error_fails_open(self):
        with mock.patch("app.middleware.ip_restriction.AsyncSessionLocal", side_effect=Exception("DB fail")):
            result = await _get_restrictions()
            assert result == []


class TestMiddlewareDispatch:
    @pytest.fixture
    def app(self):
        fast_app = FastAPI()
        fast_app.add_middleware(IPRestrictionMiddleware)

        @fast_app.get("/api/test")
        def test_endpoint():
            return {"ok": True}

        @fast_app.get("/api/health")
        def health():
            return {"status": "ok"}

        return fast_app

    def test_exempt_path_allowed(self, app):
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_no_restrictions_allowed(self, app):
        with mock.patch("app.middleware.ip_restriction._get_restrictions", return_value=[]):
            client = TestClient(app)
            response = client.get("/api/test", headers={"X-Forwarded-For": "1.2.3.4"})
            assert response.status_code == 200

    def test_allowlist_blocks_non_match(self, app):
        restrictions = [{"id": "1", "ip_range": "10.0.0.0/8", "restriction_type": "allow"}]
        with mock.patch("app.middleware.ip_restriction._get_restrictions", return_value=restrictions):
            client = TestClient(app)
            response = client.get("/api/test", headers={"X-Forwarded-For": "1.2.3.4"})
            assert response.status_code == 403
            assert "allowlist" in response.json()["detail"]

    def test_allowlist_allows_match(self, app):
        restrictions = [{"id": "1", "ip_range": "10.0.0.0/8", "restriction_type": "allow"}]
        with mock.patch("app.middleware.ip_restriction._get_restrictions", return_value=restrictions):
            client = TestClient(app)
            response = client.get("/api/test", headers={"X-Forwarded-For": "10.0.0.5"})
            assert response.status_code == 200

    def test_blocklist_blocks_match(self, app):
        restrictions = [{"id": "1", "ip_range": "1.2.3.4", "restriction_type": "block"}]
        with mock.patch("app.middleware.ip_restriction._get_restrictions", return_value=restrictions):
            client = TestClient(app)
            response = client.get("/api/test", headers={"X-Forwarded-For": "1.2.3.4"})
            assert response.status_code == 403
            assert "blocked" in response.json()["detail"]

    def test_blocklist_allows_non_match(self, app):
        restrictions = [{"id": "1", "ip_range": "1.2.3.4", "restriction_type": "block"}]
        with mock.patch("app.middleware.ip_restriction._get_restrictions", return_value=restrictions):
            client = TestClient(app)
            response = client.get("/api/test", headers={"X-Forwarded-For": "5.6.7.8"})
            assert response.status_code == 200

    def test_auth_prefix_exempt(self, app):
        restrictions = [{"id": "1", "ip_range": "1.2.3.4", "restriction_type": "block"}]
        with mock.patch("app.middleware.ip_restriction._get_restrictions", return_value=restrictions):
            client = TestClient(app)
            response = client.get("/api/auth/login", headers={"X-Forwarded-For": "1.2.3.4"})
            assert response.status_code == 404  # no route, but middleware allowed it through
