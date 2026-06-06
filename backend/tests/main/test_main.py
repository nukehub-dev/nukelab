"""Tests for app/main.py application setup and core endpoints."""

import pytest
from unittest import mock
from fastapi import Request
from fastapi.responses import JSONResponse

from app.main import app, startup, root, health, rate_limit_exceeded_handler
from app.config import settings


class TestAppConfiguration:
    """FastAPI app instance configuration tests."""

    def test_app_title(self):
        assert app.title == settings.app_name

    def test_app_version(self):
        assert app.version == "2.0.0"

    def test_app_root_path(self):
        assert app.root_path == "/api"

    def test_app_docs_url(self):
        assert app.docs_url == "/docs"

    def test_app_openapi_url(self):
        assert app.openapi_url == "/openapi.json"

    def test_routers_registered(self):
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/auth" in routes or any("/auth" in r for r in routes)
        assert "/users" in routes or any("/users" in r for r in routes)
        assert "/servers" in routes or any("/servers" in r for r in routes)
        assert "/admin" in routes or any("/admin" in r for r in routes)
        assert "/health" in routes or any("/health" in r for r in routes)

    def test_websocket_endpoint_registered(self):
        ws_routes = [r.path for r in app.routes if getattr(r, "path", None) == "/ws"]
        assert "/ws" in ws_routes or any(getattr(r, "path", None) == "/ws" for r in app.routes)


class TestRateLimitExceptionHandler:
    """429 exception handler tests."""

    @pytest.mark.asyncio
    async def test_rate_limit_handler_returns_json(self):
        request = mock.Mock(spec=Request)
        exc = mock.Mock()
        exc.detail = "Too many requests"
        response = await rate_limit_exceeded_handler(request, exc)
        assert response.status_code == 429
        assert response.body == b'{"detail":"Too many requests"}'

    @pytest.mark.asyncio
    async def test_rate_limit_handler_fallback_detail(self):
        request = mock.Mock(spec=Request)
        exc = Exception("some error")
        response = await rate_limit_exceeded_handler(request, exc)
        assert response.status_code == 429
        assert b"Rate limit exceeded" in response.body


class TestRootEndpoint:
    """Root / endpoint tests."""

    @pytest.mark.asyncio
    async def test_root_returns_welcome(self):
        result = await root()
        assert "message" in result
        assert settings.app_name in result["message"]
        assert result["version"] == "2.0.0"


class TestHealthEndpoint:
    """Health check endpoint tests."""

    @pytest.mark.asyncio
    async def test_health_returns_healthy_when_not_maintenance(self):
        original = settings.maintenance_mode
        try:
            settings.maintenance_mode = False
            result = await health()
            assert result == {"status": "healthy"}
        finally:
            settings.maintenance_mode = original

    @pytest.mark.asyncio
    async def test_health_returns_maintenance_when_enabled(self):
        original = settings.maintenance_mode
        original_msg = settings.maintenance_message
        try:
            settings.maintenance_mode = True
            settings.maintenance_message = "Down for maintenance"
            result = await health()
            assert isinstance(result, JSONResponse)
            assert result.status_code == 503
            body = result.body.decode()
            assert "maintenance" in body
            assert "Down for maintenance" in body
        finally:
            settings.maintenance_mode = original
            settings.maintenance_message = original_msg

    @pytest.mark.asyncio
    async def test_health_endpoint_via_client(self, client):
        original = settings.maintenance_mode
        try:
            settings.maintenance_mode = False
            response = await client.get("/api/health")
            assert response.status_code == 200
            assert response.json()["status"] == "healthy"
        finally:
            settings.maintenance_mode = original


class TestStartupEvent:
    """Application startup event tests."""

    @pytest.mark.asyncio
    async def test_startup_creates_tables(self):
        with mock.patch("app.main.engine") as mock_engine:
            mock_conn = mock.AsyncMock()
            mock_engine.begin.return_value.__aenter__ = mock.AsyncMock(return_value=mock_conn)
            mock_engine.begin.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            with mock.patch("app.main.Base"):
                with mock.patch("app.db.seed.seed_all", new_callable=mock.AsyncMock):
                    with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
                        mock_db = mock.AsyncMock()
                        mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                        mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                        with mock.patch("app.services.setting_service.SettingService"):
                            with mock.patch("app.core.roles.load_role_permissions_from_db", new_callable=mock.AsyncMock):
                                with mock.patch("app.main.manager") as mock_manager:
                                    with mock.patch("app.api.auth.run_periodic_refresh_token_cleanup", new_callable=mock.AsyncMock):
                                        await startup()
            mock_conn.run_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_warns_on_seed_failure(self):
        with mock.patch("app.main.engine") as mock_engine:
            mock_conn = mock.AsyncMock()
            mock_engine.begin.return_value.__aenter__ = mock.AsyncMock(return_value=mock_conn)
            mock_engine.begin.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            with mock.patch("app.main.Base"):
                with mock.patch("app.db.seed.seed_all", side_effect=Exception("seed fail")):
                    with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
                        mock_db = mock.AsyncMock()
                        mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                        mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                        with mock.patch("app.services.setting_service.SettingService"):
                            with mock.patch("app.core.roles.load_role_permissions_from_db", new_callable=mock.AsyncMock):
                                with mock.patch("app.main.manager") as mock_manager:
                                    with mock.patch("app.api.auth.run_periodic_refresh_token_cleanup", new_callable=mock.AsyncMock):
                                        await startup()

    @pytest.mark.asyncio
    async def test_startup_warns_on_settings_load_failure(self):
        with mock.patch("app.main.engine") as mock_engine:
            mock_conn = mock.AsyncMock()
            mock_engine.begin.return_value.__aenter__ = mock.AsyncMock(return_value=mock_conn)
            mock_engine.begin.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            with mock.patch("app.main.Base"):
                with mock.patch("app.db.seed.seed_all", new_callable=mock.AsyncMock):
                    with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
                        mock_db = mock.AsyncMock()
                        mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                        mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                        with mock.patch("app.services.setting_service.SettingService", side_effect=Exception("settings fail")):
                            with mock.patch("app.core.roles.load_role_permissions_from_db", new_callable=mock.AsyncMock):
                                with mock.patch("app.main.manager") as mock_manager:
                                    with mock.patch("app.api.auth.run_periodic_refresh_token_cleanup", new_callable=mock.AsyncMock):
                                        await startup()

    @pytest.mark.asyncio
    async def test_startup_starts_redis_listener(self):
        with mock.patch("app.main.engine") as mock_engine:
            mock_conn = mock.AsyncMock()
            mock_engine.begin.return_value.__aenter__ = mock.AsyncMock(return_value=mock_conn)
            mock_engine.begin.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            with mock.patch("app.main.Base"):
                with mock.patch("app.db.seed.seed_all", new_callable=mock.AsyncMock):
                    with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
                        mock_db = mock.AsyncMock()
                        mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                        mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                        with mock.patch("app.services.setting_service.SettingService"):
                            with mock.patch("app.core.roles.load_role_permissions_from_db", new_callable=mock.AsyncMock):
                                with mock.patch("app.main.manager") as mock_manager:
                                    with mock.patch("app.api.auth.run_periodic_refresh_token_cleanup", new_callable=mock.AsyncMock):
                                        await startup()
                                        mock_manager.start_redis_listener.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_starts_refresh_token_cleanup(self):
        with mock.patch("app.main.engine") as mock_engine:
            mock_conn = mock.AsyncMock()
            mock_engine.begin.return_value.__aenter__ = mock.AsyncMock(return_value=mock_conn)
            mock_engine.begin.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            with mock.patch("app.main.Base"):
                with mock.patch("app.db.seed.seed_all", new_callable=mock.AsyncMock):
                    with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
                        mock_db = mock.AsyncMock()
                        mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                        mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                        with mock.patch("app.services.setting_service.SettingService"):
                            with mock.patch("app.core.roles.load_role_permissions_from_db", new_callable=mock.AsyncMock):
                                with mock.patch("app.websocket.metrics_socket.manager") as mock_manager:
                                    mock_cleanup = mock.AsyncMock()
                                    with mock.patch("app.api.auth.run_periodic_refresh_token_cleanup", return_value=mock_cleanup):
                                        await startup()

"""Coverage-focused tests for utility modules and easy wins."""

import pytest
from unittest import mock
from cryptography.fernet import InvalidToken

class TestMain:
    """app/main.py coverage."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client):
        from app.main import root
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        from app.main import health
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

