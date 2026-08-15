# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Lightweight storage metrics helpers for the admin dashboard.

Postgres database size and Redis memory are queried directly from the
services. Detailed charts, history, and alerting live in Prometheus/Grafana;
these helpers are only for quick at-a-glance summaries.
"""

import contextlib
import logging
from typing import Any

import redis.asyncio as redis
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)


async def get_postgres_database_size(db: AsyncSession) -> dict[str, Any]:
    """Return the size of the current Postgres database in bytes."""
    try:
        result = await db.execute(sa_text("SELECT pg_database_size(current_database())"))
        size_bytes = result.scalar() or 0
        return {
            "status": "healthy",
            "size_bytes": size_bytes,
        }
    except Exception as exc:
        logger.warning("Failed to collect Postgres database size: %s", exc)
        return {"status": "unhealthy", "error": str(exc), "size_bytes": 0}


async def get_redis_memory() -> dict[str, Any]:
    """Return Redis memory usage and maxmemory limit in bytes."""
    client: redis.Redis | None = None
    try:
        client = redis.from_url(settings.redis_url)
        info = await client.info("memory")
        await client.aclose()
        used_memory = info.get("used_memory", 0)
        maxmemory = info.get("maxmemory", 0)
        return {
            "status": "healthy",
            "used_bytes": used_memory,
            "max_bytes": maxmemory,
            "percent": (used_memory / maxmemory * 100) if maxmemory else None,
        }
    except Exception as exc:
        if client:
            with contextlib.suppress(Exception):
                await client.aclose()
        logger.warning("Failed to collect Redis memory: %s", exc)
        return {"status": "unhealthy", "error": str(exc), "used_bytes": 0, "max_bytes": 0}
