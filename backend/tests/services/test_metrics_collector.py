"""Tests for MetricsCollector."""

import pytest
from unittest import mock
import json

from app.services.metrics_collector import MetricsCollector


class TestParseContainerStats:
    """Tests for _parse_container_stats method."""

    def test_parse_basic_cpu_memory(self):
        """Should calculate CPU and memory percentages."""
        collector = MetricsCollector()
        stats1 = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100000000},
                "system_cpu_usage": 1000000000,
            },
            "memory_stats": {},
        }
        stats2 = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200000000},
                "system_cpu_usage": 2000000000,
                "online_cpus": 2,
            },
            "memory_stats": {"usage": 512000000, "limit": 1073741824},
            "pids_stats": {"current": 5},
        }

        result = collector._parse_container_stats(stats1, stats2, "srv-1", "cid-1")

        assert result["server_id"] == "srv-1"
        assert result["container_id"] == "cid-1"
        assert result["cpu_cores"] == 2
        assert result["memory_used"] == 512000000
        assert result["memory_total"] == 1073741824
        assert result["memory_percent"] == 47.68  # ~47.68%
        assert result["pids"] == 5
        assert "collected_at" in result

    def test_parse_cpu_zero_system_delta(self):
        """Should handle zero system delta gracefully."""
        collector = MetricsCollector()
        stats1 = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
            },
        }
        stats2 = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 150},
                "system_cpu_usage": 1000,
                "online_cpus": 1,
            },
            "memory_stats": {"usage": 100, "limit": 1000},
        }

        result = collector._parse_container_stats(stats1, stats2, "srv", "cid")
        assert result["cpu_percent"] == 0.0

    def test_parse_network_and_disk(self):
        """Should aggregate network and disk I/O stats."""
        collector = MetricsCollector()
        stats1 = {"cpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 1}}
        stats2 = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 10},
                "system_cpu_usage": 100,
                "online_cpus": 1,
            },
            "memory_stats": {"usage": 100, "limit": 1000},
            "blkio_stats": {
                "io_service_bytes_recursive": [
                    {"op": "Read", "value": 1024},
                    {"op": "Write", "value": 2048},
                ]
            },
            "networks": {
                "eth0": {"rx_bytes": 100, "tx_bytes": 200, "rx_packets": 10, "tx_packets": 20, "rx_errors": 0, "tx_errors": 0},
                "eth1": {"rx_bytes": 50, "tx_bytes": 100, "rx_packets": 5, "tx_packets": 10, "rx_errors": 1, "tx_errors": 2},
            },
        }

        result = collector._parse_container_stats(stats1, stats2, "srv", "cid")
        assert result["disk_read_bytes"] == 1024
        assert result["disk_write_bytes"] == 2048
        assert result["network_rx_bytes"] == 150
        assert result["network_tx_bytes"] == 300
        assert result["network_rx_errors"] == 1
        assert result["network_tx_errors"] == 2

    def test_parse_missing_optional_fields(self):
        """Should handle stats with minimal fields."""
        collector = MetricsCollector()
        stats1 = {"cpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 1}}
        stats2 = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 10},
                "system_cpu_usage": 100,
            },
            "memory_stats": {},
        }

        result = collector._parse_container_stats(stats1, stats2, "srv", "cid")
        assert result["cpu_cores"] == 1  # fallback
        assert result["memory_percent"] == 0.0
        assert result["disk_read_bytes"] == 0
        assert result["network_rx_bytes"] == 0


class TestBroadcastMetrics:
    """Tests for _broadcast_metrics."""

    @pytest.mark.asyncio
    async def test_broadcast_success(self):
        """Should publish metrics to Redis channels."""
        collector = MetricsCollector()
        mock_redis = mock.AsyncMock()
        collector.redis_client = mock_redis

        metrics = {"server_id": "srv-1", "cpu_percent": 50.0}
        await collector._broadcast_metrics(metrics)

        assert mock_redis.publish.call_count == 2
        calls = mock_redis.publish.call_args_list
        assert calls[0][0][0] == "metrics:server:srv-1"
        assert calls[1][0][0] == "metrics:all"

    @pytest.mark.asyncio
    async def test_broadcast_failure_ignored(self):
        """Should silently ignore broadcast errors."""
        collector = MetricsCollector()
        mock_redis = mock.AsyncMock()
        mock_redis.publish = mock.AsyncMock(side_effect=Exception("redis down"))
        collector.redis_client = mock_redis

        metrics = {"server_id": "srv-1", "cpu_percent": 50.0}
        await collector._broadcast_metrics(metrics)  # should not raise


class TestPersistMetrics:
    """Tests for _persist_metrics."""

    @pytest.mark.asyncio
    async def test_persist_success(self):
        """Should save metric to database."""
        collector = MetricsCollector()
        mock_db = mock.AsyncMock()
        mock_db.add = mock.Mock()
        mock_engine = mock.AsyncMock()

        with mock.patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            with mock.patch("sqlalchemy.orm.sessionmaker", return_value=lambda: mock_db):
                with mock.patch("app.services.metrics_collector.ServerMetric") as mock_metric_cls:
                    metrics = {"server_id": "srv-1", "cpu_percent": 50.0}
                    await collector._persist_metrics(metrics)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_db.close.assert_awaited_once()
        mock_engine.dispose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_integrity_error_ignored(self):
        """Should ignore IntegrityError (server deleted)."""
        collector = MetricsCollector()
        mock_db = mock.AsyncMock()
        mock_db.add = mock.Mock()
        mock_db.commit = mock.AsyncMock(side_effect=Exception("IntegrityError"))
        mock_engine = mock.AsyncMock()

        with mock.patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            with mock.patch("sqlalchemy.orm.sessionmaker", return_value=lambda: mock_db):
                with mock.patch("app.services.metrics_collector.ServerMetric"):
                    metrics = {"server_id": "srv-1", "cpu_percent": 50.0}
                    await collector._persist_metrics(metrics)  # should not raise


class TestGetContainerClient:
    @pytest.mark.asyncio
    async def test_get_container_client(self):
        collector = MetricsCollector()
        with mock.patch("app.services.metrics_collector.get_fresh_container_client", new_callable=mock.AsyncMock) as mock_get:
            mock_client = mock.AsyncMock()
            mock_get.return_value = mock_client
            result = await collector._get_container_client()
            assert result == mock_client


class TestGetRedis:
    @pytest.mark.asyncio
    async def test_get_redis_creates_client(self):
        collector = MetricsCollector()
        with mock.patch("app.services.metrics_collector.redis.from_url") as mock_redis:
            mock_client = mock.Mock()
            mock_redis.return_value = mock_client
            result = await collector._get_redis()
            assert result is mock_client
            mock_redis.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_redis_reuses_client(self):
        collector = MetricsCollector()
        mock_client = mock.Mock()
        collector.redis_client = mock_client
        result = await collector._get_redis()
        assert result is mock_client


class TestCollectAll:
    """Tests for collect_all."""

    @pytest.mark.asyncio
    async def test_collect_all_no_containers(self):
        """Should exit gracefully when no containers found."""
        collector = MetricsCollector()
        mock_client = mock.AsyncMock()
        mock_client.list_containers = mock.AsyncMock(return_value=[])

        with mock.patch("app.services.metrics_collector.get_fresh_container_client", return_value=mock_client):
            await collector.collect_all()

        mock_client.list_containers.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_collect_all_client_error(self):
        """Should exit gracefully on Docker client error."""
        collector = MetricsCollector()

        with mock.patch("app.services.metrics_collector.get_fresh_container_client", side_effect=Exception("docker error")):
            await collector.collect_all()  # should not raise

    @pytest.mark.asyncio
    async def test_collect_all_with_containers(self):
        """Should process running containers with labels."""
        collector = MetricsCollector()
        mock_container = mock.AsyncMock()
        mock_container._id = "cid-1"
        mock_container.show = mock.AsyncMock(return_value={
            "Config": {"Labels": {"nukelab.server.id": "srv-1"}}
        })

        mock_client = mock.AsyncMock()
        mock_client.list_containers = mock.AsyncMock(return_value=[mock_container])

        with mock.patch("app.services.metrics_collector.get_fresh_container_client", return_value=mock_client):
            with mock.patch.object(collector, "_collect_container_metrics") as mock_collect:
                await collector.collect_all()

        mock_client.list_containers.assert_awaited_once()
        mock_collect.assert_awaited_once_with("cid-1", "srv-1")

    @pytest.mark.asyncio
    async def test_collect_all_skips_missing_labels(self):
        """Should skip containers without nukelab.server.id label."""
        collector = MetricsCollector()
        mock_container = mock.AsyncMock()
        mock_container._id = "cid-1"
        mock_container.show = mock.AsyncMock(return_value={
            "Config": {"Labels": {}}
        })

        mock_client = mock.AsyncMock()
        mock_client.list_containers = mock.AsyncMock(return_value=[mock_container])

        with mock.patch("app.services.metrics_collector.get_fresh_container_client", return_value=mock_client):
            with mock.patch.object(collector, "_collect_container_metrics") as mock_collect:
                await collector.collect_all()

        mock_collect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_collect_all_closes_client(self):
        """Should close docker client after processing."""
        collector = MetricsCollector()
        mock_client = mock.AsyncMock()
        mock_client.list_containers = mock.AsyncMock(return_value=[])

        with mock.patch("app.services.metrics_collector.get_fresh_container_client", return_value=mock_client):
            await collector.collect_all()

        mock_client.client.close.assert_awaited_once()


class TestCollectContainerMetrics:
    """Tests for _collect_container_metrics."""

    @pytest.mark.asyncio
    async def test_collect_container_metrics_success(self):
        collector = MetricsCollector()
        mock_container = mock.AsyncMock()
        mock_container.stats = mock.AsyncMock(return_value=[{"cpu_stats": {"cpu_usage": {"total_usage": 100}}, "memory_stats": {}}])

        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch("app.services.metrics_collector.get_fresh_container_client", return_value=mock_client):
            with mock.patch.object(collector, "_parse_container_stats", return_value={"server_id": "srv-1"}):
                with mock.patch.object(collector, "_persist_metrics", new_callable=mock.AsyncMock):
                    with mock.patch.object(collector, "_broadcast_metrics", new_callable=mock.AsyncMock):
                        with mock.patch("asyncio.sleep"):
                            await collector._collect_container_metrics("cid-1", "srv-1")

        mock_client.client.containers.get.assert_awaited_once_with("cid-1")
        assert mock_container.stats.call_count == 2

    @pytest.mark.asyncio
    async def test_collect_container_metrics_stats_not_dict(self):
        """Should return early when stats is not a dict."""
        collector = MetricsCollector()
        mock_container = mock.AsyncMock()
        mock_container.stats = mock.AsyncMock(return_value="not-a-dict")

        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch("app.services.metrics_collector.get_fresh_container_client", return_value=mock_client):
            with mock.patch.object(collector, "_parse_container_stats") as mock_parse:
                await collector._collect_container_metrics("cid-1", "srv-1")

        mock_parse.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_container_metrics_container_error(self):
        """Should gracefully handle container fetch errors."""
        collector = MetricsCollector()
        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(side_effect=Exception("not found"))

        with mock.patch("app.services.metrics_collector.get_fresh_container_client", return_value=mock_client):
            await collector._collect_container_metrics("cid-1", "srv-1")

    @pytest.mark.asyncio
    async def test_collect_container_metrics_closes_client(self):
        collector = MetricsCollector()
        mock_container = mock.AsyncMock()
        mock_container.stats = mock.AsyncMock(return_value=[{"cpu_stats": {"cpu_usage": {"total_usage": 100}}, "memory_stats": {}}])

        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch("app.services.metrics_collector.get_fresh_container_client", return_value=mock_client):
            with mock.patch.object(collector, "_parse_container_stats", return_value={"server_id": "srv-1"}):
                with mock.patch.object(collector, "_persist_metrics", new_callable=mock.AsyncMock):
                    with mock.patch.object(collector, "_broadcast_metrics", new_callable=mock.AsyncMock):
                        with mock.patch("asyncio.sleep"):
                            await collector._collect_container_metrics("cid-1", "srv-1")

        mock_client.client.close.assert_awaited_once()
