# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import asyncio
import threading
from datetime import timedelta

from fastapi import HTTPException

from app.config import settings
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.worker import celery_app

logger = get_logger(__name__)
import contextlib

from app.db.session import AsyncSessionLocal
from app.services.alert_service import AlertService
from app.services.health_check_service import HealthCheckService
from app.services.metrics_collector import MetricsCollector
from app.services.system_metrics_collector import SystemMetricsCollector


def _run_async(coro):
    """Run an async coroutine in a dedicated thread with its own event loop."""
    result = []
    exception = []

    def _run_in_thread():
        logger.debug("[_run_async] Starting new event loop in thread")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logger.debug("[_run_async] Event loop created: %s", loop)
        try:
            logger.debug("[_run_async] Running coroutine...")
            result.append(loop.run_until_complete(coro))
            logger.debug("[_run_async] Coroutine completed successfully")
        except Exception as e:
            logger.error("[_run_async] Exception in coroutine: %s", e)
            exception.append(e)
        finally:
            logger.debug("[_run_async] Cleaning up event loop...")
            with contextlib.suppress(Exception):
                loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)
            logger.debug("[_run_async] Event loop closed")

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
def send_notification_channels(
    self,
    user_id: str,
    event_key: str,
    title: str,
    message: str,
    severity: str,
    notification_type: str,
    extra_data: dict | None = None,
):
    """Send email/webhook notification channels asynchronously.

    The in-app notification and real-time WebSocket push are handled in the
    request path so the user gets immediate feedback. Slower outbound channels
    (email + webhook) are offloaded to this task to avoid blocking the API.
    """

    async def _send():
        from sqlalchemy import select

        from app.models.user import User
        from app.services.notification_service import NotificationService

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return "User not found"

            service = NotificationService(db)
            prefs = await service._get_user_notification_prefs(user.id)
            should_email = service._should_send(prefs, event_key, "email")
            should_webhook = service._should_send(prefs, event_key, "webhook")

            channels = []

            if should_email:
                await service._send_email_for_notification(
                    user.id, title, message, notification_type
                )
                channels.append("email")

            if should_webhook:
                await service._send_webhook_for_notification(
                    user_id=user.id,
                    event_key=event_key,
                    title=title,
                    message=message,
                    severity=severity,
                    notification_type=notification_type,
                    extra_data=extra_data or {},
                )
                channels.append("webhook")

            return f"Sent channels: {','.join(channels) if channels else 'none'} for {event_key}"

    try:
        return _run_async(_send())
    except Exception as e:
        logger.exception("Error sending notification channels: %s", e)
        return f"Error: {e}"


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
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import select

        from app.container.spawner import spawner
        from app.models.server import Server
        from app.models.server_plan import ServerPlan
        from app.models.user import User
        from app.services.credit_service import CreditService
        from app.services.notification_service import NotificationService
        from app.services.quota_service import QuotaService

        async with AsyncSessionLocal() as db:
            stopped_count = 0

            # Get all running servers with their users
            result = await db.execute(
                select(Server, User)
                .join(User, Server.user_id == User.id)
                .where(Server.status.in_(["running", "healthy"]))
            )
            servers = result.all()

            for server, user in servers:
                prefs = user.preferences or {}

                # Skip if user disabled idle shutdown
                if not prefs.get("idle_shutdown_enabled", True):
                    continue

                timeout_mins = prefs.get("idle_shutdown_timeout", 15)
                cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=timeout_mins)

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
                        if actual_status == "unknown":
                            # Runtime lookup failed (e.g. socket timeout). Do not
                            # mark the server stopped: the container may still be
                            # running. Retry on the next task cycle.
                            logger.warning(
                                "Could not determine runtime status of idle server "
                                "%s (container %s); skipping shutdown",
                                server.id,
                                server.container_id,
                            )
                            continue

                        if actual_status == "stopped":
                            server.status = "stopped"
                            server.container_id = None
                            await db.commit()
                            continue

                        await spawner.delete(server.container_id)
                        server.container_id = None

                    server.status = "stopped"
                    server.stopped_at = datetime.now(UTC).replace(tzinfo=None)
                    server.stop_reason = "idle_timeout"
                    server.expires_at = None

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
                            user_id=str(user.id), plan_id=str(server.plan_id)
                        )

                    await db.commit()

                    # Notify user
                    notif_service = NotificationService(db)
                    await notif_service.server_stopped(
                        user_id=user.id,
                        server_name=server.name,
                        reason=f"inactivity ({timeout_mins} minutes)",
                    )

                    from app.services.notification_service import broadcast_server_status_change

                    await broadcast_server_status_change(user.id, str(server.id), "stopped")
                    stopped_count += 1

                except Exception:
                    logger.exception("Error auto-stopping idle server %s", server.id)

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
        from datetime import UTC, datetime

        from sqlalchemy import select

        from app.config import settings
        from app.models.server import Server
        from app.models.server_plan import ServerPlan
        from app.models.user import User
        from app.services.credit_service import CreditService
        from app.services.notification_service import (
            NotificationService,
            broadcast_server_status_change,
        )

        async with AsyncSessionLocal() as db:
            credit_service = CreditService(db)

            # Get all running servers with their plans
            result = await db.execute(
                select(Server, ServerPlan)
                .join(ServerPlan, Server.plan_id == ServerPlan.id)
                .where(Server.status == "running")
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
                            server.stopped_at = datetime.now(UTC).replace(tzinfo=None)
                            server.stop_reason = "credit_depleted"

                            # Reconcile exact billing for final partial interval
                            await credit_service.reconcile_server_billing(server, plan)
                            await broadcast_server_status_change(
                                server.user_id,
                                str(server.id),
                                "stopped",
                                {"stop_reason": "credit_depleted"},
                            )

                            # Notify user
                            notif_service = NotificationService(db)
                            await notif_service.server_stopped(
                                user_id=server.user_id,
                                server_name=server.name,
                                reason="insufficient NUKE credits",
                            )
                            stopped_count += 1
                        except Exception:
                            logger.exception("Error stopping server %s", server.id)
                    continue

                # Deduct credits
                try:
                    await credit_service.consume_credits(
                        user_id=str(server.user_id),
                        amount=billing_amount,
                        description=f"Server usage: '{server.name}' (15 min at {plan.cost_per_hour} NUKE/hour)",
                        server_id=str(server.id),
                    )

                    # Update server billing state
                    server.total_cost = (server.total_cost or 0) + billing_amount
                    server.last_billed_at = datetime.now(UTC).replace(tzinfo=None)
                    billed_count += 1

                    # Warn user if credits getting low
                    new_balance = current_balance - billing_amount
                    if new_balance <= plan.cost_per_hour * 2:
                        notif_service = NotificationService(db)
                        await notif_service.low_balance(user_id=server.user_id, balance=new_balance)

                except Exception:
                    logger.exception("Error billing server %s", server.id)

            await db.commit()
            return f"Billed {billed_count} servers, stopped {stopped_count} servers"

    try:
        return _run_async(_bill())
    except Exception as e:
        return f"Error in NUKE billing: {e}"


@celery_app.task(bind=True)
def enforce_auto_stop(self):
    """Enforce max runtime limits on running servers"""

    async def _enforce():
        from datetime import UTC, datetime

        from sqlalchemy import select

        from app.container.spawner import spawner
        from app.models.server import Server
        from app.services.notification_service import (
            NotificationService,
            broadcast_server_status_change,
        )
        from app.services.quota_service import QuotaService

        async with AsyncSessionLocal() as db:
            quota_service = QuotaService(db)
            stopped_count = 0

            result = await db.execute(select(Server).where(Server.status == "running"))
            servers = result.scalars().all()

            for server in servers:
                now = datetime.now(UTC).replace(tzinfo=None)

                # Check max runtime
                if not (server.expires_at and now >= server.expires_at):
                    continue

                try:
                    await spawner.delete(server.container_id)
                    server.container_id = None
                    server.status = "stopped"
                    server.stopped_at = now
                    server.stop_reason = "max_runtime_exceeded"
                    server.expires_at = None
                    await broadcast_server_status_change(
                        server.user_id,
                        str(server.id),
                        "stopped",
                        {"stop_reason": "max_runtime_exceeded"},
                    )

                    # Decrement quota usage
                    if server.plan_id:
                        await quota_service.decrement_usage(
                            user_id=str(server.user_id), plan_id=str(server.plan_id)
                        )

                    # Notify user
                    notif_service = NotificationService(db)
                    await notif_service.server_stopped(
                        user_id=server.user_id,
                        server_name=server.name,
                        reason="exceeded the maximum runtime limit",
                    )
                    stopped_count += 1
                except Exception:
                    logger.exception("Error auto-stopping server %s", server.id)

            await db.commit()
            return f"Stopped {stopped_count} servers"

    try:
        return _run_async(_enforce())
    except Exception as e:
        return f"Error in auto-stop enforcement: {e}"


@celery_app.task(bind=True)
def process_server_queue(self):
    """Process queued servers - start next in line when resources free up"""

    async def _process():
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import select

        from app.config import settings
        from app.container.spawner import spawner
        from app.models.server_plan import ServerPlan
        from app.models.server_queue import ServerQueue
        from app.models.user import User
        from app.services.credit_service import CreditService
        from app.services.notification_service import NotificationService
        from app.services.quota_service import QuotaService
        from app.services.resource_pool_service import ResourcePoolService

        async with AsyncSessionLocal() as db:
            resource_pool = ResourcePoolService(db)
            credit_service = CreditService(db)
            quota_service = QuotaService(db)

            started_count = 0
            timeout_count = 0

            # Remove timed-out queue entries (older than 1 hour)
            timeout_threshold = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
            result = await db.execute(
                select(ServerQueue).where(
                    ServerQueue.status == "pending", ServerQueue.requested_at < timeout_threshold
                )
            )
            timed_out = result.scalars().all()

            for entry in timed_out:
                entry.status = "cancelled"
                entry.error_message = "Queue timeout - server was not started within 1 hour"

                notif_service = NotificationService(db)
                await notif_service.queue_timeout(
                    user_id=entry.user_id, server_name=entry.server_name
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
                user_result = await db.execute(select(User).where(User.id == next_entry.user_id))
                user = user_result.scalar_one_or_none()

                if not user or not user.is_active:
                    next_entry.status = "failed"
                    next_entry.error_message = "User not found or inactive"
                    continue

                # Check quota
                quota_check = await quota_service.check_spawn_allowed(
                    user_id=str(next_entry.user_id), plan_id=str(next_entry.plan_id)
                )

                if not quota_check["allowed"]:
                    next_entry.status = "failed"
                    next_entry.error_message = quota_check["reason"]
                    continue

                # Check credits
                if settings.credits_enabled and plan.cost_per_hour > 0:
                    has_credits = await credit_service.check_sufficient_credits(
                        user_id=str(next_entry.user_id), required=plan.cost_per_hour
                    )
                    if not has_credits:
                        next_entry.status = "failed"
                        next_entry.error_message = "Insufficient NUKE credits"
                        continue

                try:
                    # Look up environment details
                    from app.models.environment_template import EnvironmentTemplate

                    env_result = await db.execute(
                        select(EnvironmentTemplate).where(
                            EnvironmentTemplate.id == next_entry.environment_id
                        )
                    )
                    environment = env_result.scalar_one_or_none()
                    env_slug = environment.slug if environment else "dev"
                    env_image = environment.image if environment else None

                    # Deduct credits
                    if settings.credits_enabled and plan.cost_per_hour > 0:
                        await credit_service.consume_credits(
                            user_id=str(next_entry.user_id),
                            amount=plan.cost_per_hour,
                            description=f"Initial spawn cost for queued server '{next_entry.server_name}'",
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
                    server.last_activity = datetime.now(UTC).replace(tzinfo=None)

                    # Set expiration based on user's max_server_runtime preference
                    prefs = user.preferences or {}
                    if prefs.get("max_server_runtime_enabled", True):
                        max_runtime_minutes = prefs.get("max_server_runtime")
                        if max_runtime_minutes is None:
                            max_runtime_seconds = settings.server_max_runtime
                        else:
                            try:
                                max_runtime_seconds = int(max_runtime_minutes) * 60
                            except (TypeError, ValueError):
                                max_runtime_seconds = settings.server_max_runtime

                        if max_runtime_seconds > 0:
                            server.expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
                                seconds=max_runtime_seconds
                            )

                    db.add(server)
                    await db.commit()
                    await db.refresh(server)

                    # Increment quota
                    await quota_service.increment_usage(
                        user_id=str(next_entry.user_id), plan_id=str(next_entry.plan_id)
                    )

                    # Update queue entry
                    next_entry.status = "started"
                    next_entry.started_at = datetime.now(UTC).replace(tzinfo=None)

                    # Notify user
                    notif_service = NotificationService(db)
                    await notif_service.server_started(
                        user_id=next_entry.user_id, server_name=next_entry.server_name
                    )
                    started_count += 1

                except Exception as e:
                    next_entry.status = "failed"
                    next_entry.error_message = str(e)
                    next_entry.retry_count += 1

                    # Notify user of failure
                    notif_service = NotificationService(db)
                    await notif_service.server_failed(
                        user_id=next_entry.user_id, server_name=next_entry.server_name, error=str(e)
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
        from app.db.session import AsyncSessionLocal
        from app.services.schedule_service import ScheduleService

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
                        logger.error("Schedule %s failed: %s", schedule.id, result.get("error"))
                except Exception:
                    failed_count += 1
                    logger.exception("Error executing schedule %s", schedule.id)

            return f"Executed {executed_count} schedules, {failed_count} failed"

    try:
        return _run_async(_evaluate())
    except Exception as e:
        return f"Error evaluating schedules: {e}"


@celery_app.task(bind=True)
def rollup_server_metrics(self):
    """Aggregate raw ServerMetric rows into DailyServerMetric every night."""

    async def _rollup():
        from datetime import date, timedelta

        from sqlalchemy import and_, func, select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.db.session import AsyncSessionLocal
        from app.models.daily_server_metric import DailyServerMetric
        from app.models.server_metric import ServerMetric

        async with AsyncSessionLocal() as db:
            # Process the last 7 days (to catch up if missed)
            end_date = date.today()
            start_date = end_date - timedelta(days=7)

            # Find all distinct (server_id, date) pairs in the raw metrics
            func.date_trunc("day", ServerMetric.collected_at)
            result = await db.execute(
                select(
                    ServerMetric.server_id,
                    func.date(ServerMetric.collected_at).label("metric_date"),
                )
                .where(
                    and_(
                        func.date(ServerMetric.collected_at) >= start_date,
                        func.date(ServerMetric.collected_at) <= end_date,
                    )
                )
                .distinct()
            )
            pairs = result.all()

            upserted = 0
            for server_id, metric_date in pairs:
                # Compute aggregates for this server/day
                agg_result = await db.execute(
                    select(
                        func.avg(ServerMetric.cpu_percent).label("avg_cpu"),
                        func.max(ServerMetric.cpu_percent).label("peak_cpu"),
                        func.avg(ServerMetric.memory_percent).label("avg_memory"),
                        func.max(ServerMetric.memory_percent).label("peak_memory"),
                        func.avg(ServerMetric.network_rx_bytes).label("avg_network_rx"),
                        func.avg(ServerMetric.network_tx_bytes).label("avg_network_tx"),
                        func.avg(ServerMetric.disk_read_bytes).label("avg_disk_read"),
                        func.avg(ServerMetric.disk_write_bytes).label("avg_disk_write"),
                        func.avg(ServerMetric.gpu_percent).label("avg_gpu"),
                        func.max(ServerMetric.gpu_percent).label("peak_gpu"),
                        func.count().label("data_points"),
                    ).where(
                        and_(
                            ServerMetric.server_id == server_id,
                            func.date(ServerMetric.collected_at) == metric_date,
                        )
                    )
                )
                row = agg_result.one()

                # Upsert into daily_server_metrics
                stmt = (
                    pg_insert(DailyServerMetric)
                    .values(
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
                    )
                    .on_conflict_do_update(
                        index_elements=["server_id", "date"],
                        set_={
                            "avg_cpu": row.avg_cpu,
                            "peak_cpu": row.peak_cpu,
                            "avg_memory": row.avg_memory,
                            "peak_memory": row.peak_memory,
                            "avg_network_rx": row.avg_network_rx,
                            "avg_network_tx": row.avg_network_tx,
                            "avg_disk_read": row.avg_disk_read,
                            "avg_disk_write": row.avg_disk_write,
                            "avg_gpu": row.avg_gpu,
                            "peak_gpu": row.peak_gpu,
                            "data_points": row.data_points,
                        },
                    )
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
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import delete, select

        from app.db.session import AsyncSessionLocal
        from app.models.activity_log import ActivityLog
        from app.models.alert_history import AlertHistory
        from app.models.credit_transaction import CreditTransaction
        from app.models.daily_server_metric import DailyServerMetric
        from app.models.health_check import HealthCheck
        from app.models.notification import Notification
        from app.models.request_metric import RequestMetric
        from app.models.server_metric import ServerMetric
        from app.models.system_metric import SystemMetric
        from app.models.system_setting import SystemSetting

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
            credit_transaction_days = await get_retention_days(
                "credit_transaction_retention_days", 730
            )
            notification_days = await get_retention_days("notification_retention_days", 30)
            daily_rollup_days = await get_retention_days("daily_rollup_retention_days", 730)
            request_metrics_days = await get_retention_days("request_metrics_retention_days", 30)

            now = datetime.now(UTC).replace(tzinfo=None)
            deleted = {}

            # Server metrics
            cutoff = now - timedelta(days=metrics_days)
            result = await db.execute(
                delete(ServerMetric).where(ServerMetric.collected_at < cutoff)
            )
            deleted["server_metrics"] = result.rowcount

            # System metrics
            cutoff = now - timedelta(days=system_metrics_days)
            result = await db.execute(
                delete(SystemMetric).where(SystemMetric.collected_at < cutoff)
            )
            deleted["system_metrics"] = result.rowcount

            # Health checks
            cutoff = now - timedelta(days=health_check_days)
            result = await db.execute(delete(HealthCheck).where(HealthCheck.checked_at < cutoff))
            deleted["health_checks"] = result.rowcount

            # Alert history
            cutoff = now - timedelta(days=alert_history_days)
            result = await db.execute(delete(AlertHistory).where(AlertHistory.created_at < cutoff))
            deleted["alert_history"] = result.rowcount

            # Activity logs
            cutoff = now - timedelta(days=activity_log_days)
            result = await db.execute(delete(ActivityLog).where(ActivityLog.created_at < cutoff))
            deleted["activity_logs"] = result.rowcount

            # Credit transactions (ledger). Kept longer than metrics because
            # they are the financial audit trail; drop whole monthly partitions
            # first, then delete any rows that landed in the DEFAULT partition.
            from app.db.partitioning import PartitionManager

            pm = PartitionManager(db)
            dropped_partitions = await pm.drop_old_partitions(
                "credit_transactions",
                months_to_keep=max(1, credit_transaction_days // 30),
            )
            deleted["credit_transactions_partitions_dropped"] = len(dropped_partitions)

            cutoff = now - timedelta(days=credit_transaction_days)
            result = await db.execute(
                delete(CreditTransaction).where(CreditTransaction.created_at < cutoff)
            )
            deleted["credit_transactions_rows_deleted"] = result.rowcount

            # Notifications
            cutoff = now - timedelta(days=notification_days)
            result = await db.execute(delete(Notification).where(Notification.created_at < cutoff))
            deleted["notifications"] = result.rowcount

            # Daily rollups
            cutoff = now - timedelta(days=daily_rollup_days)
            result = await db.execute(
                delete(DailyServerMetric).where(DailyServerMetric.date < cutoff.date())
            )
            deleted["daily_rollups"] = result.rowcount

            # Request metrics
            cutoff = now - timedelta(days=request_metrics_days)
            result = await db.execute(
                delete(RequestMetric).where(RequestMetric.created_at < cutoff)
            )
            deleted["request_metrics"] = result.rowcount

            await db.commit()
            total = sum(deleted.values())
            return f"Cleanup complete. Deleted {total} rows: {deleted}"

    try:
        return _run_async(_cleanup())
    except Exception as e:
        return f"Error in cleanup: {e}"


@celery_app.task(bind=True)
def ensure_partitions(self):
    """Create upcoming monthly partitions for time-series tables.
    Runs daily via Celery Beat to ensure partitions exist before data arrives.
    """

    async def _ensure():
        from app.db.partitioning import PartitionManager

        async with AsyncSessionLocal() as db:
            pm = PartitionManager(db)
            created_all = []
            for table in pm.PARTITION_CONFIG:
                created = await pm.ensure_partitions(table, months_ahead=3)
                created_all.extend(created)
            await db.commit()
            return f"Partitions ensured: {len(created_all)} created ({', '.join(created_all)})"

    try:
        return _run_async(_ensure())
    except Exception as e:
        return f"Error ensuring partitions: {e}"


@celery_app.task(bind=True)
def enforce_volume_quotas(self):
    """Periodic volume quota enforcement: stop servers that exceed disk limits.

    For each mounted volume on running servers, measures current size and
    enforces limits. When XFS project quotas are enabled, reads size from
    xfs_quota report (fast, no disk walk). Otherwise falls back to du -sb.

    If a volume exceeds its max_size_bytes or the server's plan disk limit,
    the server is stopped, the volume is marked `over_limit`, and the user
    is notified. This closes the gap where a running container can write
    unbounded data to a named Docker volume (Docker StorageOpt only limits
    rootfs, not named volumes).
    """

    async def _enforce():
        from datetime import UTC, datetime

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.container.spawner import spawner
        from app.models.server import Server
        from app.models.server_plan import ServerPlan
        from app.models.server_volume import ServerVolume
        from app.models.user import User
        from app.services.credit_service import CreditService
        from app.services.notification_service import (
            NotificationService,
            broadcast_server_status_change,
        )
        from app.services.quota_service import QuotaService
        from app.services.volume_service import VolumeService
        from app.services.xfs_quota_service import xfs_quota_service

        async with AsyncSessionLocal() as db:
            volume_service = VolumeService(db)
            xfs_available = xfs_quota_service._xfs_quota_available()
            stopped_count = 0
            warned_count = 0
            xfs_used = 0
            du_used = 0

            # Get all running/healthy servers with their plans, users, and volume mounts
            result = await db.execute(
                select(Server, ServerPlan, User)
                .join(ServerPlan, Server.plan_id == ServerPlan.id)
                .join(User, Server.user_id == User.id)
                .where(Server.status.in_(["running", "healthy"]))
                .options(selectinload(Server.volume_mounts).selectinload(ServerVolume.volume))
            )
            servers = result.all()

            for server, plan, user in servers:
                should_stop = False
                over_limit_volumes = []

                # Parse plan disk limit once (0 = unlimited if not set)
                plan_bytes = volume_service._parse_memory(plan.disk_limit) if plan.disk_limit else 0

                for sv in server.volume_mounts:
                    volume = sv.volume
                    if not volume:
                        continue

                    # XFS quota report when available (fast, no disk walk), else du -sb
                    size_bytes, source = await volume_service.measure_volume_size(volume.name)
                    if source == "xfs":
                        xfs_used += 1
                    elif source == "du":
                        du_used += 1

                    if size_bytes is None:
                        logger.warning(
                            "Could not measure volume size",
                            extra={"volume": volume.name, "server": server.id},
                        )
                        continue

                    # Update size in DB
                    volume.size_bytes = size_bytes

                    # Check per-volume max_size_bytes (user-defined hard limit)
                    if volume.max_size_bytes and size_bytes > volume.max_size_bytes:
                        should_stop = True
                        over_limit_volumes.append(
                            f"'{volume.display_name or volume.name}' "
                            f"({volume_service._human_size(size_bytes)} / "
                            f"{volume_service._human_size(volume.max_size_bytes)})"
                        )
                        volume.status = "over_limit"
                        continue

                    # Check against plan disk limit
                    # A single volume exceeding the plan limit is a violation
                    if size_bytes > plan_bytes:
                        should_stop = True
                        over_limit_volumes.append(
                            f"'{volume.display_name or volume.name}' "
                            f"({volume_service._human_size(size_bytes)} / "
                            f"{plan.disk_limit})"
                        )
                        volume.status = "over_limit"
                        continue

                    # Warn at 90% of max_size_bytes or plan limit
                    limit_for_warning = volume.max_size_bytes or plan_bytes
                    if limit_for_warning and limit_for_warning > 0:
                        usage_pct = int((size_bytes / limit_for_warning) * 100)
                        if usage_pct >= 90:
                            notif_service = NotificationService(db)
                            await notif_service.volume_near_limit(
                                user_id=volume.owner_id,
                                volume_name=volume.display_name or volume.name,
                                usage_pct=usage_pct,
                            )
                            warned_count += 1

                if should_stop:
                    try:
                        if server.container_id:
                            actual_status = await spawner.get_status(server.container_id)
                            if actual_status in ("stopped", "unknown"):
                                server.status = "stopped"
                                server.container_id = None
                            else:
                                await spawner.delete(server.container_id)
                                server.container_id = None

                        server.status = "stopped"
                        server.stopped_at = datetime.now(UTC).replace(tzinfo=None)
                        server.stop_reason = "volume_quota_exceeded"

                        # Reconcile billing
                        if server.plan_id:
                            credit_service = CreditService(db)
                            await credit_service.reconcile_server_billing(server, plan)

                        # Decrement quota
                        if server.plan_id:
                            quota_service = QuotaService(db)
                            await quota_service.decrement_usage(
                                user_id=str(user.id), plan_id=str(server.plan_id)
                            )

                        await db.commit()

                        # Notify user
                        notif_service = NotificationService(db)
                        await notif_service.server_stopped(
                            user_id=user.id,
                            server_name=server.name,
                            reason=f"volume quota exceeded: {', '.join(over_limit_volumes)}",
                        )
                        await broadcast_server_status_change(
                            user.id,
                            str(server.id),
                            "stopped",
                            {"stop_reason": "volume_quota_exceeded"},
                        )
                        stopped_count += 1

                    except Exception:
                        logger.exception(
                            "Error stopping server %s for volume quota violation", server.id
                        )

            await db.commit()
            method_summary = f"XFS={xfs_used} du={du_used}" if xfs_available else f"du={du_used}"
            return (
                f"Stopped {stopped_count} servers, warned {warned_count} volumes ({method_summary})"
            )

    try:
        return _run_async(_enforce())
    except Exception as e:
        return f"Error in volume quota enforcement: {e}"


@celery_app.task(bind=True)
def check_autovacuum_health(self):
    """Log tables with high dead-tuple ratios for operational awareness.
    Run weekly via Celery Beat. Actual tuning is manual (see docs)."""

    async def _check():
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                SELECT
                    relname AS table_name,
                    n_live_tup,
                    n_dead_tup,
                    ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_pct
                FROM pg_stat_user_tables
                WHERE schemaname = 'public'
                  AND n_dead_tup > 100
                ORDER BY dead_pct DESC NULLS LAST
            """)
            )
            rows = result.mappings().all()
            warnings = [r for r in rows if (r["dead_pct"] or 0) > 20]
            if warnings:
                for w in warnings:
                    logger.warning(
                        "Autovacuum health: high dead tuples",
                        extra={
                            "table": w["table_name"],
                            "live": w["n_live_tup"],
                            "dead": w["n_dead_tup"],
                            "dead_pct": w["dead_pct"],
                        },
                    )
                return f"Autovacuum: {len(warnings)} table(s) exceed 20% dead tuples"
            return "Autovacuum: all tables healthy"

    try:
        return _run_async(_check())
    except Exception as e:
        return f"Error checking autovacuum: {e}"


@celery_app.task(bind=True)
def update_prometheus_business_metrics(self):
    """Update Prometheus gauges for business-level metrics.

    Runs every 60s via Celery Beat. Updates:
    - nukelab_users_total
    - nukelab_servers_total (by status)
    - nukelab_nuke_balance_total
    """
    if not settings.prometheus_enabled:
        return "Prometheus disabled; skipping business metrics update"

    async def _update():
        from sqlalchemy import func, select

        from app.models.server import Server
        from app.models.user import User

        async with AsyncSessionLocal() as db:
            # Total users
            result = await db.execute(select(func.count()).select_from(User))
            users_total = result.scalar() or 0

            # Total NUKE balance
            result = await db.execute(select(func.coalesce(func.sum(User.nuke_balance), 0)))
            nuke_total = result.scalar() or 0

            # Servers by status
            result = await db.execute(select(Server.status, func.count()).group_by(Server.status))
            server_counts = dict(result.all())

        from app.core.prometheus_metrics import (
            set_nuke_balance_total,
            set_servers_total,
            set_users_total,
        )

        set_users_total(users_total)
        set_nuke_balance_total(int(nuke_total))

        # Reset all known status gauges, then set current values
        known_statuses = {"pending", "starting", "running", "stopping", "stopped", "error"}
        for status in known_statuses:
            set_servers_total(status, server_counts.get(status, 0))

        return (
            f"Business metrics updated: users={users_total}, "
            f"nuke={nuke_total}, servers={dict(server_counts)}"
        )

    try:
        return _run_async(_update())
    except Exception as e:
        return f"Error updating business metrics: {e}"


@celery_app.task(bind=True)
def grant_daily_allowance_to_all(self):
    """Auto-grant the daily credit allowance to recently-active users.

    Only users who have logged in within the configured activity window
    (``credits_daily_allowance_login_window_hours``, default 48h) are
    eligible. This prevents dormant accounts from accumulating credits
    every day.

    Idempotent per UTC day: the unique partial index
    uq_credit_tx_daily_allowance_per_user_per_day guarantees a user
    cannot receive more than one daily_allowance transaction per UTC day,
    even if the beat schedule overlaps with a manual claim or a retried
    worker run. Failures for individual users (already granted, inactive, etc.)
    are logged and skipped so one user cannot block the batch.
    """

    async def _grant_all():
        from sqlalchemy import select

        from app.models.user import User
        from app.services.credit_service import CreditService
        from app.services.setting_service import SettingService

        async with AsyncSessionLocal() as db:
            credit_service = CreditService(db)
            setting_service = SettingService(db)
            window_hours = await setting_service.get_daily_allowance_login_window_hours()
            cutoff = utc_now() - timedelta(hours=window_hours)

            result = await db.execute(
                select(User.id, User.username, User.last_login).where(User.is_active.is_(True))
            )
            active_users = result.all()

            granted = 0
            already = 0
            failed = 0
            skipped_inactive = 0

            for user_id, username, last_login in active_users:
                # Only grant to users who have logged in recently. None/NULL
                # last_login means the account has never been used, so it is
                # skipped. This turns the daily allowance into a login reward
                # rather than an accrual for dormant accounts.
                if last_login is None or last_login < cutoff:
                    skipped_inactive += 1
                    continue

                try:
                    await credit_service.grant_daily_allowance(str(user_id))
                    granted += 1
                except HTTPException as exc:
                    # 400 = already granted today; expected on retries / overlaps
                    if exc.status_code == 400:
                        already += 1
                    else:
                        logger.warning(
                            "Daily allowance grant failed for user %s (%s): %s",
                            username,
                            user_id,
                            exc.detail,
                        )
                        failed += 1
                except Exception:
                    logger.exception(
                        "Unexpected error granting daily allowance to user %s (%s)",
                        username,
                        user_id,
                    )
                    failed += 1

            # One audit summary row per batch run keeps the activity log small
            # while still recording that the job ran and what it did.
            from app.services.activity_service import ActivityService

            activity_service = ActivityService(db)
            await activity_service.log(
                action="credits.daily_allowance_batch",
                target_type="system",
                details={
                    "granted": granted,
                    "already_granted": already,
                    "failed": failed,
                    "skipped_inactive": skipped_inactive,
                    "total_active": len(active_users),
                    "login_window_hours": window_hours,
                },
            )

            return (
                f"Daily allowance: granted={granted}, "
                f"already_granted={already}, failed={failed}, "
                f"skipped_inactive={skipped_inactive}, "
                f"total_active={len(active_users)}"
            )

    try:
        return _run_async(_grant_all())
    except Exception as e:
        logger.exception("Fatal error in grant_daily_allowance_to_all: %s", e)
        return f"Fatal error: {e}"


@celery_app.task(bind=True)
def cleanup_expired_allowance_overrides(self):
    """Null out expired daily-allowance overrides for storage hygiene.

    Not strictly required for correctness — grant_daily_allowance uses
    effective_daily_allowance, which already ignores an override once
    override_until < now — but keeping the columns populated past
    expiry clutters the admin UI and the user record. Runs hourly.
    """

    async def _cleanup():
        from datetime import timedelta

        from sqlalchemy import and_, select

        from app.core.time_utils import utc_now
        from app.models.user import User

        async with AsyncSessionLocal() as db:
            # Window: anything that expired at least a minute ago, so
            # we don't race the expiry boundary by milliseconds.
            cutoff = utc_now() - timedelta(minutes=1)
            result = await db.execute(
                select(User).where(
                    and_(
                        User.daily_allowance_override.is_not(None),
                        User.daily_allowance_override_until < cutoff,
                    )
                )
            )
            expired = result.scalars().all()

            for user in expired:
                user.daily_allowance_override = None
                user.daily_allowance_override_until = None

            if expired:
                await db.commit()

            return f"Cleaned up {len(expired)} expired allowance overrides"

    try:
        return _run_async(_cleanup())
    except Exception as e:
        logger.exception("Fatal error in cleanup_expired_allowance_overrides: %s", e)
        return f"Fatal error: {e}"
