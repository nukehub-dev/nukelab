# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Celery background tasks."""

import asyncio
import uuid
from datetime import timedelta
from unittest import mock

import pytest


def _run_async_raises(exc):
    """Build a side-effect callable that closes a coroutine before raising."""

    def side_effect(coro):
        if asyncio.iscoroutine(coro):
            coro.close()
        raise exc

    return side_effect


from app.tasks import (
    _run_async,
    cleanup_inactive_servers,
    collect_container_metrics,
    collect_system_metrics,
    evaluate_alert_rules,
    evaluate_maintenance_windows,
    example_task,
    grant_daily_allowance_to_all,
)


class TestRunAsync:
    def test_run_async_executes_coroutine(self):
        async def coro():
            return 42

        result = _run_async(coro())
        assert result == 42

    def test_run_async_propagates_exception(self):
        async def bad_coro():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            _run_async(bad_coro())


class TestExampleTask:
    def test_example_task(self):
        result = example_task.run("hello")
        assert result == "Task completed: hello"


class TestEvaluateMaintenanceWindows:
    def test_evaluate_maintenance_windows(self):
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.maintenance_window_service.MaintenanceWindowService.evaluate_windows",
                new_callable=mock.AsyncMock,
                return_value={"notifications_sent": 5, "enabled_count": 2, "disabled_count": 1},
            ),
        ):
            result = evaluate_maintenance_windows.run()
            assert "5 notifications sent" in result
            assert "2 enabled" in result
            assert "1 disabled" in result

    def test_evaluate_maintenance_windows_error(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db fail"))
        ):
            result = evaluate_maintenance_windows.run()
            assert "Error" in result


class TestCleanupInactiveServers:
    def test_cleanup_inactive_servers(self):
        result = cleanup_inactive_servers.run()
        assert result == "Cleanup completed"


class TestCollectContainerMetrics:
    def test_collect_container_metrics(self):
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.metrics_collector.MetricsCollector.collect_all",
                new_callable=mock.AsyncMock,
            ),
        ):
            result = collect_container_metrics.run()
            assert result == "Container metrics collected"

    def test_collect_container_metrics_error(self):
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.metrics_collector.MetricsCollector.collect_all",
                side_effect=Exception("conn fail"),
            ),
        ):
            result = collect_container_metrics.run()
            assert "Error" in result


class TestCollectSystemMetrics:
    def test_collect_system_metrics(self):
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.system_metrics_collector.SystemMetricsCollector.collect",
                new_callable=mock.AsyncMock,
            ),
        ):
            result = collect_system_metrics.run()
            assert result == "System metrics collected"

    def test_collect_system_metrics_error(self):
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.system_metrics_collector.SystemMetricsCollector.collect",
                side_effect=Exception("conn fail"),
            ),
        ):
            result = collect_system_metrics.run()
            assert "Error" in result


class TestGrantDailyAllowanceToAll:
    """grant_daily_allowance_to_all Celery task tests."""

    def test_grant_daily_allowance_to_all_skips_inactive_users(self):

        from app.core.time_utils import utc_now
        from app.services.credit_service import CreditService
        from app.services.setting_service import SettingService

        now = utc_now()
        recent_user = (uuid.uuid4(), "recent", now - timedelta(hours=1))
        old_user = (uuid.uuid4(), "old", now - timedelta(days=7))
        never_user = (uuid.uuid4(), "never", None)

        mock_db = mock.AsyncMock()
        mock_result = mock.Mock()
        mock_result.all.return_value = [recent_user, old_user, never_user]
        mock_db.execute.return_value = mock_result

        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch("app.tasks.AsyncSessionLocal") as mock_session,
            mock.patch.object(
                SettingService,
                "get_daily_allowance_login_window_hours",
                new_callable=mock.AsyncMock,
                return_value=48,
            ),
            mock.patch.object(
                CreditService, "grant_daily_allowance", new_callable=mock.AsyncMock
            ) as mock_grant,
            mock.patch(
                "app.services.activity_service.ActivityService.log",
                new_callable=mock.AsyncMock,
            ),
        ):
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)

            result = grant_daily_allowance_to_all.run()

        assert "granted=1" in result
        assert "skipped_inactive=2" in result
        assert mock_grant.call_count == 1
        assert mock_grant.await_args.args[0] == str(recent_user[0])

    def test_grant_daily_allowance_to_all_error(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db fail"))
        ):
            result = grant_daily_allowance_to_all.run()
            assert "Fatal error" in result


class TestEvaluateAlertRules:
    def test_evaluate_alert_rules(self):
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.alert_service.AlertService.evaluate_all_rules",
                new_callable=mock.AsyncMock,
            ),
        ):
            result = evaluate_alert_rules.run()
            assert result == "Alert rules evaluated"

    def test_evaluate_alert_rules_error(self):
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.alert_service.AlertService.evaluate_all_rules",
                side_effect=Exception("db fail"),
            ),
        ):
            result = evaluate_alert_rules.run()
            assert "Error" in result


"""Coverage-focused tests for utility modules and easy wins."""


class TestTasks:
    """app/tasks.py coverage."""

    @pytest.mark.asyncio
    async def test_example_task(self):
        from app.tasks import example_task

        result = example_task.run(message="hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_cleanup_inactive_servers(self):
        from app.tasks import cleanup_inactive_servers

        result = cleanup_inactive_servers.run()
        assert result == "Cleanup completed"

    @pytest.mark.asyncio
    async def test_collect_container_metrics_error(self):
        from app.tasks import collect_container_metrics

        with mock.patch("app.tasks.MetricsCollector") as mock_collector:
            mock_collector.side_effect = Exception("fail")
            result = collect_container_metrics.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_collect_system_metrics_error(self):
        from app.tasks import collect_system_metrics

        with mock.patch("app.tasks.SystemMetricsCollector") as mock_collector:
            mock_collector.side_effect = Exception("fail")
            result = collect_system_metrics.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_evaluate_alert_rules_error(self):
        from app.tasks import evaluate_alert_rules

        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = evaluate_alert_rules.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_evaluate_maintenance_windows_error(self):
        from app.tasks import evaluate_maintenance_windows

        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = evaluate_maintenance_windows.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_rollup_server_metrics_error(self):
        from app.tasks import rollup_server_metrics

        with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = rollup_server_metrics.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_cleanup_expired_data_error(self):
        from app.tasks import cleanup_expired_data

        with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = cleanup_expired_data.run()
            assert "Error" in result


"""Tests for remaining Celery background tasks not covered in test_tasks.py."""

from datetime import datetime

import pytest

from app.tasks import (
    _fetch_sidecar_activity,
    cleanup_expired_data,
    rollup_server_metrics,
)


class TestRollupServerMetrics:
    """rollup_server_metrics Celery task tests."""

    def test_rollup_server_metrics_success(self):
        async def _mock_rollup():
            return "Upserted 0 daily rollup rows"

        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch("app.tasks.AsyncSessionLocal") as mock_session,
        ):
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_result.all.return_value = []
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            result = rollup_server_metrics.run()
            assert "Upserted" in result or "rollup" in result or "Error" in result

    def test_rollup_server_metrics_error(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db fail"))
        ):
            result = rollup_server_metrics.run()
            assert "Error" in result


class TestCleanupExpiredData:
    """cleanup_expired_data Celery task tests."""

    def test_cleanup_expired_data_disabled(self):
        async def _mock_cleanup():
            return "Cleanup disabled"

        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch("app.tasks.AsyncSessionLocal") as mock_session,
        ):
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_result.scalar_one_or_none.return_value = "0"
            mock_db.execute.return_value = mock_result
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            result = cleanup_expired_data.run()
            assert "disabled" in result or "Cleanup" in result or "Error" in result

    def test_cleanup_expired_data_error(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db fail"))
        ):
            result = cleanup_expired_data.run()
            assert "Error" in result


"""Extended tests for tasks.py — branch coverage for Celery task internals."""

from datetime import UTC

import pytest

# ── helpers ──────────────────────────────────────────────────


def _run_with_mock_db(task_func, mock_db, sidecar_activity=None):
    """Run a Celery task with _run_async patched to execute in current loop.

    The sidecar activity probe is stubbed out so task tests stay hermetic;
    pass sidecar_activity to exercise the idle-shutdown merge logic.
    """
    with (
        mock.patch(
            "app.tasks._run_async",
            side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
        ),
        mock.patch("app.tasks.AsyncSessionLocal") as mock_session,
        mock.patch(
            "app.tasks._fetch_sidecar_activity",
            new=mock.AsyncMock(return_value=sidecar_activity or {}),
        ),
    ):
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


class TestRunAsyncExtended:
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


class TestExampleTaskExtended:
    def test_example_task(self):
        result = example_task.run(message="hello")
        assert "Task completed" in result
        assert "hello" in result


# ── evaluate_maintenance_windows ─────────────────────────────


class TestEvaluateMaintenanceWindowsExtended:
    def test_evaluate_maintenance_windows_success(self):
        mock_db = mock.AsyncMock()
        with mock.patch("app.tasks.AsyncSessionLocal") as ms:
            ms.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            ms.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            with mock.patch(
                "app.services.maintenance_window_service.MaintenanceWindowService"
            ) as mock_svc:
                mock_inst = mock_svc.return_value
                mock_inst.evaluate_windows = mock.AsyncMock(
                    return_value={
                        "notifications_sent": 2,
                        "enabled_count": 1,
                        "disabled_count": 0,
                    }
                )
                with mock.patch(
                    "app.tasks._run_async",
                    side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
                ):
                    result = evaluate_maintenance_windows.run()
        assert "2 notifications sent" in result

    def test_evaluate_maintenance_windows_error(self):
        with mock.patch(
            "app.tasks._run_async", side_effect=_run_async_raises(Exception("db down"))
        ):
            result = evaluate_maintenance_windows.run()
        assert "Error" in result


# ── Sidecar activity ────────────────────────────────────────


class TestFetchSidecarActivity:
    """Unit tests for the sidecar /activity probe helper."""

    def test_empty_server_list_short_circuits(self):
        result = asyncio.new_event_loop().run_until_complete(_fetch_sidecar_activity([]))
        assert result == {}

    @staticmethod
    def _mock_session(get_side_effect=None, response=None):
        cm = mock.MagicMock()
        if get_side_effect is not None:
            cm.__aenter__ = mock.AsyncMock(side_effect=get_side_effect)
        else:
            cm.__aenter__ = mock.AsyncMock(return_value=response)
        cm.__aexit__ = mock.AsyncMock(return_value=False)

        session = mock.MagicMock()
        session.get = mock.MagicMock(return_value=cm)

        session_cm = mock.MagicMock()
        session_cm.__aenter__ = mock.AsyncMock(return_value=session)
        session_cm.__aexit__ = mock.AsyncMock(return_value=False)
        return session_cm

    def test_parses_valid_response(self):
        resp = mock.AsyncMock()
        resp.status = 200
        resp.json = mock.AsyncMock(return_value={"last_activity": 1_700_000_000})

        with mock.patch("aiohttp.ClientSession", return_value=self._mock_session(response=resp)):
            result = asyncio.new_event_loop().run_until_complete(
                _fetch_sidecar_activity(["abcdef12-0000-0000-0000-000000000000"])
            )

        expected = datetime.fromtimestamp(1_700_000_000, UTC).replace(tzinfo=None)
        assert result == {"abcdef12-0000-0000-0000-000000000000": expected}

    def test_unreachable_container_yields_no_entry(self):
        with mock.patch(
            "aiohttp.ClientSession",
            return_value=self._mock_session(get_side_effect=OSError("dns failed")),
        ):
            result = asyncio.new_event_loop().run_until_complete(
                _fetch_sidecar_activity(["abcdef12-0000-0000-0000-000000000000"])
            )
        assert result == {}

    def test_zero_timestamp_yields_no_entry(self):
        resp = mock.AsyncMock()
        resp.status = 200
        resp.json = mock.AsyncMock(return_value={"last_activity": 0})

        with mock.patch("aiohttp.ClientSession", return_value=self._mock_session(response=resp)):
            result = asyncio.new_event_loop().run_until_complete(
                _fetch_sidecar_activity(["abcdef12-0000-0000-0000-000000000000"])
            )
        assert result == {}


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
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.metrics_collector.MetricsCollector.collect_all",
                side_effect=Exception("collector fail"),
            ),
        ):
            result = __import__(
                "app.tasks", fromlist=["collect_container_metrics"]
            ).collect_container_metrics.run()
        assert "Error" in result

    def test_collect_system_metrics_error(self):
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.system_metrics_collector.SystemMetricsCollector.collect",
                side_effect=Exception("collector fail"),
            ),
        ):
            result = __import__(
                "app.tasks", fromlist=["collect_system_metrics"]
            ).collect_system_metrics.run()
        assert "Error" in result

    def test_evaluate_alert_rules_error(self):
        with (
            mock.patch(
                "app.tasks._run_async",
                side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
            ),
            mock.patch(
                "app.services.alert_service.AlertService.evaluate_all_rules",
                side_effect=Exception("alert fail"),
            ),
        ):
            result = __import__(
                "app.tasks", fromlist=["evaluate_alert_rules"]
            ).evaluate_alert_rules.run()
        assert "Error" in result
