"""Redis-backed caching utility.

Provides a compact, fast serialization layer over Redis for caching
expensive-to-compute data (server lists, aggregated metrics, etc.).

All keys are automatically prefixed with ``nukelab:cache:`` to avoid
collisions with other Redis usage (pub/sub, rate limiting, Celery).

Design decisions:
- **msgpack**: More compact and faster than JSON; no ``default=str`` footgun.
- **Fail-safe**: Redis errors are logged and treated as cache misses;
  the caller falls back to the primary data source.
- **Circuit breaker**: Skips Redis entirely after repeated failures to
  avoid hammering a degraded instance and adding latency to every request.
- **Stampede protection**: ``cache_get_or_set`` uses a short-lived Redis
  lock so only one coroutine rebuilds the cache when it expires.
- **SET-based invalidation**: Track related keys in a Redis SET for
  O(M) deletion instead of O(N) SCAN.
"""

import asyncio
import base64
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from app.core.redis_client import get_redis_client

try:
    import msgpack
    _USE_MSGPACK = True
except ImportError:  # pragma: no cover
    import json
    _USE_MSGPACK = False

logger = logging.getLogger(__name__)

CACHE_PREFIX = "nukelab:cache"
LOCK_SUFFIX = ":lock"
DEFAULT_LOCK_TTL = 5  # seconds
STAMPEDE_RETRY_ATTEMPTS = 5
STAMPEDE_RETRY_DELAY = 0.1  # seconds

# Circuit breaker settings
_CIRCUIT_FAILURE_THRESHOLD = 5
_CIRCUIT_RECOVERY_TIMEOUT = 30  # seconds


def _full_key(key: str) -> str:
    return f"{CACHE_PREFIX}:{key}"


def _lock_key(key: str) -> str:
    return f"{CACHE_PREFIX}:{key}{LOCK_SUFFIX}"


def _serialize(value: Any) -> str:
    """Serialize a value to a string for Redis storage."""
    if _USE_MSGPACK:
        packed = msgpack.packb(value, use_bin_type=True)
        return base64.b64encode(packed).decode("ascii")
    return json.dumps(value, default=str)


def _deserialize(data: str) -> Any:
    """Deserialize a value from a Redis string."""
    if _USE_MSGPACK:
        packed = base64.b64decode(data)
        return msgpack.unpackb(packed, raw=False)
    return json.loads(data)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class _CacheCircuitBreaker:
    """Simple in-memory circuit breaker for Redis cache operations.

    States:
      * CLOSED  – normal operation, Redis calls allowed.
      * OPEN    – Redis is considered unhealthy; all calls short-circuited.
      * HALF_OPEN – after recovery timeout, one probe call is allowed.
    """

    def __init__(self, failure_threshold: int, recovery_timeout: float):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._last_failure_time = 0.0
        self._state = "closed"

    def record_success(self) -> None:
        if self._state != "closed":
            logger.info("Cache circuit breaker closed — Redis recovered")
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure_time = time.monotonic()
        if self._failures >= self.failure_threshold and self._state != "open":
            self._state = "open"
            logger.warning(
                "Cache circuit breaker OPENED after %d consecutive Redis failures",
                self._failures,
            )

    def can_execute(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.monotonic() - self._last_failure_time > self.recovery_timeout:
                logger.info("Cache circuit breaker entering half-open state")
                self._state = "half_open"
                return True
            return False
        # half_open — allow the probe call
        return True


_circuit_breaker = _CacheCircuitBreaker(
    failure_threshold=_CIRCUIT_FAILURE_THRESHOLD,
    recovery_timeout=_CIRCUIT_RECOVERY_TIMEOUT,
)


def _redis_call(func):
    """Decorator that applies circuit breaker and success/failure tracking."""

    async def wrapper(*args, **kwargs):
        if not _circuit_breaker.can_execute():
            return None  # Circuit open — treat as miss / no-op
        try:
            result = await func(*args, **kwargs)
            _circuit_breaker.record_success()
            return result
        except Exception as exc:
            _circuit_breaker.record_failure()
            raise exc

    return wrapper


# ---------------------------------------------------------------------------
# Low-level primitives (fail-safe)
# ---------------------------------------------------------------------------

async def cache_get(key: str) -> Optional[Any]:
    """Fetch a cached value by key.

    Returns ``None`` on cache miss, deserialization error, or Redis error.
    """
    if not _circuit_breaker.can_execute():
        return None

    try:
        client = get_redis_client()
        data = await client.get(_full_key(key))
        _circuit_breaker.record_success()
        if data is None:
            return None
        try:
            return _deserialize(data)
        except Exception:
            await client.delete(_full_key(key))
            return None
    except Exception as exc:
        _circuit_breaker.record_failure()
        logger.warning("cache_get failed for key %r: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    """Store a value in the cache with a TTL (seconds).

    Redis errors are logged and ignored.
    """
    if not _circuit_breaker.can_execute():
        return

    try:
        client = get_redis_client()
        await client.set(_full_key(key), _serialize(value), ex=ttl)
        _circuit_breaker.record_success()
    except Exception as exc:
        _circuit_breaker.record_failure()
        logger.warning("cache_set failed for key %r: %s", key, exc)


async def cache_delete(key: str) -> None:
    """Delete a single cache key. Errors are logged and ignored."""
    if not _circuit_breaker.can_execute():
        return

    try:
        client = get_redis_client()
        await client.delete(_full_key(key))
        _circuit_breaker.record_success()
    except Exception as exc:
        _circuit_breaker.record_failure()
        logger.warning("cache_delete failed for key %r: %s", key, exc)


async def cache_delete_multi(keys: list[str]) -> int:
    """Delete multiple cache keys in one round-trip.

    Returns the number of keys deleted. Errors are logged and ignored.
    """
    if not keys:
        return 0
    if not _circuit_breaker.can_execute():
        return 0

    try:
        client = get_redis_client()
        full_keys = [_full_key(k) for k in keys]
        result = await client.delete(*full_keys)
        _circuit_breaker.record_success()
        return result
    except Exception as exc:
        _circuit_breaker.record_failure()
        logger.warning("cache_delete_multi failed for %d keys: %s", len(keys), exc)
        return 0


async def cache_delete_pattern(pattern: str) -> int:
    """Delete all cache keys matching a glob pattern.

    Uses ``SCAN`` — prefer :func:`cache_delete_tracked` for hot paths.
    Returns the number of keys deleted.
    """
    if not _circuit_breaker.can_execute():
        return 0

    try:
        client = get_redis_client()
        full_pattern = _full_key(pattern)
        keys: list[str] = []
        async for key in client.scan_iter(match=full_pattern):
            keys.append(key)
        if keys:
            await client.delete(*keys)
        _circuit_breaker.record_success()
        return len(keys)
    except Exception as exc:
        _circuit_breaker.record_failure()
        logger.warning("cache_delete_pattern failed for pattern %r: %s", pattern, exc)
        return 0


# ---------------------------------------------------------------------------
# Stampede-protected get-or-set
# ---------------------------------------------------------------------------

async def cache_get_or_set(
    key: str,
    builder: Callable[[], Awaitable[Any]],
    ttl: int,
    lock_ttl: int = DEFAULT_LOCK_TTL,
) -> Any:
    """Get from cache, or build and store with stampede protection.

    Uses a Redis lock so only one coroutine rebuilds the value when the
    cache expires. Other waiters poll the cache briefly and fall back to
    calling ``builder`` directly if the lock holder is slow.

    Args:
        key: Cache key (without prefix).
        builder: Async callable that produces the value to cache.
        ttl: Time-to-live in seconds.
        lock_ttl: Lock expiration in seconds (must exceed builder runtime).

    Returns:
        The cached or freshly-built value.
    """
    # Fast path — cache hit
    cached = await cache_get(key)
    if cached is not None:
        return cached

    # Try to acquire rebuild lock (skip if circuit is open)
    acquired = False
    if _circuit_breaker.can_execute():
        try:
            client = get_redis_client()
            acquired = await client.set(_lock_key(key), "1", nx=True, ex=lock_ttl)
            _circuit_breaker.record_success()
        except Exception as exc:
            _circuit_breaker.record_failure()
            logger.warning("cache_get_or_set lock acquisition failed for %r: %s", key, exc)
            acquired = False

    if acquired:
        # We won the race — build, cache, release lock
        try:
            value = await builder()
            await cache_set(key, value, ttl)
            return value
        finally:
            try:
                client = get_redis_client()
                await client.delete(_lock_key(key))
            except Exception as exc:
                logger.warning("cache_get_or_set lock release failed for %r: %s", key, exc)

    # Lost the race — poll cache briefly, then build without caching
    for _ in range(STAMPEDE_RETRY_ATTEMPTS):
        await asyncio.sleep(STAMPEDE_RETRY_DELAY)
        cached = await cache_get(key)
        if cached is not None:
            return cached

    logger.debug("cache_get_or_set falling back to uncached build for %r", key)
    return await builder()


# ---------------------------------------------------------------------------
# SET-based invalidation (O(M) instead of O(N) SCAN)
# ---------------------------------------------------------------------------

async def cache_track_key(track_set_key: str, member_key: str) -> None:
    """Add a cache key to a Redis SET for bulk invalidation.

    Args:
        track_set_key: The SET key (without prefix) that tracks members.
        member_key: The cache key (without prefix) to track.
    """
    if not _circuit_breaker.can_execute():
        return

    try:
        client = get_redis_client()
        await client.sadd(_full_key(track_set_key), member_key)
        _circuit_breaker.record_success()
    except Exception as exc:
        _circuit_breaker.record_failure()
        logger.warning("cache_track_key failed for set %r member %r: %s", track_set_key, member_key, exc)


async def cache_delete_tracked(track_set_key: str) -> int:
    """Delete all keys tracked in a Redis SET, plus the SET itself.

    Returns the number of member keys deleted.
    """
    if not _circuit_breaker.can_execute():
        return 0

    full_set_key = _full_key(track_set_key)
    try:
        client = get_redis_client()
        members = await client.smembers(full_set_key)
        if members:
            member_list = list(members)
            full_member_keys = [_full_key(m) for m in member_list]
            await client.delete(*full_member_keys)
            count = len(member_list)
        else:
            count = 0
        await client.delete(full_set_key)
        _circuit_breaker.record_success()
        return count
    except Exception as exc:
        _circuit_breaker.record_failure()
        logger.warning("cache_delete_tracked failed for set %r: %s", track_set_key, exc)
        return 0
