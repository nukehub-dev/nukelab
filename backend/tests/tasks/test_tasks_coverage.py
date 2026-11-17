# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage-focused tests for app/tasks.py — tasks and branches not exercised
by test_tasks.py / test_enforce_volume_quotas.py."""

import asyncio
import uuid
from datetime import date, timedelta
from unittest import mock

from fastapi import HTTPException

from app.core.time_utils import utc_now
from app.tasks import (
    _fetch_sidecar_activity,
    _release_gpu_devices,
    check_autovacuum_health,
    cleanup_expired_allowance_overrides,
    cleanup_expired_data,
    ensure_partitions,
    grant_daily_allowance_to_all,
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
        with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
            inst = mock_notif.return_value
            inst._get_user_notification_prefs = mock.AsyncMock(return_value={})
            # email=True, webhook=True, push=False
            inst._should_send = mock.Mock(side_effect=[True, True, False])
            inst._send_email_for_notification = mock.AsyncMock()
            inst._send_webhook_for_notification = mock.AsyncMock()
            inst._send_push_for_notification = mock.AsyncMock()
            result = self._call(db, {"user_id": str(user.id), "extra_data": None})
        assert result == "Sent channels: email,webhook for server.stopped"
        inst._send_email_for_notification.assert_awaited_once()
        inst._send_webhook_for_notification.assert_awaited_once()
        inst._send_push_for_notification.assert_not_awaited()

    def test_no_channels_enabled(self):
        user = mock.Mock()
        user.id = uuid.uuid4()
        db = self._make_db_with_user(user)
        with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
            inst = mock_notif.return_value
            inst._get_user_notification_prefs = mock.AsyncMock(return_value={})
            inst._should_send = mock.Mock(return_value=False)
            inst._send_email_for_notification = mock.AsyncMock()
            inst._send_webhook_for_notification = mock.AsyncMock()
            inst._send_push_for_notification = mock.AsyncMock()
            result = self._call(db, {"user_id": str(user.id)})
        assert result == "Sent channels: none for server.stopped"
        inst._send_email_for_notification.assert_not_called()
        inst._send_webhook_for_notification.assert_not_called()
        inst._send_push_for_notification.assert_not_awaited()

    def test_webhook_only(self):
        user = mock.Mock()
        user.id = uuid.uuid4()
        db = self._make_db_with_user(user)
        with mock.patch("app.services.notification_service.NotificationService") as mock_notif:
            inst = mock_notif.return_value
            inst._get_user_notification_prefs = mock.AsyncMock(return_value={})
            # email=False, webhook=True, push=False
            inst._should_send = mock.Mock(side_effect=[False, True, False])
            inst._send_email_for_notification = mock.AsyncMock()
            inst._send_webhook_for_notification = mock.AsyncMock()
            inst._send_push_for_notification = mock.AsyncMock()
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
            mock_settings.return_value.get_daily_allowance_login_window_hours = mock.AsyncMock(
                return_value=48
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

    def test_check_autovacuum_error(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db down"))
        ):
            result = check_autovacuum_health.run()
        assert "Error checking autovacuum: db down" in result

    def test_prometheus_business_metrics_error(self):
        with (
            mock.patch("app.config.settings.prometheus_enabled", True),
            mock.patch("app.tasks._run_async", side_effect=_run_async_raises(Exception("db down"))),
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
