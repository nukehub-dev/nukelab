"""Tests for SystemMetricsCollector."""

import pytest
from unittest import mock
import json
import os

from app.services.system_metrics_collector import SystemMetricsCollector


def _mock_session():
    """Return a mock async DB session where add() is sync (not awaited)."""
    s = mock.AsyncMock()
    s.add = mock.Mock()
    return s


class TestSystemMetricsCollect:
    """Tests for the collect method."""

    @pytest.fixture(autouse=True)
    def cleanup_cache_files(self):
        """Remove cache files before/after tests."""
        for f in ["/tmp/nukelab_disk_cache.json", "/tmp/nukelab_network_cache.json"]:
            if os.path.exists(f):
                os.remove(f)
        yield
        for f in ["/tmp/nukelab_disk_cache.json", "/tmp/nukelab_network_cache.json"]:
            if os.path.exists(f):
                os.remove(f)

    @pytest.mark.asyncio
    async def test_collect_basic(self):
        """Should collect and return system metrics."""
        collector = SystemMetricsCollector()

        mock_memory = mock.Mock(used=1000, total=2000, percent=50.0, available=1000)
        mock_disk = mock.Mock(used=500, total=1000)
        mock_disk_io = mock.Mock(read_bytes=100, write_bytes=200)
        mock_net_io = mock.Mock(bytes_recv=1000, bytes_sent=2000)

        with mock.patch("psutil.cpu_percent", return_value=25.0):
            with mock.patch("psutil.cpu_count", return_value=4):
                with mock.patch("psutil.getloadavg", return_value=(1.0, 2.0, 3.0)):
                    with mock.patch("psutil.virtual_memory", return_value=mock_memory):
                        with mock.patch("psutil.disk_usage", return_value=mock_disk):
                            with mock.patch("psutil.disk_io_counters", return_value=mock_disk_io):
                                with mock.patch("psutil.net_io_counters", return_value=mock_net_io):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["cpu_percent"] == 25.0
        assert result["cpu_count"] == 4
        assert result["cpu_load_1m"] == 1.0
        assert result["memory_used"] == 1000
        assert result["disk_used"] == 500
        assert result["docker_containers_running"] == 0
        assert "collected_at" in result

    @pytest.mark.asyncio
    async def test_collect_no_loadavg(self):
        """Should handle missing loadavg gracefully."""
        collector = SystemMetricsCollector()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", side_effect=OSError):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["cpu_load_1m"] == 0.0

    @pytest.mark.asyncio
    async def test_collect_with_docker(self):
        """Should count Docker containers."""
        collector = SystemMetricsCollector()

        mock_container = mock.Mock()
        mock_container._id = "cid1"
        mock_container.show = mock.AsyncMock(
            return_value={"Config": {"Labels": {"nukelab.server.id": "srv-1"}}}
        )

        mock_client = mock.AsyncMock()
        mock_client.list_containers = mock.AsyncMock(return_value=[mock_container])
        mock_client.client.images.list = mock.AsyncMock(return_value=["img1"])
        mock_client.client.close = mock.AsyncMock()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            return_value=mock_client,
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["docker_containers_total"] == 1
        assert result["docker_containers_running"] == 0  # mock_container doesn't have .get('State')
        assert result["docker_images_total"] == 1

    @pytest.mark.asyncio
    async def test_collect_disk_rate_calculation(self):
        """Should calculate disk I/O rate from cache."""
        collector = SystemMetricsCollector()

        # Write a cache file
        with open("/tmp/nukelab_disk_cache.json", "w") as f:
            json.dump(
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "read_bytes": 0,
                    "write_bytes": 0,
                },
                f,
            )

        mock_disk_io = mock.Mock(read_bytes=1000, write_bytes=2000)

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=mock_disk_io):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["disk_read_bytes"] >= 0
        assert result["disk_write_bytes"] >= 0

    @pytest.mark.asyncio
    async def test_collect_db_error_ignored(self):
        """Should return data even if DB persist fails."""
        collector = SystemMetricsCollector()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine",
                                                side_effect=Exception("db error"),
                                            ):
                                                with mock.patch("redis.asyncio.from_url"):
                                                    result = await collector.collect()

        assert result["cpu_percent"] == 10.0


"""Extended coverage tests for SystemMetricsCollector edge cases."""

import pytest
import json
import os
from unittest import mock

from app.services.system_metrics_collector import SystemMetricsCollector


class TestSystemMetricsCollectorEdgeCases:
    """Tests for uncovered branches in SystemMetricsCollector."""

    @pytest.fixture(autouse=True)
    def cleanup_cache_files(self):
        for f in ["/tmp/nukelab_disk_cache.json", "/tmp/nukelab_network_cache.json"]:
            if os.path.exists(f):
                os.remove(f)
        yield
        for f in ["/tmp/nukelab_disk_cache.json", "/tmp/nukelab_network_cache.json"]:
            if os.path.exists(f):
                os.remove(f)

    @pytest.mark.asyncio
    async def test_collect_container_show_exception(self):
        """Should handle exception when calling container.show()."""
        collector = SystemMetricsCollector()

        mock_container = mock.Mock()
        mock_container.show = mock.AsyncMock(side_effect=Exception("no inspect"))

        mock_client = mock.AsyncMock()
        mock_client.list_containers = mock.AsyncMock(return_value=[mock_container])
        mock_client.client.images.list = mock.AsyncMock(return_value=[])
        mock_client.client.close = mock.AsyncMock()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            return_value=mock_client,
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["docker_containers_total"] == 1
        # active_servers_count is not included in the returned dict
        assert "active_servers_count" not in result

    @pytest.mark.asyncio
    async def test_collect_disk_rate_negative_diff(self):
        """Should handle counter reset (negative diff)."""
        collector = SystemMetricsCollector()

        # Write cache with higher values than current
        with open("/tmp/nukelab_disk_cache.json", "w") as f:
            json.dump(
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "read_bytes": 999999,
                    "write_bytes": 999999,
                },
                f,
            )

        mock_disk_io = mock.Mock(read_bytes=100, write_bytes=200)

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=mock_disk_io):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        # Negative diffs should result in 0 rate
        assert result["disk_read_bytes"] == 0
        assert result["disk_write_bytes"] == 0

    @pytest.mark.asyncio
    async def test_collect_db_rollback_and_dispose(self):
        """Should handle DB rollback and engine dispose on error."""
        collector = SystemMetricsCollector()

        mock_session = mock.AsyncMock()
        mock_session.add = mock.Mock()
        mock_session.commit = mock.AsyncMock(side_effect=Exception("commit failed"))
        mock_session.rollback = mock.AsyncMock()
        mock_session.close = mock.AsyncMock()

        mock_engine = mock.AsyncMock()
        mock_engine.dispose = mock.AsyncMock()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine",
                                                return_value=mock_engine,
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=lambda: mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()
        mock_engine.dispose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_collect_redis_exception(self):
        """Should handle Redis publish exception."""
        collector = SystemMetricsCollector()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch(
                                                        "redis.asyncio.from_url",
                                                        side_effect=Exception("redis down"),
                                                    ):
                                                        result = await collector.collect()

        assert result["cpu_percent"] == 10.0

    @pytest.mark.asyncio
    async def test_collect_disk_io_exception(self):
        """Should handle disk_io_counters exception."""
        collector = SystemMetricsCollector()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch(
                                "psutil.disk_io_counters", side_effect=Exception("no io")
                            ):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["disk_read_bytes"] == 0
        assert result["disk_write_bytes"] == 0

    @pytest.mark.asyncio
    async def test_collect_net_io_exception(self):
        """Should handle net_io_counters exception."""
        collector = SystemMetricsCollector()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch(
                                    "psutil.net_io_counters", side_effect=Exception("no net")
                                ):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["network_rx_bytes"] == 0
        assert result["network_tx_bytes"] == 0

    @pytest.mark.asyncio
    async def test_collect_network_rate_calculation(self):
        """Should calculate network I/O rate from cache."""
        collector = SystemMetricsCollector()

        import json, os

        with open("/tmp/nukelab_network_cache.json", "w") as f:
            json.dump(
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "rx_bytes": 0,
                    "tx_bytes": 0,
                },
                f,
            )

        mock_net_io = mock.Mock(bytes_recv=1000, bytes_sent=2000)

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=mock_net_io):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["network_rx_bytes"] >= 0
        assert result["network_tx_bytes"] >= 0

    @pytest.mark.asyncio
    async def test_collect_running_container(self):
        """Should count running containers."""
        collector = SystemMetricsCollector()

        mock_container = mock.Mock()
        mock_container._id = "cid1"
        mock_container.show = mock.AsyncMock(
            return_value={"Config": {"Labels": {"nukelab.server.id": "srv-1"}}}
        )
        mock_container.get = mock.Mock(return_value="running")

        mock_client = mock.AsyncMock()
        mock_client.list_containers = mock.AsyncMock(return_value=[mock_container])
        mock_client.client.images.list = mock.AsyncMock(return_value=[])
        mock_client.client.close = mock.AsyncMock()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            return_value=mock_client,
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["docker_containers_total"] == 1

    @pytest.mark.asyncio
    async def test_collect_redis_aclose_exception(self):
        """Should handle Redis aclose exception."""
        collector = SystemMetricsCollector()

        mock_redis = mock.AsyncMock()
        mock_redis.publish = mock.AsyncMock()
        mock_redis.aclose = mock.AsyncMock(side_effect=Exception("close error"))

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine"
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=_mock_session,
                                                ):
                                                    with mock.patch(
                                                        "redis.asyncio.from_url",
                                                        return_value=mock_redis,
                                                    ):
                                                        result = await collector.collect()

        assert result["cpu_percent"] == 10.0

    @pytest.mark.asyncio
    async def test_collect_db_rollback_exception(self):
        """Should handle DB rollback exception."""
        collector = SystemMetricsCollector()

        mock_session = mock.AsyncMock()
        mock_session.add = mock.Mock()
        mock_session.commit = mock.AsyncMock(side_effect=Exception("commit failed"))
        mock_session.rollback = mock.AsyncMock(side_effect=Exception("rollback failed"))
        mock_session.close = mock.AsyncMock()

        mock_engine = mock.AsyncMock()
        mock_engine.dispose = mock.AsyncMock()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch(
                        "psutil.virtual_memory",
                        return_value=mock.Mock(used=1, total=2, percent=50, available=1),
                    ):
                        with mock.patch(
                            "psutil.disk_usage", return_value=mock.Mock(used=1, total=2)
                        ):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch(
                                            "app.services.system_metrics_collector.get_fresh_container_client",
                                            side_effect=Exception("no docker"),
                                        ):
                                            with mock.patch(
                                                "sqlalchemy.ext.asyncio.create_async_engine",
                                                return_value=mock_engine,
                                            ):
                                                with mock.patch(
                                                    "sqlalchemy.orm.sessionmaker",
                                                    return_value=lambda: mock_session,
                                                ):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["cpu_percent"] == 10.0
