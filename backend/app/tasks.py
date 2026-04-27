from app.worker import celery_app

@celery_app.task(bind=True)
def example_task(self, message: str):
    """Example task for testing"""
    return f"Task completed: {message}"

@celery_app.task(bind=True)
def cleanup_inactive_servers(self):
    """Cleanup task - stops servers that have been inactive for too long"""
    # TODO: Implement cleanup logic
    return "Cleanup completed"
