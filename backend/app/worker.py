from celery import Celery, Task
from celery.signals import before_task_publish, task_prerun, task_postrun
from celery.schedules import crontab
from app.config import settings
from app.core.context import correlation_id
from app.core.logging import get_logger
from app.core.sentry import init_sentry

logger = get_logger(__name__)

# Initialize Sentry for Celery workers (idempotent — safe to call multiple times)
init_sentry()


def _get_cid_from_headers(headers: dict) -> str:
    """Extract correlation_id from Celery message headers."""
    if not headers:
        return ""
    # Check nested headers structure
    hdrs = headers.get("headers", {}) or {}
    return hdrs.get("correlation_id", "")


@before_task_publish.connect
def inject_correlation_id(headers=None, body=None, **kwargs):
    """Inject current correlation_id into Celery message headers before publish."""
    if headers is not None:
        hdrs = headers.setdefault("headers", {})
        hdrs["correlation_id"] = correlation_id.get("")


@task_prerun.connect
def set_correlation_id(task_id=None, task=None, kwargs=None, **rest):
    """Restore correlation_id from headers when task starts."""
    if task is None:
        return
    # task.request.headers may be None or a dict
    req_headers = getattr(task.request, "headers", None) or {}
    cid = req_headers.get("correlation_id", "")
    if cid:
        correlation_id.set(cid)
        logger.debug("Correlation ID restored for task", extra={"correlation_id": cid, "task_id": task_id})


@task_postrun.connect
def clear_correlation_id(task_id=None, task=None, **rest):
    """Clear correlation_id after task completes."""
    correlation_id.set("")


class ContextTask(Task):
    """Custom Celery task base that propagates correlation IDs."""

    def apply_async(self, args=None, kwargs=None, task_id=None, producer=None,
                    link=None, link_error=None, shadow=None, **options):
        # Ensure headers exist
        headers = options.setdefault("headers", {})
        headers.setdefault("correlation_id", correlation_id.get(""))
        return super().apply_async(
            args=args, kwargs=kwargs, task_id=task_id, producer=producer,
            link=link, link_error=link_error, shadow=shadow, **options
        )

    def delay(self, *args, **kwargs):
        # delay() wraps apply_async; our apply_async handles headers
        return super().delay(*args, **kwargs)


celery_app = Celery(
    "nukelab",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
    task_cls=ContextTask,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    worker_prefetch_multiplier=1,
    worker_pool='threads',
    worker_concurrency=4,
    beat_schedule={
        'collect-container-metrics': {
            'task': 'app.tasks.collect_container_metrics',
            'schedule': 5.0,  # Every 5 seconds
        },
        'collect-system-metrics': {
            'task': 'app.tasks.collect_system_metrics',
            'schedule': 60.0,  # Every 60 seconds
        },
        'check-container-health': {
            'task': 'app.tasks.check_container_health',
            'schedule': 30.0,  # Every 30 seconds
        },
        'evaluate-alert-rules': {
            'task': 'app.tasks.evaluate_alert_rules',
            'schedule': 60.0,  # Every 60 seconds
        },
        'process-nuke-billing': {
            'task': 'app.tasks.process_nuke_billing',
            'schedule': 900.0,  # Every 15 minutes
        },
        'enforce-auto-stop': {
            'task': 'app.tasks.enforce_auto_stop',
            'schedule': 60.0,  # Every 60 seconds
        },
        'shutdown-idle-servers': {
            'task': 'app.tasks.shutdown_idle_servers',
            'schedule': 300.0,  # Every 5 minutes
        },
        'process-server-queue': {
            'task': 'app.tasks.process_server_queue',
            'schedule': 30.0,  # Every 30 seconds
        },
        'evaluate-schedules': {
            'task': 'app.tasks.evaluate_schedules',
            'schedule': 60.0,  # Every 60 seconds
        },
        'evaluate-maintenance-windows': {
            'task': 'app.tasks.evaluate_maintenance_windows',
            'schedule': 60.0,  # Every 60 seconds
        },
        'rollup-server-metrics': {
            'task': 'app.tasks.rollup_server_metrics',
            'schedule': crontab(hour=3, minute=0),  # Daily at 3 AM
        },
        'cleanup-expired-data': {
            'task': 'app.tasks.cleanup_expired_data',
            'schedule': crontab(hour=4, minute=0),  # Daily at 4 AM
        },
        'ensure-partitions': {
            'task': 'app.tasks.ensure_partitions',
            'schedule': crontab(hour=0, minute=5),  # Daily at 00:05
        },
        'enforce-volume-quotas': {
            'task': 'app.tasks.enforce_volume_quotas',
            'schedule': settings.volume_quota_check_interval_minutes * 60.0,
        },
        'check-autovacuum-health': {
            'task': 'app.tasks.check_autovacuum_health',
            'schedule': crontab(day_of_week=0, hour=6, minute=0),  # Weekly Sunday 6 AM
        },
        'update-prometheus-business-metrics': {
            'task': 'app.tasks.update_prometheus_business_metrics',
            'schedule': 60.0,  # Every 60 seconds
        },
    },
)

# Discover tasks automatically
celery_app.autodiscover_tasks()
