# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""CSRF double-submit cookie protection.

Validates that state-changing requests include an X-CSRF-Token header
matching the csrf_token cookie. Bearer/Token auth is exempt because
browsers do not send Authorization headers automatically.

Safe methods (GET, HEAD, OPTIONS, TRACE) are always exempt.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Paths exempt from CSRF validation
_EXEMPT_PATHS = {
    "/api/health",
    "/api/docs",
    "/api/openapi.json",
}

_EXEMPT_PREFIXES = {
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/logout",
    "/api/auth/csrf-token",
    "/api/auth/oauth",
}


class CSRFProtectMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces double-submit CSRF token validation.

    For unsafe HTTP methods (POST, PUT, PATCH, DELETE):
      - If Authorization Bearer/Token header is present → exempt (not CSRF-vulnerable)
      - Otherwise require X-CSRF-Token header == csrf_token cookie
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        if not getattr(settings, "csrf_protection_enabled", True):
            return await call_next(request)

        path = request.url.path

        # Always allow safe methods
        if request.method in SAFE_METHODS:
            return await call_next(request)

        # Always allow exempt paths
        if path in _EXEMPT_PATHS:
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)

        # Bearer/Token auth is not vulnerable to CSRF
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") or auth.startswith("Token "):
            return await call_next(request)

        # Only enforce CSRF if the user has an active session cookie.
        # Unauthenticated requests have no session to hijack.
        session_cookie = request.cookies.get("nukelab_token")
        if not session_cookie:
            return await call_next(request)

        # Cookie-based state-changing request requires CSRF double-submit
        csrf_cookie = request.cookies.get("csrf_token")
        csrf_header = request.headers.get("X-CSRF-Token")

        if not csrf_cookie or not csrf_header:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token required. Include X-CSRF-Token header matching the csrf_token cookie."
                },
            )

        if csrf_cookie != csrf_header:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token mismatch."},
            )

        return await call_next(request)
