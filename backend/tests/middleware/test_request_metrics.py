# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Request Metrics Middleware."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import pytest_asyncio

from app.middleware.request_metrics import (
    RequestMetricsMiddleware,
    _metrics_buffer,
)


class TestRequestMetricsBuffer:
    """Buffered metrics flush behavior."""

    @pytest_asyncio.fixture(autouse=True)
    async def reset_buffer(self):
        """Clear the global buffer before and after each test."""
        _metrics_buffer.reset()
        yield
        await _metrics_buffer.shutdown()
        _metrics_buffer.reset()

    @pytest.mark.asyncio
    async def test_add_to_buffer(self):
        """Should add records to the buffer."""
        await _metrics_buffer.add({"method": "GET", "path": "/test"})
        assert len(_metrics_buffer._buffer) == 1

    @pytest.mark.asyncio
    async def test_flush_clears_buffer(self):
        """Flush should clear the buffer."""
        await _metrics_buffer.add({"method": "GET", "path": "/test"})
        assert len(_metrics_buffer._buffer) == 1

        with patch("app.middleware.request_metrics.AsyncSessionLocal") as mock_session:
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__.return_value = mock_db
            mock_db.add = Mock()
            mock_db.commit = AsyncMock()

            await _metrics_buffer.flush()
            assert len(_metrics_buffer._buffer) == 0
            mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_handles_db_errors(self):
        """Should not raise on DB error during flush."""
        await _metrics_buffer.add({"method": "GET", "path": "/test"})

        with patch("app.middleware.request_metrics.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = RuntimeError("DB down")
            await _metrics_buffer.flush()
            # Should not raise


class TestPathNormalization:
    """Path ID normalization for aggregation."""

    def test_uuid_replacement(self):
        from app.middleware.request_metrics import _fallback_normalize

        assert (
            _fallback_normalize("/api/servers/e2dc7a61-4e86-4b47-8464-a8c46178579f/stop")
            == "/api/servers/:id/stop"
        )

    def test_numeric_replacement(self):
        from app.middleware.request_metrics import _fallback_normalize

        assert _fallback_normalize("/api/users/123/profile") == "/api/users/:id/profile"

    def test_mixed_uuid_and_numeric(self):
        from app.middleware.request_metrics import _fallback_normalize

        assert (
            _fallback_normalize("/api/servers/e2dc7a61-4e86-4b47-8464-a8c46178579f/logs/5")
            == "/api/servers/:id/logs/:id"
        )

    def test_avatar_filename(self):
        from app.middleware.request_metrics import _fallback_normalize

        assert (
            _fallback_normalize("/api/users/avatar/16f9aa35-5522-498b-b67e-72cc540e9eff.jpg")
            == "/api/users/avatar/:id.jpg"
        )

    def test_static_paths_unchanged(self):
        from app.middleware.request_metrics import _fallback_normalize

        assert _fallback_normalize("/api/users/me/profile") == "/api/users/me/profile"
        assert _fallback_normalize("/api/auth/login") == "/api/auth/login"

    def test_trailing_slash_removed(self):
        from app.middleware.request_metrics import _fallback_normalize

        assert _fallback_normalize("/api/servers/") == "/api/servers"
        assert (
            _fallback_normalize("/api/servers/e2dc7a61-4e86-4b47-8464-a8c46178579f/stop/")
            == "/api/servers/:id/stop"
        )
        assert _fallback_normalize("/") == "/"


class TestRouteAwareNormalizer:
    """Route-aware path normalization using actual FastAPI routes."""

    def test_uuid_route_normalized_to_template(self):
        from app.main import app
        from app.middleware.request_metrics import _RouteAwareNormalizer

        normalizer = _RouteAwareNormalizer(app)

        # /api/servers/{server_id}/stop
        result = normalizer.normalize("/api/servers/e2dc7a61-4e86-4b47-8464-a8c46178579f/stop")
        assert result == "/api/servers/{server_id}/stop"

    def test_by_path_route_with_slugs(self):
        from app.main import app
        from app.middleware.request_metrics import _RouteAwareNormalizer

        normalizer = _RouteAwareNormalizer(app)

        # /api/servers/by-path/{username}/{server_name}
        result = normalizer.normalize("/api/servers/by-path/alice/my-nuke-server")
        assert result == "/api/servers/by-path/{username}/{server_name}"

    def test_static_route_unchanged(self):
        from app.main import app
        from app.middleware.request_metrics import _RouteAwareNormalizer

        normalizer = _RouteAwareNormalizer(app)

        result = normalizer.normalize("/api/auth/login")
        assert result == "/api/auth/login"

    def test_unknown_path_falls_back(self):
        from app.main import app
        from app.middleware.request_metrics import _RouteAwareNormalizer

        normalizer = _RouteAwareNormalizer(app)

        # A path that doesn't match any route falls back to UUID stripping
        result = normalizer.normalize("/api/unknown/e2dc7a61-4e86-4b47-8464-a8c46178579f")
        assert result == "/api/unknown/:id"

    def test_avatar_filename_with_uuid(self):
        from app.main import app
        from app.middleware.request_metrics import _RouteAwareNormalizer

        normalizer = _RouteAwareNormalizer(app)

        # /api/users/avatar/{filename} — filename contains UUID
        result = normalizer.normalize("/api/users/avatar/16f9aa35-5522-498b-b67e-72cc540e9eff.jpg")
        assert result == "/api/users/avatar/{filename}"


class TestRequestMetricsMiddleware:
    """Request metrics middleware behavior."""

    @pytest.fixture
    def middleware(self):
        return RequestMetricsMiddleware(app=None)

    @pytest.fixture(autouse=True)
    def enable_db_metrics_store(self):
        """Force DB metrics storage so middleware calls the buffer."""
        with patch("app.middleware.request_metrics.settings.request_metrics_store", "both"):
            yield

    @pytest.fixture
    def mock_request(self):
        req = MagicMock()
        req.url.path = "/api/users"
        req.method = "GET"
        req.headers = {"user-agent": "test-agent"}
        req.client = MagicMock()
        req.client.host = "127.0.0.1"
        req.state = MagicMock()
        req.state.auth_context = None
        return req

    @pytest.mark.asyncio
    async def test_skips_health_path(self, middleware, mock_request):
        """Should skip /api/health."""
        mock_request.url.path = "/api/health"

        async def call_next(req):
            return MagicMock(status_code=200)

        with patch("app.middleware.request_metrics.asyncio.create_task"):
            response = await middleware.dispatch(mock_request, call_next)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_records_metric_for_api_path(self, middleware, mock_request):
        """Should buffer a metric for API paths."""

        async def call_next(req):
            return MagicMock(status_code=200)

        with patch.object(_metrics_buffer, "add", new_callable=AsyncMock) as mock_add:
            await middleware.dispatch(mock_request, call_next)

            # Wait for the background task to execute
            await asyncio.sleep(0.05)
            mock_add.assert_awaited_once()
            record = mock_add.call_args[0][0]
            assert record["method"] == "GET"
            assert record["path"] == "/api/users"
            assert record["status_code"] == 200
            assert record["duration_ms"] > 0

    @pytest.mark.asyncio
    async def test_extracts_user_id_from_auth_context(self, middleware, mock_request):
        """Should read user_id from request.state.auth_context."""
        auth_ctx = MagicMock()
        auth_ctx.user_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_request.state.auth_context = auth_ctx

        async def call_next(req):
            return MagicMock(status_code=200)

        with patch.object(_metrics_buffer, "add", new_callable=AsyncMock) as mock_add:
            await middleware.dispatch(mock_request, call_next)
            await asyncio.sleep(0.05)
            record = mock_add.call_args[0][0]
            assert record["user_id"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_reads_correlation_id_header(self, middleware, mock_request):
        """Should use X-Correlation-ID header if present."""
        mock_request.headers = {"user-agent": "test", "X-Correlation-ID": "hdr-cid-123"}

        async def call_next(req):
            return MagicMock(status_code=200)

        with patch.object(_metrics_buffer, "add", new_callable=AsyncMock) as mock_add:
            await middleware.dispatch(mock_request, call_next)
            await asyncio.sleep(0.05)
            record = mock_add.call_args[0][0]
            assert record["correlation_id"] == "hdr-cid-123"

    def test_skip_paths_configuration(self, middleware):
        """Should have expected skip paths."""
        assert "/api/health" in middleware.SKIP_PATHS
        assert "/api/docs" in middleware.SKIP_PATHS
        assert "/api/openapi.json" in middleware.SKIP_PATHS
        assert "/api/ws" in middleware.SKIP_PATHS
        assert "/api/metrics" in middleware.SKIP_PATHS
