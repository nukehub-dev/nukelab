"""Tests for Celery background tasks."""

import pytest
import asyncio
from unittest import mock

from app.tasks import (
    example_task,
    evaluate_maintenance_windows,
    cleanup_inactive_servers,
    collect_container_metrics,
    collect_system_metrics,
    check_container_health,
    evaluate_alert_rules,
    _run_async,
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
        with mock.patch("app.tasks._run_async", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
            with mock.patch("app.services.maintenance_window_service.MaintenanceWindowService.evaluate_windows", new_callable=mock.AsyncMock, return_value={"notifications_sent": 5, "enabled_count": 2, "disabled_count": 1}):
                result = evaluate_maintenance_windows.run()
                assert "5 notifications sent" in result
                assert "2 enabled" in result
                assert "1 disabled" in result

    def test_evaluate_maintenance_windows_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = evaluate_maintenance_windows.run()
            assert "Error" in result


class TestCleanupInactiveServers:
    def test_cleanup_inactive_servers(self):
        result = cleanup_inactive_servers.run()
        assert result == "Cleanup completed"


class TestCollectContainerMetrics:
    def test_collect_container_metrics(self):
        with mock.patch("app.tasks._run_async") as mock_run:
            mock_run.return_value = None
            with mock.patch("app.services.metrics_collector.MetricsCollector.collect_all", new_callable=mock.AsyncMock):
                result = collect_container_metrics.run()
                assert result == "Container metrics collected"

    def test_collect_container_metrics_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("conn fail")):
            result = collect_container_metrics.run()
            assert "Error" in result


class TestCollectSystemMetrics:
    def test_collect_system_metrics(self):
        with mock.patch("app.tasks._run_async") as mock_run:
            mock_run.return_value = None
            with mock.patch("app.services.system_metrics_collector.SystemMetricsCollector.collect", new_callable=mock.AsyncMock):
                result = collect_system_metrics.run()
                assert result == "System metrics collected"

    def test_collect_system_metrics_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("conn fail")):
            result = collect_system_metrics.run()
            assert "Error" in result


class TestCheckContainerHealth:
    def test_check_container_health(self):
        with mock.patch("app.tasks._run_async") as mock_run:
            mock_run.return_value = None
            with mock.patch("app.services.health_check_service.HealthCheckService.check_all_containers", new_callable=mock.AsyncMock):
                result = check_container_health.run()
                assert result == "Health checks completed"

    def test_check_container_health_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = check_container_health.run()
            assert "Error" in result


class TestEvaluateAlertRules:
    def test_evaluate_alert_rules(self):
        with mock.patch("app.tasks._run_async") as mock_run:
            mock_run.return_value = None
            with mock.patch("app.services.alert_service.AlertService.evaluate_all_rules", new_callable=mock.AsyncMock):
                result = evaluate_alert_rules.run()
                assert result == "Alert rules evaluated"

    def test_evaluate_alert_rules_error(self):
        with mock.patch("app.tasks._run_async", side_effect=Exception("db fail")):
            result = evaluate_alert_rules.run()
            assert "Error" in result
