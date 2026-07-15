# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the OpenTelemetry tracing enrichment middleware."""

from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request
from sqlalchemy.orm.exc import DetachedInstanceError
from starlette.datastructures import URL, Headers

from app.middleware.tracing import SKIP_PATHS, TracingEnrichmentMiddleware


class _DetachedUser:
    """Stand-in for an ORM user whose session has closed with expired attributes."""

    @property
    def id(self):
        raise DetachedInstanceError("Instance is not bound to a Session")

    @property
    def role(self):
        raise DetachedInstanceError("Instance is not bound to a Session")


@pytest.fixture
def middleware():
    return TracingEnrichmentMiddleware(app=None)


def _make_request(path: str, method: str = "GET", headers: dict | None = None, auth_context=None):
    request = MagicMock(spec=Request)
    request.url = URL(f"http://localhost:8000{path}")
    request.method = method
    request.headers = Headers(headers or {})
    request.scope = {}
    request.state.auth_context = auth_context
    return request


class TestTracingEnrichmentMiddleware:
    """Unit tests for span enrichment behavior."""

    @pytest.mark.asyncio
    async def test_skips_health_and_metrics_paths(self, middleware):
        for path in SKIP_PATHS:
            request = _make_request(path)
            response = MagicMock(status_code=200)
            call_next = AsyncMock(return_value=response)

            with mock.patch("app.middleware.tracing.trace.get_current_span") as mock_get_span:
                result = await middleware.dispatch(request, call_next)
                assert result == response
                mock_get_span.assert_not_called()
                call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enriches_span_with_auth_context(self, middleware):
        request = _make_request("/api/users", "GET")
        response = MagicMock(status_code=200)
        call_next = AsyncMock(return_value=response)

        user = MagicMock()
        user.id = "user-uuid-123"
        user.role = "admin"

        auth_context = MagicMock()
        auth_context.user = user
        auth_context.user_id = "user-uuid-123"
        auth_context.user_role = "admin"
        auth_context.auth_method = "jwt"
        auth_context.api_token_id = None
        request.state.auth_context = auth_context

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with mock.patch("app.middleware.tracing.trace.get_current_span", return_value=mock_span):
            with mock.patch("app.middleware.tracing.set_correlation_from_trace"):
                result = await middleware.dispatch(request, call_next)
                assert result == response

                mock_span.set_attribute.assert_any_call("http.method", "GET")
                mock_span.set_attribute.assert_any_call("http.target", "/api/users")
                mock_span.set_attribute.assert_any_call("http.status_code", 200)
                mock_span.set_attribute.assert_any_call("enduser.id", "user-uuid-123")
                mock_span.set_attribute.assert_any_call("enduser.role", "admin")
                mock_span.set_attribute.assert_any_call("auth.method", "jwt")

    @pytest.mark.asyncio
    async def test_enriches_span_with_api_token(self, middleware):
        request = _make_request("/api/servers", "POST")
        response = MagicMock(status_code=201)
        call_next = AsyncMock(return_value=response)

        user = MagicMock()
        user.id = "user-uuid-456"
        user.role = "user"

        auth_context = MagicMock()
        auth_context.user = user
        auth_context.user_id = "user-uuid-456"
        auth_context.user_role = "user"
        auth_context.auth_method = "api_token"
        auth_context.api_token_id = "token-uuid-789"
        request.state.auth_context = auth_context

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with mock.patch("app.middleware.tracing.trace.get_current_span", return_value=mock_span):
            with mock.patch("app.middleware.tracing.set_correlation_from_trace"):
                await middleware.dispatch(request, call_next)
                mock_span.set_attribute.assert_any_call("auth.api_token.id", "token-uuid-789")

    @pytest.mark.asyncio
    async def test_no_span_when_not_recording(self, middleware):
        request = _make_request("/api/users")
        response = MagicMock(status_code=200)
        call_next = AsyncMock(return_value=response)

        mock_span = MagicMock()
        mock_span.is_recording.return_value = False

        with mock.patch("app.middleware.tracing.trace.get_current_span", return_value=mock_span):
            with mock.patch("app.middleware.tracing.set_correlation_from_trace"):
                await middleware.dispatch(request, call_next)
                mock_span.set_attribute.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_status_marks_span_error(self, middleware):
        request = _make_request("/api/users", "POST")
        response = MagicMock(status_code=500)
        call_next = AsyncMock(return_value=response)

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with mock.patch("app.middleware.tracing.trace.get_current_span", return_value=mock_span):
            with mock.patch("app.middleware.tracing.set_correlation_from_trace"):
                with mock.patch("app.middleware.tracing.set_span_status_from_http") as mock_status:
                    await middleware.dispatch(request, call_next)
                    mock_status.assert_called_once_with(500)

    @pytest.mark.asyncio
    async def test_extracts_http_route_from_scope(self, middleware):
        request = _make_request("/api/users/123", "GET")
        route = MagicMock()
        route.path = "/api/users/{user_id}"
        request.scope["route"] = route
        response = MagicMock(status_code=200)
        call_next = AsyncMock(return_value=response)

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with mock.patch("app.middleware.tracing.trace.get_current_span", return_value=mock_span):
            with mock.patch("app.middleware.tracing.set_correlation_from_trace"):
                await middleware.dispatch(request, call_next)
                mock_span.set_attribute.assert_any_call("http.route", "/api/users/{user_id}")

    @pytest.mark.asyncio
    async def test_enriches_span_with_detached_user(self, middleware):
        """Regression: failed requests roll back and close the session before the
        middleware runs, leaving auth_context.user detached with expired
        attributes. Enrichment must use the AuthContext snapshots and never
        touch ORM attributes on the user object."""
        request = _make_request("/api/auth/oauth/sync", "POST")
        response = MagicMock(status_code=500)
        call_next = AsyncMock(return_value=response)

        auth_context = MagicMock()
        auth_context.user = _DetachedUser()
        auth_context.user_id = "user-uuid-detached"
        auth_context.user_role = "user"
        auth_context.auth_method = "jwt"
        auth_context.api_token_id = None
        request.state.auth_context = auth_context

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with mock.patch("app.middleware.tracing.trace.get_current_span", return_value=mock_span):
            with mock.patch("app.middleware.tracing.set_correlation_from_trace"):
                with mock.patch("app.middleware.tracing.logger") as mock_logger:
                    result = await middleware.dispatch(request, call_next)
                    assert result == response
                    mock_logger.exception.assert_not_called()
                    mock_span.set_attribute.assert_any_call("enduser.id", "user-uuid-detached")
                    mock_span.set_attribute.assert_any_call("enduser.role", "user")
                    mock_span.set_attribute.assert_any_call("auth.method", "jwt")
