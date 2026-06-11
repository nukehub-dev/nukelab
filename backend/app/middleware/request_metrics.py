"""
HTTP Request Metrics Middleware.

Tracks latency, status codes, and error rates per endpoint.
Writes are batched to reduce DB pressure.
"""

import asyncio
import re
import time
import uuid
from typing import List, Optional
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.logging import get_logger
from app.core.context import correlation_id
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.request_metric import RequestMetric

logger = get_logger(__name__)

# Regex to match UUIDs and numeric IDs in paths
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(r"^\d+$")


def _fallback_normalize(path: str) -> str:
    """Best-effort normalization for paths that don't match any known route."""
    # Strip trailing slash (except root)
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    parts = path.split("/")
    normalized = []
    for part in parts:
        if not part:
            normalized.append(part)
            continue
        if _UUID_RE.search(part):
            normalized.append(_UUID_RE.sub(":id", part))
            continue
        if _NUMERIC_RE.match(part):
            normalized.append(":id")
            continue
        normalized.append(part)
    return "/".join(normalized)


class _RouteAwareNormalizer:
    """Normalize paths using FastAPI route patterns.

    Converts actual request paths like /api/servers/abc-123/stop
    into their route templates /api/servers/{server_id}/stop.
    """

    def __init__(self, app):
        self._patterns: list[tuple[re.Pattern, str]] = []
        root = app.root_path or ""

        for route in app.routes:
            if not hasattr(route, "path_regex") or not hasattr(route, "path"):
                continue
            # Skip websocket routes
            if getattr(route, "methods", None) is None:
                continue

            regex = route.path_regex
            template = route.path

            # Prepend root_path so /servers/{id} becomes /api/servers/{id}
            if root and root != "/":
                pattern = regex.pattern
                if pattern.startswith("^"):
                    pattern = "^" + root + pattern[1:]
                else:
                    pattern = root + pattern
                regex = re.compile(pattern)
                template = root + template

            self._patterns.append((regex, template))

    def normalize(self, path: str) -> str:
        for regex, template in self._patterns:
            if regex.match(path):
                return template
        return _fallback_normalize(path)


# Lazily initialized on first request
_route_normalizer: Optional[_RouteAwareNormalizer] = None


def _normalize_path(path: str) -> str:
    """Normalize a request path using route-aware matching."""
    global _route_normalizer
    if _route_normalizer is None:
        # Lazy import to avoid circular dependency at module load time
        from app.main import app as fastapi_app
        _route_normalizer = _RouteAwareNormalizer(fastapi_app)
    return _route_normalizer.normalize(path)


class _RequestMetricsBuffer:
    """In-memory buffer with periodic flush for request metrics."""

    def __init__(self, max_size: int = 100, flush_interval: float = 5.0):
        self._buffer: List[dict] = []
        self._lock = asyncio.Lock()
        self._max_size = max_size
        self._flush_interval = flush_interval
        self._flush_task: Optional[asyncio.Task] = None
        self._started = False
        self._pending_adds: set = set()

    async def add(self, record: dict) -> None:
        if not self._started:
            self._start()

        async with self._lock:
            self._buffer.append(record)
            should_flush = len(self._buffer) >= self._max_size

        if should_flush:
            await self.flush()

    def _start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            self._flush_task = asyncio.create_task(self._periodic_flush())
        except RuntimeError:
            # No event loop yet (shouldn't happen in middleware, but be safe)
            pass

    async def _periodic_flush(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._flush_interval)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Periodic metrics flush failed")

    async def flush(self) -> None:
        async with self._lock:
            batch = self._buffer[:]
            self._buffer = []

        if not batch:
            return

        try:
            async with AsyncSessionLocal() as db:
                for record in batch:
                    metric = RequestMetric(**record)
                    db.add(metric)
                await db.commit()
        except Exception:
            logger.exception("Failed to flush request metrics batch (size=%s)", len(batch))

    async def shutdown(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Yield so any fire-and-forget add() tasks that were created just
        # before shutdown have a chance to append to the buffer.
        if self._pending_adds:
            await asyncio.sleep(0)
            # Clean up completed tasks from the set
            self._pending_adds = {t for t in self._pending_adds if not t.done()}

        await self.flush()


# Global buffer instance
_metrics_buffer = _RequestMetricsBuffer()


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware that tracks HTTP request latency and outcome.
    Skips health checks, docs, WebSocket, and metrics endpoints.
    """

    SKIP_PATHS = [
        "/api/health",
        "/api/docs",
        "/api/openapi.json",
        "/api/ws",
        "/api/metrics",  # skip self to avoid recursion
    ]

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        if not settings.request_metrics_enabled:
            return await call_next(request)

        path = request.url.path

        # Skip certain paths entirely
        if any(path.startswith(skip) for skip in self.SKIP_PATHS):
            return await call_next(request)

        # Capture start time
        start = time.perf_counter()

        # Ensure correlation_id is set for the request (if not already)
        existing_cid = correlation_id.get("")
        if not existing_cid:
            cid = request.headers.get("X-Correlation-ID", "")
            if not cid:
                cid = str(uuid.uuid4())
            correlation_id.set(cid)

        # Process request
        response = await call_next(request)

        # Skip 404s from scanners/bots — they don't reflect real API performance
        if response.status_code == 404:
            return response

        # Compute duration
        duration_ms = (time.perf_counter() - start) * 1000

        # Extract user info from auth context (no DB hit)
        user_id = None
        auth_context = getattr(request.state, "auth_context", None)
        if auth_context:
            # auth_context may have user_id or we need to derive it
            user_id = getattr(auth_context, "user_id", None)
            if not user_id and hasattr(auth_context, "sub"):
                # JWT payload has 'sub' = username; we skip the DB lookup here
                pass

        # Get IP address
        ip_address = None
        if request.client and request.client.host:
            ip_address = request.client.host

        # Build record (normalize path for meaningful aggregation)
        record = {
            "method": request.method,
            "path": _normalize_path(path),
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 3),
            "user_id": user_id,
            "ip_address": ip_address,
            "user_agent": request.headers.get("user-agent"),
            "correlation_id": correlation_id.get(""),
        }

        # Fire-and-forget buffer add (tracked so shutdown can wait for stragglers)
        try:
            task = asyncio.create_task(_metrics_buffer.add(record))
            _metrics_buffer._pending_adds.add(task)
            task.add_done_callback(_metrics_buffer._pending_adds.discard)
        except Exception:
            logger.exception("Failed to buffer request metric")

        return response


async def flush_request_metrics() -> None:
    """Flush any pending metrics (call on shutdown)."""
    await _metrics_buffer.flush()
