"""Tests for MaintenanceMiddleware."""

import pytest
from unittest import mock
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.middleware.maintenance import MaintenanceMiddleware


@pytest.fixture
def app():
    fast_app = FastAPI()
    fast_app.add_middleware(MaintenanceMiddleware)

    @fast_app.get("/api/test")
    def test_endpoint():
        return {"ok": True}

    @fast_app.get("/api/health")
    def health():
        return {"status": "ok"}

    @fast_app.get("/api/auth/login")
    def auth():
        return {"auth": True}

    return fast_app


class TestMaintenanceMiddlewareOff:
    def test_normal_request_when_maintenance_off(self, app):
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", False):
            client = TestClient(app)
            response = client.get("/api/test")
            assert response.status_code == 200
            assert response.json() == {"ok": True}


class TestMaintenanceMiddlewareOn:
    def test_blocked_during_maintenance(self, app):
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
            with mock.patch(
                "app.middleware.maintenance.settings.maintenance_message", "Down for maintenance"
            ):
                client = TestClient(app)
                response = client.get("/api/test")
                assert response.status_code == 503
                assert response.json()["status"] == "maintenance"
                assert "Down for maintenance" in response.json()["detail"]

    def test_exempt_paths_allowed(self, app):
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
            client = TestClient(app)
            response = client.get("/api/health")
            assert response.status_code == 200

    def test_exempt_prefixes_allowed(self, app):
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
            client = TestClient(app)
            response = client.get("/api/auth/login")
            assert response.status_code == 200

    def test_admin_allowed_during_maintenance(self, app, admin_token):
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
            client = TestClient(app)
            response = client.get("/api/test", headers={"Authorization": f"Bearer {admin_token}"})
            assert response.status_code == 200

    def test_non_admin_blocked_during_maintenance(self, app, user_token):
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
            client = TestClient(app)
            response = client.get("/api/test", headers={"Authorization": f"Bearer {user_token}"})
            assert response.status_code == 503

    def test_unauthenticated_blocked_during_maintenance(self, app):
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
            client = TestClient(app)
            response = client.get("/api/test")
            assert response.status_code == 503

    def test_rate_limiting_503s(self, app):
        with mock.patch.object(MaintenanceMiddleware, "_request_log", {}):
            with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
                client = TestClient(app)
                # Make many requests quickly
                for _ in range(35):
                    response = client.get("/api/test")
                # After rate limit threshold, should get 429
                assert response.status_code == 429
                assert response.json()["status"] == "rate_limited"


class TestIsAdmin:
    def test_is_admin_with_bearer_token(self, app, admin_token):
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
            client = TestClient(app)
            response = client.get("/api/test", headers={"Authorization": f"Bearer {admin_token}"})
            assert response.status_code == 200

    def test_is_admin_with_token_prefix(self, app, admin_token):
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
            client = TestClient(app)
            response = client.get("/api/test", headers={"Authorization": f"Token {admin_token}"})
            assert response.status_code == 200

    def test_invalid_token_not_admin(self, app):
        # Clear rate limiter state from previous tests
        MaintenanceMiddleware._request_log.clear()
        with mock.patch("app.middleware.maintenance.settings.maintenance_mode", True):
            client = TestClient(app)
            response = client.get(
                "/api/test", headers={"Authorization": "Bearer invalid.token.here"}
            )
            assert response.status_code == 503
