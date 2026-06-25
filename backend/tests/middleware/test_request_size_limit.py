"""Tests for request body size limit middleware."""

from unittest import mock

import pytest

from app.middleware.request_size_limit import RequestBodyTooLarge, RequestSizeLimitMiddleware


class TestRequestSizeLimitMiddleware:
    """Request body size enforcement tests."""

    @pytest.fixture
    def mock_app(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"OK"})

        return app

    @pytest.mark.asyncio
    async def test_allows_request_within_limit(self, mock_app):
        middleware = RequestSizeLimitMiddleware(mock_app, max_size=100)
        scope = {
            "type": "http",
            "headers": [(b"content-length", b"50")],
        }
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b"x" * 50, "more_body": False}

        await middleware(scope, receive, send)

        assert any(m.get("status") == 200 for m in messages)

    @pytest.mark.asyncio
    async def test_rejects_request_over_limit_by_content_length(self, mock_app):
        middleware = RequestSizeLimitMiddleware(mock_app, max_size=100)
        scope = {
            "type": "http",
            "headers": [(b"content-length", b"200")],
        }
        messages = []

        async def send(message):
            messages.append(message)

        await middleware(scope, None, send)

        start_msg = next(m for m in messages if m.get("type") == "http.response.start")
        assert start_msg["status"] == 413

    @pytest.mark.asyncio
    async def test_rejects_request_at_exact_limit_plus_one(self, mock_app):
        middleware = RequestSizeLimitMiddleware(mock_app, max_size=100)
        scope = {
            "type": "http",
            "headers": [(b"content-length", b"101")],
        }
        messages = []

        async def send(message):
            messages.append(message)

        await middleware(scope, None, send)

        start_msg = next(m for m in messages if m.get("type") == "http.response.start")
        assert start_msg["status"] == 413

    @pytest.mark.asyncio
    async def test_allows_request_at_exact_limit(self, mock_app):
        middleware = RequestSizeLimitMiddleware(mock_app, max_size=100)
        scope = {
            "type": "http",
            "headers": [(b"content-length", b"100")],
        }
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b"x" * 100, "more_body": False}

        await middleware(scope, receive, send)

        assert any(m.get("status") == 200 for m in messages)

    @pytest.mark.asyncio
    async def test_allows_request_with_no_content_length(self, mock_app):
        """Chunked requests without Content-Length are allowed through (wrapped receive)."""
        middleware = RequestSizeLimitMiddleware(mock_app, max_size=100)
        scope = {
            "type": "http",
            "headers": [],
        }
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b"small", "more_body": False}

        await middleware(scope, receive, send)

        assert any(m.get("status") == 200 for m in messages)

    @pytest.mark.asyncio
    async def test_wraps_receive_for_chunked_transfer(self, mock_app):
        """When Content-Length is missing, receive is wrapped to count bytes."""
        middleware = RequestSizeLimitMiddleware(mock_app, max_size=100)
        scope = {
            "type": "http",
            "headers": [],
        }
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b"chunk", "more_body": False}

        await middleware(scope, receive, send)

        # Should reach the inner app (no 413 because body is small)
        assert any(m.get("status") == 200 for m in messages)

    @pytest.mark.asyncio
    async def test_non_http_requests_passthrough(self, mock_app):
        """WebSocket and lifespan scopes are not checked."""
        middleware = RequestSizeLimitMiddleware(mock_app, max_size=100)
        scope = {"type": "websocket"}
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "websocket.connect"}

        await middleware(scope, receive, send)

        # Inner app should have been called
        assert len(messages) > 0

    @pytest.mark.asyncio
    async def test_error_response_includes_max_size(self, mock_app):
        middleware = RequestSizeLimitMiddleware(mock_app, max_size=1024)
        scope = {
            "type": "http",
            "headers": [(b"content-length", b"2048")],
        }
        messages = []

        async def send(message):
            messages.append(message)

        await middleware(scope, None, send)

        body_msg = next(m for m in messages if m.get("type") == "http.response.body")
        body = body_msg.get("body", b"").decode()
        assert "1024" in body
        # content_length must NOT be leaked in the public response
        assert "2048" not in body

    @pytest.mark.asyncio
    async def test_chunked_transfer_raises_when_limit_exceeded(self):
        """When no Content-Length is present, the wrapped receive raises
        RequestBodyTooLarge once the cumulative body exceeds the limit."""

        async def body_reading_app(scope, receive, send):
            # Read both chunks — the second one should trigger the exception
            await receive()
            await receive()

        middleware = RequestSizeLimitMiddleware(body_reading_app, max_size=9)
        scope = {"type": "http", "headers": []}

        chunks = [
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"67890", "more_body": False},
        ]

        async def receive():
            return chunks.pop(0)

        with pytest.raises(RequestBodyTooLarge) as exc_info:
            await middleware(scope, receive, mock.AsyncMock())

        assert exc_info.value.max_size == 9
        assert exc_info.value.bytes_received == 10

    @pytest.mark.asyncio
    async def test_chunked_transfer_allows_small_bodies(self, mock_app):
        middleware = RequestSizeLimitMiddleware(mock_app, max_size=100)
        scope = {"type": "http", "headers": []}
        messages = []

        async def send(message):
            messages.append(message)

        chunks = [
            {"type": "http.request", "body": b"small", "more_body": True},
            {"type": "http.request", "body": b" body", "more_body": False},
        ]

        async def receive():
            return chunks.pop(0)

        await middleware(scope, receive, send)
        assert any(m.get("status") == 200 for m in messages)
