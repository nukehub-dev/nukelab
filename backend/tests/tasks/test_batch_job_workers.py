# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Batch job workers own bounded loops and are registered on the beat."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import tasks
from app.services.batch_job_dispatch_service import BatchJobDispatchReport
from app.services.batch_job_monitor import MonitorReport
from app.services.batch_job_reconciliation import BatchJobRecoveryReport
from app.services.batch_job_retention import LogPurgeReport
from app.services.batch_job_runtime import RuntimeStartResult
from tests.tasks.test_lifecycle_workers import database, worker_resources


def test_batch_tasks_and_beat_entries_are_registered():
    from app.worker import _JOURNAL_RELATIONS, celery_app

    for name in (
        "app.tasks.dispatch_batch_jobs",
        "app.tasks.run_batch_job",
        "app.tasks.monitor_batch_jobs",
        "app.tasks.reconcile_batch_jobs",
        "app.tasks.purge_batch_job_logs",
    ):
        assert name in celery_app.tasks

    schedule = celery_app.conf.beat_schedule
    assert schedule["dispatch-batch-jobs"]["task"] == "app.tasks.dispatch_batch_jobs"
    assert schedule["monitor-batch-jobs"]["task"] == "app.tasks.monitor_batch_jobs"
    assert schedule["reconcile-batch-jobs"]["task"] == "app.tasks.reconcile_batch_jobs"
    assert schedule["purge-batch-job-logs"]["task"] == "app.tasks.purge_batch_job_logs"
    assert "process-server-queue" in schedule
    assert "reconcile-operations" in schedule
    assert _JOURNAL_RELATIONS["batch_jobs"] == {
        "executor_id",
        "heartbeat_at",
        "state",
        "fencing_token",
    }


def test_dispatch_task_returns_a_short_summary():
    db = database()
    service = SimpleNamespace(
        dispatch=AsyncMock(
            return_value=BatchJobDispatchReport(selected=2, admitted=1, enqueued=1, waiting=1)
        )
    )
    with (
        worker_resources(db),
        patch(
            "app.services.batch_job_dispatch_service.BatchJobDispatchService",
            return_value=service,
        ),
    ):
        result = tasks.dispatch_batch_jobs.run()
    assert result == (
        "Selected 2 batch jobs: 1 admitted, 1 enqueued, 1 waiting, 0 failed, 0 errors"
    )
    service.dispatch.assert_awaited_once()


def test_run_batch_job_task_validates_identifier_and_returns_action():
    identifier = uuid.uuid4()
    db = database()
    service = SimpleNamespace(
        start=AsyncMock(return_value=RuntimeStartResult(identifier, "running"))
    )
    with (
        worker_resources(db),
        patch(
            "app.services.batch_job_runtime.BatchJobRuntimeService",
            return_value=service,
        ),
    ):
        assert tasks.run_batch_job.run(str(identifier)) == "Batch job running"
        assert tasks.run_batch_job.run("not-a-uuid") == "Invalid batch job id"
    service.start.assert_awaited_once_with(identifier)


def test_monitor_task_returns_a_short_summary():
    db = database()
    service = SimpleNamespace(
        monitor=AsyncMock(
            return_value=MonitorReport(
                scanned=3, observed=3, started=1, finalized=1, recovery_required=1
            )
        )
    )
    with (
        worker_resources(db),
        patch(
            "app.services.batch_job_monitor.BatchJobMonitorService",
            return_value=service,
        ),
    ):
        result = tasks.monitor_batch_jobs.run()
    assert result.startswith("Observed 3 batch jobs:")
    assert "1 running" in result
    assert "1 finalized" in result
    service.monitor.assert_awaited_once()


def test_reconcile_task_returns_a_short_summary():
    db = database()
    service = SimpleNamespace(
        scan=AsyncMock(
            return_value=BatchJobRecoveryReport(
                scanned=4,
                finalized=1,
                recovery_required=1,
                cleanup_completed=1,
                cleanup_pending=1,
            )
        )
    )
    with (
        worker_resources(db),
        patch(
            "app.services.batch_job_reconciliation.BatchJobReconciliationService",
            return_value=service,
        ),
    ):
        result = tasks.reconcile_batch_jobs.run()
    assert result.startswith("Scanned 4 batch jobs:")
    assert "1 cleanups complete" in result
    assert "1 cleanups pending" in result
    service.scan.assert_awaited_once()


class _EmptySession:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *args):
        return False


def test_purge_task_returns_bounded_counts():
    with (
        patch("app.tasks.AsyncSessionLocal", return_value=_EmptySession()),
        patch(
            "app.services.batch_job_retention.purge_expired_logs",
            AsyncMock(return_value=LogPurgeReport(scanned=5, deleted=4, errors=1)),
        ) as purge,
    ):
        result = tasks.purge_batch_job_logs.run()
    assert result == "Batch job log purge: scanned=5, deleted=4, errors=1"
    purge.assert_awaited_once()


def test_purge_task_failure_is_reported_without_raising():
    with (
        patch("app.tasks.AsyncSessionLocal", return_value=_EmptySession()),
        patch(
            "app.services.batch_job_retention.purge_expired_logs",
            AsyncMock(side_effect=RuntimeError("database unavailable")),
        ),
    ):
        assert tasks.purge_batch_job_logs.run() == "Batch job log purge deferred"


def test_service_failure_is_reported_without_raising():
    db = database()
    service = SimpleNamespace(dispatch=AsyncMock(side_effect=RuntimeError("database unavailable")))
    with (
        worker_resources(db),
        patch(
            "app.services.batch_job_dispatch_service.BatchJobDispatchService",
            return_value=service,
        ),
    ):
        assert tasks.dispatch_batch_jobs.run() == "Batch job dispatch deferred"
