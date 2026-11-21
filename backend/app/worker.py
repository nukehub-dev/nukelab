# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import asyncio
import concurrent.futures
import os
import threading
from dataclasses import dataclass

from celery import Celery, Task
from celery.schedules import crontab
from celery.signals import (
    before_task_publish,
    task_postrun,
    task_prerun,
    worker_ready,
    worker_shutdown,
)
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.context import correlation_id
from app.core.logging import get_logger
from app.core.sentry import init_sentry
from app.core.tracing import init_tracing
from app.db.schema_guard import SchemaCompatibilityResult, check_schema_compatibility
from app.services.worker_heartbeat import (
    start_celery_worker_heartbeat,
    stop_celery_worker_heartbeat,
)

logger = get_logger(__name__)

# Tables and columns the recovery journal needs before this image may consume
# journal work. A missing relation means a partially-applied or old schema.
_JOURNAL_RELATIONS: dict[str, frozenset[str]] = {
    "worker_heartbeats": frozenset({"executor_id", "state", "heartbeat_at", "schema_version"}),
    "server_launch_operations": frozenset({"executor_id", "heartbeat_at"}),
    "volume_backups": frozenset({"executor_id", "heartbeat_at"}),
    "volume_restores": frozenset({"executor_id", "heartbeat_at"}),
}

_journal_schema_state: bool | None = None
_journal_schema_lock = threading.Lock()
_initial_reconciliation_scheduled = False


class JournalSchemaIncompatible(RuntimeError):
    """The database journal schema cannot be safely consumed by this image."""


@dataclass(frozen=True, slots=True)
class JournalSchemaResult:
    """Outcome of the worker startup journal-schema handshake."""

    ok: bool
    db_unreachable: bool = False
    unknown_revisions: tuple[str, ...] = ()
    missing_relations: tuple[str, ...] = ()


def _alembic_script_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic")


def _create_handshake_engine() -> AsyncEngine:
    """Create a loop-owned engine so the handshake never leaks a pooled loop."""
    connect_args: dict = {
        "command_timeout": settings.database_query_timeout_seconds,
    }
    if settings.pgbouncer_enabled:
        connect_args.update(statement_cache_size=0, prepared_statement_name_func=lambda: "")
    database_url = (
        settings.database_pgbouncer_url if settings.pgbouncer_enabled else settings.database_url
    )
    return create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args=connect_args,
        echo=settings.database_echo,
    )


async def _missing_journal_relations(engine: AsyncEngine) -> tuple[str, ...]:
    """Return missing tables/columns using the live catalog, not a revision list."""

    def inspect_relations(connection) -> tuple[str, ...]:
        inspector = sqlalchemy_inspect(connection)
        tables = set(inspector.get_table_names())
        missing: list[str] = []
        for table, required in _JOURNAL_RELATIONS.items():
            if table not in tables:
                missing.append(table)
                continue
            present = {column["name"] for column in inspector.get_columns(table)}
            missing.extend(
                f"{table}.{column}" for column in sorted(required) if column not in present
            )
        return tuple(missing)

    async with engine.connect() as connection:
        return await connection.run_sync(inspect_relations)


async def check_journal_schema(
    engine: AsyncEngine | None = None,
    script_dir_path: str | os.PathLike[str] | None = None,
) -> JournalSchemaResult:
    """Check both the Alembic revision and the live recovery-journal shape.

    The Alembic revision detects a database newer than this image. The catalog
    check detects a missing ``worker_heartbeats`` table or executor/heartbeat
    columns, which an old worker would silently treat as ordinary rows.
    """
    owns_engine = engine is None
    if owns_engine:
        engine = _create_handshake_engine()
    try:
        missing: tuple[str, ...] = ()
        inspection_failed = False
        try:
            missing = await _missing_journal_relations(engine)
        except Exception:
            inspection_failed = True

        compatibility: SchemaCompatibilityResult = await check_schema_compatibility(
            engine, script_dir_path or _alembic_script_dir()
        )
        if inspection_failed:
            # Do not cache a ready state when the live catalog could not be read.
            return JournalSchemaResult(
                ok=compatibility.ok,
                db_unreachable=compatibility.ok,
                unknown_revisions=compatibility.unknown_revisions,
            )
        if compatibility.db_unreachable:
            # A fresh/unmanaged database has no alembic_version table. The live
            # catalog result is still authoritative when it could be read.
            return JournalSchemaResult(
                ok=not missing,
                unknown_revisions=compatibility.unknown_revisions,
                missing_relations=missing,
            )

        return JournalSchemaResult(
            ok=compatibility.ok and not missing,
            unknown_revisions=compatibility.unknown_revisions,
            missing_relations=missing,
        )
    finally:
        if owns_engine:
            await engine.dispose()


def _run_coroutine_sync(awaitable):
    """Run the handshake from the synchronous ``worker_ready`` callback."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, awaitable).result()


def run_journal_schema_handshake() -> JournalSchemaResult:
    """Run the journal schema handshake in this process."""
    return _run_coroutine_sync(check_journal_schema())


def ensure_journal_schema() -> bool:
    """Return whether recovery journal work may be consumed.

    A blocked result is re-checked on the next call so a worker can recover
    from a transient missing relation once migrations finish. A database
    outage never becomes a new startup failure mode; the scan itself will
    fail and retry on a later beat.
    """
    global _journal_schema_state
    with _journal_schema_lock:
        if _journal_schema_state is True:
            return True
        try:
            result = run_journal_schema_handshake()
        except Exception as exc:
            logger.warning(
                "Worker journal schema handshake could not run (%s); deferring",
                type(exc).__name__,
            )
            return True
        if result.db_unreachable:
            logger.warning(
                "Worker journal schema handshake could not reach the database; deferring"
            )
            return True
        if result.ok:
            _journal_schema_state = True
            return True
        already_reported = _journal_schema_state is False
        _journal_schema_state = False
        if not already_reported:
            logger.critical(
                "Worker journal schema is incompatible with this image; refusing journal work",
                extra={
                    "unknown_db_revisions": list(result.unknown_revisions),
                    "missing_journal_relations": list(result.missing_relations),
                },
            )
        return False


def schedule_initial_reconciliation() -> bool:
    """Enqueue one delayed pass after a real worker executor registers.

    The process-local guard prevents repeated readiness callbacks from
    enqueueing duplicate initial passes. The durable journal makes the task
    idempotent even if the guard is lost with the process.
    """
    global _initial_reconciliation_scheduled
    if _initial_reconciliation_scheduled:
        return False
    _initial_reconciliation_scheduled = True
    try:
        from app.tasks import reconcile_operations

        reconcile_operations.apply_async(
            countdown=settings.recovery_initial_delay_seconds,
            kwargs={"jitter": False},
        )
    except Exception as exc:
        logger.warning(
            "Initial operation reconciliation pass could not be scheduled (%s); "
            "the beat schedule will retry",
            type(exc).__name__,
        )
    return True


# Initialize Sentry and OpenTelemetry for Celery workers (both idempotent)
init_sentry()
if init_tracing():
    CeleryInstrumentor().instrument()


def _get_cid_from_headers(headers: dict) -> str:
    """Extract correlation_id from Celery message headers."""
    if not headers:
        return ""
    # Check nested headers structure
    hdrs = headers.get("headers", {}) or {}
    return hdrs.get("correlation_id", "")


@before_task_publish.connect
def inject_correlation_id(headers=None, body=None, **kwargs):
    """Inject current correlation_id into Celery message headers before publish."""
    if headers is not None:
        hdrs = headers.setdefault("headers", {})
        hdrs["correlation_id"] = correlation_id.get("")


@task_prerun.connect
def set_correlation_id(task_id=None, task=None, kwargs=None, **rest):
    """Restore correlation_id from headers when task starts."""
    if task is None:
        return
    # task.request.headers may be None or a dict
    req_headers = getattr(task.request, "headers", None) or {}
    cid = req_headers.get("correlation_id", "")
    if cid:
        correlation_id.set(cid)
        logger.debug(
            "Correlation ID restored for task", extra={"correlation_id": cid, "task_id": task_id}
        )


@task_postrun.connect
def clear_correlation_id(task_id=None, task=None, **rest):
    """Clear correlation_id after task completes."""
    correlation_id.set("")


@worker_ready.connect
def start_worker_heartbeat(sender=None, **kwargs):
    """Register the executor, verify the journal schema, and seed one scan."""
    heartbeat = None
    try:
        heartbeat = start_celery_worker_heartbeat()
    except Exception as exc:
        logger.warning("Failed to start worker heartbeat: %s", type(exc).__name__)

    if not ensure_journal_schema():
        logger.critical("Worker readiness failed: incompatible recovery journal schema")
        raise JournalSchemaIncompatible(
            "Refusing recovery journal work: the database schema is incompatible "
            "with this worker image"
        )

    # Tests and partially-wired bootstraps may replace the heartbeat starter.
    # Only schedule after a real process lifetime registered.
    if heartbeat is None:
        return
    schedule_initial_reconciliation()


@worker_shutdown.connect
def stop_worker_heartbeat(sender=None, **kwargs):
    """Write the graceful stopped marker after in-flight tasks have drained."""
    stop_celery_worker_heartbeat()


class ContextTask(Task):
    """Custom Celery task base that propagates correlation IDs."""

    def apply_async(
        self,
        args=None,
        kwargs=None,
        task_id=None,
        producer=None,
        link=None,
        link_error=None,
        shadow=None,
        **options,
    ):
        # Ensure headers exist
        headers = options.setdefault("headers", {})
        headers.setdefault("correlation_id", correlation_id.get(""))
        return super().apply_async(
            args=args,
            kwargs=kwargs,
            task_id=task_id,
            producer=producer,
            link=link,
            link_error=link_error,
            shadow=shadow,
            **options,
        )

    def delay(self, *args, **kwargs):
        # delay() wraps apply_async; our apply_async handles headers
        return super().delay(*args, **kwargs)


celery_app = Celery(
    "nukelab",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
    task_cls=ContextTask,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    worker_prefetch_multiplier=1,
    worker_pool="threads",
    worker_concurrency=4,
    beat_schedule={
        "dispatch-volume-recovery": {
            "task": "app.tasks.dispatch_volume_recovery",
            "schedule": 30.0,
        },
        "reconcile-operations": {
            "task": "app.tasks.reconcile_operations",
            "schedule": float(settings.recovery_scan_interval_seconds),
        },
        "collect-container-metrics": {
            "task": "app.tasks.collect_container_metrics",
            "schedule": 5.0,  # Every 5 seconds
        },
        "collect-system-metrics": {
            "task": "app.tasks.collect_system_metrics",
            "schedule": 60.0,  # Every 60 seconds
        },
        "check-container-health": {
            "task": "app.tasks.check_container_health",
            "schedule": 30.0,  # Every 30 seconds
        },
        "evaluate-alert-rules": {
            "task": "app.tasks.evaluate_alert_rules",
            "schedule": 60.0,  # Every 60 seconds
        },
        "process-nuke-billing": {
            "task": "app.tasks.process_nuke_billing",
            "schedule": 900.0,  # Every 15 minutes
        },
        "enforce-auto-stop": {
            "task": "app.tasks.enforce_auto_stop",
            "schedule": 60.0,  # Every 60 seconds
        },
        "shutdown-idle-servers": {
            "task": "app.tasks.shutdown_idle_servers",
            "schedule": 300.0,  # Every 5 minutes
        },
        "process-server-queue": {
            "task": "app.tasks.process_server_queue",
            "schedule": float(settings.queue_tick_seconds),
        },
        "evaluate-schedules": {
            "task": "app.tasks.evaluate_schedules",
            "schedule": 60.0,  # Every 60 seconds
        },
        "evaluate-maintenance-windows": {
            "task": "app.tasks.evaluate_maintenance_windows",
            "schedule": 60.0,  # Every 60 seconds
        },
        "remind-stale-credit-requests": {
            "task": "app.tasks.remind_stale_credit_requests",
            "schedule": 3600.0,  # Hourly
        },
        "remind-recovery-required-operations": {
            "task": "app.tasks.remind_recovery_required_operations",
            "schedule": crontab(hour=8, minute=0),  # Daily at 08:00 UTC
        },
        "rollup-server-metrics": {
            "task": "app.tasks.rollup_server_metrics",
            "schedule": crontab(hour=3, minute=0),  # Daily at 3 AM
        },
        "cleanup-expired-data": {
            "task": "app.tasks.cleanup_expired_data",
            "schedule": crontab(hour=4, minute=0),  # Daily at 4 AM
        },
        "grant-daily-allowance": {
            "task": "app.tasks.grant_daily_allowance_to_all",
            "schedule": crontab(hour=0, minute=0),  # Daily at 00:00 UTC
        },
        "cleanup-expired-allowance-overrides": {
            "task": "app.tasks.cleanup_expired_allowance_overrides",
            "schedule": crontab(minute="*/60"),  # Hourly
        },
        "ensure-partitions": {
            "task": "app.tasks.ensure_partitions",
            "schedule": crontab(hour=0, minute=5),  # Daily at 00:05
        },
        "enforce-volume-quotas": {
            "task": "app.tasks.enforce_volume_quotas",
            "schedule": settings.volume_quota_check_interval_minutes * 60.0,
        },
        "check-autovacuum-health": {
            "task": "app.tasks.check_autovacuum_health",
            "schedule": crontab(day_of_week=0, hour=6, minute=0),  # Weekly Sunday 6 AM
        },
        "update-prometheus-business-metrics": {
            "task": "app.tasks.update_prometheus_business_metrics",
            "schedule": 60.0,  # Every 60 seconds
        },
    },
)

# Discover tasks automatically
celery_app.autodiscover_tasks()
