"""
Redis-backed per-user rate limiting helpers for explicit route dependencies.

For automatic rate limiting on all routes, see app.middleware.rate_limit.
This module provides explicit dependencies for endpoints that need custom
or stricter limits than the middleware's role-based defaults.

Usage:
    @router.post("/expensive-operation")
    async def expensive_op(
        request: Request,
        _: None = Depends(rate_limit_strict),
    ):
        ...

Algorithm: Fixed-window counter with atomic Lua INCR+EXPIRE.
"""

import time
import logging
import hashlib
from typing import Optional
from fastapi import Request, HTTPException, status
from jose import jwt, JWTError, ExpiredSignatureError

from app.config import settings

logger = logging.getLogger(__name__)

# Role → RPM mapping
ROLE_RATE_LIMITS = {
    "guest": settings.rate_limit_guest_rpm,
    "user": settings.rate_limit_user_rpm,
    "support": settings.rate_limit_support_rpm,
    "moderator": settings.rate_limit_moderator_rpm,
    "admin": settings.rate_limit_admin_rpm,
    "super_admin": settings.rate_limit_super_admin_rpm,
}

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


class RateLimitExceeded(HTTPException):
    """Raised when a user exceeds their rate limit."""

    def __init__(self, retry_after: int = 60, limit: int = 0):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": "Too many requests. Please slow down.",
                "retry_after": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + retry_after),
            },
        )


def _get_redis_client():
    """Lazy-import redis to avoid startup dependency issues."""
    import redis.asyncio as redis
    return redis.from_url(settings.redis_url)


def _extract_jwt_sub(token: str) -> Optional[str]:
    """Decode and verify JWT, return sub claim. Returns None for expired/invalid tokens."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except ExpiredSignatureError:
        return None
    except JWTError:
        return None


def _hash_token(token: str) -> str:
    """Hash a raw token for stable rate-limit keying."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _get_user_key_and_role(request: Request) -> tuple[str, Optional[str]]:
    """
    Extract (rate_limit_key, role) from the request.

    Priority:
      1. Valid JWT → username + role from payload
      2. API token → token hash (each key gets its own budget)
      3. Unauthenticated → IP-based fallback
    """
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer ") or auth_header.startswith("Token "):
        token = auth_header.split(" ", 1)[1]
    else:
        token = request.cookies.get("nukelab_token", "")

    if token:
        # Try JWT
        sub = _extract_jwt_sub(token)
        if sub:
            try:
                payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
                role = payload.get("role", "user")
                return (sub, role)
            except JWTError:
                pass
        # API token fallback
        return (f"tkn:{_hash_token(token)}", "user")

    # Unauthenticated fallback
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    if client_ip and "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()
    return (f"ip:{client_ip}", "unauthenticated")


def _get_limit_for_role(role: Optional[str]) -> int:
    """Get RPM limit for a role. Unknown roles default to 'user' tier."""
    if not role:
        return ROLE_RATE_LIMITS["user"]
    return ROLE_RATE_LIMITS.get(role.lower(), ROLE_RATE_LIMITS["user"])


async def _check_limit(
    request: Request,
    multiplier: float = 1.0,
    custom_key_suffix: str = "",
    limit_override: Optional[int] = None,
) -> tuple[int, int]:
    """
    Check rate limit. Returns (limit, remaining). Raises RateLimitExceeded if over.
    """
    if not settings.rate_limit_enabled:
        return 0, 0

    user_key, role = _get_user_key_and_role(request)

    if role == "super_admin" and multiplier >= 1.0 and not limit_override:
        return 0, 0

    if limit_override is not None:
        limit = limit_override
    else:
        limit = int(_get_limit_for_role(role) * multiplier)

    window = settings.rate_limit_window_seconds
    bucket = int(time.time()) // window
    redis_key = f"rl:{user_key}:{bucket}:{custom_key_suffix or 'dep'}"
    ttl = window * settings.rate_limit_bucket_ttl_multiplier

    try:
        redis_client = _get_redis_client()
        lua_sha = await redis_client.script_load(_LUA_INCR_EXPIRE)
        current = int(await redis_client.evalsha(lua_sha, 1, redis_key, ttl))
        remaining = max(0, limit - current)

        if current > limit:
            retry_after = window - (int(time.time()) % window)
            raise RateLimitExceeded(retry_after=retry_after, limit=limit)

        return limit, remaining

    except RateLimitExceeded:
        raise
    except Exception as e:
        logger.warning(f"Rate limiter Redis error (fail-open): {e}")
        return 0, 0


# ─── FastAPI Dependencies ───

async def rate_limit_general(request: Request) -> None:
    """Standard tier rate limit (1.0×). Use as Depends()."""
    await _check_limit(request, multiplier=1.0)


async def rate_limit_strict(request: Request) -> None:
    """Strict rate limit (0.5× of tier). For mutations, admin ops, bulk actions."""
    await _check_limit(request, multiplier=settings.rate_limit_strict_multiplier)


async def rate_limit_auth(request: Request) -> None:
    """Auth endpoint rate limit (separate key suffix to isolate from general)."""
    await _check_limit(request, multiplier=1.0, custom_key_suffix="auth")


async def rate_limit_websocket(request: Request) -> None:
    """WebSocket connection rate limit."""
    await _check_limit(
        request,
        multiplier=1.0,
        custom_key_suffix="ws",
        limit_override=settings.rate_limit_websocket_cpm,
    )
