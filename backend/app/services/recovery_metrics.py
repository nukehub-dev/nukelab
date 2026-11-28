# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded recovery and operations metrics for Prometheus.

Every label set here is fixed and small: worker freshness, operation kind,
registry policy, and recovery-scan report counters. User IDs, operation IDs,
server IDs, and image references never become labels.

The collector reads durable rows only. A database failure belongs to the
caller; this module never changes recovery decisions and never releases work.
Scan duration/counters are recorded by the reconciler after a completed pass so
the periodic metrics task cannot overwrite them with placeholder values.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from prometheus_client import Gauge
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.core.prometheus_metrics import REGISTRY
from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.system_setting import SystemSetting
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.models.worker_heartbeat import WorkerHeartbeat

if TYPE_CHECKING:
    from app.services.operation_reconciler import ReconcileReport

logger = get_logger(__name__)

_WORKER_STATES = ("fresh", "stale", "stopped")
_OPERATION_KINDS = ("launch", "backup", "restore")
_POLICY_VALUES = ("off", "prefer", "require")
_SCAN_REPORT_RESULTS = ("scanned", "finalized", "deferred", "errors")


def _gauge(
    name: str,
    documentation: str,
    labelnames: tuple[str, ...] = (),
) -> Gauge:
    """Register a gauge once, even if the module is reloaded in the process."""
    try:
        return Gauge(name, documentation, labelnames, registry=REGISTRY)
    except ValueError:
        # Reloads and repeated imports hit the already-registered collector.
        existing = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
        if existing is None:
            raise
        return existing


WORKERS_REGISTERED = _gauge(
    "nukelab_workers_registered",
    "Process-lifetime executor rows in the worker heartbeat registry",
)

WORKER_HEARTBEATS = _gauge(
    "nukelab_worker_heartbeats",
    "Worker heartbeat rows by freshness state",
    ("state",),
)

WORKER_HEARTBEAT_AGE_SECONDS = _gauge(
    "nukelab_worker_heartbeat_age_seconds",
    "Age in seconds of the most recent worker heartbeat",
)

WORKER_LAST_HEARTBEAT_TIMESTAMP_SECONDS = _gauge(
    "nukelab_worker_last_heartbeat_timestamp_seconds",
    "Unix timestamp of the most recent worker heartbeat",
)

OPERATIONS_ACTIVE = _gauge(
    "nukelab_operations_active",
    "Active launch, backup, and restore journal rows by kind",
    ("kind",),
)

OPERATIONS_RECOVERY_REQUIRED = _gauge(
    "nukelab_operations_recovery_required",
    "Active journal rows that require operator recovery, by kind",
    ("kind",),
)

OPERATIONS_STALLED = _gauge(
    "nukelab_operations_stalled",
    "Active journal rows whose operation heartbeat exceeded the stale threshold",
    ("kind",),
)

BATCH_JOBS_QUEUED = _gauge(
    "nukelab_batch_jobs_queued",
    "Queued batch jobs waiting for admission",
)

BATCH_JOBS_ACTIVE = _gauge(
    "nukelab_batch_jobs_active",
    "Batch jobs in starting, running or cancelling state",
)

BATCH_JOBS_RECOVERY_REQUIRED = _gauge(
    "nukelab_batch_jobs_recovery_required",
    "Batch jobs whose runtime outcome requires operator inspection",
)

BATCH_JOBS_CLEANUP_PENDING = _gauge(
    "nukelab_batch_jobs_cleanup_pending",
    "Terminal batch jobs whose container removal is still pending",
)

RECOVERY_SCAN_LAST_SUCCESS_TIMESTAMP_SECONDS = _gauge(
    "nukelab_recovery_scan_last_success_timestamp_seconds",
    "Unix timestamp of the last recovery scan pass without errors",
)

RECOVERY_SCAN_DURATION_SECONDS = _gauge(
    "nukelab_recovery_scan_duration_seconds",
    "Duration in seconds of the most recent recovery scan pass",
)

RECOVERY_SCAN_LAST_REPORT = _gauge(
    "nukelab_recovery_scan_last_report",
    "Counters from the most recent recovery scan pass",
    ("result",),
)

REGISTRY_VERIFICATION_POLICY = _gauge(
    "nukelab_registry_verification_policy",
    "Configured registry verification policy (1 for the active policy)",
    ("policy",),
)

REGISTRY_LOCAL_ONLY_REVISIONS = _gauge(
    "nukelab_registry_local_only_revisions",
    "Non-revoked environment revisions without a portable registry identity",
)

REGISTRY_TEMPLATES_WITHOUT_VERIFIED_REVISION = _gauge(
    "nukelab_registry_templates_without_verified_revision",
    "Active environment templates with no non-revoked registry-verified revision",
)


@dataclass(frozen=True, slots=True)
class WorkerMetrics:
    total: int
    fresh: int
    stale: int
    stopped: int
    heartbeat_age_seconds: float
    last_heartbeat_timestamp: float


@dataclass(frozen=True, slots=True)
class OperationMetrics:
    kind: str
    active: int
    recovery_required: int
    stalled: int


@dataclass(frozen=True, slots=True)
class RegistryMetrics:
    policy: str
    local_only_revisions: int
    templates_without_verified_revision: int


@dataclass(frozen=True, slots=True)
class BatchJobMetrics:
    queued: int
    active: int
    recovery_required: int
    cleanup_pending: int


@dataclass(frozen=True, slots=True)
class RecoveryMetricsSnapshot:
    workers: WorkerMetrics
    operations: tuple[OperationMetrics, ...]
    registry: RegistryMetrics
    jobs: BatchJobMetrics | None = None


_OPERATION_SPECS = (
    (
        "launch",
        ServerLaunchOperation,
        ServerLaunchOperation.state,
        ("prepared", "executing", "uncertain"),
        ("uncertain",),
    ),
    (
        "backup",
        VolumeBackup,
        VolumeBackup.status,
        ("pending", "in_progress", "recovery_required"),
        ("recovery_required",),
    ),
    (
        "restore",
        VolumeRestore,
        VolumeRestore.status,
        ("pending", "in_progress", "recovery_required"),
        ("recovery_required",),
    ),
)


async def collect_recovery_metrics(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> RecoveryMetricsSnapshot:
    """Read bounded recovery/operations state from durable rows."""
    moment = now or utc_now()
    workers = await _collect_workers(session, moment)
    operations = tuple(
        [await _collect_operations(session, spec, moment) for spec in _OPERATION_SPECS]
    )
    registry = await _collect_registry(session)
    jobs = await _collect_jobs(session)
    return RecoveryMetricsSnapshot(
        workers=workers,
        operations=operations,
        registry=registry,
        jobs=jobs,
    )


async def _collect_workers(session: AsyncSession, now: datetime) -> WorkerMetrics:
    rows = (
        await session.execute(select(WorkerHeartbeat.state, WorkerHeartbeat.heartbeat_at))
    ).all()
    cutoff = now - timedelta(seconds=settings.worker_heartbeat_stale_seconds)

    fresh = 0
    stopped = 0
    latest: datetime | None = None
    for state, heartbeat_at in rows:
        if heartbeat_at is not None and (latest is None or heartbeat_at > latest):
            latest = heartbeat_at
        if state == "stopped":
            stopped += 1
        elif heartbeat_at is not None and heartbeat_at >= cutoff:
            fresh += 1

    total = len(rows)
    age = 0.0 if latest is None else max(0.0, (now - latest).total_seconds())
    return WorkerMetrics(
        total=total,
        fresh=fresh,
        stale=max(0, total - fresh - stopped),
        stopped=stopped,
        heartbeat_age_seconds=round(age, 3),
        last_heartbeat_timestamp=0.0 if latest is None else _timestamp(latest),
    )


async def _collect_operations(
    session: AsyncSession,
    spec: tuple[str, Any, Any, tuple[str, ...], tuple[str, ...]],
    now: datetime,
) -> OperationMetrics:
    kind, model, state_column, active_states, recovery_states = spec
    active = (
        await session.scalar(
            select(func.count()).select_from(model).where(state_column.in_(active_states))
        )
        or 0
    )
    recovery_required = (
        await session.scalar(
            select(func.count()).select_from(model).where(state_column.in_(recovery_states))
        )
        or 0
    )
    executing_states = tuple(state for state in active_states if state not in recovery_states)
    cutoff = now - timedelta(seconds=settings.operation_heartbeat_stale_seconds)
    stalled = (
        await session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                state_column.in_(executing_states),
                model.executor_id.is_not(None),
                model.heartbeat_at.is_not(None),
                model.heartbeat_at < cutoff,
            )
        )
        or 0
    )
    return OperationMetrics(
        kind=kind,
        active=int(active),
        recovery_required=int(recovery_required),
        stalled=int(stalled),
    )


async def _collect_jobs(session: AsyncSession) -> BatchJobMetrics:
    queued = (
        await session.scalar(
            select(func.count()).select_from(BatchJob).where(BatchJob.state == "queued")
        )
        or 0
    )
    active = (
        await session.scalar(
            select(func.count())
            .select_from(BatchJob)
            .where(BatchJob.state.in_(("starting", "running", "cancelling")))
        )
        or 0
    )
    recovery_required = (
        await session.scalar(
            select(func.count()).select_from(BatchJob).where(BatchJob.state == "recovery_required")
        )
        or 0
    )
    cleanup_pending = (
        await session.scalar(
            select(func.count())
            .select_from(BatchJob)
            .where(
                BatchJob.state.in_(("succeeded", "failed", "cancelled", "timed_out", "expired")),
                BatchJob.cleanup_state != "complete",
            )
        )
        or 0
    )
    return BatchJobMetrics(
        queued=int(queued),
        active=int(active),
        recovery_required=int(recovery_required),
        cleanup_pending=int(cleanup_pending),
    )


async def _collect_registry(session: AsyncSession) -> RegistryMetrics:
    local_only = (
        await session.scalar(
            select(func.count())
            .select_from(EnvironmentRevision)
            .where(
                EnvironmentRevision.revoked.is_(False),
                EnvironmentRevision.portable_fingerprint.is_(None),
            )
        )
        or 0
    )
    verified_revision = (
        select(EnvironmentRevision.id)
        .where(
            EnvironmentRevision.template_id == EnvironmentTemplate.id,
            EnvironmentRevision.revoked.is_(False),
            EnvironmentRevision.portable_fingerprint.is_not(None),
        )
        .exists()
    )
    without_verified = (
        await session.scalar(
            select(func.count())
            .select_from(EnvironmentTemplate)
            .where(
                EnvironmentTemplate.is_active.is_(True),
                ~verified_revision,
            )
        )
        or 0
    )
    return RegistryMetrics(
        policy=str(settings.registry_verification_policy),
        local_only_revisions=int(local_only),
        templates_without_verified_revision=int(without_verified),
    )


def publish_recovery_metrics(snapshot: RecoveryMetricsSnapshot) -> None:
    """Write one collected snapshot to the process metric registry."""
    WORKERS_REGISTERED.set(snapshot.workers.total)
    for state in _WORKER_STATES:
        WORKER_HEARTBEATS.labels(state=state).set(_worker_state_count(snapshot, state))
    WORKER_HEARTBEAT_AGE_SECONDS.set(snapshot.workers.heartbeat_age_seconds)
    WORKER_LAST_HEARTBEAT_TIMESTAMP_SECONDS.set(snapshot.workers.last_heartbeat_timestamp)

    by_kind = {metrics.kind: metrics for metrics in snapshot.operations}
    for kind in _OPERATION_KINDS:
        metrics = by_kind.get(kind)
        OPERATIONS_ACTIVE.labels(kind=kind).set(metrics.active if metrics else 0)
        OPERATIONS_RECOVERY_REQUIRED.labels(kind=kind).set(
            metrics.recovery_required if metrics else 0
        )
        OPERATIONS_STALLED.labels(kind=kind).set(metrics.stalled if metrics else 0)

    policy = snapshot.registry.policy
    for value in _POLICY_VALUES:
        REGISTRY_VERIFICATION_POLICY.labels(policy=value).set(1 if policy == value else 0)
    REGISTRY_LOCAL_ONLY_REVISIONS.set(snapshot.registry.local_only_revisions)
    REGISTRY_TEMPLATES_WITHOUT_VERIFIED_REVISION.set(
        snapshot.registry.templates_without_verified_revision
    )

    jobs = snapshot.jobs or BatchJobMetrics(
        queued=0,
        active=0,
        recovery_required=0,
        cleanup_pending=0,
    )
    BATCH_JOBS_QUEUED.set(jobs.queued)
    BATCH_JOBS_ACTIVE.set(jobs.active)
    BATCH_JOBS_RECOVERY_REQUIRED.set(jobs.recovery_required)
    BATCH_JOBS_CLEANUP_PENDING.set(jobs.cleanup_pending)


def record_recovery_scan(
    report: ReconcileReport,
    *,
    succeeded: bool | None = None,
    now: datetime | None = None,
) -> None:
    """Record one completed reconciliation pass without affecting the scan.

    A pass with selection/row errors is still reported, but it does not advance
    the last-success timestamp. Metric failures are logged by exception class
    and never propagate to the reconciler.
    """
    if not settings.prometheus_enabled:
        return
    try:
        if succeeded is None:
            succeeded = report.errors == 0
        if succeeded:
            RECOVERY_SCAN_LAST_SUCCESS_TIMESTAMP_SECONDS.set(_timestamp(now or utc_now()))
        RECOVERY_SCAN_DURATION_SECONDS.set(float(report.duration_seconds))
        for result in _SCAN_REPORT_RESULTS:
            RECOVERY_SCAN_LAST_REPORT.labels(result=result).set(int(getattr(report, result)))
    except Exception as exc:
        logger.warning(
            "Recovery scan metrics update failed",
            extra={"error_class": type(exc).__name__},
        )


SCAN_STATE_KEY = "recovery_scan_state"


async def persist_recovery_scan(
    session: AsyncSession,
    report: ReconcileReport,
    *,
    succeeded: bool | None = None,
) -> None:
    """Persist scan freshness so a backend scrape can publish it.

    The reconciler runs in the Celery process; process-local Prometheus gauges
    there are not scraped by the backend. A single bounded ``system_settings``
    row carries the last success/duration/counters across processes. It contains
    no identifiers or secrets.
    """
    if not settings.prometheus_enabled:
        return
    if succeeded is None:
        succeeded = report.errors == 0
    row = await session.get(SystemSetting, SCAN_STATE_KEY)
    previous: dict[str, Any] = {}
    if row is not None and row.value:
        try:
            loaded = json.loads(row.value)
            if isinstance(loaded, dict):
                previous = loaded
        except (ValueError, TypeError):
            previous = {}
    last_success = previous.get("last_success_at", 0.0)
    if succeeded:
        last_success = time.time()
    payload = {
        "last_success_at": float(last_success or 0.0),
        "duration_seconds": float(report.duration_seconds),
        "report": {result: int(getattr(report, result)) for result in _SCAN_REPORT_RESULTS},
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if row is None:
        session.add(SystemSetting(key=SCAN_STATE_KEY, value=encoded))
    else:
        row.value = encoded
    await session.commit()


async def load_recovery_scan_state(session: AsyncSession) -> dict[str, Any] | None:
    """Read the durable scan-state row for a backend Prometheus scrape."""
    row = await session.get(SystemSetting, SCAN_STATE_KEY)
    if row is None or not row.value:
        return None
    try:
        value = json.loads(row.value)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def publish_recovery_scan_state(state: Mapping[str, Any] | None) -> None:
    """Publish a durable scan-state snapshot into this process's registry."""
    if not settings.prometheus_enabled or not state:
        return
    RECOVERY_SCAN_LAST_SUCCESS_TIMESTAMP_SECONDS.set(float(state.get("last_success_at") or 0.0))
    RECOVERY_SCAN_DURATION_SECONDS.set(float(state.get("duration_seconds") or 0.0))
    report = state.get("report")
    if not isinstance(report, dict):
        report = {}
    for result in _SCAN_REPORT_RESULTS:
        RECOVERY_SCAN_LAST_REPORT.labels(result=result).set(int(report.get(result, 0) or 0))


def _worker_state_count(snapshot: RecoveryMetricsSnapshot, state: str) -> int:
    workers = snapshot.workers
    if state == "fresh":
        return workers.fresh
    if state == "stale":
        return workers.stale
    return workers.stopped


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()
