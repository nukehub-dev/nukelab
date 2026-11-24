# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Celery wiring for the bounded recovery reconciliation scan."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import app.worker as worker
from app import tasks
from app.config import settings
from app.db.schema_guard import SchemaCompatibilityResult
from app.services.operation_reconciler import ReconcileReport
from app.worker import celery_app


@pytest.fixture(autouse=True)
def reset_worker_recovery_state(monkeypatch):
    monkeypatch.setattr(worker, "_initial_reconciliation_scheduled", False)
    monkeypatch.setattr(worker, "_journal_schema_state", None)


def test_reconcile_task_is_registered_and_beats_on_the_recovery_interval():
    assert tasks.reconcile_operations.name == "app.tasks.reconcile_operations"
    assert "app.tasks.reconcile_operations" in celery_app.tasks

    entry = celery_app.conf.beat_schedule["reconcile-operations"]
    assert entry["task"] == "app.tasks.reconcile_operations"
    assert entry["schedule"] == float(settings.recovery_scan_interval_seconds)
    assert settings.recovery_scan_interval_seconds == 30


def test_global_celery_acknowledgement_is_not_the_recovery_mechanism():
    assert not celery_app.conf.task_acks_late
    assert not celery_app.conf.task_reject_on_worker_lost


def test_reconcile_task_owns_loop_resources_and_scans_the_configured_batch(monkeypatch):
    report = ReconcileReport(scanned=2, finalized=1, deferred=1, duration_seconds=0.2)
    captured = {}
    events = []

    class FakeReconciler:
        def __init__(self, session_factory, driver):
            captured["factory"] = session_factory
            captured["driver"] = driver

        async def scan(self, limit=None):
            captured["limit"] = limit
            return report

    @asynccontextmanager
    async def resources():
        events.append("enter")
        try:
            yield SimpleNamespace(db=SimpleNamespace(bind="engine"), driver="driver")
        finally:
            events.append("exit")

    monkeypatch.setattr(tasks, "ensure_journal_schema", lambda: True)
    monkeypatch.setattr(tasks, "operation_resources", resources)
    monkeypatch.setattr(
        tasks,
        "async_sessionmaker",
        lambda bind, expire_on_commit=False: ("factory", bind),
    )
    monkeypatch.setattr(tasks, "OperationReconciler", FakeReconciler)

    output = tasks.reconcile_operations.run(False)

    assert output == (
        "Reconciled 2 operations: 1 finalized, 1 deferred, 0 recovery required, 0 errors"
    )
    assert captured == {
        "factory": ("factory", "engine"),
        "driver": "driver",
        "limit": settings.recovery_scan_batch_size,
    }
    assert events == ["enter", "exit"]


def test_reconcile_task_jitters_only_when_requested(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(tasks, "ensure_journal_schema", lambda: True)
    monkeypatch.setattr(tasks.time, "sleep", sleep)
    monkeypatch.setattr(tasks.random, "uniform", Mock(return_value=2.5))
    monkeypatch.setattr(tasks, "run_operation", Mock(return_value=ReconcileReport(scanned=1)))

    tasks.reconcile_operations.run()

    tasks.random.uniform.assert_called_once_with(0.0, tasks.RECOVERY_SCAN_JITTER_SECONDS)
    sleep.assert_called_once_with(2.5)

    sleep.reset_mock()
    tasks.reconcile_operations.run(False)
    sleep.assert_not_called()


def test_reconcile_task_defers_on_database_failure_without_raising(monkeypatch):
    monkeypatch.setattr(tasks, "ensure_journal_schema", lambda: True)
    monkeypatch.setattr(tasks.time, "sleep", Mock())
    monkeypatch.setattr(
        tasks,
        "run_operation",
        Mock(side_effect=RuntimeError("database unavailable")),
    )

    assert tasks.reconcile_operations.run(False) == "Operation reconciliation deferred"


def test_reconcile_task_refuses_incompatible_journal_schema(monkeypatch):
    monkeypatch.setattr(tasks, "ensure_journal_schema", lambda: False)
    run = Mock()
    monkeypatch.setattr(tasks, "run_operation", run)

    output = tasks.reconcile_operations.run(False)

    assert output == "Operation reconciliation blocked: incompatible journal schema"
    run.assert_not_called()


def test_worker_ready_schedules_one_delayed_initial_pass(monkeypatch):
    heartbeat = object()
    sent = []
    monkeypatch.setattr(worker, "ensure_journal_schema", lambda: True)
    monkeypatch.setattr(worker, "start_celery_worker_heartbeat", lambda: heartbeat)
    monkeypatch.setattr(
        tasks.reconcile_operations,
        "apply_async",
        lambda **kwargs: sent.append(kwargs),
    )

    worker.start_worker_heartbeat(sender=None)
    worker.start_worker_heartbeat(sender=None)

    assert sent == [
        {
            "countdown": settings.recovery_initial_delay_seconds,
            "kwargs": {"jitter": False},
        }
    ]
    assert settings.recovery_initial_delay_seconds == 60


def test_initial_reconciliation_guard_survives_a_broker_failure(monkeypatch):
    send = Mock(side_effect=RuntimeError("broker unavailable"))
    monkeypatch.setattr(tasks.reconcile_operations, "apply_async", send)

    assert worker.schedule_initial_reconciliation() is True
    assert worker.schedule_initial_reconciliation() is False

    send.assert_called_once_with(
        countdown=settings.recovery_initial_delay_seconds,
        kwargs={"jitter": False},
    )


def test_worker_ready_does_not_schedule_without_a_registered_heartbeat(monkeypatch):
    sent = Mock()
    monkeypatch.setattr(worker, "ensure_journal_schema", lambda: True)
    monkeypatch.setattr(worker, "start_celery_worker_heartbeat", lambda: None)
    monkeypatch.setattr(tasks.reconcile_operations, "apply_async", sent)

    worker.start_worker_heartbeat(sender=None)

    sent.assert_not_called()


def test_worker_ready_fails_and_does_not_enqueue_on_incompatible_schema(monkeypatch):
    critical = Mock()
    sent = Mock()
    monkeypatch.setattr(worker, "ensure_journal_schema", lambda: False)
    monkeypatch.setattr(worker, "start_celery_worker_heartbeat", lambda: object())
    monkeypatch.setattr(worker.logger, "critical", critical)
    monkeypatch.setattr(tasks.reconcile_operations, "apply_async", sent)

    with pytest.raises(worker.JournalSchemaIncompatible):
        worker.start_worker_heartbeat(sender=None)

    sent.assert_not_called()
    critical.assert_called_once()


@pytest.mark.asyncio
async def test_journal_schema_handshake_reads_the_live_catalog():
    result = await worker.check_journal_schema()

    assert result.ok is True
    assert result.missing_relations == ()


@pytest.mark.asyncio
async def test_journal_schema_handshake_detects_a_newer_database_revision(monkeypatch):
    compatibility = SchemaCompatibilityResult(
        ok=False,
        unknown_revisions=("future-revision",),
        db_revisions=("future-revision",),
        known_revisions=frozenset({"local-revision"}),
    )
    monkeypatch.setattr(worker, "check_schema_compatibility", AsyncMock(return_value=compatibility))
    monkeypatch.setattr(worker, "_missing_journal_relations", AsyncMock(return_value=()))

    result = await worker.check_journal_schema(engine=object(), script_dir_path="/alembic")

    assert result.ok is False
    assert result.unknown_revisions == ("future-revision",)
    assert result.missing_relations == ()


@pytest.mark.asyncio
async def test_journal_schema_handshake_detects_missing_relations(monkeypatch):
    compatibility = SchemaCompatibilityResult(
        ok=True,
        unknown_revisions=(),
        db_revisions=("local-revision",),
        known_revisions=frozenset({"local-revision"}),
    )
    monkeypatch.setattr(worker, "check_schema_compatibility", AsyncMock(return_value=compatibility))
    monkeypatch.setattr(
        worker,
        "_missing_journal_relations",
        AsyncMock(return_value=("worker_heartbeats", "volume_backups.executor_id")),
    )

    result = await worker.check_journal_schema(engine=object(), script_dir_path="/alembic")

    assert result.ok is False
    assert result.missing_relations == (
        "worker_heartbeats",
        "volume_backups.executor_id",
    )


@pytest.mark.asyncio
async def test_journal_schema_handshake_defers_when_database_is_unreachable(monkeypatch):
    compatibility = SchemaCompatibilityResult(
        ok=True,
        unknown_revisions=(),
        db_revisions=(),
        known_revisions=frozenset(),
        db_unreachable=True,
    )
    monkeypatch.setattr(worker, "check_schema_compatibility", AsyncMock(return_value=compatibility))
    monkeypatch.setattr(
        worker,
        "_missing_journal_relations",
        AsyncMock(side_effect=RuntimeError("catalog unavailable")),
    )

    result = await worker.check_journal_schema(engine=object(), script_dir_path="/alembic")

    assert result.ok is True
    assert result.db_unreachable is True


def test_ensure_journal_schema_logs_critical_and_recovers_after_relations_appear(
    monkeypatch,
):
    critical = Mock()
    monkeypatch.setattr(worker.logger, "critical", critical)
    monkeypatch.setattr(
        worker,
        "run_journal_schema_handshake",
        Mock(
            return_value=worker.JournalSchemaResult(
                ok=False, unknown_revisions=("future-revision",)
            )
        ),
    )

    assert worker.ensure_journal_schema() is False
    assert worker._journal_schema_state is False
    critical.assert_called_once()

    monkeypatch.setattr(
        worker,
        "run_journal_schema_handshake",
        Mock(return_value=worker.JournalSchemaResult(ok=True)),
    )

    assert worker.ensure_journal_schema() is True
    assert worker._journal_schema_state is True


@pytest.mark.asyncio
async def test_journal_schema_handshake_uses_the_catalog_for_unmanaged_databases(
    monkeypatch,
):
    compatibility = SchemaCompatibilityResult(
        ok=True,
        unknown_revisions=(),
        db_revisions=(),
        known_revisions=frozenset(),
        db_unreachable=True,
    )
    monkeypatch.setattr(worker, "check_schema_compatibility", AsyncMock(return_value=compatibility))
    monkeypatch.setattr(
        worker, "_missing_journal_relations", AsyncMock(return_value=("worker_heartbeats",))
    )

    result = await worker.check_journal_schema(engine=object(), script_dir_path="/alembic")

    assert result.ok is False
    assert result.db_unreachable is False
    assert result.missing_relations == ("worker_heartbeats",)


def test_ensure_journal_schema_defers_when_the_handshake_raises(monkeypatch):
    monkeypatch.setattr(
        worker,
        "run_journal_schema_handshake",
        Mock(side_effect=RuntimeError("handshake failed")),
    )

    assert worker.ensure_journal_schema() is True
    assert worker._journal_schema_state is None


@pytest.mark.asyncio
async def test_run_coroutine_sync_works_inside_an_active_loop():
    async def value():
        return 7

    assert worker._run_coroutine_sync(value()) == 7


def test_ensure_journal_schema_does_not_cache_a_database_outage(monkeypatch):
    monkeypatch.setattr(
        worker,
        "run_journal_schema_handshake",
        Mock(return_value=worker.JournalSchemaResult(ok=True, db_unreachable=True)),
    )

    assert worker.ensure_journal_schema() is True
    assert worker._journal_schema_state is None
