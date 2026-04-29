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

        # Docker stats
        docker_containers_running = 0
        docker_containers_total = 0
        docker_images_total = 0
        docker = None
        try:
            docker = await get_fresh_docker_client()
            containers = await docker.list_containers()
            docker_containers_total = len(containers)
            docker_containers_running = sum(
                1 for c in containers if c.get('State') == 'running'
            )
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
            'network_rx_bytes': net_io.bytes_recv if net_io else 0,
            'network_tx_bytes': net_io.bytes_sent if net_io else 0,
            'docker_containers_running': docker_containers_running,
            'docker_containers_total': docker_containers_total,
            'docker_images_total': docker_images_total,
            'collected_at': datetime.utcnow(),
        }

        # Persist to DB
        async with AsyncSessionLocal() as db:
            try:
                metric = SystemMetric(**data)
                db.add(metric)
                await db.commit()
            except Exception as e:
                await db.rollback()
                print(f"Error persisting system metrics: {e}")
            finally:
                await db.close()

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
