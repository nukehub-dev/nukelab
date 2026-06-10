import asyncio
import json
from datetime import datetime, UTC
from typing import Dict, List, Optional
import aiodocker
from app.container.client import get_fresh_container_client
from app.models.server_metric import ServerMetric
import redis.asyncio as redis
from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """
    Collects container metrics from Docker Stats API.
    """

    def __init__(self):
        self.container_client = None
        self.redis_client = None
        self._running = False

    async def _get_container_client(self):
        """Get a fresh Docker client for each collection cycle."""
        container_client = await get_fresh_container_client()
        return container_client

    async def _get_redis(self):
        if not self.redis_client:
            self.redis_client = redis.from_url(settings.redis_url)
        return self.redis_client

    async def collect_all(self):
        """Collect metrics for all running containers"""
        container_client = None
        containers = []
        try:
            container_client = await self._get_container_client()
            containers = await container_client.list_containers(
                filters={"status": ["running"], "label": ["nukelab.server.id"]}
            )
        except Exception:
            return

        for container in containers:
            try:
                # aiodocker returns DockerContainer objects, not dicts
                container_id = container._id
                container_info = await container.show()
                labels = container_info.get('Config', {}).get('Labels', {}) or {}
                server_id = labels.get('nukelab.server.id')
                
                if not server_id or not container_id:
                    continue
                
                await self._collect_container_metrics(container_id, server_id)
            except Exception:
                pass
        
        # Close docker client after all processing is done
        if container_client and container_client.client:
            try:
                await container_client.client.close()
            except Exception:
                pass

    async def _collect_container_metrics(self, container_id, server_id):
        """Collect metrics for a single container"""
        container_client = None
        try:
            container_client = await get_fresh_container_client()
            container = await container_client.client.containers.get(container_id)

            # Take two readings 1 second apart for accurate CPU delta.
            # Container's built-in precpu_stats comes from an arbitrary previous
            # query time — could be seconds or minutes ago — making CPU %
            # completely unreliable from a single snapshot.
            stats1_list = await container.stats(stream=False)
            stats1 = stats1_list[0] if isinstance(stats1_list, list) and stats1_list else stats1_list
            if not isinstance(stats1, dict):
                return

            await asyncio.sleep(1.0)

            stats2_list = await container.stats(stream=False)
            stats2 = stats2_list[0] if isinstance(stats2_list, list) and stats2_list else stats2_list
            if not isinstance(stats2, dict):
                return

            metrics = self._parse_container_stats(stats1, stats2, server_id, container_id)
            await self._persist_metrics(metrics)
            await self._broadcast_metrics(metrics)
        except Exception:
            pass
        finally:
            if container_client and container_client.client:
                try:
                    await container_client.client.close()
                except Exception:
                    pass

    def _parse_container_stats(self, stats1: dict, stats2: dict, server_id: str, container_id: str) -> dict:
        """Parse raw container stats into normalized metrics using two 1-second-apart samples"""

        # Use stats2 as the "current" and stats1 as the "previous"
        cpu_stats = stats2.get('cpu_stats', {})
        precpu_stats = stats1.get('cpu_stats', {})  # previous reading

        cpu_usage = cpu_stats.get('cpu_usage', {})
        precpu_usage = precpu_stats.get('cpu_usage', {})

        cpu_delta = (
            cpu_usage.get('total_usage', 0) -
            precpu_usage.get('total_usage', 0)
        )
        system_delta = (
            cpu_stats.get('system_cpu_usage', 0) -
            precpu_stats.get('system_cpu_usage', 0)
        )

        cpu_percent = 0.0
        # online_cpus is the cgroup-visible CPU count (respects CpusetCpus).
        # percpu_usage is often empty on cgroup v2, so we prefer online_cpus.
        cpu_count = cpu_stats.get('online_cpus') or len(cpu_usage.get('percpu_usage', [])) or 1

        if system_delta > 0 and cpu_delta >= 0:
            # cpu_delta and system_delta are both scoped to the same cgroup,
            # so the ratio directly gives the utilization percentage.
            # No need to multiply by cpu_count — that would overcount.
            cpu_percent = (cpu_delta / system_delta) * 100.0

        # Cap at reasonable max to catch calculation glitches
        cpu_percent = min(cpu_percent, cpu_count * 100.0)

        # Memory (doesn't need delta — instantaneous reading)
        memory_stats = stats2.get('memory_stats', {})
        memory_usage = memory_stats.get('usage', 0)
        memory_limit = memory_stats.get('limit', 1)
        memory_percent = (memory_usage / memory_limit) * 100.0 if memory_limit > 0 else 0

        # Disk I/O (cumulative counters — no delta needed for instantaneous)
        blkio_stats = stats2.get('blkio_stats', {})
        io_service_bytes = blkio_stats.get('io_service_bytes_recursive', [])
        disk_read = sum(item['value'] for item in io_service_bytes if item.get('op') == 'Read')
        disk_write = sum(item['value'] for item in io_service_bytes if item.get('op') == 'Write')

        # Network (cumulative counters)
        networks = stats2.get('networks', {})
        network_rx = sum(n.get('rx_bytes', 0) for n in networks.values())
        network_tx = sum(n.get('tx_bytes', 0) for n in networks.values())
        network_rx_packets = sum(n.get('rx_packets', 0) for n in networks.values())
        network_tx_packets = sum(n.get('tx_packets', 0) for n in networks.values())
        network_rx_errors = sum(n.get('rx_errors', 0) for n in networks.values())
        network_tx_errors = sum(n.get('tx_errors', 0) for n in networks.values())

        return {
            'server_id': server_id,
            'container_id': container_id,
            'cpu_percent': round(cpu_percent, 2),
            'cpu_usage_ns': cpu_usage.get('total_usage', 0),
            'cpu_system_ns': cpu_stats.get('system_cpu_usage', 0),
            'cpu_cores': cpu_count,
            'memory_used': memory_usage,
            'memory_total': memory_limit,
            'memory_percent': round(memory_percent, 2),
            'memory_cache': memory_stats.get('stats', {}).get('cache', 0),
            'memory_swap_used': memory_stats.get('stats', {}).get('swap', 0),
            'disk_read_bytes': disk_read,
            'disk_write_bytes': disk_write,
            'network_rx_bytes': network_rx,
            'network_tx_bytes': network_tx,
            'network_rx_packets': network_rx_packets,
            'network_tx_packets': network_tx_packets,
            'network_rx_errors': network_rx_errors,
            'network_tx_errors': network_tx_errors,
            'pids': stats2.get('pids_stats', {}).get('current', 0),
            'collected_at': datetime.now(UTC).replace(tzinfo=None),
        }

    async def _persist_metrics(self, metrics: dict):
        """Save metrics to database using a fresh engine"""
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.pool import NullPool
        from app.config import settings

        _use_pgbouncer = bool(settings.database_pgbouncer_url)
        _connect_args = {"command_timeout": settings.database_query_timeout_seconds}
        if _use_pgbouncer:
            _connect_args["statement_cache_size"] = 0
            _connect_args["prepared_statement_name_func"] = lambda: ""

        _engine_kwargs = {
            "echo": False,
            "future": True,
            "connect_args": _connect_args,
        }
        if _use_pgbouncer:
            _engine_kwargs["poolclass"] = NullPool
        else:
            _engine_kwargs.update(pool_size=1, max_overflow=0)

        _db_url = settings.database_pgbouncer_url if _use_pgbouncer else settings.database_url

        engine = None
        db = None
        try:
            # Create a fresh engine for this thread/event loop
            engine = create_async_engine(_db_url, **_engine_kwargs)
            
            AsyncSessionLocal = sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            
            db = AsyncSessionLocal()
            metric = ServerMetric(**metrics)
            db.add(metric)
            await db.commit()
            logger.debug("Metrics collector: Saved metric to database for server %s", metrics['server_id'])
        except IntegrityError:
            # Server no longer exists in database (e.g., deleted but container still running)
            # Silently skip - metrics are still broadcast via Redis
            pass
        except Exception:
            logger.exception("Metrics collector: Error during persist")
            if db:
                try:
                    await db.rollback()
                except Exception:
                    pass
        finally:
            if db:
                try:
                    await db.close()
                except Exception:
                    pass
            if engine:
                try:
                    await engine.dispose()
                except Exception:
                    pass

    async def _broadcast_metrics(self, metrics: dict):
        """Broadcast metrics via Redis pub/sub"""
        try:
            redis_client = await self._get_redis()
            await redis_client.publish(
                f"metrics:server:{metrics['server_id']}",
                json.dumps(metrics, default=str)
            )
            await redis_client.publish(
                "metrics:all",
                json.dumps(metrics, default=str)
            )
        except Exception:
            logger.exception("Error broadcasting metrics")


collector = MetricsCollector()
