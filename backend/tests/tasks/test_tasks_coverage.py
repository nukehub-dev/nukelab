# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage-focused tests for app/tasks.py — tasks and branches not exercised
by test_tasks.py / test_enforce_volume_quotas.py."""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest import mock

from fastapi import HTTPException

from app.core.time_utils import utc_now
from app.tasks import (
    _fetch_sidecar_activity,
    _release_gpu_devices,
    check_autovacuum_health,
    cleanup_expired_allowance_overrides,
    cleanup_expired_data,
    enforce_auto_stop,
    enforce_volume_quotas,
    ensure_partitions,
    evaluate_schedules,
    grant_daily_allowance_to_all,
    process_nuke_billing,
    process_server_queue,
    rollup_server_metrics,
    send_notification_channels,
    update_prometheus_business_metrics,
)


def _run_task(task_func, mock_db):
    """Run a Celery task with _run_async executed in-line and both
    AsyncSessionLocal import locations (module-level in app.tasks and the
    re-import inside some task bodies) patched to yield mock_db."""
    with (
        mock.patch(
            "app.tasks._run_async",
            side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
        ),
        mock.patch("app.tasks.AsyncSessionLocal") as ms_tasks,
        mock.patch("app.db.session.AsyncSessionLocal") as ms_session,
    ):
        for ms in (ms_tasks, ms_session):
            ms.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            ms.return_value.__aexit__ = mock.AsyncMock(return_value=False)
        return task_func.run()


def _make_db():
    db = mock.AsyncMock()
    db.commit = mock.AsyncMock()
    db.refresh = mock.AsyncMock()
    db.add = mock.Mock()
    return db


# ── _release_gpu_devices ─────────────────────────────────────


class TestReleaseGpuDevices:
    async def test_releases_devices(self):
        db = mock.AsyncMock()
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_svc:
            mock_svc.return_value.release = mock.AsyncMock()
            await _release_gpu_devices(db, "server-1")
            mock_svc.return_value.release.assert_awaited_once_with("server-1")

    async def test_failure_is_swallowed(self):
        db = mock.AsyncMock()
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_svc:
            mock_svc.return_value.release = mock.AsyncMock(side_effect=Exception("gpu down"))
            # Must not raise — a failed release must not block task-driven stops.
            await _release_gpu_devices(db, "server-1")


# ── send_notification_channels ───────────────────────────────


class TestSendNotificationChannels:
    def _make_db_with_user(self, user):
        db = _make_db()
        res = mock.Mock()
        res.scalar_one_or_none.return_value = user
        db.execute = mock.AsyncMock(return_value=res)
        return db

    _DEFAULT_KWARGS = {
        "event_key": "server.stopped",
        "title": "t",
        "message": "m",
        "severity": "info",
        "notification_type": "server",
    }

    def _call(self, db, overrides):
        kwargs = {**self._DEFAULT_KWARGS, **overrides}
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch("app.tasks.AsyncSessionLocal") as ms,
        ):
            ms.return_value.__aenter__ = mock.AsyncMock(return_value=db)
            ms.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            return send_notification_channels.run(**kwargs)

    def test_user_not_found(self):
        db = self._make_db_with_user(None)
        result = self._call(db, {"user_id": "x"})
        assert result == "User not found"

    def test_email_and_webhook_sent(self):
        user = mock.Mock()
        user.id = uuid.uuid4()
        db = self._make_db_with_user(user)
        with mock.patch(
            "app.services.notification_service.NotificationService"
        ) as mock_notif:
            inst = mock_notif.return_value
            inst._get_user_notification_prefs = mock.AsyncMock(return_value={})
            inst._should_send = mock.Mock(return_value=True)
            inst._send_email_for_notification = mock.AsyncMock()
            inst._send_webhook_for_notification = mock.AsyncMock()
            result = self._call(db, {"user_id": str(user.id), "extra_data": None})
        assert result == "Sent channels: email,webhook for server.stopped"
        inst._send_email_for_notification.assert_awaited_once()
        inst._send_webhook_for_notification.assert_awaited_once()

    def test_no_channels_enabled(self):
        user = mock.Mock()
        user.id = uuid.uuid4()
        db = self._make_db_with_user(user)
        with mock.patch(
            "app.services.notification_service.NotificationService"
        ) as mock_notif:
            inst = mock_notif.return_value
            inst._get_user_notification_prefs = mock.AsyncMock(return_value={})
            inst._should_send = mock.Mock(return_value=False)
            inst._send_email_for_notification = mock.AsyncMock()
            inst._send_webhook_for_notification = mock.AsyncMock()
            result = self._call(db, {"user_id": str(user.id)})
        assert result == "Sent channels: none for server.stopped"
        inst._send_email_for_notification.assert_not_called()
        inst._send_webhook_for_notification.assert_not_called()

    def test_webhook_only(self):
        user = mock.Mock()
        user.id = uuid.uuid4()
        db = self._make_db_with_user(user)
        with mock.patch(
            "app.services.notification_service.NotificationService"
        ) as mock_notif:
            inst = mock_notif.return_value
            inst._get_user_notification_prefs = mock.AsyncMock(return_value={})
            # email=False, webhook=True
            inst._should_send = mock.Mock(side_effect=[False, True])
            inst._send_email_for_notification = mock.AsyncMock()
            inst._send_webhook_for_notification = mock.AsyncMock()
            result = self._call(db, {"user_id": str(user.id), "extra_data": {"k": "v"}})
        assert result == "Sent channels: webhook for server.stopped"

    def test_error_path(self):
        def _raise(coro):
            if asyncio.iscoroutine(coro):
                coro.close()
            raise RuntimeError("boom")

        with mock.patch("app.tasks._run_async", side_effect=_raise):
            result = send_notification_channels.run(
                user_id="x",
                event_key="k",
                title="t",
                message="m",
                severity="info",
                notification_type="server",
            )
        assert "Error: boom" in result


# ── process_nuke_billing extra branches ──────────────────────


class TestProcessNukeBillingExtra:
    def _rows_db(self, rows, balance):
        db = _make_db()
        rows_res = mock.Mock()
        rows_res.all.return_value = rows
        balance_res = mock.Mock()
        balance_res.scalar_one_or_none.return_value = balance
        db.execute = mock.AsyncMock(side_effect=[rows_res, balance_res])
        return db

    def _server_plan(self, cost=10):
        server = mock.Mock()
        server.user_id = uuid.uuid4()
        server.id = uuid.uuid4()
        server.container_id = "cid-1"
        server.status = "running"
        server.name = "srv"
        server.total_cost = 0
        plan = mock.Mock()
        plan.cost_per_hour = cost
        return server, plan

    def test_depletion_auto_stop_disabled(self):
        server, plan = self._server_plan()
        db = self._rows_db([(server, plan)], 0)
        with mock.patch("app.config.settings.server_auto_stop_on_depletion", False):
            result = _run_task(process_nuke_billing, db)
        assert "Billed 0 servers, stopped 0 servers" in result
        assert server.status == "running"

    def test_auto_stop_failure_is_caught(self):
        server, plan = self._server_plan()
        db = self._rows_db([(server, plan)], 0)
        with (
            mock.patch("app.config.settings.server_auto_stop_on_depletion", True),
            mock.patch(
                "app.container.spawner.spawner.delete",
                new=mock.AsyncMock(side_effect=Exception("docker gone")),
            ),
        ):
            result = _run_task(process_nuke_billing, db)
        assert "stopped 0 servers" in result

    def test_minimum_one_credit_billed(self):
        # cost_per_hour=3 -> int(3 * 0.25) == 0 -> minimum 1 credit
        server, plan = self._server_plan(cost=3)
        db = self._rows_db([(server, plan)], 100)
        with mock.patch("app.services.credit_service.CreditService") as mock_credit:
            mock_credit.return_value.consume_credits = mock.AsyncMock()
            result = _run_task(process_nuke_billing, db)
        assert "Billed 1 servers" in result
        assert mock_credit.return_value.consume_credits.await_args.kwargs["amount"] == 1
        assert server.total_cost == 1

    def test_billing_exception_is_caught(self):
        server, plan = self._server_plan()
        db = self._rows_db([(server, plan)], 100)
        with mock.patch("app.services.credit_service.CreditService") as mock_credit:
            mock_credit.return_value.consume_credits = mock.AsyncMock(
                side_effect=Exception("ledger locked")
            )
            result = _run_task(process_nuke_billing, db)
        assert "Billed 0 servers" in result


# ── enforce_auto_stop exception branch ───────────────────────


class TestEnforceAutoStopExtra:
    def test_stop_exception_is_caught(self):
        server = mock.Mock()
        server.user_id = uuid.uuid4()
        server.id = uuid.uuid4()
        server.container_id = "cid-1"
        server.status = "running"
        server.name = "srv"
        server.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)

        db = _make_db()
        res = mock.Mock()
        res.scalars.return_value.all.return_value = [server]
        db.execute = mock.AsyncMock(return_value=res)

        with mock.patch(
            "app.container.spawner.spawner.delete",
            new=mock.AsyncMock(side_effect=Exception("docker gone")),
        ):
            result = _run_task(enforce_auto_stop, db)
        assert "Stopped 0 servers" in result
        assert server.status == "running"


# ── process_server_queue success / GPU paths ─────────────────


class TestProcessServerQueueSuccess:
    def _setup(self, user_prefs):
        entry = mock.Mock()
        entry.user_id = uuid.uuid4()
        entry.server_name = "queued-srv"
        entry.plan_id = uuid.uuid4()
        entry.environment_id = uuid.uuid4()
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
        plan.gpu_limit = 0

        user = mock.Mock()
        user.is_active = True
        user.username = "testuser"
        user.preferences = user_prefs

        env = mock.Mock()
        env.slug = "dev"
        env.image = "img:latest"

        db = _make_db()
        timeout_res = mock.Mock()
        timeout_res.scalars.return_value.all.return_value = []
        plan_res = mock.Mock()
        plan_res.scalar_one_or_none.return_value = plan
        user_res = mock.Mock()
        user_res.scalar_one_or_none.return_value = user
        env_res = mock.Mock()
        env_res.scalar_one_or_none.return_value = env
        db.execute = mock.AsyncMock(side_effect=[timeout_res, plan_res, user_res, env_res])
        return entry, plan, user, db

    def _patch_common(self, entry):
        pool = mock.patch("app.services.resource_pool_service.ResourcePoolService")
        quota = mock.patch("app.services.quota_service.QuotaService")
        gpu = mock.patch("app.api.servers._ensure_gpu_devices", new_callable=mock.AsyncMock)
        spawn = mock.patch(
            "app.container.spawner.spawner.spawn", new_callable=mock.AsyncMock
        )
        notif = mock.patch("app.services.notification_service.NotificationService")
        return pool, quota, gpu, spawn, notif, entry

    def test_successful_spawn(self):
        entry, plan, user, db = self._setup(
            {"max_server_runtime_enabled": True, "max_server_runtime": 30}
        )
        pool, quota, gpu, spawn, notif, _ = self._patch_common(entry)
        with (
            pool as mock_pool,
            quota as mock_quota,
            gpu as mock_gpu,
            spawn as mock_spawn,
            notif as mock_notif,
        ):
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(
                side_effect=[entry, None]
            )
            mock_quota.return_value.check_spawn_allowed = mock.AsyncMock(
                return_value={"allowed": True}
            )
            mock_quota.return_value.increment_usage = mock.AsyncMock()
            mock_gpu.return_value = []
            spawned = mock.Mock()
            mock_spawn.return_value = spawned
            mock_notif.return_value.server_started = mock.AsyncMock()
            result = _run_task(process_server_queue, db)

        assert "Started 1 queued servers, timed out 0 entries" in result
        assert entry.status == "started"
        assert spawned.plan_id == entry.plan_id
        # 30 minutes -> expires_at set in the future
        assert spawned.expires_at is not None
        mock_quota.return_value.increment_usage.assert_awaited_once()

    def test_invalid_max_runtime_pref_falls_back_to_default(self):
        entry, plan, user, db = self._setup(
            {"max_server_runtime_enabled": True, "max_server_runtime": "not-a-number"}
        )
        pool, quota, gpu, spawn, notif, _ = self._patch_common(entry)
        with (
            pool as mock_pool,
            quota as mock_quota,
            gpu as mock_gpu,
            spawn as mock_spawn,
            notif as mock_notif,
        ):
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(
                side_effect=[entry, None]
            )
            mock_quota.return_value.check_spawn_allowed = mock.AsyncMock(
                return_value={"allowed": True}
            )
            mock_quota.return_value.increment_usage = mock.AsyncMock()
            mock_gpu.return_value = []
            mock_spawn.return_value = mock.Mock()
            mock_notif.return_value.server_started = mock.AsyncMock()
            result = _run_task(process_server_queue, db)
        assert "Started 1 queued servers" in result

    def test_gpu_unavailable_fails_entry(self):
        entry, plan, user, db = self._setup({})
        pool, quota, gpu, spawn, notif, _ = self._patch_common(entry)
        with (
            pool as mock_pool,
            quota as mock_quota,
            gpu as mock_gpu,
            spawn as mock_spawn,
            notif,
        ):
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(
                side_effect=[entry, None]
            )
            mock_quota.return_value.check_spawn_allowed = mock.AsyncMock(
                return_value={"allowed": True}
            )
            mock_gpu.side_effect = HTTPException(status_code=503, detail="No GPU devices free")
            result = _run_task(process_server_queue, db)
        assert "Started 0 queued servers" in result
        assert entry.status == "failed"
        assert entry.error_message == "No GPU devices free"
        mock_spawn.assert_not_called()

    def test_paid_plan_deducts_initial_credits(self):
        entry, plan, user, db = self._setup({})
        plan.cost_per_hour = 10
        pool, quota, gpu, spawn, notif, _ = self._patch_common(entry)
        with (
            pool as mock_pool,
            quota as mock_quota,
            gpu as mock_gpu,
            spawn as mock_spawn,
            notif as mock_notif,
            mock.patch("app.config.settings.credits_enabled", True),
            mock.patch("app.services.credit_service.CreditService") as mock_credit,
        ):
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(
                side_effect=[entry, None]
            )
            mock_quota.return_value.check_spawn_allowed = mock.AsyncMock(
                return_value={"allowed": True}
            )
            mock_quota.return_value.increment_usage = mock.AsyncMock()
            mock_credit.return_value.check_sufficient_credits = mock.AsyncMock(
                return_value=True
            )
            mock_credit.return_value.consume_credits = mock.AsyncMock()
            mock_gpu.return_value = []
            mock_spawn.return_value = mock.Mock()
            mock_notif.return_value.server_started = mock.AsyncMock()
            result = _run_task(process_server_queue, db)
        assert "Started 1 queued servers" in result
        mock_credit.return_value.consume_credits.assert_awaited_once()
        assert mock_credit.return_value.consume_credits.await_args.kwargs["amount"] == 10

    def test_default_max_runtime_when_pref_missing(self):
        # max_server_runtime_enabled but no explicit max_server_runtime value
        entry, plan, user, db = self._setup({"max_server_runtime_enabled": True})
        pool, quota, gpu, spawn, notif, _ = self._patch_common(entry)
        with (
            pool as mock_pool,
            quota as mock_quota,
            gpu as mock_gpu,
            spawn as mock_spawn,
            notif as mock_notif,
        ):
            mock_pool.return_value.get_next_in_queue = mock.AsyncMock(
                side_effect=[entry, None]
            )
            mock_quota.return_value.check_spawn_allowed = mock.AsyncMock(
                return_value={"allowed": True}
            )
            mock_quota.return_value.increment_usage = mock.AsyncMock()
            mock_gpu.return_value = []
            mock_spawn.return_value = mock.Mock()
            mock_notif.return_value.server_started = mock.AsyncMock()
            result = _run_task(process_server_queue, db)
        assert "Started 1 queued servers" in result


# ── evaluate_schedules success branch ────────────────────────


class TestEvaluateSchedulesSuccess:
    def test_schedule_success(self):
        schedule = mock.Mock()
        schedule.id = uuid.uuid4()
        db = _make_db()
        with mock.patch("app.services.schedule_service.ScheduleService") as mock_svc:
            inst = mock_svc.return_value
            inst.get_due_schedules = mock.AsyncMock(return_value=[schedule])
            inst.execute_schedule = mock.AsyncMock(return_value={"success": True})
            result = _run_task(evaluate_schedules, db)
        assert "Executed 1 schedules, 0 failed" in result


# ── rollup_server_metrics happy path ─────────────────────────


class TestRollupServerMetrics:
    def test_upserts_daily_rows(self):
        db = _make_db()
        pairs_res = mock.Mock()
        pairs_res.all.return_value = [(uuid.uuid4(), date(2026, 7, 20))]
        agg_row = mock.Mock(
            avg_cpu=1.5,
            peak_cpu=9.0,
            avg_memory=2.0,
            peak_memory=8.0,
            avg_network_rx=10,
            avg_network_tx=20,
            avg_disk_read=30,
            avg_disk_write=40,
            avg_gpu=0.5,
            peak_gpu=1.0,
            data_points=42,
        )
        agg_res = mock.Mock()
        agg_res.one.return_value = agg_row
        upsert_res = mock.Mock()
        db.execute = mock.AsyncMock(side_effect=[pairs_res, agg_res, upsert_res])

        result = _run_task(rollup_server_metrics, db)
        assert "Upserted 1 daily rollup rows" in result
        db.commit.assert_awaited()


# ── cleanup_expired_data ─────────────────────────────────────


def _setting(value):
    res = mock.Mock()
    res.scalar_one_or_none.return_value = value
    return res


def _delete_result(rowcount):
    return mock.Mock(rowcount=rowcount)


class TestCleanupExpiredData:
    def test_full_cleanup(self):
        db = _make_db()
        db.execute = mock.AsyncMock(
            side_effect=[
                _setting("1"),  # cleanup_enabled
                _setting("30"),  # metrics_retention_days
                _setting("not-an-int"),  # system_metrics -> ValueError -> default
                _setting("30"),  # health_check
                _setting("90"),  # alert_history
                _setting("365"),  # activity_log
                _setting("730"),  # credit_transaction
                _setting("30"),  # notification
                _setting("730"),  # daily_rollup
                _setting("30"),  # request_metrics
                _delete_result(5),  # server_metrics
                _delete_result(3),  # system_metrics
                _delete_result(2),  # health_checks
                _delete_result(1),  # alert_history
                _delete_result(4),  # activity_logs
                _delete_result(6),  # credit_transactions rows
                _delete_result(7),  # notifications
                _delete_result(8),  # daily_rollups
                _delete_result(9),  # request_metrics
            ]
        )
        with mock.patch("app.db.partitioning.PartitionManager") as mock_pm:
            mock_pm.return_value.drop_old_partitions = mock.AsyncMock(
                return_value=["p_2026_05", "p_2026_06"]
            )
            result = _run_task(cleanup_expired_data, db)
        # rows: 5+3+2+1+4+6+7+8+9 = 45, plus 2 dropped partitions = 47
        assert "Cleanup complete. Deleted 47 rows" in result
        db.commit.assert_awaited()

    def test_cleanup_disabled(self):
        db = _make_db()
        db.execute = mock.AsyncMock(return_value=_setting("0"))
        result = _run_task(cleanup_expired_data, db)
        assert result == "Cleanup disabled"


# ── ensure_partitions ────────────────────────────────────────


class TestEnsurePartitions:
    def test_creates_partitions(self):
        db = _make_db()
        with mock.patch("app.db.partitioning.PartitionManager") as mock_pm:
            inst = mock_pm.return_value
            inst.PARTITION_CONFIG = {"t1": {}, "t2": {}}
            inst.ensure_partitions = mock.AsyncMock(side_effect=[["p_a"], ["p_b", "p_c"]])
            result = _run_task(ensure_partitions, db)
        assert "Partitions ensured: 3 created (p_a, p_b, p_c)" in result
        db.commit.assert_awaited()

    def test_error_path(self):
        def _raise(coro):
            if asyncio.iscoroutine(coro):
                coro.close()
            raise RuntimeError("ddl fail")

        with mock.patch("app.tasks._run_async", side_effect=_raise):
            result = ensure_partitions.run()
        assert "Error ensuring partitions: ddl fail" in result


# ── check_autovacuum_health ──────────────────────────────────


class TestCheckAutovacuumHealth:
    def _db_with_rows(self, rows):
        db = _make_db()
        res = mock.Mock()
        res.mappings.return_value.all.return_value = rows
        db.execute = mock.AsyncMock(return_value=res)
        return db

    def test_reports_bloated_tables(self):
        db = self._db_with_rows(
            [
                {"table_name": "t1", "n_live_tup": 100, "n_dead_tup": 50, "dead_pct": 33.3},
                {"table_name": "t2", "n_live_tup": 100, "n_dead_tup": 5, "dead_pct": 4.8},
            ]
        )
        result = _run_task(check_autovacuum_health, db)
        assert result == "Autovacuum: 1 table(s) exceed 20% dead tuples"

    def test_all_healthy(self):
        db = self._db_with_rows(
            [
                {"table_name": "t1", "n_live_tup": 100, "n_dead_tup": 5, "dead_pct": 4.8},
                {"table_name": "t2", "n_live_tup": 0, "n_dead_tup": 200, "dead_pct": None},
            ]
        )
        result = _run_task(check_autovacuum_health, db)
        assert result == "Autovacuum: all tables healthy"


# ── update_prometheus_business_metrics ───────────────────────


class TestUpdatePrometheusBusinessMetrics:
    def test_prometheus_disabled(self):
        with mock.patch("app.config.settings.prometheus_enabled", False):
            result = update_prometheus_business_metrics.run()
        assert "Prometheus disabled" in result

    def test_updates_gauges(self):
        db = _make_db()
        users_res = mock.Mock()
        users_res.scalar.return_value = 5
        balance_res = mock.Mock()
        balance_res.scalar.return_value = None  # coalesce miss -> 0
        servers_res = mock.Mock()
        servers_res.all.return_value = [("running", 2), ("stopped", 3)]
        db.execute = mock.AsyncMock(side_effect=[users_res, balance_res, servers_res])

        with (
            mock.patch("app.config.settings.prometheus_enabled", True),
            mock.patch("app.core.prometheus_metrics.set_users_total") as m_users,
            mock.patch("app.core.prometheus_metrics.set_nuke_balance_total") as m_nuke,
            mock.patch("app.core.prometheus_metrics.set_servers_total") as m_servers,
        ):
            result = _run_task(update_prometheus_business_metrics, db)

        assert "users=5" in result
        assert "nuke=0" in result
        m_users.assert_called_once_with(5)
        m_nuke.assert_called_once_with(0)
        m_servers.assert_any_call("running", 2)
        # All six known statuses are reset/set
        assert m_servers.call_count == 6


# ── grant_daily_allowance_to_all failure branches ────────────


class TestGrantDailyAllowanceBranches:
    def test_mixed_outcomes(self):
        now = utc_now()
        users = [
            (uuid.uuid4(), "ok", now - timedelta(hours=1)),
            (uuid.uuid4(), "already", now - timedelta(hours=2)),
            (uuid.uuid4(), "http-err", now - timedelta(hours=3)),
            (uuid.uuid4(), "boom", now - timedelta(hours=4)),
        ]
        db = _make_db()
        res = mock.Mock()
        res.all.return_value = users
        db.execute = mock.AsyncMock(return_value=res)

        with (
            mock.patch("app.services.credit_service.CreditService") as mock_credit,
            mock.patch("app.services.setting_service.SettingService") as mock_settings,
            mock.patch("app.services.activity_service.ActivityService") as mock_activity,
        ):
            mock_credit.return_value.grant_daily_allowance = mock.AsyncMock(
                side_effect=[
                    None,
                    HTTPException(status_code=400, detail="already granted"),
                    HTTPException(status_code=500, detail="weird"),
                    RuntimeError("unexpected"),
                ]
            )
            mock_settings.return_value.get_daily_allowance_login_window_hours = (
                mock.AsyncMock(return_value=48)
            )
            mock_activity.return_value.log = mock.AsyncMock()
            result = _run_task(grant_daily_allowance_to_all, db)

        assert "granted=1" in result
        assert "already_granted=1" in result
        assert "failed=2" in result
        assert "skipped_inactive=0" in result
        assert "total_active=4" in result
        mock_activity.return_value.log.assert_awaited_once()


# ── cleanup_expired_allowance_overrides ──────────────────────


class TestCleanupExpiredAllowanceOverrides:
    def test_clears_expired_overrides(self):
        user = mock.Mock()
        user.daily_allowance_override = 50
        user.daily_allowance_override_until = utc_now() - timedelta(hours=1)

        db = _make_db()
        res = mock.Mock()
        res.scalars.return_value.all.return_value = [user]
        db.execute = mock.AsyncMock(return_value=res)

        result = _run_task(cleanup_expired_allowance_overrides, db)
        assert result == "Cleaned up 1 expired allowance overrides"
        assert user.daily_allowance_override is None
        assert user.daily_allowance_override_until is None
        db.commit.assert_awaited()

    def test_nothing_expired_skips_commit(self):
        db = _make_db()
        res = mock.Mock()
        res.scalars.return_value.all.return_value = []
        db.execute = mock.AsyncMock(return_value=res)

        result = _run_task(cleanup_expired_allowance_overrides, db)
        assert result == "Cleaned up 0 expired allowance overrides"
        db.commit.assert_not_awaited()


# ── error tails (outer try/except of each task) ──────────────


def _run_async_raises(exc):
    def side_effect(coro):
        if asyncio.iscoroutine(coro):
            coro.close()
        raise exc

    return side_effect


class TestTaskErrorTails:
    def test_rollup_error(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db down"))
        ):
            result = rollup_server_metrics.run()
        assert "Error rolling up server metrics: db down" in result

    def test_enforce_volume_quotas_error(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db down"))
        ):
            result = enforce_volume_quotas.run()
        assert "Error in volume quota enforcement: db down" in result

    def test_check_autovacuum_error(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db down"))
        ):
            result = check_autovacuum_health.run()
        assert "Error checking autovacuum: db down" in result

    def test_prometheus_business_metrics_error(self):
        with (
            mock.patch("app.config.settings.prometheus_enabled", True),
            mock.patch(
                "app.tasks._run_async", side_effect=_run_async_raises(Exception("db down"))
            ),
        ):
            result = update_prometheus_business_metrics.run()
        assert "Error updating business metrics: db down" in result

    def test_cleanup_expired_allowance_overrides_fatal(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db down"))
        ):
            result = cleanup_expired_allowance_overrides.run()
        assert "Fatal error: db down" in result


# ── _fetch_sidecar_activity non-200 branch ───────────────────


class TestFetchSidecarActivityExtra:
    @staticmethod
    def _mock_session(response):
        cm = mock.MagicMock()
        cm.__aenter__ = mock.AsyncMock(return_value=response)
        cm.__aexit__ = mock.AsyncMock(return_value=False)
        session = mock.MagicMock()
        session.get = mock.MagicMock(return_value=cm)
        session_cm = mock.MagicMock()
        session_cm.__aenter__ = mock.AsyncMock(return_value=session)
        session_cm.__aexit__ = mock.AsyncMock(return_value=False)
        return session_cm

    def test_non_200_status_yields_no_entry(self):
        resp = mock.AsyncMock()
        resp.status = 503
        with mock.patch("aiohttp.ClientSession", return_value=self._mock_session(resp)):
            result = asyncio.new_event_loop().run_until_complete(
                _fetch_sidecar_activity(["abcdef12-0000-0000-0000-000000000000"])
            )
        assert result == {}


# ── enforce_volume_quotas ────────────────────────────────────


class TestEnforceVolumeQuotasBranches:
    def _make_fixtures(self, volume, *, disk_limit="10g", plan_id=None):
        server = mock.Mock()
        server.id = uuid.uuid4()
        server.container_id = "cid-1"
        server.status = "running"
        server.name = "srv"
        server.plan_id = plan_id
        sv = mock.Mock()
        sv.volume = volume
        server.volume_mounts = [sv]

        plan = mock.Mock()
        plan.disk_limit = disk_limit

        user = mock.Mock()
        user.id = uuid.uuid4()

        db = _make_db()
        res = mock.Mock()
        res.all.return_value = [(server, plan, user)]
        db.execute = mock.AsyncMock(return_value=res)
        return server, plan, user, db

    def _patches(self):
        return (
            mock.patch("app.services.volume_service.VolumeService"),
            mock.patch("app.services.xfs_quota_service.xfs_quota_service"),
            mock.patch("app.container.spawner.spawner.get_status", new_callable=mock.AsyncMock),
            mock.patch("app.container.spawner.spawner.delete", new_callable=mock.AsyncMock),
            mock.patch("app.services.credit_service.CreditService"),
            mock.patch("app.services.quota_service.QuotaService"),
            mock.patch("app.services.notification_service.NotificationService"),
            mock.patch(
                "app.services.notification_service.broadcast_server_status_change",
                new_callable=mock.AsyncMock,
            ),
            mock.patch("app.tasks._release_gpu_devices", new_callable=mock.AsyncMock),
        )

    def _run_enforce(self, db, *, xfs_available=True, parse=10**9, measure=(0, "du"),
                     get_status="running"):
        (
            p_vs,
            p_xfs,
            p_get_status,
            p_delete,
            p_credit,
            p_quota,
            p_notif,
            p_broadcast,
            p_release,
        ) = self._patches()
        with (
            p_vs as mock_vs,
            p_xfs as mock_xfs,
            p_get_status as mock_get_status,
            p_delete as mock_delete,
            p_credit as mock_credit,
            p_quota as mock_quota,
            p_notif as mock_notif,
            p_broadcast,
            p_release,
        ):
            inst = mock_vs.return_value
            inst._parse_memory = mock.Mock(return_value=parse)
            inst._human_size = mock.Mock(side_effect=lambda b: f"{b}B")
            inst.measure_volume_size = mock.AsyncMock(return_value=measure)
            mock_xfs._xfs_quota_available = mock.Mock(return_value=xfs_available)
            mock_get_status.return_value = get_status
            mock_credit.return_value.reconcile_server_billing = mock.AsyncMock()
            mock_quota.return_value.decrement_usage = mock.AsyncMock()
            mock_notif.return_value.server_stopped = mock.AsyncMock()
            mock_notif.return_value.volume_near_limit = mock.AsyncMock()
            result = _run_task(enforce_volume_quotas, db)
            return result, mock_delete, mock_notif

    def test_over_max_size_bytes_stops_server(self):
        volume = mock.Mock()
        volume.name = "vol-1"
        volume.display_name = "data"
        volume.max_size_bytes = 100
        volume.owner_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        server, plan, user, db = self._make_fixtures(volume, plan_id=plan_id)

        result, mock_delete, _ = self._run_enforce(db, measure=(200, "xfs"))

        assert result == "Stopped 1 servers, warned 0 volumes (XFS=1 du=0)"
        assert volume.status == "over_limit"
        assert server.status == "stopped"
        assert server.stop_reason == "volume_quota_exceeded"
        assert server.container_id is None
        mock_delete.assert_awaited_once_with("cid-1")

    def test_over_plan_limit_with_stopped_runtime(self):
        volume = mock.Mock()
        volume.name = "vol-1"
        volume.display_name = None
        volume.max_size_bytes = None
        volume.owner_id = uuid.uuid4()
        server, plan, user, db = self._make_fixtures(volume)  # plan_id None

        result, mock_delete, _ = self._run_enforce(db, parse=10, measure=(20, "xfs"),
                                                   get_status="stopped")

        assert result == "Stopped 1 servers, warned 0 volumes (XFS=1 du=0)"
        assert volume.status == "over_limit"
        # Runtime already stopped: no delete call, just state fixup.
        mock_delete.assert_not_called()

    def test_unmeasurable_volume_is_skipped(self):
        volume = mock.Mock()
        volume.name = "vol-1"
        volume.display_name = "data"
        volume.max_size_bytes = None
        volume.owner_id = uuid.uuid4()
        server, plan, user, db = self._make_fixtures(volume)

        result, _, _ = self._run_enforce(db, measure=(None, "du"))
        assert result == "Stopped 0 servers, warned 0 volumes (XFS=0 du=1)"
        assert server.status == "running"

    def test_near_limit_volume_warns(self):
        volume = mock.Mock()
        volume.name = "vol-1"
        volume.display_name = "data"
        volume.max_size_bytes = 100
        volume.owner_id = uuid.uuid4()
        server, plan, user, db = self._make_fixtures(volume)

        result, _, mock_notif = self._run_enforce(db, measure=(95, "du"))
        assert result == "Stopped 0 servers, warned 1 volumes (XFS=0 du=1)"
        mock_notif.return_value.volume_near_limit.assert_awaited_once()
        assert mock_notif.return_value.volume_near_limit.await_args.kwargs["usage_pct"] == 95

    def test_stop_failure_is_caught(self):
        volume = mock.Mock()
        volume.name = "vol-1"
        volume.display_name = "data"
        volume.max_size_bytes = 100
        volume.owner_id = uuid.uuid4()
        server, plan, user, db = self._make_fixtures(volume)

        (
            p_vs,
            p_xfs,
            p_get_status,
            p_delete,
            p_credit,
            p_quota,
            p_notif,
            p_broadcast,
            p_release,
        ) = self._patches()
        with (
            p_vs as mock_vs,
            p_xfs as mock_xfs,
            p_get_status as mock_get_status,
            p_delete,
            p_credit,
            p_quota,
            p_notif,
            p_broadcast,
            p_release,
        ):
            inst = mock_vs.return_value
            inst._parse_memory = mock.Mock(return_value=10**9)
            inst._human_size = mock.Mock(side_effect=lambda b: f"{b}B")
            inst.measure_volume_size = mock.AsyncMock(return_value=(200, "xfs"))
            mock_xfs._xfs_quota_available = mock.Mock(return_value=True)
            mock_get_status.side_effect = Exception("docker gone")
            result = _run_task(enforce_volume_quotas, db)

        assert result == "Stopped 0 servers, warned 0 volumes (XFS=1 du=0)"
        assert server.status == "running"

    def test_mount_without_volume_and_xfs_unavailable(self):
        server = mock.Mock()
        server.id = uuid.uuid4()
        server.container_id = "cid-1"
        server.status = "running"
        server.name = "srv"
        server.plan_id = None
        sv_orphan = mock.Mock()
        sv_orphan.volume = None
        volume = mock.Mock()
        volume.name = "vol-ok"
        volume.display_name = "ok"
        volume.max_size_bytes = None
        volume.owner_id = uuid.uuid4()
        sv_ok = mock.Mock()
        sv_ok.volume = volume
        server.volume_mounts = [sv_orphan, sv_ok]

        plan = mock.Mock()
        plan.disk_limit = "10g"
        user = mock.Mock()
        user.id = uuid.uuid4()

        db = _make_db()
        res = mock.Mock()
        res.all.return_value = [(server, plan, user)]
        db.execute = mock.AsyncMock(return_value=res)

        result, _, _ = self._run_enforce(db, xfs_available=False, measure=(5, "du"))
        assert result == "Stopped 0 servers, warned 0 volumes (du=1)"
        assert volume.size_bytes == 5
