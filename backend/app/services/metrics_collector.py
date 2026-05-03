import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional
import aiodocker
from app.docker.client import get_fresh_docker_client
from app.db.session import AsyncSessionLocal
from app.models.server import Server
from app.models.server_metric import ServerMetric
from sqlalchemy import select
import redis.asyncio as redis
from app.config import settings


class MetricsCollector:
    """
    Collects container metrics from Docker Stats API.
    """

    def __init__(self):
        self.docker = None
        self.redis_client = None
        self._running = False

    async def _get_docker(self):
        """Get a fresh Docker client for each collection cycle."""
        docker = await get_fresh_docker_client()
        return docker

    async def _get_redis(self):
        if not self.redis_client:
            self.redis_client = redis.from_url(settings.redis_url)
        return self.redis_client

    async def collect_all(self):
        """Collect metrics for all running containers"""
        docker = None
        containers = []
        try:
            docker = await self._get_docker()
            containers = await docker.list_containers(
                filters={"status": ["running"], "label": ["nukelab.server.id"]}
            )
            print(f"Metrics collector: Found {len(containers)} containers with nukelab.server.id label")
        except Exception as e:
            print(f"Error listing containers: {e}")
            return

        for container in containers:
            try:
                # aiodocker returns DockerContainer objects, not dicts
                container_id = container._id
                container_info = await container.show()
                labels = container_info.get('Config', {}).get('Labels', {}) or {}
                server_id = labels.get('nukelab.server.id')
                
                print(f"Metrics collector: Processing container {container_id[:12]} for server {server_id}")
                
                if not server_id or not container_id:
                    print(f"Metrics collector: Skipping container {container_id[:12]} - missing server_id or container_id")
                    continue
                
                async with AsyncSessionLocal() as db:
                    result = await db.execute(select(Server).where(Server.id == server_id))
                    server = result.scalar_one_or_none()
                    if not server:
                        print(f"Metrics collector: Skipping container {container_id[:12]} - server {server_id} not found in database")
                        continue
                    
                await self._collect_container_metrics(container_id, server_id)
            except Exception as e:
                container_id = getattr(container, '_id', 'unknown')
                print(f"Error collecting metrics for {container_id}: {e}")
        
        # Close docker client after all processing is done
        if docker and docker.client:
            try:
                await docker.client.close()
            except Exception:
                pass

    async def _collect_container_metrics(self, container_id, server_id):
        """Collect metrics for a single container"""
        docker = None
        try:
            print(f"Metrics collector: Step 1 - Getting docker client...")
            docker = await get_fresh_docker_client()
            print(f"Metrics collector: Step 2 - Getting container {container_id[:12]}...")
            container = await docker.client.containers.get(container_id)
            print(f"Metrics collector: Step 3 - Getting stats...")
            stats_list = await container.stats(stream=False)
            print(f"Metrics collector: Got stats for container {container_id[:12]}")
            
            # stats() returns a list with one dict item when stream=False
            stats = stats_list[0] if isinstance(stats_list, list) and stats_list else stats_list
            if not isinstance(stats, dict):
                print(f"Metrics collector: Unexpected stats format: {type(stats)}")
                return

            print(f"Metrics collector: Step 4 - Parsing stats...")
            metrics = self._parse_docker_stats(stats, server_id, container_id)
            print(f"Metrics collector: Parsed metrics - CPU: {metrics['cpu_percent']}%, Memory: {metrics['memory_percent']}%")

            print(f"Metrics collector: Step 5 - Persisting metrics...")
            await self._persist_metrics(metrics)
            print(f"Metrics collector: Step 6 - Broadcasting metrics...")
            await self._broadcast_metrics(metrics)
            print(f"Metrics collector: Saved and broadcast metrics for server {server_id}")
        except Exception as e:
            import traceback
            print(f"Error collecting metrics for container {container_id}: {e}")
            print(f"Traceback: {traceback.format_exc()}")
        finally:
            if docker and docker.client:
                try:
                    await docker.client.close()
                except Exception:
                    pass

    def _parse_docker_stats(self, stats: dict, server_id: str, container_id: str) -> dict:
        """Parse raw Docker stats into normalized metrics"""

        cpu_stats = stats.get('cpu_stats', {})
        precpu_stats = stats.get('precpu_stats', {})

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
        cpu_count = 1
        if system_delta > 0 and cpu_delta > 0:
            percpu = cpu_usage.get('percpu_usage', [])
            cpu_count = len(percpu) if percpu else 1
            cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0

        # Memory
        memory_stats = stats.get('memory_stats', {})
        memory_usage = memory_stats.get('usage', 0)
        memory_limit = memory_stats.get('limit', 1)
        memory_percent = (memory_usage / memory_limit) * 100.0 if memory_limit > 0 else 0

        # Disk I/O
        blkio_stats = stats.get('blkio_stats', {})
        io_service_bytes = blkio_stats.get('io_service_bytes_recursive', [])
        disk_read = sum(item['value'] for item in io_service_bytes if item.get('op') == 'Read')
        disk_write = sum(item['value'] for item in io_service_bytes if item.get('op') == 'Write')

        # Network
        networks = stats.get('networks', {})
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
            'pids': stats.get('pids_stats', {}).get('current', 0),
            'collected_at': datetime.utcnow(),
        }

    async def _persist_metrics(self, metrics: dict):
        """Save metrics to database using a fresh engine"""
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from app.config import settings
        
        engine = None
        db = None
        try:
            # Create a fresh engine for this thread/event loop
            engine = create_async_engine(
                settings.database_url,
                echo=False,
                future=True,
                pool_size=1,
                max_overflow=0,
            )
            
            AsyncSessionLocal = sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            
            db = AsyncSessionLocal()
            metric = ServerMetric(**metrics)
            db.add(metric)
            await db.commit()
            print(f"Metrics collector: Saved metric to database for server {metrics['server_id']}")
        except Exception as e:
            print(f"Metrics collector: Error during persist: {e}")
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
        except Exception as e:
            print(f"Error broadcasting metrics: {e}")


collector = MetricsCollector()
