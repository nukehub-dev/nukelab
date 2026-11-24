# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded recovery/operations metrics and alert-rule contracts."""

from __future__ import annotations

import importlib
import re
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from prometheus_client import generate_latest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.models.worker_heartbeat import WorkerHeartbeat
from app.services import recovery_metrics as metrics_module
from app.services.operation_reconciler import OperationReconciler, ReconcileReport
from app.services.recovery_metrics import (
    collect_recovery_metrics,
    load_recovery_scan_state,
    persist_recovery_scan,
    publish_recovery_metrics,
    publish_recovery_scan_state,
    record_recovery_scan,
)

RULE_TEMPLATE = (
    Path(__file__).resolve().parents[3] / "monitoring" / "prometheus" / "rules" / "nukelab.yml.tpl"
)

RECOVERY_METRICS = {
    "nukelab_workers_registered",
    "nukelab_worker_heartbeats",
    "nukelab_worker_heartbeat_age_seconds",
    "nukelab_worker_last_heartbeat_timestamp_seconds",
    "nukelab_operations_active",
    "nukelab_operations_recovery_required",
    "nukelab_operations_stalled",
    "nukelab_recovery_scan_last_success_timestamp_seconds",
    "nukelab_recovery_scan_duration_seconds",
    "nukelab_recovery_scan_last_report",
    "nukelab_registry_verification_policy",
    "nukelab_registry_local_only_revisions",
    "nukelab_registry_templates_without_verified_revision",
}

FORBIDDEN_LABELS = {
    "user_id",
    "owner_id",
    "server_id",
    "operation_id",
    "revision_id",
    "template_id",
    "executor_id",
    "container_id",
}


@asynccontextmanager
async def _bound_session(db: AsyncSession):
    async with AsyncSession(
        bind=db.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session


def _worker(executor_id: uuid.UUID, state: str, heartbeat_at) -> WorkerHeartbeat:
    return WorkerHeartbeat(
        executor_id=executor_id,
        hostname="worker-host",
        container_id="worker-container",
        container_started_at="2026-11-21T09:00:00.000000000Z",
        pid=1234,
        process_start_time="100",
        single_process_container=True,
        schema_version="nukelab-journal/v1",
        state=state,
        heartbeat_at=heartbeat_at,
    )


async def _launch(
    db: AsyncSession,
    user,
    *,
    state: str,
    executor_id: uuid.UUID | None = None,
    heartbeat_at=None,
) -> ServerLaunchOperation:
    marker = uuid.uuid4().hex
    server = Server(
        name=f"server-{marker}",
        user_id=user.id,
        status="starting",
    )
    db.add(server)
    await db.flush()
    operation = ServerLaunchOperation(
        server_id=server.id,
        owner_id=user.id,
        action="create",
        state=state,
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        heartbeat_at=heartbeat_at,
        mounts=[],
        gpu_devices=[],
        username=user.username,
        resources={},
        created_at=utc_now(),
    )
    db.add(operation)
    await db.flush()
    return operation


async def _backup(
    db: AsyncSession,
    user,
    *,
    status: str,
    executor_id: uuid.UUID | None = None,
    heartbeat_at=None,
) -> VolumeBackup:
    backup = VolumeBackup(
        volume_name=f"volume-{uuid.uuid4().hex}",
        user_id=user.id,
        status=status,
        reserved_bytes=0,
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        heartbeat_at=heartbeat_at,
    )
    db.add(backup)
    await db.flush()
    return backup


async def _restore(
    db: AsyncSession,
    user,
    backup: VolumeBackup,
    *,
    status: str,
    executor_id: uuid.UUID | None = None,
    heartbeat_at=None,
) -> VolumeRestore:
    restore = VolumeRestore(
        backup_id=backup.id,
        user_id=user.id,
        destination_name=f"restore-{uuid.uuid4().hex}",
        display_name="Restored",
        max_size_bytes=1024,
        reserved_bytes=0,
        status=status,
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        heartbeat_at=heartbeat_at,
    )
    db.add(restore)
    await db.flush()
    return restore


async def _template(db: AsyncSession, *, active: bool = True) -> EnvironmentTemplate:
    marker = uuid.uuid4().hex
    template = EnvironmentTemplate(
        name=f"template-{marker}",
        slug=f"template-{marker}",
        image="approved:latest",
        is_active=active,
        is_public=True,
    )
    db.add(template)
    await db.flush()
    return template


def _revision(
    db: AsyncSession,
    template: EnvironmentTemplate,
    *,
    portable: bool,
    revoked: bool = False,
) -> EnvironmentRevision:
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
        template_fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
        portable_fingerprint=("a" * 64 if portable else None),
        configuration={},
        runtime_identity={},
        revoked=revoked,
    )
    db.add(revision)
    return revision


def _sample_value(text: str, name: str, **labels: str) -> float:
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        sample, _, raw_value = line.rpartition(" ")
        if sample == name or (
            sample.startswith(f"{name}{{")
            and all(f'{key}="{value}"' in sample for key, value in labels.items())
        ):
            return float(raw_value)
    raise AssertionError(f"metric sample not found: {name} {labels}")


def _operations(snapshot, kind: str):
    return next(item for item in snapshot.operations if item.kind == kind)


@pytest.mark.asyncio
async def test_collect_reports_bounded_recovery_state(db_session, test_user, monkeypatch):
    monkeypatch.setattr(settings, "registry_verification_policy", "require")
    await db_session.execute(delete(WorkerHeartbeat))
    await db_session.flush()
    now = utc_now()
    fresh_executor = uuid.uuid4()
    stale_executor = uuid.uuid4()
    stopped_executor = uuid.uuid4()
    db_session.add_all(
        [
            _worker(fresh_executor, "running", now - timedelta(seconds=5)),
            _worker(stale_executor, "running", now - timedelta(seconds=120)),
            _worker(stopped_executor, "stopped", now - timedelta(seconds=1)),
        ]
    )

    await _launch(
        db_session,
        test_user,
        state="executing",
        executor_id=fresh_executor,
        heartbeat_at=now - timedelta(seconds=10),
    )
    await _launch(db_session, test_user, state="uncertain")
    backup = await _backup(
        db_session,
        test_user,
        status="in_progress",
        executor_id=stale_executor,
        heartbeat_at=now - timedelta(seconds=95),
    )
    await _backup(db_session, test_user, status="recovery_required")
    await _restore(db_session, test_user, backup, status="completed")

    verified_template = await _template(db_session)
    _revision(db_session, verified_template, portable=True)
    local_template = await _template(db_session)
    _revision(db_session, local_template, portable=False)
    _revision(db_session, local_template, portable=True, revoked=True)
    _revision(db_session, local_template, portable=False, revoked=True)
    retired_template = await _template(db_session, active=False)
    _revision(db_session, retired_template, portable=False)
    await db_session.flush()

    snapshot = await collect_recovery_metrics(db_session, now=now)

    assert snapshot.workers.total == 3
    assert snapshot.workers.fresh == 1
    assert snapshot.workers.stale == 1
    assert snapshot.workers.stopped == 1
    assert snapshot.workers.heartbeat_age_seconds == 1.0
    assert snapshot.workers.last_heartbeat_timestamp == pytest.approx(
        (now - timedelta(seconds=1)).replace(tzinfo=UTC).timestamp()
    )

    launch = _operations(snapshot, "launch")
    assert (launch.active, launch.recovery_required, launch.stalled) == (2, 1, 0)
    backup_metrics = _operations(snapshot, "backup")
    assert (backup_metrics.active, backup_metrics.recovery_required, backup_metrics.stalled) == (
        2,
        1,
        1,
    )
    restore = _operations(snapshot, "restore")
    assert (restore.active, restore.recovery_required, restore.stalled) == (0, 0, 0)

    assert snapshot.registry.policy == "require"
    assert snapshot.registry.local_only_revisions == 2
    assert snapshot.registry.templates_without_verified_revision == 1

    publish_recovery_metrics(snapshot)
    text = generate_latest(metrics_module.REGISTRY).decode()

    assert _sample_value(text, "nukelab_workers_registered") == 3
    assert _sample_value(text, "nukelab_worker_heartbeats", state="fresh") == 1
    assert _sample_value(text, "nukelab_worker_heartbeats", state="stale") == 1
    assert _sample_value(text, "nukelab_worker_heartbeats", state="stopped") == 1
    assert _sample_value(text, "nukelab_operations_active", kind="launch") == 2
    assert _sample_value(text, "nukelab_operations_recovery_required", kind="backup") == 1
    assert _sample_value(text, "nukelab_operations_stalled", kind="backup") == 1
    assert _sample_value(text, "nukelab_registry_verification_policy", policy="require") == 1
    assert _sample_value(text, "nukelab_registry_verification_policy", policy="off") == 0
    assert _sample_value(text, "nukelab_registry_local_only_revisions") == 2
    assert _sample_value(text, "nukelab_registry_templates_without_verified_revision") == 1


@pytest.mark.asyncio
async def test_stalled_operations_respect_the_configured_threshold(db_session, test_user):
    now = utc_now()
    executor_id = uuid.uuid4()
    threshold = settings.operation_heartbeat_stale_seconds

    await _launch(
        db_session,
        test_user,
        state="executing",
        executor_id=executor_id,
        heartbeat_at=now - timedelta(seconds=threshold - 1),
    )
    snapshot = await collect_recovery_metrics(db_session, now=now)
    assert _operations(snapshot, "launch").stalled == 0

    await _launch(
        db_session,
        test_user,
        state="executing",
        executor_id=executor_id,
        heartbeat_at=now - timedelta(seconds=threshold),
    )
    snapshot = await collect_recovery_metrics(db_session, now=now)
    assert _operations(snapshot, "launch").stalled == 0

    await _launch(
        db_session,
        test_user,
        state="executing",
        executor_id=executor_id,
        heartbeat_at=now - timedelta(seconds=threshold + 1),
    )
    snapshot = await collect_recovery_metrics(db_session, now=now)
    assert _operations(snapshot, "launch").stalled == 1


@pytest.mark.asyncio
async def test_recovery_required_rows_are_not_counted_as_stalled(db_session, test_user):
    now = utc_now()
    executor_id = uuid.uuid4()
    recovery_cutoff = now - timedelta(seconds=settings.operation_heartbeat_stale_seconds + 60)
    await _launch(
        db_session,
        test_user,
        state="uncertain",
        executor_id=executor_id,
        heartbeat_at=recovery_cutoff,
    )
    backup = await _backup(
        db_session,
        test_user,
        status="recovery_required",
        executor_id=executor_id,
        heartbeat_at=recovery_cutoff,
    )
    await _restore(
        db_session,
        test_user,
        backup,
        status="recovery_required",
        executor_id=executor_id,
        heartbeat_at=recovery_cutoff,
    )
    await db_session.flush()

    snapshot = await collect_recovery_metrics(db_session, now=now)

    assert _operations(snapshot, "launch").recovery_required == 1
    assert _operations(snapshot, "launch").stalled == 0
    assert _operations(snapshot, "backup").recovery_required == 1
    assert _operations(snapshot, "backup").stalled == 0
    assert _operations(snapshot, "restore").recovery_required == 1
    assert _operations(snapshot, "restore").stalled == 0


@pytest.mark.asyncio
async def test_collect_with_no_rows_reports_zeroes(db_session):
    await db_session.execute(delete(WorkerHeartbeat))
    await db_session.flush()
    snapshot = await collect_recovery_metrics(db_session, now=utc_now())

    assert snapshot.workers.total == 0
    assert snapshot.workers.heartbeat_age_seconds == 0
    assert snapshot.workers.last_heartbeat_timestamp == 0
    assert {item.kind: item.active for item in snapshot.operations} == {
        "launch": 0,
        "backup": 0,
        "restore": 0,
    }
    assert snapshot.registry.local_only_revisions == 0
    assert snapshot.registry.templates_without_verified_revision == 0


@pytest.mark.asyncio
async def test_reconciler_records_scan_success_duration_and_counters(db_session, monkeypatch):
    monkeypatch.setattr(settings, "prometheus_enabled", True)
    metrics_module.RECOVERY_SCAN_LAST_SUCCESS_TIMESTAMP_SECONDS.set(0)
    reconciler = OperationReconciler(lambda: _bound_session(db_session), Mock())

    report = await reconciler.scan(limit=10)

    text = generate_latest(metrics_module.REGISTRY).decode()
    assert _sample_value(text, "nukelab_recovery_scan_last_report", result="scanned") == (
        report.scanned
    )
    assert _sample_value(text, "nukelab_recovery_scan_last_report", result="finalized") == 0
    assert _sample_value(text, "nukelab_recovery_scan_last_report", result="deferred") == 0
    assert _sample_value(text, "nukelab_recovery_scan_last_report", result="errors") == 0
    assert _sample_value(text, "nukelab_recovery_scan_duration_seconds") >= 0
    successful_at = _sample_value(text, "nukelab_recovery_scan_last_success_timestamp_seconds")
    assert successful_at > 0

    async def _fail(_bound):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(reconciler, "_select", _fail)
    failed = await reconciler.scan(limit=10)

    assert failed.errors == 1
    text = generate_latest(metrics_module.REGISTRY).decode()
    assert _sample_value(text, "nukelab_recovery_scan_last_report", result="errors") == 1
    assert (
        _sample_value(text, "nukelab_recovery_scan_last_success_timestamp_seconds") == successful_at
    )


@pytest.mark.asyncio
async def test_scan_state_persists_for_the_backend_scrape(db_session, monkeypatch):
    monkeypatch.setattr(settings, "prometheus_enabled", True)
    report = ReconcileReport(
        scanned=3,
        finalized=1,
        deferred=2,
        errors=0,
        duration_seconds=0.2,
    )

    async with _bound_session(db_session) as session:
        await persist_recovery_scan(session, report)
        state = await load_recovery_scan_state(session)

    assert state is not None
    assert state["last_success_at"] > 0
    assert state["duration_seconds"] == 0.2
    assert state["report"] == {
        "scanned": 3,
        "finalized": 1,
        "deferred": 2,
        "errors": 0,
    }

    publish_recovery_scan_state(state)
    text = generate_latest(metrics_module.REGISTRY).decode()
    assert _sample_value(text, "nukelab_recovery_scan_last_report", result="scanned") == 3
    assert _sample_value(text, "nukelab_recovery_scan_duration_seconds") == 0.2


def test_metric_registration_is_safe_under_reload():
    registered = metrics_module.WORKERS_REGISTERED

    reloaded = importlib.reload(metrics_module)

    assert reloaded.WORKERS_REGISTERED is registered
    assert reloaded.WORKER_HEARTBEATS is metrics_module.WORKER_HEARTBEATS


def test_metric_label_sets_are_fixed_and_bounded():
    unlabeled = (
        metrics_module.WORKERS_REGISTERED,
        metrics_module.WORKER_HEARTBEAT_AGE_SECONDS,
        metrics_module.WORKER_LAST_HEARTBEAT_TIMESTAMP_SECONDS,
        metrics_module.RECOVERY_SCAN_LAST_SUCCESS_TIMESTAMP_SECONDS,
        metrics_module.RECOVERY_SCAN_DURATION_SECONDS,
        metrics_module.REGISTRY_LOCAL_ONLY_REVISIONS,
        metrics_module.REGISTRY_TEMPLATES_WITHOUT_VERIFIED_REVISION,
    )
    for gauge in unlabeled:
        assert gauge._labelnames == ()
    assert metrics_module.WORKER_HEARTBEATS._labelnames == ("state",)
    assert metrics_module.OPERATIONS_ACTIVE._labelnames == ("kind",)
    assert metrics_module.OPERATIONS_RECOVERY_REQUIRED._labelnames == ("kind",)
    assert metrics_module.OPERATIONS_STALLED._labelnames == ("kind",)
    assert metrics_module.RECOVERY_SCAN_LAST_REPORT._labelnames == ("result",)
    assert metrics_module.REGISTRY_VERIFICATION_POLICY._labelnames == ("policy",)


def test_disabled_metrics_do_not_record_recovery_scan(monkeypatch):
    monkeypatch.setattr(settings, "prometheus_enabled", False)
    metrics_module.RECOVERY_SCAN_DURATION_SECONDS.set(12.5)

    record_recovery_scan(ReconcileReport(duration_seconds=1.0))

    text = generate_latest(metrics_module.REGISTRY).decode()
    assert _sample_value(text, "nukelab_recovery_scan_duration_seconds") == 12.5


def test_scan_metric_failure_is_logged_by_exception_class(monkeypatch):
    monkeypatch.setattr(settings, "prometheus_enabled", True)

    with (
        patch.object(
            metrics_module.RECOVERY_SCAN_DURATION_SECONDS,
            "set",
            side_effect=RuntimeError("metric registry unavailable"),
        ),
        patch.object(metrics_module.logger, "warning") as warning,
    ):
        record_recovery_scan(ReconcileReport())

    warning.assert_called_once_with(
        "Recovery scan metrics update failed",
        extra={"error_class": "RuntimeError"},
    )


def test_recovery_alert_rules_are_bounded_and_use_known_metrics():
    if not RULE_TEMPLATE.exists():
        pytest.skip("monitoring rule templates are not mounted in the backend test container")

    import yaml

    data = yaml.safe_load(RULE_TEMPLATE.read_text(encoding="utf-8"))
    groups = {group["name"]: group for group in data["groups"]}
    group = groups["nukelab-recovery"]
    assert len(group["rules"]) == 6

    for rule in group["rules"]:
        expression = rule["expr"]
        assert rule.get("for")
        assert rule["labels"]["severity"] in {"warning", "critical"}
        assert rule["annotations"]["summary"]
        description = rule["annotations"]["description"]
        assert "doctor" in description
        assert "Admin > " in description

        referenced = set(re.findall(r"\bnukelab_[a-z0-9_]+", expression))
        assert referenced
        assert referenced <= RECOVERY_METRICS, (rule["alert"], referenced - RECOVERY_METRICS)

        for name, selector in re.findall(r"(nukelab_[a-z0-9_]+)\{([^}]*)\}", expression):
            labels = dict(re.findall(r'([a-z_]+)\s*=\s*"([^"]*)"', selector))
            assert set(labels) <= {"state", "policy"}
            assert not (set(labels) & FORBIDDEN_LABELS)
            if name == "nukelab_worker_heartbeats":
                assert labels["state"] in {"fresh", "stale", "stopped"}
            if name == "nukelab_registry_verification_policy":
                assert labels["policy"] in {"off", "prefer", "require"}
