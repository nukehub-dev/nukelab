# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""OpenTelemetry tracing enrichment middleware.

This middleware sits after authentication-dependent middleware so that
`request.state.auth_context` is populated and can be attached to the active
span created by the OpenTelemetry FastAPI instrumentor.
"""

from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.core.logging import get_logger
from app.core.tracing import set_correlation_from_trace, set_span_status_from_http

logger = get_logger(__name__)

# Paths that do not need enrichment (the FastAPI instrumentor may still create
# spans for some of these; we simply skip our custom enrichment).
SKIP_PATHS = [
    "/api/health",
    "/api/health/",
    "/api/metrics",
    "/api/metrics/",
    "/api/docs",
    "/api/openapi.json",
    "/api/ws",
]


class TracingEnrichmentMiddleware(BaseHTTPMiddleware):
    """Enrich the active OTel span with request metadata after the response."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        should_skip = any(path.startswith(skip) for skip in SKIP_PATHS)

        # Bridge correlation ID to trace ID early so logs inside route handlers
        # carry the trace ID even when no explicit X-Correlation-ID was sent.
        if not should_skip:
            set_correlation_from_trace()

        response = await call_next(request)

        if should_skip:
            return response

        try:
            await self._enrich_span(request, response)
        except Exception:
            logger.exception("Failed to enrich OTel span")

        return response

    async def _enrich_span(self, request: Request, response: Response) -> None:
        span = trace.get_current_span()
        if not span or not span.is_recording():
            return

        # HTTP attributes
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.target", request.url.path)
        span.set_attribute("http.status_code", response.status_code)
        span.set_attribute("http.scheme", request.url.scheme)
        span.set_attribute("http.host", request.url.hostname or "")

        # Route-aware path normalization if available
        route = request.scope.get("route") if isinstance(request.scope, dict) else None
        if route and hasattr(route, "path"):
            span.set_attribute("http.route", route.path)

        # Auth/user attributes (PII policy: only id and role). Read the
        # primitive snapshots from AuthContext: the request-scoped DB session
        # is already closed here, and touching ORM attributes on the user
        # object can raise DetachedInstanceError after a rollback.
        auth_context = getattr(request.state, "auth_context", None)
        if auth_context and auth_context.user:
            if auth_context.user_id:
                span.set_attribute("enduser.id", auth_context.user_id)
            if auth_context.user_role:
                span.set_attribute("enduser.role", auth_context.user_role)
            span.set_attribute("auth.method", auth_context.auth_method)
            if auth_context.auth_method == "api_token" and auth_context.api_token_id:
                span.set_attribute("auth.api_token.id", str(auth_context.api_token_id))

        set_span_status_from_http(response.status_code)
