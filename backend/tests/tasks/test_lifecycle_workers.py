# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Worker orchestration around loop-owned resources and guarded business services."""

import asyncio
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.orm import make_transient_to_detached

from app import tasks
from app.config import settings
from app.core.time_utils import utc_now
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.server_schedule import ServerSchedule
from app.services.server_launch_service import LaunchError
from app.services.server_queue_dispatch_service import QueueDispatchResult


def result(*, rows=(), scalar=None, one=None):
    value = Mock()
    value.all.return_value = list(rows)
    value.scalars.return_value.all.return_value = list(rows)
    value.scalar_one_or_none.return_value = scalar
    value.one_or_none.return_value = one
    return value


def server(**changes):
    now = utc_now()
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="worker-server",
        container_id="runtime-id",
        status="running",
        plan_id=None,
        total_cost=0,
        started_at=now - timedelta(hours=2),
        last_activity=now - timedelta(hours=1),
        updated_at=now,
        expires_at=now - timedelta(minutes=1),
        **changes,
    )


def database(rows=(), objects=None):
    db = Mock()
    db.execute = AsyncMock(return_value=result(rows=rows))
    db.get = AsyncMock(
        side_effect=lambda model, identifier, **kwargs: (objects or {}).get((model, identifier))
    )
    db.commit, db.rollback, db.close = AsyncMock(), AsyncMock(), AsyncMock()
    return db


@contextmanager
def worker_resources(db):
    try:
        previous_loop = asyncio.get_event_loop()
    except RuntimeError:
        previous_loop = None
    runtime = SimpleNamespace(
        close=AsyncMock(), delete_container=AsyncMock(), stop_container=AsyncMock()
    )
    events = []

    @asynccontextmanager
    async def resources():
        events.append(("enter", asyncio.get_running_loop()))
        try:
            yield SimpleNamespace(db=db, driver=runtime)
        finally:
            await db.close()
            await runtime.close()
            events.append(("exit", asyncio.get_running_loop()))

    with (
        patch("app.tasks.operation_resources", resources),
        patch("app.tasks._run_async", side_effect=AssertionError("Legacy runner must not execute")),
        patch(
            "app.tasks.AsyncSessionLocal",
            side_effect=AssertionError("Global session must not execute"),
        ),
        patch(
            "app.services.xfs_quota_service.xfs_quota_service._xfs_quota_available",
            return_value=False,
        ),
    ):
        try:
            yield SimpleNamespace(db=db, driver=runtime, events=events)
        finally:
            # Preserve pytest's outer fixture loop after the actual runner closes
            # its separate job loop; legacy task tests still use that fixture loop.
            asyncio.set_event_loop(previous_loop)


@pytest.mark.parametrize(
    "task",
    [
        tasks.shutdown_idle_servers,
        tasks.process_nuke_billing,
        tasks.enforce_auto_stop,
        tasks.enforce_volume_quotas,
        tasks.check_container_health,
        tasks.evaluate_schedules,
    ],
)
def test_worker_failures_close_operation_resources_and_do_not_enter_legacy_runner(task):
    db = database()
    db.execute.side_effect = RuntimeError("database unavailable")
    health = SimpleNamespace(
        check_all_containers=AsyncMock(side_effect=RuntimeError("health unavailable"))
    )
    schedule = SimpleNamespace(
        get_due_schedules=AsyncMock(side_effect=RuntimeError("schedule unavailable"))
    )
    with (
        worker_resources(db) as owned,
        patch("app.tasks.HealthCheckService", return_value=health),
        patch("app.services.schedule_service.ScheduleService", return_value=schedule),
    ):
        output = task.run()
    assert "Error" in output
    assert [event for event, _ in owned.events] == ["enter", "exit"]
    assert owned.events[0][1] is owned.events[1][1]
    assert owned.events[0][1].is_closed()
    db.close.assert_awaited_once()
    owned.driver.close.assert_awaited_once()
    owned.driver.delete_container.assert_not_awaited()


@pytest.mark.parametrize(
    "task,expected",
    [
        (tasks.shutdown_idle_servers, "Stopped 0 idle servers"),
        (tasks.process_nuke_billing, "Billed 0 servers, stopped 0 servers"),
        (tasks.enforce_auto_stop, "Stopped 0 servers"),
        (tasks.enforce_volume_quotas, "Stopped 0 servers, warned 0 volumes (du=0)"),
        (tasks.check_container_health, "Health checks completed"),
        (tasks.evaluate_schedules, "Executed 0 schedules, 0 failed"),
    ],
)
def test_empty_worker_results_still_close_owned_loop_resources(task, expected):
    db = database()
    health = SimpleNamespace(check_all_containers=AsyncMock())
    schedules = SimpleNamespace(get_due_schedules=AsyncMock(return_value=[]))
    with (
        worker_resources(db) as owned,
        patch("app.tasks.HealthCheckService", return_value=health),
        patch("app.services.schedule_service.ScheduleService", return_value=schedules),
        patch("app.tasks._fetch_sidecar_activity", new=AsyncMock(return_value={})),
    ):
        assert task.run() == expected
    owned.driver.close.assert_awaited_once()
    assert owned.events[-1][1].is_closed()


@pytest.mark.parametrize(
    "mode,stops",
    [
        ("disabled", 0),
        ("no_activity", 0),
        ("recent", 0),
        ("fresh_sidecar", 0),
        ("stale_sidecar", 1),
        ("idle", 1),
    ],
)
def test_idle_worker_preserves_preferences_and_sidecar_activity(mode, stops):
    row = server()
    prefs = {"idle_shutdown_enabled": mode != "disabled", "idle_shutdown_timeout": 15}
    if mode == "no_activity":
        row.last_activity = row.started_at = None
    if mode == "recent":
        row.last_activity = utc_now()
    observed = utc_now() if mode == "fresh_sidecar" else utc_now() - timedelta(minutes=30)
    activity = {str(row.id): observed} if "sidecar" in mode else {}
    db = database([(row, SimpleNamespace(preferences=prefs))], {(Server, row.id): row})

    async def stop(db_arg, driver_arg, identifier, **kwargs):
        assert db.commit.await_count >= 1
        assert identifier == row.id and kwargs["stop_reason"] == "idle_timeout"

    with (
        worker_resources(db),
        patch("app.tasks._fetch_sidecar_activity", new=AsyncMock(return_value=activity)),
        patch(
            "app.tasks._stop_server_with_bookkeeping", new=AsyncMock(side_effect=stop)
        ) as terminate,
    ):
        output = tasks.shutdown_idle_servers.run()
    assert output == f"Stopped {stops} idle servers"
    assert terminate.await_count == stops
    if mode == "fresh_sidecar":
        assert row.last_activity == observed
        db.commit.assert_awaited_once()


def test_unknown_idle_stop_leaves_runtime_and_reservations_to_termination_owner():
    row = server()
    db = database([(row, SimpleNamespace(preferences={}))], {(Server, row.id): row})
    with (
        worker_resources(db) as owned,
        patch("app.tasks._fetch_sidecar_activity", new=AsyncMock(return_value={})),
        patch(
            "app.tasks._stop_server_with_bookkeeping",
            new=AsyncMock(side_effect=LaunchError("recovery_required", 503)),
        ),
        patch("app.tasks._release_gpu_devices", new_callable=AsyncMock) as release,
    ):
        output = tasks.shutdown_idle_servers.run()
    assert output == "Stopped 0 idle servers"
    assert row.status == "running" and row.container_id == "runtime-id"
    db.rollback.assert_awaited_once()
    release.assert_not_awaited()
    owned.driver.delete_container.assert_not_awaited()


@pytest.mark.parametrize(
    "mode,stops",
    [("expired", 1), ("future", 0), ("no_expiry", 0), ("already_stopped", 0), ("vanished", 0)],
)
def test_expiry_worker_rechecks_each_persisted_server(mode, stops):
    row = server()
    if mode == "future":
        row.expires_at = utc_now() + timedelta(hours=1)
    if mode == "no_expiry":
        row.expires_at = None
    if mode == "already_stopped":
        row.status = "stopped"
    db = database([row], {(Server, row.id): None if mode == "vanished" else row})
    with (
        worker_resources(db) as owned,
        patch("app.tasks._stop_server_with_bookkeeping", new_callable=AsyncMock) as terminate,
    ):
        output = tasks.enforce_auto_stop.run()
    assert output == f"Stopped {stops} servers"
    if stops:
        terminate.assert_awaited_once_with(
            db,
            owned.driver,
            row.id,
            expected_version=row.updated_at,
            stop_reason="max_runtime_exceeded",
            notification_reason="exceeded the maximum runtime limit",
            reconcile_billing=False,
        )


@pytest.mark.parametrize(
    "rate,balance,enabled,billed,stopped",
    [
        (0, 100, True, 0, 0),
        (10, 0, False, 0, 0),
        (10, 0, True, 0, 1),
        (3, 100, True, 1, 0),
        (8, 3, True, 1, 0),
        (8, 100, True, 1, 0),
    ],
)
def test_billing_only_charges_running_usage_and_routes_depletion_to_guarded_stop(
    monkeypatch, rate, balance, enabled, billed, stopped
):
    monkeypatch.setattr(settings, "server_auto_stop_on_depletion", enabled)
    row = server()
    plan = SimpleNamespace(id=uuid.uuid4(), cost_per_hour=rate)
    db = database(objects={(Server, row.id): row, (ServerPlan, plan.id): plan})
    db.execute.side_effect = [result(rows=[(row, plan)]), result(scalar=balance)]
    credit = SimpleNamespace(
        consume_credits=AsyncMock(),
        get_spendable_balance=AsyncMock(return_value=balance),
    )
    notify = SimpleNamespace(low_balance=AsyncMock())
    with (
        worker_resources(db),
        patch("app.services.credit_service.CreditService", return_value=credit),
        patch("app.services.notification_service.NotificationService", return_value=notify),
        patch("app.tasks._stop_server_with_bookkeeping", new_callable=AsyncMock) as terminate,
    ):
        output = tasks.process_nuke_billing.run()
    assert output == f"Billed {billed} servers, stopped {stopped} servers"
    assert credit.consume_credits.await_count == billed
    assert terminate.await_count == stopped
    if billed:
        amount = max(1, int(rate * 0.25))
        assert credit.consume_credits.call_args.kwargs["amount"] == amount
        assert row.total_cost == amount and row.last_billed_at is not None
        assert notify.low_balance.await_count == int(balance - amount <= rate * 2)


def test_failed_billing_does_not_increment_cost_or_force_a_runtime_stop():
    row = server()
    plan = SimpleNamespace(id=uuid.uuid4(), cost_per_hour=10)
    db = database(objects={(Server, row.id): row, (ServerPlan, plan.id): plan})
    db.execute.side_effect = [result(rows=[(row, plan)]), result(scalar=100)]
    with (
        worker_resources(db),
        patch("app.services.credit_service.CreditService") as credit,
        patch("app.tasks._stop_server_with_bookkeeping", new_callable=AsyncMock) as terminate,
    ):
        credit.return_value.get_spendable_balance = AsyncMock(return_value=100)
        credit.return_value.consume_credits = AsyncMock(
            side_effect=RuntimeError("ledger unavailable")
        )
        output = tasks.process_nuke_billing.run()
    assert output == "Billed 0 servers, stopped 0 servers"
    assert row.total_cost == 0 and row.status == "running"
    db.rollback.assert_awaited_once()
    terminate.assert_not_awaited()


def test_queue_worker_uses_dispatcher_summary_without_upfront_credit_or_legacy_scan():
    summary = QueueDispatchResult(scanned=6, started=2, waiting=1, expired=3, recovery_required=1)
    with (
        patch("app.tasks.run_queue_dispatch", return_value=summary) as dispatch,
        patch("app.services.credit_service.CreditService") as credit,
        patch("app.tasks._run_async", side_effect=AssertionError("No old worker")),
    ):
        assert tasks.process_server_queue.run() == "Started 2 queued servers, timed out 3 entries"
    dispatch.assert_called_once_with(
        timeout_seconds=settings.server_launch_timeout_seconds,
        batch_size=settings.queue_dispatch_batch_size,
    )
    credit.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("dispatch unavailable"), TimeoutError("deadline")])
def test_queue_worker_does_not_retry_or_charge_after_dispatch_failure(error):
    with (
        patch("app.tasks.run_queue_dispatch", side_effect=error) as dispatch,
        patch("app.services.credit_service.CreditService") as credit,
    ):
        assert "Error processing queue" in tasks.process_server_queue.run()
    dispatch.assert_called_once()
    credit.assert_not_called()


def test_queue_worker_propagates_cancellation_without_starting_a_second_executor():
    with patch("app.tasks.run_queue_dispatch", side_effect=asyncio.CancelledError()) as dispatch:
        with pytest.raises(asyncio.CancelledError):
            tasks.process_server_queue.run()
    dispatch.assert_called_once()


def test_health_worker_uses_operation_owned_session():
    db = database()
    health = SimpleNamespace(check_all_containers=AsyncMock())
    with (
        worker_resources(db),
        patch("app.tasks.HealthCheckService", return_value=health) as service,
    ):
        assert tasks.check_container_health.run() == "Health checks completed"
    service.assert_called_once_with(db)
    health.check_all_containers.assert_awaited_once()


def test_schedule_worker_continues_after_result_and_executor_failures():
    ids = [uuid.uuid4() for _ in range(3)]
    schedules = [ServerSchedule(id=identifier) for identifier in ids]
    for schedule in schedules:
        make_transient_to_detached(schedule)
    service = SimpleNamespace(
        get_due_schedules=AsyncMock(return_value=schedules),
        execute_schedule=AsyncMock(
            side_effect=[
                {"success": True},
                {"success": False, "error": "launch_in_progress"},
                RuntimeError("executor unavailable"),
            ]
        ),
    )
    db = database()
    with (
        worker_resources(db),
        patch("app.services.schedule_service.ScheduleService", return_value=service) as factory,
    ):
        assert tasks.evaluate_schedules.run() == "Executed 1 schedules, 2 failed"
    factory.assert_called_once_with(db)
    assert service.execute_schedule.await_count == 3
    db.rollback.assert_awaited_once()


def test_deadline_joins_cancellation_closes_resources_and_does_not_release_guards(monkeypatch):
    monkeypatch.setattr(settings, "server_launch_timeout_seconds", 0.01)
    db = database()
    cancellation_finished = []

    async def slow():
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cancellation_finished.append(True)

    with (
        worker_resources(db) as owned,
        patch(
            "app.tasks.HealthCheckService", return_value=SimpleNamespace(check_all_containers=slow)
        ),
        patch("app.tasks._release_gpu_devices", new_callable=AsyncMock) as release,
    ):
        output = tasks.check_container_health.run()
    assert "Error checking health" in output and cancellation_finished == [True]
    assert [event for event, _ in owned.events] == ["enter", "exit"]
    release.assert_not_awaited()
    owned.driver.delete_container.assert_not_awaited()


@pytest.mark.parametrize(
    "mode",
    [
        "over_volume",
        "over_plan",
        "near_limit",
        "under_limit",
        "unknown_size",
        "missing_volume",
        "xfs",
        "unlimited",
        "vanished",
    ],
)
def test_volume_worker_commits_measurements_before_guarded_termination(mode):
    volume = SimpleNamespace(
        name="data-volume",
        display_name="Data",
        owner_id=uuid.uuid4(),
        max_size_bytes=100,
        status="active",
        size_bytes=None,
    )
    row = server()
    row.volume_mounts = [SimpleNamespace(volume=None if mode == "missing_volume" else volume)]
    plan = SimpleNamespace(disk_limit=None if mode == "unlimited" else "10g")
    user = SimpleNamespace(id=row.user_id)
    if mode in ("over_plan", "unlimited"):
        volume.max_size_bytes = None
    measured = (
        None
        if mode == "unknown_size"
        else (95 if mode == "near_limit" else 50 if mode in ("under_limit", "unlimited") else 101)
    )
    source = "xfs" if mode == "xfs" else "du"
    should_stop = mode in ("over_volume", "over_plan", "xfs")
    should_warn = mode == "near_limit"
    db = database()
    db.execute.side_effect = [
        result(rows=[(row, plan, user)]),
        result(one=None if mode == "vanished" else (row, plan, user)),
    ]
    volumes = SimpleNamespace(
        _parse_memory=Mock(return_value=100 if mode == "over_plan" else 1000),
        _human_size=Mock(side_effect=lambda size: f"{size}B"),
        measure_volume_size=AsyncMock(return_value=(measured, source)),
    )
    notify = SimpleNamespace(volume_near_limit=AsyncMock())

    async def stop(db_arg, driver_arg, identifier, **kwargs):
        assert db.commit.await_count >= 1
        assert volume.status == "over_limit" and volume.size_bytes == measured
        assert kwargs["stop_reason"] == "volume_quota_exceeded" and identifier == row.id

    with (
        worker_resources(db),
        patch("app.services.volume_service.VolumeService", return_value=volumes),
        patch("app.services.notification_service.NotificationService", return_value=notify),
        patch(
            "app.services.xfs_quota_service.xfs_quota_service._xfs_quota_available",
            return_value=mode == "xfs",
        ),
        patch(
            "app.tasks._stop_server_with_bookkeeping", new=AsyncMock(side_effect=stop)
        ) as terminate,
    ):
        output = tasks.enforce_volume_quotas.run()
    assert f"Stopped {int(should_stop)} servers, warned {int(should_warn)} volumes" in output
    assert terminate.await_count == int(should_stop)
    assert notify.volume_near_limit.await_count == int(should_warn)
    if mode == "xfs":
        assert "XFS=1 du=0" in output
    if mode in ("vanished", "missing_volume"):
        volumes.measure_volume_size.assert_not_awaited()
    elif measured is not None:
        assert volume.size_bytes == measured


def test_unknown_volume_termination_does_not_claim_stopped_or_release_runtime():
    volume = SimpleNamespace(
        name="data",
        display_name="Data",
        owner_id=uuid.uuid4(),
        max_size_bytes=100,
        status="active",
        size_bytes=0,
    )
    row = server()
    row.volume_mounts = [SimpleNamespace(volume=volume)]
    plan, user = SimpleNamespace(disk_limit="10g"), SimpleNamespace(id=row.user_id)
    db = database()
    db.execute.side_effect = [result(rows=[(row, plan, user)]), result(one=(row, plan, user))]
    volumes = SimpleNamespace(
        _parse_memory=Mock(return_value=1000),
        _human_size=Mock(return_value="size"),
        measure_volume_size=AsyncMock(return_value=(101, "du")),
    )
    with (
        worker_resources(db) as owned,
        patch("app.services.volume_service.VolumeService", return_value=volumes),
        patch(
            "app.tasks._stop_server_with_bookkeeping",
            new=AsyncMock(side_effect=LaunchError("recovery_required", 503)),
        ),
        patch("app.tasks._release_gpu_devices", new_callable=AsyncMock) as release,
    ):
        output = tasks.enforce_volume_quotas.run()
    assert "Stopped 0 servers" in output
    assert row.status == "running" and row.container_id == "runtime-id"
    assert volume.status == "over_limit" and volume.size_bytes == 101
    release.assert_not_awaited()
    owned.driver.delete_container.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("reconcile", [False, True])
async def test_stop_bookkeeping_occurs_only_after_verified_termination(reconcile):
    row = server()
    row.plan_id = uuid.uuid4()
    events = []
    db = database(objects={(ServerPlan, row.plan_id): SimpleNamespace(id=row.plan_id)})

    async def terminate(identifier):
        assert identifier == row.id
        events.append("terminated")
        row.status = "stopped"
        return row

    async def commit():
        assert row.status == "stopped" and row.stop_reason == "idle_timeout"
        events.append("commit")

    async def billing(*args):
        events.append("billing")

    async def notification(**kwargs):
        assert kwargs["server_id"] == str(row.id)
        events.append("notification")

    async def broadcast(*args):
        events.append("broadcast")

    db.commit.side_effect = commit
    runtime = Mock()
    with (
        patch("app.tasks.ServerTerminationService") as service,
        patch("app.services.credit_service.CreditService") as credit,
        patch("app.services.notification_service.NotificationService") as notify,
        patch(
            "app.services.notification_service.broadcast_server_status_change",
            new=AsyncMock(side_effect=broadcast),
        ),
    ):
        service.return_value.stop = AsyncMock(side_effect=terminate)
        credit.return_value.reconcile_server_billing = AsyncMock(side_effect=billing)
        notify.return_value.server_stopped = AsyncMock(side_effect=notification)
        await tasks._stop_server_with_bookkeeping(
            db,
            runtime,
            row.id,
            stop_reason="idle_timeout",
            notification_reason="inactivity",
            reconcile_billing=reconcile,
        )
    expected = (
        ["terminated", "commit"]
        + (["billing"] if reconcile else [])
        + ["commit", "notification", "broadcast"]
    )
    assert events == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [LaunchError("recovery_required", 503), asyncio.CancelledError()])
async def test_unconfirmed_stop_cannot_run_bookkeeping_or_release_gpu(error):
    db = database()
    runtime = Mock()
    with (
        patch("app.tasks.ServerTerminationService") as service,
        patch("app.services.credit_service.CreditService") as credit,
        patch("app.services.notification_service.NotificationService") as notify,
        patch("app.tasks._release_gpu_devices", new_callable=AsyncMock) as release,
    ):
        service.return_value.stop = AsyncMock(side_effect=error)
        with pytest.raises(type(error)):
            await tasks._stop_server_with_bookkeeping(
                db,
                runtime,
                uuid.uuid4(),
                stop_reason="idle_timeout",
                notification_reason="inactivity",
            )
    db.commit.assert_not_awaited()
    credit.assert_not_called()
    notify.assert_not_called()
    release.assert_not_awaited()
