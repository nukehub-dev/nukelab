from celery import Celery
from app.config import settings

celery_app = Celery(
    "nukelab",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
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
        'process-server-queue': {
            'task': 'app.tasks.process_server_queue',
            'schedule': 30.0,  # Every 30 seconds
        },
        'evaluate-schedules': {
            'task': 'app.tasks.evaluate_schedules',
            'schedule': 60.0,  # Every 60 seconds
        },
    },
)

# Discover tasks automatically
celery_app.autodiscover_tasks()
