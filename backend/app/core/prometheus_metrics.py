# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Prometheus metrics registry and helpers for NukeLab.

Metrics are registered eagerly at import time so that /api/metrics always
exposes valid metric descriptors, even before the first sample is recorded.
The registry is global; in single-process Uvicorn this is sufficient.
For future Gunicorn deployments, set PROMETHEUS_MULTIPROC_DIR and use
prometheus_client.multiprocess.MultiProcessCollector.
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)
from sqlalchemy import func, select

from app.config import settings

REGISTRY = CollectorRegistry(auto_describe=True)
# Expose per-process resource metrics (memory, CPU seconds, etc.) on the
# custom registry used by the /api/metrics endpoint.
ProcessCollector(registry=REGISTRY)
PlatformCollector(registry=REGISTRY)


def _metric_name(name: str) -> str:
    """Prefix all metrics with nukelab_ for easy identification."""
    return f"nukelab_{name}"


# ---------------------------------------------------------------------------
# Application metrics (registered eagerly)
# ---------------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    _metric_name("http_requests_total"),
    "Total HTTP requests",
    ["method", "path", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    _metric_name("http_request_duration_seconds"),
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=[
        0.005,
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        7.5,
        10.0,
        30.0,
        60.0,
    ],
    registry=REGISTRY,
)

ACTIVE_WEBSOCKET_CONNECTIONS = Gauge(
    _metric_name("active_websocket_connections"),
    "Number of active WebSocket connections",
    registry=REGISTRY,
)

REDIS_CACHE_HITS_TOTAL = Counter(
    _metric_name("redis_cache_hits_total"),
    "Total Redis cache hits",
    registry=REGISTRY,
)

REDIS_CACHE_MISSES_TOTAL = Counter(
    _metric_name("redis_cache_misses_total"),
    "Total Redis cache misses",
    registry=REGISTRY,
)

SERVERS_TOTAL = Gauge(
    _metric_name("servers_total"),
    "Total number of servers by status",
    ["status"],
    registry=REGISTRY,
)

CONTAINER_STATUS_LOOKUP_FAILURES_TOTAL = Counter(
    _metric_name("container_status_lookup_failures_total"),
    "Total container runtime status lookup failures",
    ["reason"],
    registry=REGISTRY,
)

USERS_TOTAL = Gauge(
    _metric_name("users_total"),
    "Total number of users",
    registry=REGISTRY,
)

NUKE_BALANCE_TOTAL = Gauge(
    _metric_name("nuke_balance_total"),
    "Total NUKE currency balance across all users",
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Recording helpers (settings-gated)
# ---------------------------------------------------------------------------


def record_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    """Record a completed HTTP request in Prometheus."""
    if not settings.prometheus_enabled:
        return

    HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status_code=str(status_code)).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path).observe(duration_seconds)


def increment_redis_cache_hit() -> None:
    if settings.prometheus_enabled:
        REDIS_CACHE_HITS_TOTAL.inc()


def increment_redis_cache_miss() -> None:
    if settings.prometheus_enabled:
        REDIS_CACHE_MISSES_TOTAL.inc()


def set_active_websocket_connections(count: int) -> None:
    if settings.prometheus_enabled:
        ACTIVE_WEBSOCKET_CONNECTIONS.set(count)


def set_servers_total(status: str, count: int) -> None:
    if settings.prometheus_enabled:
        SERVERS_TOTAL.labels(status=status).set(count)


def set_users_total(count: int) -> None:
    if settings.prometheus_enabled:
        USERS_TOTAL.set(count)


def set_nuke_balance_total(balance: int) -> None:
    if settings.prometheus_enabled:
        NUKE_BALANCE_TOTAL.set(balance)


async def refresh_business_metrics() -> None:
    """Refresh user/server/NUKE gauges from the database on each scrape.

    These gauges are cheap to recalculate (small tables) and doing it here
    keeps the dashboard accurate without a separate background task.
    """
    if not settings.prometheus_enabled:
        return

    from app.db.session import AsyncSessionLocal
    from app.models.server import Server
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0

        nuke_sum = (
            await db.execute(select(func.coalesce(func.sum(User.nuke_balance), 0)))
        ).scalar() or 0

        server_rows = (
            await db.execute(select(Server.status, func.count()).group_by(Server.status))
        ).all()

    set_users_total(user_count)
    set_nuke_balance_total(nuke_sum)
    for status, count in server_rows:
        set_servers_total(status, count)


async def get_metrics_output() -> tuple[bytes, str]:
    """Return (data, content_type) for the /api/metrics endpoint."""
    await refresh_business_metrics()
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
