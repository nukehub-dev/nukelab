"""
Request body size limit middleware.

Prevents abuse from oversized request bodies (e.g., multi-gigabyte JSON payloads).
Checks Content-Length header when available; for chunked transfer encoding,
counts bytes as they stream through and aborts if the limit is exceeded.

Returns 413 Payload Too Large if the limit is exceeded.
"""

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestBodyTooLarge(Exception):
    """Raised when an incoming request body exceeds the configured maximum size."""

    def __init__(self, max_size: int, bytes_received: int):
        self.max_size = max_size
        self.bytes_received = bytes_received
        super().__init__(
            f"Request body too large: {bytes_received} bytes exceeds maximum {max_size} bytes"
        )


class RequestSizeLimitMiddleware:
    """ASGI middleware that enforces a maximum request body size."""

    def __init__(
        self,
        app: ASGIApp,
        max_size: int = 10 * 1024 * 1024,  # 10 MB default
    ):
        self.app = app
        self.max_size = max_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = self._get_content_length(scope)

        # Fast path: Content-Length header tells us the size upfront
        if content_length is not None and content_length > self.max_size:
            await self._reject(send, content_length)
            return

        # Slow path: no Content-Length (chunked) — wrap receive to count bytes
        if content_length is None:
            receive = self._wrap_receive(receive)

        await self.app(scope, receive, send)

    def _get_content_length(self, scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    return int(value.decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    return None
        return None

    def _wrap_receive(self, receive: Receive) -> Receive:
        """Wrap the receive channel to count bytes and abort if limit exceeded."""
        bytes_received = 0
        limit = self.max_size

        async def wrapped_receive():
            nonlocal bytes_received
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                bytes_received += len(body)
                if bytes_received > limit:
                    logger.warning(
                        "request_body_limit_exceeded",
                        extra={
                            "max_size": limit,
                            "bytes_received": bytes_received,
                        },
                    )
                    raise RequestBodyTooLarge(limit, bytes_received)
            return message

        return wrapped_receive

    async def _reject(self, send: Send, content_length: int) -> None:
        import json

        body = json.dumps(
            {
                "detail": f"Request body too large. Maximum allowed is {self.max_size} bytes.",
                "max_size": self.max_size,
            }
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
