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
def evaluate_maintenance_windows(self):
    """Evaluate scheduled maintenance windows: send notifications, enable/disable maintenance mode."""
    async def _evaluate():
        from app.services.maintenance_window_service import MaintenanceWindowService

        async with AsyncSessionLocal() as db:
            service = MaintenanceWindowService(db)
            result = await service.evaluate_windows()
            return (
                f"Maintenance windows: {result['notifications_sent']} notifications sent, "
                f"{result['enabled_count']} enabled, {result['disabled_count']} disabled"
            )

    try:
        return _run_async(_evaluate())
    except Exception as e:
        return f"Error evaluating maintenance windows: {e}"


@celery_app.task(bind=True)
def cleanup_inactive_servers(self):
    """Cleanup task - stops servers that have been inactive for too long"""
    return "Cleanup completed"


@celery_app.task(bind=True)
def shutdown_idle_servers(self):
    """Stop servers that have been idle beyond user preference timeout"""
    async def _enforce():
        from sqlalchemy import select
        from app.models.server import Server
        from app.models.server_plan import ServerPlan
        from app.models.user import User
        from app.services.notification_service import NotificationService
        from app.services.credit_service import CreditService
        from app.services.quota_service import QuotaService
        from app.container.spawner import spawner
        from datetime import datetime, timedelta
        
        async with AsyncSessionLocal() as db:
            stopped_count = 0
            warned_count = 0
            
            # Get all running servers with their users
            result = await db.execute(
                select(Server, User).join(
                    User, Server.user_id == User.id
                ).where(Server.status.in_(["running", "healthy"]))
            )
            servers = result.all()
            
            for server, user in servers:
                prefs = user.preferences or {}
                
                # Skip if user disabled idle shutdown
                if not prefs.get("idle_shutdown_enabled", True):
                    continue
                
                timeout_mins = prefs.get("idle_shutdown_timeout", 30)
                cutoff = datetime.utcnow() - timedelta(minutes=timeout_mins)
                
                # Determine last activity time
                last_activity = server.last_activity or server.started_at
                if not last_activity:
                    continue
                
                if last_activity >= cutoff:
                    continue
                
                # Server is idle beyond user threshold — stop it
                try:
                    if server.container_id:
                        actual_status = await spawner.get_status(server.container_id)
                        if actual_status in ("stopped", "unknown"):
                            server.status = "stopped"
                            server.container_id = None
                            await db.commit()
                            continue
                        
                        await spawner.delete(server.container_id)
                        server.container_id = None
                    
                    server.status = "stopped"
                    server.stopped_at = datetime.utcnow()
                    server.stop_reason = "idle_timeout"
                    
                    # Reconcile billing
                    if server.plan_id:
                        credit_service = CreditService(db)
                        plan_result = await db.execute(
                            select(ServerPlan).where(ServerPlan.id == server.plan_id)
                        )
                        plan = plan_result.scalar_one_or_none()
                        if plan:
                            await credit_service.reconcile_server_billing(server, plan)
                    
                    # Decrement quota
                    if server.plan_id:
                        quota_service = QuotaService(db)
                        await quota_service.decrement_usage(
                            user_id=str(user.id),
                            plan_id=str(server.plan_id)
                        )
                    
                    await db.commit()
                    
                    # Notify user
                    notif_service = NotificationService(db)
                    await notif_service.server_stopped(
                        user_id=user.id,
                        server_name=server.name,
                        reason=f"inactivity ({timeout_mins} minutes)"
                    )
                    
                    from app.services.notification_service import broadcast_server_status_change
                    await broadcast_server_status_change(user.id, str(server.id), "stopped")
                    stopped_count += 1
                
                except Exception as e:
                    print(f"Error auto-stopping idle server {server.id}: {e}")
            
            return f"Stopped {stopped_count} idle servers"
    
    try:
        return _run_async(_enforce())
    except Exception as e:
        return f"Error in idle shutdown enforcement: {e}"


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
        from app.services.notification_service import NotificationService, broadcast_server_status_change
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
                        from app.container.spawner import spawner
                        try:
                            await spawner.delete(server.container_id)
                            server.container_id = None
                            server.status = "stopped"
                            server.stopped_at = datetime.utcnow()
                            server.stop_reason = "credit_depleted"
                            
                            # Reconcile exact billing for final partial interval
                            await credit_service.reconcile_server_billing(server, plan)
                            await broadcast_server_status_change(server.user_id, str(server.id), "stopped", {"stop_reason": "credit_depleted"})
                            
                            # Notify user
                            notif_service = NotificationService(db)
                            await notif_service.server_stopped(
                                user_id=server.user_id,
                                server_name=server.name,
                                reason="insufficient NUKE credits"
                            )
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
                        notif_service = NotificationService(db)
                        await notif_service.low_balance(
                            user_id=server.user_id,
                            balance=new_balance
                        )
                
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
        from app.services.notification_service import NotificationService, broadcast_server_status_change
        from datetime import datetime, timedelta
        from app.core.time_utils import parse_duration
        from app.config import settings
        from app.container.spawner import spawner
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
                                notif_service = NotificationService(db)
                                await notif_service.server_idle_warning(
                                    user_id=server.user_id,
                                    server_name=server.name,
                                    idle_minutes=int(idle_duration / 60)
                                )
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
                        
                        # Notify user
                        notif_service = NotificationService(db)
                        reason_messages = {
                            "max_runtime_exceeded": "exceeded the maximum runtime limit",
                            "idle_timeout": "inactivity",
                        }
                        await notif_service.server_stopped(
                            user_id=server.user_id,
                            server_name=server.name,
                            reason=reason_messages.get(stop_reason, "automatic stop")
                        )
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
        from app.services.notification_service import NotificationService
        from app.services.resource_pool_service import ResourcePoolService
        from app.services.credit_service import CreditService
        from app.services.quota_service import QuotaService
        from app.container.spawner import spawner
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
                
                notif_service = NotificationService(db)
                await notif_service.queue_timeout(
                    user_id=entry.user_id,
                    server_name=entry.server_name
                )
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
                    notif_service = NotificationService(db)
                    await notif_service.server_started(
                        user_id=next_entry.user_id,
                        server_name=next_entry.server_name
                    )
                    started_count += 1
                    
                except Exception as e:
                    next_entry.status = "failed"
                    next_entry.error_message = str(e)
                    next_entry.retry_count += 1
                    
                    # Notify user of failure
                    notif_service = NotificationService(db)
                    await notif_service.server_failed(
                        user_id=next_entry.user_id,
                        server_name=next_entry.server_name,
                        error=str(e)
                    )
            
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


@celery_app.task(bind=True)
def rollup_server_metrics(self):
    """Aggregate raw ServerMetric rows into DailyServerMetric every night."""
    async def _rollup():
        from sqlalchemy import select, func, and_, insert, update
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from app.models.server_metric import ServerMetric
        from app.models.daily_server_metric import DailyServerMetric
        from app.db.session import AsyncSessionLocal
        from datetime import datetime, timedelta, date

        async with AsyncSessionLocal() as db:
            # Process the last 7 days (to catch up if missed)
            end_date = date.today()
            start_date = end_date - timedelta(days=7)

            # Find all distinct (server_id, date) pairs in the raw metrics
            day_trunc = func.date_trunc('day', ServerMetric.collected_at)
            result = await db.execute(
                select(
                    ServerMetric.server_id,
                    func.date(ServerMetric.collected_at).label('metric_date')
                ).where(
                    and_(
                        func.date(ServerMetric.collected_at) >= start_date,
                        func.date(ServerMetric.collected_at) <= end_date,
                    )
                ).distinct()
            )
            pairs = result.all()

            upserted = 0
            for server_id, metric_date in pairs:
                # Compute aggregates for this server/day
                agg_result = await db.execute(
                    select(
                        func.avg(ServerMetric.cpu_percent).label('avg_cpu'),
                        func.max(ServerMetric.cpu_percent).label('peak_cpu'),
                        func.avg(ServerMetric.memory_percent).label('avg_memory'),
                        func.max(ServerMetric.memory_percent).label('peak_memory'),
                        func.avg(ServerMetric.network_rx_bytes).label('avg_network_rx'),
                        func.avg(ServerMetric.network_tx_bytes).label('avg_network_tx'),
                        func.avg(ServerMetric.disk_read_bytes).label('avg_disk_read'),
                        func.avg(ServerMetric.disk_write_bytes).label('avg_disk_write'),
                        func.avg(ServerMetric.gpu_percent).label('avg_gpu'),
                        func.max(ServerMetric.gpu_percent).label('peak_gpu'),
                        func.count().label('data_points')
                    ).where(
                        and_(
                            ServerMetric.server_id == server_id,
                            func.date(ServerMetric.collected_at) == metric_date,
                        )
                    )
                )
                row = agg_result.one()

                # Upsert into daily_server_metrics
                stmt = pg_insert(DailyServerMetric).values(
                    server_id=server_id,
                    date=metric_date,
                    avg_cpu=row.avg_cpu,
                    peak_cpu=row.peak_cpu,
                    avg_memory=row.avg_memory,
                    peak_memory=row.peak_memory,
                    avg_network_rx=row.avg_network_rx,
                    avg_network_tx=row.avg_network_tx,
                    avg_disk_read=row.avg_disk_read,
                    avg_disk_write=row.avg_disk_write,
                    avg_gpu=row.avg_gpu,
                    peak_gpu=row.peak_gpu,
                    data_points=row.data_points,
                ).on_conflict_do_update(
                    index_elements=['server_id', 'date'],
                    set_={
                        'avg_cpu': row.avg_cpu,
                        'peak_cpu': row.peak_cpu,
                        'avg_memory': row.avg_memory,
                        'peak_memory': row.peak_memory,
                        'avg_network_rx': row.avg_network_rx,
                        'avg_network_tx': row.avg_network_tx,
                        'avg_disk_read': row.avg_disk_read,
                        'avg_disk_write': row.avg_disk_write,
                        'avg_gpu': row.avg_gpu,
                        'peak_gpu': row.peak_gpu,
                        'data_points': row.data_points,
                    }
                )
                await db.execute(stmt)
                upserted += 1

            await db.commit()
            return f"Upserted {upserted} daily rollup rows for {start_date} to {end_date}"

    try:
        return _run_async(_rollup())
    except Exception as e:
        return f"Error rolling up server metrics: {e}"


@celery_app.task(bind=True)
def cleanup_expired_data(self):
    """Delete expired raw data based on retention settings."""
    async def _cleanup():
        from sqlalchemy import delete, text, select
        from app.models.server_metric import ServerMetric
        from app.models.system_metric import SystemMetric
        from app.models.health_check import HealthCheck
        from app.models.alert_history import AlertHistory
        from app.models.activity_log import ActivityLog
        from app.models.notification import Notification
        from app.models.daily_server_metric import DailyServerMetric
        from app.models.system_setting import SystemSetting
        from app.db.session import AsyncSessionLocal
        from datetime import datetime, timedelta

        async with AsyncSessionLocal() as db:
            # Helper to read retention setting
            async def get_retention_days(key: str, default: int) -> int:
                result = await db.execute(
                    select(SystemSetting.value).where(SystemSetting.key == key)
                )
                row = result.scalar_one_or_none()
                if row:
                    try:
                        return int(row)
                    except ValueError:
                        pass
                return default

            cleanup_enabled = await get_retention_days("cleanup_enabled", 1)  # 1 = true
            if not cleanup_enabled:
                return "Cleanup disabled"

            metrics_days = await get_retention_days("metrics_retention_days", 30)
            system_metrics_days = await get_retention_days("system_metrics_retention_days", 90)
            health_check_days = await get_retention_days("health_check_retention_days", 30)
            alert_history_days = await get_retention_days("alert_history_retention_days", 90)
            activity_log_days = await get_retention_days("activity_log_retention_days", 365)
            notification_days = await get_retention_days("notification_retention_days", 30)
            daily_rollup_days = await get_retention_days("daily_rollup_retention_days", 730)

            now = datetime.utcnow()
            deleted = {}

            # Server metrics
            cutoff = now - timedelta(days=metrics_days)
            result = await db.execute(
                delete(ServerMetric).where(ServerMetric.collected_at < cutoff)
            )
            deleted['server_metrics'] = result.rowcount

            # System metrics
            cutoff = now - timedelta(days=system_metrics_days)
            result = await db.execute(
                delete(SystemMetric).where(SystemMetric.collected_at < cutoff)
            )
            deleted['system_metrics'] = result.rowcount

            # Health checks
            cutoff = now - timedelta(days=health_check_days)
            result = await db.execute(
                delete(HealthCheck).where(HealthCheck.checked_at < cutoff)
            )
            deleted['health_checks'] = result.rowcount

            # Alert history
            cutoff = now - timedelta(days=alert_history_days)
            result = await db.execute(
                delete(AlertHistory).where(AlertHistory.created_at < cutoff)
            )
            deleted['alert_history'] = result.rowcount

            # Activity logs
            cutoff = now - timedelta(days=activity_log_days)
            result = await db.execute(
                delete(ActivityLog).where(ActivityLog.created_at < cutoff)
            )
            deleted['activity_logs'] = result.rowcount

            # Notifications
            cutoff = now - timedelta(days=notification_days)
            result = await db.execute(
                delete(Notification).where(Notification.created_at < cutoff)
            )
            deleted['notifications'] = result.rowcount

            # Daily rollups
            cutoff = now - timedelta(days=daily_rollup_days)
            result = await db.execute(
                delete(DailyServerMetric).where(DailyServerMetric.date < cutoff.date())
            )
            deleted['daily_rollups'] = result.rowcount

            await db.commit()
            total = sum(deleted.values())
            return f"Cleanup complete. Deleted {total} rows: {deleted}"

    try:
        return _run_async(_cleanup())
    except Exception as e:
        return f"Error in cleanup: {e}"
