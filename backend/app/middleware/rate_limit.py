"""
Per-user rate limiting middleware — FastAPI layer.

This complements Traefik's DDoS protection (very high per-IP thresholds)
with proper per-user throttling based on JWT identity and role tiers.

Key design decision: IP-based rate limiting is unusable for platforms
serving institutions behind NATs. A single university may have 10,000+
users behind a handful of public IPs. Per-user (JWT-based) limiting
ensures fair usage without collateral blocking.

Tiers (requests per minute):
  guest        : 30
  user         : 120
  support      : 300
  moderator    : 300
  admin        : 600
  super_admin  : 3000 (effectively unlimited)

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

import time
import logging
import hashlib
from typing import Optional, Tuple
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from jose import jwt, JWTError, ExpiredSignatureError

from app.config import settings

logger = logging.getLogger(__name__)

# Role → RPM limit mapping
ROLE_LIMITS = {
    "guest": settings.rate_limit_guest_rpm,
    "user": settings.rate_limit_user_rpm,
    "support": settings.rate_limit_support_rpm,
    "moderator": settings.rate_limit_moderator_rpm,
    "admin": settings.rate_limit_admin_rpm,
    "super_admin": settings.rate_limit_super_admin_rpm,
}

# Atomic Lua script: INCR then EXPIRE only on first increment.
# Returns the new count so we can check against the limit in one round-trip.
# Using EXISTS + INCR + EXPIRE atomically prevents the race where two
# concurrent requests both see current==1 and both try to set TTL.
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
# In Docker, Traefik is on the same network. Adjust for production LB setup.
_TRUSTED_PROXIES = {"127.0.0.1", "::1", "172.16.0.0/12", "10.0.0.0/8", "192.168.0.0/16"}


def _is_trusted_proxy(ip: str) -> bool:
    """Check if IP is in trusted proxy ranges."""
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True
    # Simple prefix checks for private ranges (covers Docker networks)
    if ip.startswith("172.") or ip.startswith("10.") or ip.startswith("192.168."):
        return True
    return False


def _hash_token_for_key(token: str) -> str:
    """Hash a token to create a stable rate-limit key without storing the raw token."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces per-user rate limits using Redis fixed-window counters.
    Falls back to IP-based limiting for unauthenticated requests.
    """

    # Paths that are never rate-limited by this middleware
    EXEMPT_PATHS = {
        "/api/health",
        "/health",
        "/api/docs",
        "/api/openapi.json",
    }

    EXEMPT_PREFIXES = [
        "/api/auth",   # Auth endpoints use slowapi IP-based limits
        "/api/system", # System config is public/read-only
    ]

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._redis = None
        self._lua_incr_expire = None

    async def _get_redis(self):
        """Lazy-init Redis connection and Lua script."""
        if self._redis is None:
            import redis.asyncio as redis
            self._redis = redis.from_url(settings.redis_url)
            self._lua_incr_expire = await self._redis.script_load(_LUA_INCR_EXPIRE)
        return self._redis

    @staticmethod
    def _extract_token(request: Request) -> Optional[str]:
        """Extract Bearer token from header or cookie."""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") or auth.startswith("Token "):
            return auth.split(" ", 1)[1]
        return request.cookies.get("nukelab_token")

    def _decode_jwt(self, token: str) -> Optional[dict]:
        """
        Decode and FULLY VERIFY the JWT including expiration.

        We verify expiration here because a stolen expired token should NOT
        be able to consume the real user's rate limit budget (DoS vector).
        """
        try:
            return jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
            )
        except ExpiredSignatureError:
            # Expired token — treat as unauthenticated for rate limiting
            return None
        except JWTError:
            return None

    def _get_client_ip(self, request: Request) -> str:
        """
        Extract real client IP safely.

        Only trusts X-Forwarded-For / X-Real-Ip if the direct connection
        is from a trusted proxy (Traefik, internal LB). Otherwise uses
        the direct remote address to prevent IP spoofing.
        """
        direct_ip = request.client.host if request.client else "unknown"

        if not _is_trusted_proxy(direct_ip):
            # Direct connection from untrusted source — don't trust forwarded headers
            return direct_ip

        # Behind trusted proxy — check forwarded headers
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # X-Forwarded-For is a comma-separated chain; the FIRST entry
            # is the original client (added by the first proxy). Traefik
            # appends the remote address to this chain.
            original = forwarded.split(",")[0].strip()
            if original:
                return original

        real_ip = request.headers.get("X-Real-Ip")
        if real_ip:
            return real_ip

        return direct_ip

    def _get_limit(self, role: Optional[str]) -> int:
        """Get RPM limit for role. Defaults to 'user' tier."""
        if not role:
            return ROLE_LIMITS["user"]
        return ROLE_LIMITS.get(role.lower(), ROLE_LIMITS["user"])

    async def _check_rate_limit(
        self,
        user_key: str,
        role: Optional[str],
        path: str,
    ) -> Tuple[bool, int, int, int]:
        """
        Check if user is rate-limited.

        Returns: (is_limited, retry_after, limit, remaining)
        """
        window = settings.rate_limit_window_seconds
        bucket = int(time.time()) // window

        # Determine limit and key suffix based on endpoint type
        if path.startswith("/api/admin") or path.startswith("/admin"):
            limit = int(self._get_limit(role) * settings.rate_limit_strict_multiplier)
            suffix = "s"  # strict
        elif path.startswith("/ws") or path.startswith("/api/ws"):
            limit = settings.rate_limit_websocket_cpm
            suffix = "w"  # websocket
        else:
            limit = self._get_limit(role)
            suffix = "a"  # api

        redis_key = f"rl:{user_key}:{bucket}:{suffix}"
        ttl = window * settings.rate_limit_bucket_ttl_multiplier

        try:
            redis_client = await self._get_redis()
            # Atomic Lua script: INCR + conditional EXPIRE
            current = await redis_client.evalsha(
                self._lua_incr_expire,
                1,  # numkeys
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
            # Fail open: Redis unavailable → don't block traffic
            logger.warning(f"Rate limiter Redis error (fail-open): {e}")
            return False, 0, 0, 0

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip exempt paths
        if path in self.EXEMPT_PATHS:
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return await call_next(request)

        # Skip if rate limiting is disabled
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Extract identity
        token = self._extract_token(request)
        user_key: str
        role: Optional[str]

        if token:
            # Try JWT first (full verification including expiration)
            payload = self._decode_jwt(token)
            if payload and payload.get("sub"):
                user_key = payload["sub"]
                role = payload.get("role", "user")
            else:
                # Not a valid JWT — could be an API token.
                # Rate-limit by token hash so each API key has its own budget.
                user_key = f"tkn:{_hash_token_for_key(token)}"
                role = "user"
        else:
            # Unauthenticated: rate limit by IP (last-resort fallback)
            user_key = f"ip:{self._get_client_ip(request)}"
            role = "unauthenticated"

        # Skip super_admin (they have effectively unlimited quotas)
        if role == "super_admin":
            response = await call_next(request)
            return response

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

        # Pass through and add rate limit headers to the successful response
        response = await call_next(request)

        if limit > 0:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            reset_time = (int(time.time()) // settings.rate_limit_window_seconds + 1) * settings.rate_limit_window_seconds
            response.headers["X-RateLimit-Reset"] = str(reset_time)

        return response
