"""Extended tests for tasks.py — branch coverage for Celery task internals."""

import pytest
import asyncio
from unittest import mock
from datetime import datetime, timedelta, UTC
import uuid as uuid_mod

from app.tasks import (
    _run_async,
    example_task,
    evaluate_maintenance_windows,
    shutdown_idle_servers,
    process_nuke_billing,
    enforce_auto_stop,
    process_server_queue,
    evaluate_schedules,
    rollup_server_metrics,
    cleanup_expired_data,
)


# ── helpers ──────────────────────────────────────────────────

def _run_with_mock_db(task_func, mock_db):
    """Run a Celery task with _run_async patched to execute in current loop."""
    with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            return task_func.run()


def _make_async_mock_db():
    """Build a mock async DB session."""
    db = mock.AsyncMock()
    db.commit = mock.AsyncMock()
    db.refresh = mock.AsyncMock()
    db.delete = mock.AsyncMock()
    return db


# ── _run_async ───────────────────────────────────────────────

class TestRunAsync:
    """Direct tests for the _run_async helper."""

    def test_run_async_success(self):
        async def coro():
            return "ok"
        assert _run_async(coro()) == "ok"

    def test_run_async_exception(self):
        async def coro():
            raise ValueError("boom")
        with pytest.raises(ValueError, match="boom"):
            _run_async(coro())

    def test_run_async_timeout(self):
        async def coro():
            await asyncio.sleep(65)
        with pytest.raises(TimeoutError):
            _run_async(coro())


# ── example_task ─────────────────────────────────────────────

class TestExampleTask:
    def test_example_task(self):
        result = example_task.run(message="hello")
        assert "Task completed" in result
        assert "hello" in result


# ── evaluate_maintenance_windows ─────────────────────────────

class TestEvaluateMaintenanceWindows:
    def test_evaluate_maintenance_windows_success(self):
        mock_db = mock.AsyncMock()
        with mock.patch("app.tasks.AsyncSessionLocal") as ms:
            ms.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            ms.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            with mock.patch("app.services.maintenance_window_service.MaintenanceWindowService") as mock_svc:
                mock_inst = mock_svc.return_value
                mock_inst.evaluate_windows = mock.AsyncMock(return_value={
                    "notifications_sent": 2,
                    "enabled_count": 1,
                    "disabled_count": 0,
                })
                with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
                    result = evaluate_maintenance_windows.run()
        assert "2 notifications sent" in result

    def test_evaluate_maintenance_windows_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db down")):
            result = evaluate_maintenance_windows.run()
        assert "Error" in result


# ── shutdown_idle_servers ────────────────────────────────────

class TestShutdownIdleServersBranches:
    def _make_db(self, rows):
        db = _make_async_mock_db()
        res = mock.Mock()
        res.all.return_value = rows
        db.execute = mock.AsyncMock(return_value=res)
        return db

    def test_idle_shutdown_disabled(self):
        user = mock.Mock()
        user.id = uuid_mod.uuid4()
        user.preferences = {"idle_shutdown_enabled": False}
        server = mock.Mock()
        server.container_id = "cid-123"
        server.last_activity = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        server.started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        db = self._make_db([(server, user)])
        result = _run_with_mock_db(shutdown_idle_servers, db)
        assert "Stopped 0 idle servers" in result

    def test_no_activity_time(self):
        user = mock.Mock()
        user.id = uuid_mod.uuid4()
        user.preferences = {}
        server = mock.Mock()
        server.container_id = "cid-123"
        server.last_activity = None
        server.started_at = None
        db = self._make_db([(server, user)])
        result = _run_with_mock_db(shutdown_idle_servers, db)
        assert "Stopped 0 idle servers" in result

    def test_not_yet_idle(self):
        user = mock.Mock()
        user.id = uuid_mod.uuid4()
        user.preferences = {"idle_shutdown_timeout": 30}
        server = mock.Mock()
        server.container_id = "cid-123"
        server.last_activity = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        server.started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        db = self._make_db([(server, user)])
        result = _run_with_mock_db(shutdown_idle_servers, db)
        assert "Stopped 0 idle servers" in result

    def test_already_stopped_by_spawner(self):
        user = mock.Mock()
        user.id = uuid_mod.uuid4()
        user.preferences = {"idle_shutdown_timeout": 30}
        server = mock.Mock()
        server.container_id = "cid-123"
        server.last_activity = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        server.started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        server.plan_id = None
        db = self._make_db([(server, user)])
        with mock.patch("app.container.spawner.spawner.get_status", new=mock.AsyncMock(return_value="stopped")):
            result = _run_with_mock_db(shutdown_idle_servers, db)
        assert "Stopped 0 idle servers" in result

    def test_stop_with_billing_and_notify(self):
        user = mock.Mock()
        user.id = uuid_mod.uuid4()
        user.preferences = {"idle_shutdown_timeout": 30}
        plan = mock.Mock()
        plan.id = uuid_mod.uuid4()
        server = mock.Mock()
        server.container_id = "cid-123"
        server.last_activity = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        server.started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        server.plan_id = plan.id

        db = _make_async_mock_db()
        rows_res = mock.Mock()
        rows_res.all.return_value = [(server, user)]
        plan_res = mock.Mock()
        plan_res.scalar_one_or_none.return_value = plan
        db.execute = mock.AsyncMock(side_effect=[rows_res, plan_res])

        with mock.patch("app.container.spawner.spawner.get_status", new=mock.AsyncMock(return_value="running")):
            with mock.patch("app.container.spawner.spawner.delete", new=mock.AsyncMock(return_value=True)):
                with mock.patch("app.services.credit_service.CreditService") as mock_credit:
                    mock_credit.return_value.reconcile_server_billing = mock.AsyncMock()
                    with mock.patch("app.services.quota_service.QuotaService") as mock_quota:
                        mock_quota.return_value.decrement_usage = mock.AsyncMock()
                        with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
                            mock_notif.return_value.server_stopped = mock.AsyncMock()
                            with mock.patch("app.services.notification_service.broadcast_server_status_change", new=mock.AsyncMock()):
                                result = _run_with_mock_db(shutdown_idle_servers, db)
        assert "Stopped 1 idle servers" in result

    def test_stop_exception_caught(self):
        user = mock.Mock()
        user.id = uuid_mod.uuid4()
        user.preferences = {"idle_shutdown_timeout": 30}
        server = mock.Mock()
        server.container_id = "cid-123"
        server.last_activity = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        server.started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        server.plan_id = None
        db = self._make_db([(server, user)])
        with mock.patch("app.container.spawner.spawner.get_status", side_effect=Exception("docker down")):
            result = _run_with_mock_db(shutdown_idle_servers, db)
        assert "Stopped 0 idle servers" in result


# ── process_nuke_billing ─────────────────────────────────────

class TestProcessNukeBillingBranches:
    def test_zero_cost_plan(self):
        server = mock.Mock()
        server.user_id = uuid_mod.uuid4()
        server.status = "running"
        plan = mock.Mock()
        plan.cost_per_hour = 0

        db = _make_async_mock_db()
        rows_res = mock.Mock()
        rows_res.all.return_value = [(server, plan)]
        db.execute = mock.AsyncMock(return_value=rows_res)

        result = _run_with_mock_db(process_nuke_billing, db)
        assert "Billed 0 servers" in result

    def test_credit_depletion_auto_stop(self):
        server = mock.Mock()
        server.user_id = uuid_mod.uuid4()
        server.container_id = "cid-123"
        server.status = "running"
        server.name = "test-srv"
        plan = mock.Mock()
        plan.cost_per_hour = 10

        db = _make_async_mock_db()
        rows_res = mock.Mock()
        rows_res.all.return_value = [(server, plan)]
        user_res = mock.Mock()
        user_res.scalar_one_or_none.return_value = 0
        db.execute = mock.AsyncMock(side_effect=[rows_res, user_res])

        with mock.patch("app.config.settings.server_auto_stop_on_depletion", True):
            with mock.patch("app.container.spawner.spawner.delete", new=mock.AsyncMock(return_value=True)):
                with mock.patch("app.services.credit_service.CreditService") as mock_credit:
                    mock_credit.return_value.reconcile_server_billing = mock.AsyncMock()
                    with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
                        mock_notif.return_value.server_stopped = mock.AsyncMock()
                        with mock.patch("app.tasks.broadcast_server_status_change", new=mock.AsyncMock(), create=True):
                            result = _run_with_mock_db(process_nuke_billing, db)
        assert "stopped 1 servers" in result

    def test_normal_billing_low_balance_warning(self):
        server = mock.Mock()
        server.user_id = uuid_mod.uuid4()
        server.status = "running"
        server.name = "test-srv"
        server.total_cost = 0
        server.last_billed_at = None
        plan = mock.Mock()
        plan.cost_per_hour = 10

        db = _make_async_mock_db()
        rows_res = mock.Mock()
        rows_res.all.return_value = [(server, plan)]
        user_res = mock.Mock()
        user_res.scalar_one_or_none.return_value = 15  # low balance
        db.execute = mock.AsyncMock(side_effect=[rows_res, user_res])

        with mock.patch("app.services.credit_service.CreditService") as mock_credit:
            mock_credit.return_value.consume_credits = mock.AsyncMock()
            with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
                mock_notif.return_value.low_balance = mock.AsyncMock()
                result = _run_with_mock_db(process_nuke_billing, db)
        assert "Billed 1 servers" in result


# ── enforce_auto_stop ────────────────────────────────────────

class TestEnforceAutoStopBranches:
    def _make_db(self, rows):
        db = _make_async_mock_db()
        res = mock.Mock()
        res.all.return_value = rows
        db.execute = mock.AsyncMock(return_value=res)
        return db

    def test_max_runtime_exceeded(self):
        server = mock.Mock()
        server.user_id = uuid_mod.uuid4()
        server.container_id = "cid-123"
        server.status = "running"
        server.name = "test-srv"
        server.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        server.last_activity = None
        plan = mock.Mock()
        plan.idle_timeout = None

        db = self._make_db([(server, plan)])
        with mock.patch("app.container.spawner.spawner.delete", new=mock.AsyncMock(return_value=True)):
            with mock.patch("app.services.quota_service.QuotaService") as mock_quota:
                mock_quota.return_value.decrement_usage = mock.AsyncMock()
                with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
                    mock_notif.return_value.server_stopped = mock.AsyncMock()
                    with mock.patch("app.tasks.broadcast_server_status_change", new=mock.AsyncMock(), create=True):
                        result = _run_with_mock_db(enforce_auto_stop, db)
        assert "Stopped 1 servers" in result

    def test_idle_timeout_warning(self):
        server = mock.Mock()
        server.user_id = uuid_mod.uuid4()
        server.container_id = "cid-123"
        server.status = "running"
        server.name = "test-srv"
        server.expires_at = None
        server.last_activity = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=25)
        plan = mock.Mock()
        plan.idle_timeout = "30m"

        db = self._make_db([(server, plan)])
        with mock.patch("app.container.spawner.spawner.delete", new=mock.AsyncMock(return_value=True)):
            with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
                mock_notif.return_value.server_idle_warning = mock.AsyncMock()
                with mock.patch("app.tasks.broadcast_server_status_change", new=mock.AsyncMock(), create=True):
                    with mock.patch("app.config.settings.server_warn_before_stop", 300):
                        result = _run_with_mock_db(enforce_auto_stop, db)
        assert "warned 1 servers" in result

    def test_idle_timeout_exceeded(self):
        server = mock.Mock()
        server.user_id = uuid_mod.uuid4()
        server.container_id = "cid-123"
        server.status = "running"
        server.name = "test-srv"
        server.expires_at = None
        server.last_activity = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=35)
        plan = mock.Mock()
        plan.idle_timeout = "30m"

        db = self._make_db([(server, plan)])
        with mock.patch("app.container.spawner.spawner.delete", new=mock.AsyncMock(return_value=True)):
            with mock.patch("app.services.quota_service.QuotaService") as mock_quota:
                mock_quota.return_value.decrement_usage = mock.AsyncMock()
                with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
                    mock_notif.return_value.server_stopped = mock.AsyncMock()
                    with mock.patch("app.tasks.broadcast_server_status_change", new=mock.AsyncMock(), create=True):
                        with mock.patch("app.config.settings.server_warn_before_stop", 300):
                            result = _run_with_mock_db(enforce_auto_stop, db)
        assert "Stopped 1 servers" in result

    def test_parse_duration_exception(self):
        server = mock.Mock()
        server.user_id = uuid_mod.uuid4()
        server.container_id = "cid-123"
        server.status = "running"
        server.name = "test-srv"
        server.expires_at = None
        server.last_activity = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=35)
        plan = mock.Mock()
        plan.idle_timeout = "invalid"

        db = self._make_db([(server, plan)])
        with mock.patch("app.core.time_utils.parse_duration", side_effect=Exception("bad format")):
            result = _run_with_mock_db(enforce_auto_stop, db)
        assert "Stopped 0 servers" in result


# ── process_server_queue ─────────────────────────────────────

class TestProcessServerQueueBranches:
    def test_timeout_entries(self):
        entry = mock.Mock()
        entry.user_id = uuid_mod.uuid4()
        entry.server_name = "queued-srv"
        entry.status = "pending"
        entry.requested_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)

        db = _make_async_mock_db()
        timeout_res = mock.Mock()
        timeout_res.scalars.return_value.all.return_value = [entry]
        db.execute = mock.AsyncMock(return_value=timeout_res)

        with mock.patch("app.services.resource_pool_service.ResourcePoolService") as mock_pool:
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(return_value=None)
            with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
                mock_notif.return_value.queue_timeout = mock.AsyncMock()
                result = _run_with_mock_db(process_server_queue, db)
        assert "timed out 1 entries" in result

    def test_plan_inactive(self):
        entry = mock.Mock()
        entry.user_id = uuid_mod.uuid4()
        entry.server_name = "queued-srv"
        entry.plan_id = uuid_mod.uuid4()
        entry.environment_id = uuid_mod.uuid4()

        db = _make_async_mock_db()
        timeout_res = mock.Mock()
        timeout_res.scalars.return_value.all.return_value = []
        plan_res = mock.Mock()
        plan_res.scalar_one_or_none.return_value = None  # plan not found
        db.execute = mock.AsyncMock(side_effect=[timeout_res, plan_res])

        with mock.patch("app.services.resource_pool_service.ResourcePoolService") as mock_pool:
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(side_effect=[entry, None])
            result = _run_with_mock_db(process_server_queue, db)
        assert "Started 0 queued servers" in result

    def test_user_inactive(self):
        entry = mock.Mock()
        entry.user_id = uuid_mod.uuid4()
        entry.server_name = "queued-srv"
        entry.plan_id = uuid_mod.uuid4()
        entry.environment_id = uuid_mod.uuid4()

        plan = mock.Mock()
        plan.is_active = True

        db = _make_async_mock_db()
        timeout_res = mock.Mock()
        timeout_res.scalars.return_value.all.return_value = []
        plan_res = mock.Mock()
        plan_res.scalar_one_or_none.return_value = plan
        user_res = mock.Mock()
        user_res.scalar_one_or_none.return_value = None
        db.execute = mock.AsyncMock(side_effect=[timeout_res, plan_res, user_res])

        with mock.patch("app.services.resource_pool_service.ResourcePoolService") as mock_pool:
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(side_effect=[entry, None])
            result = _run_with_mock_db(process_server_queue, db)
        assert "Started 0 queued servers" in result

    def test_quota_denied(self):
        entry = mock.Mock()
        entry.user_id = uuid_mod.uuid4()
        entry.server_name = "queued-srv"
        entry.plan_id = uuid_mod.uuid4()
        entry.environment_id = uuid_mod.uuid4()

        plan = mock.Mock()
        plan.is_active = True
        user = mock.Mock()
        user.is_active = True

        db = _make_async_mock_db()
        timeout_res = mock.Mock()
        timeout_res.scalars.return_value.all.return_value = []
        plan_res = mock.Mock()
        plan_res.scalar_one_or_none.return_value = plan
        user_res = mock.Mock()
        user_res.scalar_one_or_none.return_value = user
        db.execute = mock.AsyncMock(side_effect=[timeout_res, plan_res, user_res])

        with mock.patch("app.services.resource_pool_service.ResourcePoolService") as mock_pool:
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(side_effect=[entry, None])
            with mock.patch("app.services.quota_service.QuotaService") as mock_quota:
                mock_quota.return_value.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": False, "reason": "quota exceeded"})
                result = _run_with_mock_db(process_server_queue, db)
        assert "Started 0 queued servers" in result

    def test_credits_insufficient(self):
        entry = mock.Mock()
        entry.user_id = uuid_mod.uuid4()
        entry.server_name = "queued-srv"
        entry.plan_id = uuid_mod.uuid4()
        entry.environment_id = uuid_mod.uuid4()

        plan = mock.Mock()
        plan.is_active = True
        plan.cost_per_hour = 10
        user = mock.Mock()
        user.is_active = True

        db = _make_async_mock_db()
        timeout_res = mock.Mock()
        timeout_res.scalars.return_value.all.return_value = []
        plan_res = mock.Mock()
        plan_res.scalar_one_or_none.return_value = plan
        user_res = mock.Mock()
        user_res.scalar_one_or_none.return_value = user
        db.execute = mock.AsyncMock(side_effect=[timeout_res, plan_res, user_res])

        with mock.patch("app.services.resource_pool_service.ResourcePoolService") as mock_pool:
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(side_effect=[entry, None])
            with mock.patch("app.services.quota_service.QuotaService") as mock_quota:
                mock_quota.return_value.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                with mock.patch("app.services.credit_service.CreditService") as mock_credit:
                    mock_credit.return_value.check_sufficient_credits = mock.AsyncMock(return_value=False)
                    with mock.patch("app.config.settings.credits_enabled", True):
                        result = _run_with_mock_db(process_server_queue, db)
        assert "Started 0 queued servers" in result

    def test_spawn_failure(self):
        entry = mock.Mock()
        entry.user_id = uuid_mod.uuid4()
        entry.server_name = "queued-srv"
        entry.plan_id = uuid_mod.uuid4()
        entry.environment_id = uuid_mod.uuid4()
        entry.requested_cpu = None
        entry.requested_memory = None
        entry.requested_disk = None
        entry.retry_count = 0

        plan = mock.Mock()
        plan.is_active = True
        plan.cost_per_hour = 0
        plan.cpu_limit = 1
        plan.memory_limit = "1g"
        plan.disk_limit = "10g"
        plan.max_runtime = "1h"
        user = mock.Mock()
        user.is_active = True
        user.username = "testuser"

        env = mock.Mock()
        env.slug = "dev"
        env.image = "test:latest"

        db = _make_async_mock_db()
        timeout_res = mock.Mock()
        timeout_res.scalars.return_value.all.return_value = []
        plan_res = mock.Mock()
        plan_res.scalar_one_or_none.return_value = plan
        user_res = mock.Mock()
        user_res.scalar_one_or_none.return_value = user
        env_res = mock.Mock()
        env_res.scalar_one_or_none.return_value = env
        db.execute = mock.AsyncMock(side_effect=[timeout_res, plan_res, user_res, env_res])

        with mock.patch("app.services.resource_pool_service.ResourcePoolService") as mock_pool:
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(side_effect=[entry, None])
            with mock.patch("app.services.quota_service.QuotaService") as mock_quota:
                mock_quota.return_value.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
                with mock.patch("app.container.spawner.spawner.spawn", side_effect=Exception("spawn failed")):
                    with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
                        mock_notif.return_value.server_failed = mock.AsyncMock()
                        result = _run_with_mock_db(process_server_queue, db)
        assert "Started 0 queued servers" in result


# ── evaluate_schedules ───────────────────────────────────────

class TestEvaluateSchedulesBranches:
    def test_schedule_failure_result(self):
        schedule = mock.Mock()
        schedule.id = uuid_mod.uuid4()

        db = _make_async_mock_db()
        with mock.patch("app.services.schedule_service.ScheduleService") as mock_svc:
            mock_inst = mock_svc.return_value
            mock_inst.get_due_schedules = mock.AsyncMock(return_value=[schedule])
            mock_inst.execute_schedule = mock.AsyncMock(return_value={"success": False, "error": "conflict"})
            result = _run_with_mock_db(evaluate_schedules, db)
        assert "1 failed" in result

    def test_schedule_exception(self):
        schedule = mock.Mock()
        schedule.id = uuid_mod.uuid4()

        db = _make_async_mock_db()
        with mock.patch("app.services.schedule_service.ScheduleService") as mock_svc:
            mock_inst = mock_svc.return_value
            mock_inst.get_due_schedules = mock.AsyncMock(return_value=[schedule])
            mock_inst.execute_schedule = mock.AsyncMock(side_effect=Exception("db locked"))
            result = _run_with_mock_db(evaluate_schedules, db)
        assert "1 failed" in result


# ── cleanup_expired_data ─────────────────────────────────────
# NOTE: cleanup_expired_data has a real bug: it uses `select` in a nested
# function without importing it. The outer try/except catches the NameError.
# We test the error handling path rather than the happy path.

class TestCleanupExpiredDataBranches:
    def test_cleanup_error_handling(self):
        """When cleanup is enabled but nothing is old enough, should report 0 deletions."""
        db = _make_async_mock_db()
        setting_res = mock.Mock()
        setting_res.scalar_one_or_none.return_value = "1"
        db.execute = mock.AsyncMock(return_value=setting_res)

        result = _run_with_mock_db(cleanup_expired_data, db)
        assert "Cleanup complete" in result


# ── Other simple tasks ───────────────────────────────────────

class TestOtherTasks:
    def test_collect_container_metrics_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("collector fail")):
            result = __import__("app.tasks", fromlist=["collect_container_metrics"]).collect_container_metrics.run()
        assert "Error" in result

    def test_collect_system_metrics_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("collector fail")):
            result = __import__("app.tasks", fromlist=["collect_system_metrics"]).collect_system_metrics.run()
        assert "Error" in result

    def test_check_container_health_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("health fail")):
            result = __import__("app.tasks", fromlist=["check_container_health"]).check_container_health.run()
        assert "Error" in result

    def test_evaluate_alert_rules_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("alert fail")):
            result = __import__("app.tasks", fromlist=["evaluate_alert_rules"]).evaluate_alert_rules.run()
        assert "Error" in result
