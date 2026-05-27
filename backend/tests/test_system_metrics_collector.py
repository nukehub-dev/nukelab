"""Tests for SystemMetricsCollector."""

import pytest
from unittest import mock
import json
import os

from app.services.system_metrics_collector import SystemMetricsCollector


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

        mock_memory = mock.Mock(
            used=1000, total=2000, percent=50.0, available=1000
        )
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
                                        with mock.patch("app.services.system_metrics_collector.get_fresh_container_client", side_effect=Exception("no docker")):
                                            with mock.patch("sqlalchemy.ext.asyncio.create_async_engine"):
                                                with mock.patch("sqlalchemy.orm.sessionmaker", return_value=lambda: mock.AsyncMock()):
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
                    with mock.patch("psutil.virtual_memory", return_value=mock.Mock(used=1, total=2, percent=50, available=1)):
                        with mock.patch("psutil.disk_usage", return_value=mock.Mock(used=1, total=2)):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch("app.services.system_metrics_collector.get_fresh_container_client", side_effect=Exception("no docker")):
                                            with mock.patch("sqlalchemy.ext.asyncio.create_async_engine"):
                                                with mock.patch("sqlalchemy.orm.sessionmaker", return_value=lambda: mock.AsyncMock()):
                                                    with mock.patch("redis.asyncio.from_url"):
                                                        result = await collector.collect()

        assert result["cpu_load_1m"] == 0.0

    @pytest.mark.asyncio
    async def test_collect_with_docker(self):
        """Should count Docker containers."""
        collector = SystemMetricsCollector()

        mock_container = mock.Mock()
        mock_container._id = "cid1"
        mock_container.show = mock.AsyncMock(return_value={
            "Config": {"Labels": {"nukelab.server.id": "srv-1"}}
        })

        mock_client = mock.AsyncMock()
        mock_client.list_containers = mock.AsyncMock(return_value=[mock_container])
        mock_client.client.images.list = mock.AsyncMock(return_value=["img1"])
        mock_client.client.close = mock.AsyncMock()

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch("psutil.virtual_memory", return_value=mock.Mock(used=1, total=2, percent=50, available=1)):
                        with mock.patch("psutil.disk_usage", return_value=mock.Mock(used=1, total=2)):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch("app.services.system_metrics_collector.get_fresh_container_client", return_value=mock_client):
                                            with mock.patch("sqlalchemy.ext.asyncio.create_async_engine"):
                                                with mock.patch("sqlalchemy.orm.sessionmaker", return_value=lambda: mock.AsyncMock()):
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
            json.dump({
                "timestamp": "2026-01-01T00:00:00",
                "read_bytes": 0,
                "write_bytes": 0,
            }, f)

        mock_disk_io = mock.Mock(read_bytes=1000, write_bytes=2000)

        with mock.patch("psutil.cpu_percent", return_value=10.0):
            with mock.patch("psutil.cpu_count", return_value=2):
                with mock.patch("psutil.getloadavg", return_value=(0.0, 0.0, 0.0)):
                    with mock.patch("psutil.virtual_memory", return_value=mock.Mock(used=1, total=2, percent=50, available=1)):
                        with mock.patch("psutil.disk_usage", return_value=mock.Mock(used=1, total=2)):
                            with mock.patch("psutil.disk_io_counters", return_value=mock_disk_io):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch("app.services.system_metrics_collector.get_fresh_container_client", side_effect=Exception("no docker")):
                                            with mock.patch("sqlalchemy.ext.asyncio.create_async_engine"):
                                                with mock.patch("sqlalchemy.orm.sessionmaker", return_value=lambda: mock.AsyncMock()):
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
                    with mock.patch("psutil.virtual_memory", return_value=mock.Mock(used=1, total=2, percent=50, available=1)):
                        with mock.patch("psutil.disk_usage", return_value=mock.Mock(used=1, total=2)):
                            with mock.patch("psutil.disk_io_counters", return_value=None):
                                with mock.patch("psutil.net_io_counters", return_value=None):
                                    with mock.patch("asyncio.sleep"):
                                        with mock.patch("app.services.system_metrics_collector.get_fresh_container_client", side_effect=Exception("no docker")):
                                            with mock.patch("sqlalchemy.ext.asyncio.create_async_engine", side_effect=Exception("db error")):
                                                with mock.patch("redis.asyncio.from_url"):
                                                    result = await collector.collect()

        assert result["cpu_percent"] == 10.0
