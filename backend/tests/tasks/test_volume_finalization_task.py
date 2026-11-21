# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Volume completion-hook wiring for the recovery reconciliation task."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

from app import tasks
from app.config import settings
from app.services.operation_reconciler import ReconcileReport


def _resources(driver="driver"):
    @asynccontextmanager
    async def resources():
        yield SimpleNamespace(db=SimpleNamespace(bind="engine"), driver=driver)

    return resources


def test_reconcile_task_builds_volume_hooks_from_loop_resources(monkeypatch, tmp_path):
    report = ReconcileReport(scanned=1, finalized=1, duration_seconds=0.1)
    captured = {}

    class FakeHooks:
        def __init__(self, session_factory, driver):
            captured["hook_factory"] = session_factory
            captured["hook_driver"] = driver
            self.marker = "hooks"

    class FakeReconciler:
        def __init__(self, session_factory, driver, *, volume_hooks=None):
            captured["factory"] = session_factory
            captured["driver"] = driver
            captured["hooks"] = volume_hooks

        async def scan(self, limit=None):
            captured["limit"] = limit
            return report

    monkeypatch.setattr(tasks, "ensure_journal_schema", lambda: True)
    monkeypatch.setattr(tasks, "operation_resources", _resources())
    monkeypatch.setattr(
        tasks,
        "async_sessionmaker",
        lambda bind, expire_on_commit=False: ("factory", bind),
    )
    monkeypatch.setattr(tasks, "VolumeFinalizationHooks", FakeHooks)
    monkeypatch.setattr(tasks, "OperationReconciler", FakeReconciler)
    monkeypatch.setattr(settings, "volume_backup_storage_path", str(tmp_path))

    output = tasks.reconcile_operations.run(False)

    assert output == (
        "Reconciled 1 operations: 1 finalized, 0 deferred, 0 recovery required, 0 errors"
    )
    assert captured["hook_factory"] == ("factory", "engine")
    assert captured["hook_driver"] == "driver"
    assert captured["hooks"].marker == "hooks"
    assert captured["factory"] == ("factory", "engine")
    assert captured["driver"] == "driver"
    assert captured["limit"] == settings.recovery_scan_batch_size


def test_reconcile_task_runs_without_hooks_when_recovery_storage_is_disabled(monkeypatch, tmp_path):
    report = ReconcileReport(scanned=1, deferred=1, duration_seconds=0.1)
    captured = {}

    class FailHooks:
        def __init__(self, session_factory, driver):
            raise AssertionError("hooks must not be built without recovery storage")

    class FakeReconciler:
        def __init__(self, session_factory, driver, **kwargs):
            captured["kwargs"] = kwargs

        async def scan(self, limit=None):
            return report

    monkeypatch.setattr(tasks, "ensure_journal_schema", lambda: True)
    monkeypatch.setattr(tasks, "operation_resources", _resources())
    monkeypatch.setattr(tasks, "VolumeFinalizationHooks", FailHooks)
    monkeypatch.setattr(tasks, "OperationReconciler", FakeReconciler)

    for storage in ("", str(tmp_path / "missing")):
        monkeypatch.setattr(settings, "volume_backup_storage_path", storage)
        output = tasks.reconcile_operations.run(False)
        assert "1 deferred" in output
        assert captured["kwargs"] == {}


def test_reconcile_task_keeps_launch_reconciliation_when_hooks_cannot_be_built(
    monkeypatch, tmp_path
):
    report = ReconcileReport(scanned=2, finalized=1, deferred=1, duration_seconds=0.1)
    captured = {}

    class BrokenHooks:
        def __init__(self, session_factory, driver):
            raise RuntimeError("recovery inspector unavailable")

    class FakeReconciler:
        def __init__(self, session_factory, driver, **kwargs):
            captured["kwargs"] = kwargs

        async def scan(self, limit=None):
            return report

    monkeypatch.setattr(tasks, "ensure_journal_schema", lambda: True)
    monkeypatch.setattr(tasks, "operation_resources", _resources())
    monkeypatch.setattr(tasks, "VolumeFinalizationHooks", BrokenHooks)
    monkeypatch.setattr(tasks, "OperationReconciler", FakeReconciler)
    monkeypatch.setattr(settings, "volume_backup_storage_path", str(tmp_path))

    output = tasks.reconcile_operations.run(False)

    assert "1 finalized" in output and "1 deferred" in output
    assert captured["kwargs"] == {}
