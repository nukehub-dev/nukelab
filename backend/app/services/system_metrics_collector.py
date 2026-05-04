import json
import psutil
from datetime import datetime
from typing import Dict
from app.db.session import AsyncSessionLocal
from app.models.system_metric import SystemMetric
from app.docker.client import get_fresh_docker_client
from app.config import settings
import redis.asyncio as redis


class SystemMetricsCollector:
    """Collect host-level system metrics"""

    async def collect(self) -> Dict:
        """Collect current system metrics"""

        # CPU
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count()
        try:
            load_avg = psutil.getloadavg()
        except (AttributeError, OSError):
            load_avg = (0.0, 0.0, 0.0)

        # Memory
        memory = psutil.virtual_memory()

        # Disk
        disk = psutil.disk_usage('/')
        try:
            disk_io = psutil.disk_io_counters()
        except Exception:
            disk_io = None

        # Network
        try:
            net_io = psutil.net_io_counters()
        except Exception:
            net_io = None

        # Docker stats - count only server containers with nukelab.server.id label
        docker_containers_running = 0
        docker_containers_total = 0
        docker_images_total = 0
        active_servers_count = 0
        docker = None
        try:
            docker = await get_fresh_docker_client()
            containers = await docker.list_containers()
            docker_containers_total = len(containers)
            docker_containers_running = sum(
                1 for c in containers if c.get('State') == 'running'
            )
            # Count actual nukelab servers (containers with nukelab.server.id label)
            for container in containers:
                try:
                    container_info = await container.show()
                    labels = container_info.get('Config', {}).get('Labels', {}) or {}
                    if labels.get('nukelab.server.id'):
                        active_servers_count += 1
                except Exception:
                    pass
            images = await docker.client.images.list()
            docker_images_total = len(images)
        except Exception:
            pass
        finally:
            if docker and docker.client:
                try:
                    await docker.client.close()
                except Exception:
                    pass

        # Calculate network throughput rate (bytes/sec) by comparing with previous reading
        network_rx_rate = 0
        network_tx_rate = 0
        try:
            # Try to get previous values from a simple cache file
            import os
            cache_file = '/tmp/nukelab_network_cache.json'
            prev_data = None
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r') as f:
                        prev_data = json.load(f)
                except Exception:
                    pass

            if prev_data and net_io:
                time_diff = (datetime.utcnow() - datetime.fromisoformat(prev_data['timestamp'])).total_seconds()
                if time_diff > 0:
                    rx_diff = net_io.bytes_recv - prev_data.get('rx_bytes', 0)
                    tx_diff = net_io.bytes_sent - prev_data.get('tx_bytes', 0)
                    # Handle counter reset (if system rebooted)
                    if rx_diff >= 0:
                        network_rx_rate = max(0, rx_diff / time_diff)
                    if tx_diff >= 0:
                        network_tx_rate = max(0, tx_diff / time_diff)

            # Save current values
            if net_io:
                with open(cache_file, 'w') as f:
                    json.dump({
                        'timestamp': datetime.utcnow().isoformat(),
                        'rx_bytes': net_io.bytes_recv,
                        'tx_bytes': net_io.bytes_sent,
                    }, f)
        except Exception:
            pass

        data = {
            'host': 'localhost',
            'cpu_percent': cpu_percent,
            'cpu_count': cpu_count,
            'cpu_load_1m': load_avg[0],
            'cpu_load_5m': load_avg[1],
            'cpu_load_15m': load_avg[2],
            'memory_used': memory.used,
            'memory_total': memory.total,
            'memory_percent': memory.percent,
            'memory_available': memory.available,
            'disk_used': disk.used,
            'disk_total': disk.total,
            'disk_percent': (disk.used / disk.total) * 100 if disk.total else 0,
            'disk_read_bytes': disk_io.read_bytes if disk_io else 0,
            'disk_write_bytes': disk_io.write_bytes if disk_io else 0,
            # Network throughput rates (bytes/sec)
            'network_rx_bytes': int(network_rx_rate),
            'network_tx_bytes': int(network_tx_rate),
            # Cumulative counters (for reference)
            'network_rx_total': net_io.bytes_recv if net_io else 0,
            'network_tx_total': net_io.bytes_sent if net_io else 0,
            # Server counts
            'active_servers': active_servers_count,
            'total_servers': docker_containers_running,
            'docker_containers_running': docker_containers_running,
            'docker_containers_total': docker_containers_total,
            'docker_images_total': docker_images_total,
            'collected_at': datetime.utcnow(),
        }

        # Persist to DB using a fresh engine to avoid asyncpg conflicts in Celery threads
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker

        engine = None
        db = None
        try:
            engine = create_async_engine(
                settings.database_url,
                echo=False,
                future=True,
                pool_size=1,
                max_overflow=0,
            )
            AsyncSessionLocalFresh = sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            db = AsyncSessionLocalFresh()
            metric = SystemMetric(**data)
            db.add(metric)
            await db.commit()
            print(f"System metrics persisted to database")
        except Exception as e:
            print(f"Error persisting system metrics: {e}")
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

        # Broadcast via Redis
        try:
            print(f"Broadcasting system metrics to Redis...")
            redis_client = redis.from_url(settings.redis_url)
            result = await redis_client.publish(
                "metrics:system",
                json.dumps(data, default=str)
            )
            print(f"Redis publish result: {result} subscribers notified")
            await redis_client.close()
        except Exception as e:
            print(f"Error broadcasting system metrics: {e}")

        return data


system_collector = SystemMetricsCollector()
