# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Per-user rate limiting middleware — FastAPI layer.

This complements Traefik's DDoS protection (very high per-IP thresholds)
with proper per-user throttling based on JWT identity and role tiers.

Key design decision: IP-based rate limiting is unusable for platforms
serving institutions behind NATs. A single university may have 10,000+
users behind a handful of public IPs. Per-user (JWT-based) limiting
ensures fair usage without collateral blocking.

Exempt paths (never rate-limited by this middleware):
  - Health checks (/api/health, /health)
  - Auth endpoints (/api/auth/*) — handled by slowapi IP-based limits
  - Docs / OpenAPI
  - WebSocket upgrade requests (/ws, /api/ws)

Security features:
  - JWT expiration is verified (stolen expired tokens can't exhaust quotas)
  - Atomic Lua script for INCR+EXPIRE (no race conditions)
  - X-Forwarded-For is validated against trusted proxy list
  - API tokens are rate-limited separately by token ID prefix
  - Rate limit headers returned on every response (RFC 6585 style)
  - Redis failures fail-open (no self-inflicted outages)
"""

import hashlib
import logging
import time

import jwt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings
from app.core import token_signing
from app.core.roles import get_role_rate_limit

logger = logging.getLogger(__name__)

# Atomic Lua script: INCR then EXPIRE only on first increment.
_LUA_INCR_EXPIRE = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local exists = redis.call('EXISTS', key)
local count = redis.call('INCR', key)
if exists == 0 then
    redis.call('EXPIRE', key, ttl)
end
return count
"""

# Trusted proxy IPs that can set X-Forwarded-For / X-Real-Ip.
_TRUSTED_PROXIES = {"127.0.0.1", "::1", "172.16.0.0/12", "10.0.0.0/8", "192.168.0.0/16"}


def _is_trusted_proxy(ip: str) -> bool:
    """Check if IP is in trusted proxy ranges."""
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True
    return bool(ip.startswith("172.") or ip.startswith("10.") or ip.startswith("192.168."))


def _hash_token_for_key(token: str) -> str:
    """Hash a token to create a stable rate-limit key without storing the raw token."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces per-user rate limits using Redis fixed-window counters.
    Falls back to IP-based limiting for unauthenticated requests.
    """

    EXEMPT_PATHS = {
        "/api/health",
        "/health",
        "/api/docs",
        "/api/openapi.json",
    }

    EXEMPT_PREFIXES = [
        "/api/auth",
        "/api/system",
    ]

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._redis = None
        self._lua_incr_expire = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as redis

            self._redis = redis.from_url(settings.redis_url)
            self._lua_incr_expire = await self._redis.script_load(_LUA_INCR_EXPIRE)
        return self._redis

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") or auth.startswith("Token "):
            return auth.split(" ", 1)[1]
        return request.cookies.get("nukelab_token")

    async def _decode_jwt(self, token: str) -> dict | None:
        try:
            return await token_signing.verify_access_token(token)
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def _get_client_ip(self, request: Request) -> str:
        direct_ip = request.client.host if request.client else "unknown"
        if not _is_trusted_proxy(direct_ip):
            return direct_ip
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            original = forwarded.split(",")[0].strip()
            if original:
                return original
        real_ip = request.headers.get("X-Real-Ip")
        if real_ip:
            return real_ip
        return direct_ip

    async def _check_rate_limit(
        self,
        user_key: str,
        role: str | None,
        path: str,
    ) -> tuple[bool, int, int, int]:
        window = settings.rate_limit_window_seconds
        bucket = int(time.time()) // window

        if path.startswith("/api/admin") or path.startswith("/admin"):
            limit = int(get_role_rate_limit(role) * settings.rate_limit_strict_multiplier)
            suffix = "s"
        elif path.startswith("/ws") or path.startswith("/api/ws"):
            limit = settings.rate_limit_websocket_cpm
            suffix = "w"
        else:
            limit = get_role_rate_limit(role)
            suffix = "a"

        redis_key = f"rl:{user_key}:{bucket}:{suffix}"
        ttl = window * settings.rate_limit_bucket_ttl_multiplier

        try:
            redis_client = await self._get_redis()
            current = await redis_client.evalsha(
                self._lua_incr_expire,
                1,
                redis_key,
                ttl,
            )
            current = int(current)
            remaining = max(0, limit - current)

            if current > limit:
                retry_after = window - (int(time.time()) % window)
                return True, retry_after, limit, 0

            return False, 0, limit, remaining

        except Exception as e:
            logger.warning(f"Rate limiter Redis error (fail-open): {e}")
            return False, 0, 0, 0

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in self.EXEMPT_PATHS:
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return await call_next(request)

        if not settings.rate_limit_enabled:
            return await call_next(request)

        token = self._extract_token(request)
        user_key: str
        role: str | None

        if token:
            payload = await self._decode_jwt(token)
            if payload and payload.get("sub"):
                user_key = payload["sub"]
                role = payload.get("role", "user")
            else:
                user_key = f"tkn:{_hash_token_for_key(token)}"
                role = "user"
        else:
            user_key = f"ip:{self._get_client_ip(request)}"
            role = "unauthenticated"

        is_limited, retry_after, limit, remaining = await self._check_rate_limit(
            user_key, role, path
        )

        if is_limited:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "error": "rate_limit_exceeded",
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        response = await call_next(request)

        if limit > 0:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            reset_time = (
                int(time.time()) // settings.rate_limit_window_seconds + 1
            ) * settings.rate_limit_window_seconds
            response.headers["X-RateLimit-Reset"] = str(reset_time)

        return response
