# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Exception-safe ASGI security headers middleware.

Unlike BaseHTTPMiddleware, this wraps at the ASGI message layer,
guaranteeing headers are injected into the http.response.start message
even when Starlette's ServerErrorMiddleware generates a 500 response.
"""

from starlette.datastructures import MutableHeaders

from app.config import settings


class SecurityHeadersMiddleware:
    """ASGI middleware that injects security headers into every HTTP response.

    Headers are added at the ASGI message level (http.response.start),
    so they appear even on 500 Internal Server Error responses generated
    by Starlette's exception handlers.

    Headers added unconditionally:
      - X-Content-Type-Options: nosniff
      - X-Frame-Options: SAMEORIGIN
      - Referrer-Policy: strict-origin-when-cross-origin
      - Permissions-Policy: disables unused browser features
      - Cross-Origin-Resource-Policy: same-origin

    Headers added conditionally:
      - Strict-Transport-Security (HSTS) only when scheme == "https"

    This middleware is skipped entirely when ``security_headers_enabled``
    is set to ``False`` (useful for local development behind plain HTTP).
    """

    _PERMISSIONS_POLICY = (
        "accelerometer=(), "
        "camera=(), "
        "geolocation=(), "
        "gyroscope=(), "
        "magnetometer=(), "
        "microphone=(), "
        "payment=(), "
        "usb=()"
    )

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not getattr(settings, "security_headers_enabled", True):
            await self.app(scope, receive, send)
            return

        scheme = scope.get("scheme", "http")
        path = scope.get("path", "")

        # Paths that should never be cached (auth, admin, tokens)
        _SENSITIVE_PREFIXES = ("/api/auth", "/api/admin")
        is_sensitive = path.startswith(_SENSITIVE_PREFIXES)

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "SAMEORIGIN"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = self._PERMISSIONS_POLICY
                headers["Cross-Origin-Resource-Policy"] = "same-origin"
                security_endpoint = getattr(settings, "sentry_security_endpoint", "")
                if security_endpoint:
                    headers["Content-Security-Policy-Report-Only"] = (
                        "default-src 'self'; "
                        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                        "style-src 'self' 'unsafe-inline'; "
                        f"report-uri {security_endpoint}"
                    )
                if is_sensitive:
                    headers["Cache-Control"] = (
                        "no-store, no-cache, must-revalidate, proxy-revalidate"
                    )
                    headers["Pragma"] = "no-cache"
                    headers["Expires"] = "0"
                if scheme == "https":
                    headers["Strict-Transport-Security"] = (
                        "max-age=31536000; includeSubDomains; preload"
                    )
            await send(message)

        await self.app(scope, receive, wrapped_send)
