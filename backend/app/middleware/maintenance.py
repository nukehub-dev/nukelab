"""Maintenance mode middleware — blocks non-admin requests during maintenance."""

import time

import jwt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings
from app.core import token_signing
from app.core.permissions import Permission
from app.core.roles import get_role_permissions


class MaintenanceMiddleware(BaseHTTPMiddleware):
    """
    Middleware that returns 503 for all non-exempt requests when maintenance_mode is enabled.
    Exempt paths: health checks, auth, docs, openapi, websocket, system config, admin APIs.
    Admin users (role='admin') are always allowed through.
    Rate-limits 503 responses to prevent abuse during maintenance (30/min per IP).
    """

    EXEMPT_PATHS = [
        "/api/health",
        "/health",
        "/api/docs",
        "/api/openapi.json",
        "/api/ws",
        "/ws",
    ]

    EXEMPT_PREFIXES = [
        "/api/auth",
        "/api/system",
        "/api/admin",
    ]

    # Rate limit config: max requests per window (seconds)
    RATE_LIMIT_MAX = 30
    RATE_LIMIT_WINDOW = 60

    # In-memory request log: ip -> list of timestamps
    _request_log: dict[str, list[float]] = {}

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    def _is_rate_limited(self, ip: str) -> bool:
        """Sliding-window rate limiter per IP."""
        now = time.time()
        timestamps = self._request_log.get(ip, [])

        # Remove entries outside the window
        timestamps = [t for t in timestamps if now - t < self.RATE_LIMIT_WINDOW]

        if len(timestamps) >= self.RATE_LIMIT_MAX:
            self._request_log[ip] = timestamps
            return True

        timestamps.append(now)
        self._request_log[ip] = timestamps
        return False

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Always allow exempt paths
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return await call_next(request)
        if path in self.EXEMPT_PATHS:
            return await call_next(request)

        # If not in maintenance mode, allow everything
        if not settings.maintenance_mode:
            return await call_next(request)

        # Check if user is admin — allow admins through
        is_admin = await self._is_admin(request)
        if is_admin:
            return await call_next(request)

        # Rate-limit the 503 responses to prevent abuse
        client_ip = request.client.host if request.client else "unknown"
        if self._is_rate_limited(client_ip):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please try again later.",
                    "status": "rate_limited",
                },
            )

        # Block the request
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={
                "detail": settings.maintenance_message or "System under maintenance",
                "status": "maintenance",
            },
        )

    async def _is_admin(self, request: Request) -> bool:
        """Check if the requesting user has ADMIN_ACCESS via JWT role claim."""
        token = None

        # Try Authorization header
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") or auth.startswith("Token "):
            token = auth.split(" ", 1)[1]
        else:
            # Try cookie
            token = request.cookies.get("nukelab_token")

        if not token:
            return False

        try:
            payload = await token_signing.verify_access_token(token)
            role = payload.get("role")
            if not role:
                return False
            perms = get_role_permissions(role)
            return Permission.ADMIN_ACCESS in perms or Permission.ALL in perms
        except jwt.InvalidTokenError:
            return False
