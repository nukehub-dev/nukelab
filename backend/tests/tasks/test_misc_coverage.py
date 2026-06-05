"""Coverage-focused tests for utility modules and easy wins."""

import pytest
from unittest import mock
from cryptography.fernet import InvalidToken

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
        assert "Cleanup completed" == result

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
    async def test_check_container_health_error(self):
        from app.tasks import check_container_health
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = check_container_health.run()
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
    async def test_process_nuke_billing_error(self):
        from app.tasks import process_nuke_billing
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = process_nuke_billing.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_enforce_auto_stop_error(self):
        from app.tasks import enforce_auto_stop
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = enforce_auto_stop.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_process_server_queue_error(self):
        from app.tasks import process_server_queue
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = process_server_queue.run()
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_evaluate_schedules_error(self):
        from app.tasks import evaluate_schedules
        with mock.patch("app.db.session.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = evaluate_schedules.run()
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

    @pytest.mark.asyncio
    async def test_shutdown_idle_servers_error(self):
        from app.tasks import shutdown_idle_servers
        with mock.patch("app.tasks.AsyncSessionLocal") as mock_session:
            mock_session.side_effect = Exception("fail")
            result = shutdown_idle_servers.run()
            assert "Error" in result



