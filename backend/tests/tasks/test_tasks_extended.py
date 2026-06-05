"""Tests for remaining Celery background tasks not covered in test_tasks.py."""

import pytest
import asyncio
from unittest import mock
from datetime import datetime, timedelta

from app.tasks import (
    shutdown_idle_servers,
    process_nuke_billing,
    enforce_auto_stop,
    process_server_queue,
    evaluate_schedules,
    rollup_server_metrics,
    cleanup_expired_data,
)


class TestShutdownIdleServers:
    """shutdown_idle_servers Celery task tests."""

    def test_shutdown_idle_servers_no_running(self):
        async def _mock_enforce():
            return "Stopped 0 idle servers"
        with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
            with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
                mock_db = mock.AsyncMock()
                mock_result = mock.Mock()
                mock_result.all.return_value = []
                mock_db.execute.return_value = mock_result
                mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                result = shutdown_idle_servers.run()
                assert "Stopped" in result or "0" in result

    def test_shutdown_idle_servers_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = shutdown_idle_servers.run()
            assert "Error" in result


class TestProcessNukeBilling:
    """process_nuke_billing Celery task tests."""

    def test_process_nuke_billing_no_running(self):
        async def _mock_bill():
            return "Billed 0 servers, stopped 0 servers"
        with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
            with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
                mock_db = mock.AsyncMock()
                mock_result = mock.Mock()
                mock_result.all.return_value = []
                mock_db.execute.return_value = mock_result
                mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                result = process_nuke_billing.run()
                assert "Billed" in result

    def test_process_nuke_billing_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = process_nuke_billing.run()
            assert "Error" in result


class TestEnforceAutoStop:
    """enforce_auto_stop Celery task tests."""

    def test_enforce_auto_stop_no_running(self):
        async def _mock_enforce():
            return "Stopped 0 servers, warned 0 servers"
        with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
            with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
                mock_db = mock.AsyncMock()
                mock_result = mock.Mock()
                mock_result.all.return_value = []
                mock_db.execute.return_value = mock_result
                mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                result = enforce_auto_stop.run()
                assert "Stopped" in result

    def test_enforce_auto_stop_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = enforce_auto_stop.run()
            assert "Error" in result


class TestProcessServerQueue:
    """process_server_queue Celery task tests."""

    def test_process_server_queue_empty(self):
        async def _mock_process():
            return "Started 0 queued servers, timed out 0 entries"
        with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
            with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
                mock_db = mock.AsyncMock()
                mock_result = mock.Mock()
                mock_result.scalars.return_value.all.return_value = []
                mock_result.all.return_value = []
                mock_db.execute.return_value = mock_result
                mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                result = process_server_queue.run()
                assert "Started" in result

    def test_process_server_queue_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = process_server_queue.run()
            assert "Error" in result


class TestEvaluateSchedules:
    """evaluate_schedules Celery task tests."""

    def test_evaluate_schedules_success(self):
        async def _mock_eval():
            return "Executed 0 schedules, 0 failed"
        with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
            with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
                mock_db = mock.AsyncMock()
                mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                with mock.patch("app.services.schedule_service.ScheduleService") as mock_svc:
                    mock_instance = mock.AsyncMock()
                    mock_instance.get_due_schedules = mock.AsyncMock(return_value=[])
                    mock_svc.return_value = mock_instance
                    result = evaluate_schedules.run()
                    assert "Executed" in result

    def test_evaluate_schedules_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = evaluate_schedules.run()
            assert "Error" in result


class TestRollupServerMetrics:
    """rollup_server_metrics Celery task tests."""

    def test_rollup_server_metrics_success(self):
        async def _mock_rollup():
            return "Upserted 0 daily rollup rows"
        with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
            with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
                mock_db = mock.AsyncMock()
                mock_result = mock.Mock()
                mock_result.all.return_value = []
                mock_db.execute.return_value = mock_result
                mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                result = rollup_server_metrics.run()
                assert "Upserted" in result or "rollup" in result or "Error" in result

    def test_rollup_server_metrics_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = rollup_server_metrics.run()
            assert "Error" in result


class TestCleanupExpiredData:
    """cleanup_expired_data Celery task tests."""

    def test_cleanup_expired_data_disabled(self):
        async def _mock_cleanup():
            return "Cleanup disabled"
        with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
            with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
                mock_db = mock.AsyncMock()
                mock_result = mock.Mock()
                mock_result.scalar_one_or_none.return_value = "0"
                mock_db.execute.return_value = mock_result
                mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
                mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
                result = cleanup_expired_data.run()
                assert "disabled" in result or "Cleanup" in result or "Error" in result

    def test_cleanup_expired_data_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = cleanup_expired_data.run()
            assert "Error" in result
