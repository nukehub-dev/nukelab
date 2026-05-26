"""IP allowlist/blocklist middleware.

Runs before MaintenanceMiddleware so bad IPs are rejected at the edge.
Uses an in-memory TTL cache to avoid hitting the database on every request.

Logic:
  1. Extract client IP (proxy-aware, same logic as RateLimitMiddleware).
  2. Check exempt paths (health, auth, docs, openapi, ws).
  3. Query active restrictions from DB (cached for 30s).
  4. If active allowlist entries exist:
       - IP must match at least one allow entry → permit
       - Otherwise → 403 Forbidden
  5. Else (no allowlist):
       - IP must NOT match any block entry → permit
       - Otherwise → 403 Forbidden
  6. Blocked attempts are logged to ActivityLog.
  7. DB errors fail-open (permit traffic, log warning).
"""

import ipaddress
import logging
import time
from typing import Optional, List

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Exempt paths — never blocked by IP restrictions
_EXEMPT_PATHS = {
    "/api/health",
    "/health",
    "/api/docs",
    "/api/openapi.json",
    "/api/ws",
    "/ws",
}

_EXEMPT_PREFIXES = {
    "/api/auth",
    "/api/admin/ip-restrictions",
}

# In-memory cache: (restrictions_list, timestamp)
_cache: Optional[tuple] = None
_CACHE_TTL_SECONDS = 30


def _get_client_ip(request: Request) -> str:
    """Extract real client IP with X-Forwarded-For validation."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For: client, proxy1, proxy2
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real_ip = request.headers.get("X-Real-Ip")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"


def _ip_matches(client_ip: str, pattern: str) -> bool:
    """Check if a client IP matches a CIDR range or single IP."""
    try:
        client = ipaddress.ip_address(client_ip)
        network = ipaddress.ip_network(pattern, strict=False)
        return client in network
    except ValueError:
        return False


async def _get_restrictions() -> List[dict]:
    """Fetch active IP restrictions from DB with caching."""
    global _cache

    if _cache is not None:
        entries, cached_at = _cache
        if time.time() - cached_at < _CACHE_TTL_SECONDS:
            return entries

    try:
        from app.models.ip_restriction import IPRestriction

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                __import__("sqlalchemy", fromlist=["select"]).select(IPRestriction).where(
                    IPRestriction.is_active == True
                )
            )
            entries = [
                {
                    "id": str(r.id),
                    "ip_range": r.ip_range,
                    "restriction_type": r.restriction_type,
                }
                for r in result.scalars().all()
            ]
            _cache = (entries, time.time())
            return entries
    except Exception as exc:
        logger.warning(f"IP restriction DB query failed, failing open: {exc}")
        return []


def _invalidate_cache():
    """Invalidate the in-memory restriction cache."""
    global _cache
    _cache = None


class IPRestrictionMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces IP-based allowlist/blocklist rules."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Always allow exempt paths
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        client_ip = _get_client_ip(request)
        restrictions = await _get_restrictions()

        if not restrictions:
            return await call_next(request)

        allowlist = [r for r in restrictions if r["restriction_type"] == "allow"]
        blocklist = [r for r in restrictions if r["restriction_type"] == "block"]

        # Mode 1: Allowlist exists — restrictive mode
        if allowlist:
            matched = any(_ip_matches(client_ip, r["ip_range"]) for r in allowlist)
            if matched:
                return await call_next(request)
            await _log_blocked(request, client_ip, "allowlist_miss")
            return _forbidden_response("Access denied: IP not in allowlist")

        # Mode 2: Blocklist only
        matched = any(_ip_matches(client_ip, r["ip_range"]) for r in blocklist)
        if matched:
            await _log_blocked(request, client_ip, "blocklist_match")
            return _forbidden_response("Access denied: IP blocked")

        return await call_next(request)


def _forbidden_response(detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=403,
        content={"detail": detail, "status": "forbidden"},
    )


async def _log_blocked(request: Request, client_ip: str, reason: str):
    """Log a blocked IP attempt to ActivityLog."""
    try:
        from app.models.activity_log import ActivityLog
        from app.db.session import AsyncSessionLocal
        import uuid as uuid_mod

        async with AsyncSessionLocal() as db:
            log = ActivityLog(
                id=uuid_mod.uuid4(),
                action="ip_blocked",
                target_type="ip_restriction",
                target_id=None,
                details={
                    "path": request.url.path,
                    "method": request.method,
                    "reason": reason,
                    "ip": client_ip,
                },
                ip_address=client_ip if client_ip != "unknown" else None,
                user_agent=request.headers.get("User-Agent"),
            )
            db.add(log)
            await db.commit()
    except Exception as exc:
        logger.warning(f"Failed to log blocked IP attempt: {exc}")
