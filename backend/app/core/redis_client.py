"""Shared async Redis client singleton.

Replaces the ad-hoc ``redis.from_url()`` pattern scattered across the codebase
with a single connection-pooled instance that all modules can import.
"""

import redis.asyncio as redis
from app.config import settings

_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Return the shared async Redis client, creating it on first call.

    The client is configured with ``decode_responses=True`` so that string
    values (JSON payloads, cache entries, etc.) round-trip without manual
    encoding/decoding.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


async def close_redis_client() -> None:
    """Close the shared Redis client and clear the singleton reference.

    Called during graceful shutdown to release connections cleanly.
    Idempotent — safe to call multiple times.
    """
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
