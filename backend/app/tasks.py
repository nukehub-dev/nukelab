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


@celery_app.task(bind=True)
def process_nuke_billing(self):
    """Periodic NUKE billing - deduct usage costs for running servers"""
    async def _bill():
        from sqlalchemy import select
        from app.models.server import Server
        from app.models.server_plan import ServerPlan
        from app.models.user import User
        from app.models.notification import Notification
        from app.services.credit_service import CreditService
        from datetime import datetime, timedelta
        from app.config import settings
        
        async with AsyncSessionLocal() as db:
            credit_service = CreditService(db)
            
            # Get all running servers with their plans
            result = await db.execute(
                select(Server, ServerPlan).join(
                    ServerPlan, Server.plan_id == ServerPlan.id
                ).where(Server.status == "running")
            )
            servers = result.all()
            
            billed_count = 0
            stopped_count = 0
            
            for server, plan in servers:
                if plan.cost_per_hour <= 0:
                    continue
                
                # Calculate billing amount (15 minutes = 0.25 hours)
                billing_amount = int(plan.cost_per_hour * 0.25)
                if billing_amount <= 0:
                    billing_amount = 1  # Minimum 1 credit
                
                # Get user balance
                user_result = await db.execute(
                    select(User.nuke_balance).where(User.id == server.user_id)
                )
                current_balance = user_result.scalar_one_or_none() or 0
                
                if current_balance <= 0:
                    # Auto-stop server if credits depleted
                    if settings.server_auto_stop_on_depletion:
                        from app.docker.spawner import spawner
                        try:
                            await spawner.delete(server.container_id)
                            server.container_id = None
                            server.status = "stopped"
                            server.stopped_at = datetime.utcnow()
                            server.stop_reason = "credit_depleted"
                            
                            # Reconcile exact billing for final partial interval
                            await credit_service.reconcile_server_billing(server, plan)
                            await broadcast_server_status_change(server.user_id, str(server.id), "stopped", {"stop_reason": "credit_depleted"})
                            
                            # Create notification
                            notification = Notification(
                                user_id=server.user_id,
                                title="Server Stopped",
                                message=f"Server '{server.name}' was stopped due to insufficient NUKE credits.",
                                type="server",
                                severity="warning"
                            )
                            db.add(notification)
                            stopped_count += 1
                        except Exception as e:
                            print(f"Error stopping server {server.id}: {e}")
                    continue
                
                # Deduct credits
                try:
                    await credit_service.consume_credits(
                        user_id=str(server.user_id),
                        amount=billing_amount,
                        description=f"Server usage: '{server.name}' (15 min at {plan.cost_per_hour} NUKE/hour)",
                        server_id=str(server.id)
                    )
                    
                    # Update server billing state
                    server.total_cost = (server.total_cost or 0) + billing_amount
                    server.last_billed_at = datetime.utcnow()
                    billed_count += 1
                    
                    # Warn user if credits getting low
                    new_balance = current_balance - billing_amount
                    if new_balance <= plan.cost_per_hour * 2:
                        notification = Notification(
                            user_id=server.user_id,
                            title="Low NUKE Credits",
                            message=f"Server '{server.name}' is running low on credits. Balance: {new_balance} NUKE.",
                            type="credit",
                            severity="warning"
                        )
                        db.add(notification)
                
                except Exception as e:
                    print(f"Error billing server {server.id}: {e}")
            
            await db.commit()
            return f"Billed {billed_count} servers, stopped {stopped_count} servers"
    
    try:
        return _run_async(_bill())
    except Exception as e:
        return f"Error in NUKE billing: {e}"


@celery_app.task(bind=True)
def enforce_auto_stop(self):
    """Enforce idle timeout and max runtime limits on running servers"""
    async def _enforce():
        from sqlalchemy import select
        from app.models.server import Server
        from app.models.server_plan import ServerPlan
        from app.models.notification import Notification
        from datetime import datetime, timedelta
        from app.core.time_utils import parse_duration
        from app.config import settings
        from app.docker.spawner import spawner
        from app.services.quota_service import QuotaService
        
        async with AsyncSessionLocal() as db:
            quota_service = QuotaService(db)
            stopped_count = 0
            warned_count = 0
            
            result = await db.execute(
                select(Server, ServerPlan).join(
                    ServerPlan, Server.plan_id == ServerPlan.id
                ).where(Server.status == "running")
            )
            servers = result.all()
            
            for server, plan in servers:
                now = datetime.utcnow()
                should_stop = False
                stop_reason = ""
                
                # Check max runtime
                if server.expires_at and now >= server.expires_at:
                    should_stop = True
                    stop_reason = "max_runtime_exceeded"
                
                # Check idle timeout
                if not should_stop and server.last_activity and plan.idle_timeout:
                    try:
                        idle_timeout_seconds = parse_duration(plan.idle_timeout)
                        if idle_timeout_seconds > 0:
                            idle_duration = (now - server.last_activity).total_seconds()
                            
                            if idle_duration >= idle_timeout_seconds:
                                should_stop = True
                                stop_reason = "idle_timeout"
                            elif idle_duration >= (idle_timeout_seconds - settings.server_warn_before_stop):
                                # Send warning notification
                                warning = Notification(
                                    user_id=server.user_id,
                                    title="Server Idle Warning",
                                    message=f"Server '{server.name}' will stop soon due to inactivity. Last activity: {int(idle_duration/60)} minutes ago.",
                                    type="server",
                                    severity="warning"
                                )
                                db.add(warning)
                                warned_count += 1
                    except Exception as e:
                        print(f"Error checking idle timeout for server {server.id}: {e}")
                
                if should_stop:
                    try:
                        await spawner.delete(server.container_id)
                        server.container_id = None
                        server.status = "stopped"
                        server.stopped_at = now
                        server.stop_reason = stop_reason
                        await broadcast_server_status_change(server.user_id, str(server.id), "stopped", {"stop_reason": stop_reason})
                        
                        # Decrement quota usage
                        if server.plan_id:
                            await quota_service.decrement_usage(
                                user_id=str(server.user_id),
                                plan_id=str(server.plan_id)
                            )
                        
                        # Create notification
                        reason_messages = {
                            "max_runtime_exceeded": f"Server '{server.name}' stopped because it exceeded the maximum runtime limit.",
                            "idle_timeout": f"Server '{server.name}' stopped due to inactivity.",
                        }
                        
                        notification = Notification(
                            user_id=server.user_id,
                            title="Server Stopped",
                            message=reason_messages.get(stop_reason, f"Server '{server.name}' was stopped automatically."),
                            type="server",
                            severity="info"
                        )
                        db.add(notification)
                        stopped_count += 1
                    except Exception as e:
                        print(f"Error auto-stopping server {server.id}: {e}")
            
            await db.commit()
            return f"Stopped {stopped_count} servers, warned {warned_count} servers"
    
    try:
        return _run_async(_enforce())
    except Exception as e:
        return f"Error in auto-stop enforcement: {e}"


@celery_app.task(bind=True)
def process_server_queue(self):
    """Process queued servers - start next in line when resources free up"""
    async def _process():
        from sqlalchemy import select
        from app.models.server_queue import ServerQueue
        from app.models.server_plan import ServerPlan
        from app.models.user import User
        from app.models.notification import Notification
        from app.services.resource_pool_service import ResourcePoolService
        from app.services.credit_service import CreditService
        from app.services.quota_service import QuotaService
        from app.docker.spawner import spawner
        from app.core.time_utils import parse_duration
        from datetime import datetime, timedelta
        from app.config import settings
        
        async with AsyncSessionLocal() as db:
            resource_pool = ResourcePoolService(db)
            credit_service = CreditService(db)
            quota_service = QuotaService(db)
            
            started_count = 0
            timeout_count = 0
            
            # Remove timed-out queue entries (older than 1 hour)
            timeout_threshold = datetime.utcnow() - timedelta(hours=1)
            result = await db.execute(
                select(ServerQueue).where(
                    ServerQueue.status == "pending",
                    ServerQueue.requested_at < timeout_threshold
                )
            )
            timed_out = result.scalars().all()
            
            for entry in timed_out:
                entry.status = "cancelled"
                entry.error_message = "Queue timeout - server was not started within 1 hour"
                
                notification = Notification(
                    user_id=entry.user_id,
                    title="Queue Timeout",
                    message=f"Server '{entry.server_name}' was removed from the queue due to timeout.",
                    type="server",
                    severity="warning"
                )
                db.add(notification)
                timeout_count += 1
            
            # Process queue - try to start next available server
            while True:
                next_entry = await resource_pool.get_next_in_queue()
                if not next_entry:
                    break
                
                # Get plan details
                plan_result = await db.execute(
                    select(ServerPlan).where(ServerPlan.id == next_entry.plan_id)
                )
                plan = plan_result.scalar_one_or_none()
                
                if not plan or not plan.is_active:
                    next_entry.status = "failed"
                    next_entry.error_message = "Plan no longer available"
                    continue
                
                # Get user
                user_result = await db.execute(
                    select(User).where(User.id == next_entry.user_id)
                )
                user = user_result.scalar_one_or_none()
                
                if not user or not user.is_active:
                    next_entry.status = "failed"
                    next_entry.error_message = "User not found or inactive"
                    continue
                
                # Check quota
                quota_check = await quota_service.check_spawn_allowed(
                    user_id=str(next_entry.user_id),
                    plan_id=str(next_entry.plan_id)
                )
                
                if not quota_check["allowed"]:
                    next_entry.status = "failed"
                    next_entry.error_message = quota_check["reason"]
                    continue
                
                # Check credits
                if settings.credits_enabled and plan.cost_per_hour > 0:
                    has_credits = await credit_service.check_sufficient_credits(
                        user_id=str(next_entry.user_id),
                        required=plan.cost_per_hour
                    )
                    if not has_credits:
                        next_entry.status = "failed"
                        next_entry.error_message = "Insufficient NUKE credits"
                        continue
                
                try:
                    # Look up environment details
                    from app.models.environment_template import EnvironmentTemplate
                    env_result = await db.execute(
                        select(EnvironmentTemplate).where(EnvironmentTemplate.id == next_entry.environment_id)
                    )
                    environment = env_result.scalar_one_or_none()
                    env_slug = environment.slug if environment else "dev"
                    env_image = environment.image if environment else None
                    
                    # Deduct credits
                    if settings.credits_enabled and plan.cost_per_hour > 0:
                        await credit_service.consume_credits(
                            user_id=str(next_entry.user_id),
                            amount=plan.cost_per_hour,
                            description=f"Initial spawn cost for queued server '{next_entry.server_name}'"
                        )
                    
                    # Spawn the server
                    server = await spawner.spawn(
                        user_id=str(next_entry.user_id),
                        username=user.username,
                        server_name=next_entry.server_name,
                        environment=env_slug,
                        environment_id=str(next_entry.environment_id),
                        image=env_image,
                        cpu=next_entry.requested_cpu or plan.cpu_limit,
                        memory=next_entry.requested_memory or plan.memory_limit,
                        disk=next_entry.requested_disk or plan.disk_limit,
                    )
                    
                    server.plan_id = next_entry.plan_id
                    server.last_activity = datetime.utcnow()
                    
                    # Set expiration
                    max_runtime_seconds = parse_duration(plan.max_runtime)
                    if max_runtime_seconds > 0:
                        server.expires_at = datetime.utcnow() + timedelta(seconds=max_runtime_seconds)
                    
                    db.add(server)
                    await db.commit()
                    await db.refresh(server)
                    
                    # Increment quota
                    await quota_service.increment_usage(
                        user_id=str(next_entry.user_id),
                        plan_id=str(next_entry.plan_id)
                    )
                    
                    # Update queue entry
                    next_entry.status = "started"
                    next_entry.started_at = datetime.utcnow()
                    
                    # Notify user
                    notification = Notification(
                        user_id=next_entry.user_id,
                        title="Server Started",
                        message=f"Your queued server '{next_entry.server_name}' has been started.",
                        type="server",
                        severity="success"
                    )
                    db.add(notification)
                    started_count += 1
                    
                except Exception as e:
                    next_entry.status = "failed"
                    next_entry.error_message = str(e)
                    next_entry.retry_count += 1
                    
                    # Notify user of failure
                    notification = Notification(
                        user_id=next_entry.user_id,
                        title="Server Start Failed",
                        message=f"Failed to start queued server '{next_entry.server_name}': {str(e)}",
                        type="server",
                        severity="error"
                    )
                    db.add(notification)
            
            await db.commit()
            return f"Started {started_count} queued servers, timed out {timeout_count} entries"
    
    try:
        return _run_async(_process())
    except Exception as e:
        return f"Error processing queue: {e}"


@celery_app.task(bind=True)
def evaluate_schedules(self):
    """Evaluate and execute due server schedules"""
    async def _evaluate():
        from app.services.schedule_service import ScheduleService
        from app.db.session import AsyncSessionLocal
        
        async with AsyncSessionLocal() as db:
            service = ScheduleService(db)
            due_schedules = await service.get_due_schedules()
            
            executed_count = 0
            failed_count = 0
            
            for schedule in due_schedules:
                try:
                    result = await service.execute_schedule(schedule)
                    if result.get("success"):
                        executed_count += 1
                    else:
                        failed_count += 1
                        print(f"Schedule {schedule.id} failed: {result.get('error')}")
                except Exception as e:
                    failed_count += 1
                    print(f"Error executing schedule {schedule.id}: {e}")
            
            return f"Executed {executed_count} schedules, {failed_count} failed"
    
    try:
        return _run_async(_evaluate())
    except Exception as e:
        return f"Error evaluating schedules: {e}"
