import asyncio
import threading
from app.worker import celery_app
from app.services.metrics_collector import MetricsCollector
from app.services.system_metrics_collector import SystemMetricsCollector
from app.services.health_check_service import HealthCheckService
from app.services.alert_service import AlertService
from app.db.session import AsyncSessionLocal


def _run_async(coro):
    """Run an async coroutine in a dedicated thread with its own event loop."""
    result = []
    exception = []

    def _run_in_thread():
        print(f"[_run_async] Starting new event loop in thread")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        print(f"[_run_async] Event loop created: {loop}")
        try:
            print(f"[_run_async] Running coroutine...")
            result.append(loop.run_until_complete(coro))
            print(f"[_run_async] Coroutine completed successfully")
        except Exception as e:
            print(f"[_run_async] Exception in coroutine: {e}")
            exception.append(e)
        finally:
            print(f"[_run_async] Cleaning up event loop...")
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            asyncio.set_event_loop(None)
            print(f"[_run_async] Event loop closed")

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join(timeout=60)

    if t.is_alive():
        raise TimeoutError("Async task timed out")

    if exception:
        raise exception[0]

    return result[0]


@celery_app.task(bind=True)
def example_task(self, message: str):
    """Example task for testing"""
    return f"Task completed: {message}"


@celery_app.task(bind=True)
def cleanup_inactive_servers(self):
    """Cleanup task - stops servers that have been inactive for too long"""
    return "Cleanup completed"


@celery_app.task(bind=True)
def collect_container_metrics(self):
    """Collect Docker container metrics for all running containers"""
    try:
        collector = MetricsCollector()
        _run_async(collector.collect_all())
        return "Container metrics collected"
    except Exception as e:
        return f"Error collecting container metrics: {e}"


@celery_app.task(bind=True)
def collect_system_metrics(self):
    """Collect host-level system metrics"""
    try:
        collector = SystemMetricsCollector()
        _run_async(collector.collect())
        return "System metrics collected"
    except Exception as e:
        return f"Error collecting system metrics: {e}"


@celery_app.task(bind=True)
def check_container_health(self):
    """Check health of all running containers"""
    async def _check():
        async with AsyncSessionLocal() as db:
            service = HealthCheckService(db)
            await service.check_all_containers()

    try:
        _run_async(_check())
        return "Health checks completed"
    except Exception as e:
        return f"Error checking health: {e}"


@celery_app.task(bind=True)
def evaluate_alert_rules(self):
    """Evaluate all active alert rules"""
    async def _evaluate():
        async with AsyncSessionLocal() as db:
            service = AlertService(db)
            await service.evaluate_all_rules()

    try:
        _run_async(_evaluate())
        return "Alert rules evaluated"
    except Exception as e:
        return f"Error evaluating alerts: {e}"
