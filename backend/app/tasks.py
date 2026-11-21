# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import asyncio
import random
import threading
import time
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.services.operation_reconciler import OperationReconciler
from app.worker import celery_app, ensure_journal_schema

logger = get_logger(__name__)
import contextlib

from app.db.session import AsyncSessionLocal
from app.services.alert_service import AlertService
from app.services.health_check_service import HealthCheckService
from app.services.metrics_collector import MetricsCollector
from app.services.operation_runner import operation_resources, run_operation
from app.services.server_queue_dispatch_service import run_queue_dispatch
from app.services.server_termination_service import ServerTerminationService
from app.services.system_metrics_collector import SystemMetricsCollector

# The recovery scan is scheduled every ``RECOVERY_SCAN_INTERVAL_SECONDS`` but
# each delivery waits a bounded random delay so simultaneous workers do not
# inspect the same rows in lockstep.
RECOVERY_SCAN_JITTER_SECONDS = 5.0


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


async def _release_gpu_devices(db, server_id) -> None:
    """Release a stopped/deleted server's exclusive GPU devices (idempotent).

    Never raises: a failed release must not block task-driven stops;
    GpuAllocatorService.reconcile() is the safety net.
    """
    try:
        from app.services.gpu_allocator import GpuAllocatorService

        await GpuAllocatorService(db).release(str(server_id))
    except Exception:
        logger.exception("Failed to release GPU devices for server %s", server_id)


async def _stop_server_with_bookkeeping(
    db,
    driver,
    server_id,
    *,
    stop_reason,
    notification_reason,
    reconcile_billing=True,
    expected_version=None,
):
    """Terminate first; billing/notifications never run under admission locks."""
    from app.models.server_plan import ServerPlan
    from app.services.credit_service import CreditService
    from app.services.notification_service import (
        NotificationService,
        broadcast_server_status_change,
    )

    server = await ServerTerminationService(db, driver).stop(
        server_id,
        **({"expected_version": expected_version} if expected_version is not None else {}),
    )
    owner_id, name, plan_id = server.user_id, server.name, server.plan_id
    server.stop_reason = stop_reason
    await db.commit()
    if reconcile_billing and plan_id:
        plan = await db.get(ServerPlan, plan_id, populate_existing=True)
        if plan is not None:
            await CreditService(db).reconcile_server_billing(server, plan)
    await db.commit()
    await NotificationService(db).server_stopped(
        user_id=owner_id, server_name=name, reason=notification_reason, server_id=str(server_id)
    )
    await broadcast_server_status_change(
        owner_id, str(server_id), "stopped", {"stop_reason": stop_reason}
    )


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
    action_url: str | None = None,
    extra_data: dict | None = None,
):
    """Send email/webhook/push notification channels asynchronously.

    The in-app notification and real-time WebSocket push are handled in the
    request path so the user gets immediate feedback. Slower outbound channels
    (email, webhook, push) are offloaded to this task to avoid blocking the API.
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
            should_push = service._should_send(prefs, event_key, "push")

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

            if should_push:
                # Push payload is intentionally short and never contains the
                # full message text, which may include sensitive details.
                await service._send_push_for_notification(
                    user_id=user.id,
                    title=title,
                    body=message[:120],
                    action_url=action_url,
                )
                channels.append("push")

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
def remind_stale_credit_requests(self):
    """Re-notify reviewers about open credit requests waiting > 24h.

    Throttled inside CreditRequestService to at most one reminder per
    request per 24h, so the hourly beat entry is safe to overlap.
    """

    async def _remind():
        from app.services.credit_request_service import CreditRequestService

        async with AsyncSessionLocal() as db:
            service = CreditRequestService(db)
            reminded = await service.remind_stale_requests(hours=24)
            return f"Stale credit requests: {reminded} reminders sent"

    try:
        return _run_async(_remind())
    except Exception as e:
        return f"Error reminding stale credit requests: {e}"


@celery_app.task(bind=True)
def cleanup_inactive_servers(self):
    """Cleanup task - stops servers that have been inactive for too long"""
    return "Cleanup completed"


async def _fetch_sidecar_activity(server_ids: list[str]) -> dict[str, datetime]:
    """Poll each server container's auth sidecar for its last allowed request.

    The sidecar records every request it lets through (valid token or
    auth-disabled pass-through), so this captures real proxied traffic that
    never touches the API. Returns naive-UTC datetimes keyed by server id.
    Unreachable containers or older sidecars without /activity simply have no
    entry — callers fall back to the database timestamp, so probe failures
    never block idle shutdown.
    """
    import aiohttp

    results: dict[str, datetime] = {}
    if not server_ids:
        return results

    timeout = aiohttp.ClientTimeout(total=2)

    async with aiohttp.ClientSession(timeout=timeout) as session:

        async def probe(server_id: str) -> None:
            # Short DNS-safe alias assigned at spawn time (see spawner.py).
            url = f"http://srv-{server_id[:8]}:8080/activity"
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()
            except Exception:
                return
            ts = data.get("last_activity") or 0
            if ts > 0:
                results[server_id] = datetime.fromtimestamp(int(ts), UTC).replace(tzinfo=None)

        await asyncio.gather(*(probe(sid) for sid in server_ids))

    return results


@celery_app.task(bind=True)
def shutdown_idle_servers(self):
    """Stop idle servers through the durable runtime termination boundary."""

    async def enforce():
        from sqlalchemy import select

        from app.models.server import Server
        from app.models.user import User

        async with operation_resources() as resources:
            db = resources.db
            rows = (
                await db.execute(
                    select(Server, User)
                    .join(User, Server.user_id == User.id)
                    .where(Server.status.in_(["running", "healthy"]))
                )
            ).all()
            candidates = [
                (server.id, dict(user.preferences or {}), bool(server.container_id))
                for server, user in rows
            ]
            activity = await _fetch_sidecar_activity(
                [str(id_) for id_, _, mounted in candidates if mounted]
            )
            stopped = 0
            for server_id, prefs, _ in candidates:
                if not prefs.get("idle_shutdown_enabled", True):
                    continue
                server = await db.get(Server, server_id, populate_existing=True)
                if server is None or server.status not in ("running", "healthy"):
                    continue
                timeout = prefs.get("idle_shutdown_timeout", 15)
                cutoff = utc_now() - timedelta(minutes=timeout)
                last_activity = server.last_activity or server.started_at
                observed = activity.get(str(server_id))
                if observed and (last_activity is None or observed > last_activity):
                    last_activity = observed
                if observed and (server.last_activity is None or observed > server.last_activity):
                    server.last_activity = observed
                    await db.commit()
                if last_activity is None or last_activity >= cutoff:
                    continue
                try:
                    await db.commit()
                    await _stop_server_with_bookkeeping(
                        db,
                        resources.driver,
                        server_id,
                        expected_version=server.updated_at,
                        stop_reason="idle_timeout",
                        notification_reason=f"inactivity ({timeout} minutes)",
                    )
                    stopped += 1
                except Exception:
                    await db.rollback()
                    logger.exception("Error auto-stopping idle server %s", server_id)
            return f"Stopped {stopped} idle servers"

    try:
        return run_operation(enforce, timeout_seconds=settings.server_launch_timeout_seconds)
    except Exception as exc:
        return f"Error in idle shutdown enforcement: {exc}"


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
    """Probe/restart using resources owned by this joined worker operation."""

    async def check():
        async with operation_resources() as resources:
            await HealthCheckService(resources.db).check_all_containers()

    try:
        run_operation(check, timeout_seconds=settings.server_launch_timeout_seconds)
        return "Health checks completed"
    except Exception as exc:
        return f"Error checking health: {exc}"


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
    """Bill running servers; depletion stops use verified durable termination."""

    async def bill():
        from sqlalchemy import select

        from app.models.server import Server
        from app.models.server_plan import ServerPlan
        from app.models.user import User
        from app.services.credit_service import CreditService
        from app.services.notification_service import NotificationService

        async with operation_resources() as resources:
            db = resources.db
            rows = (
                await db.execute(
                    select(Server, ServerPlan)
                    .join(ServerPlan, Server.plan_id == ServerPlan.id)
                    .where(Server.status == "running")
                )
            ).all()
            candidates = [(server.id, plan.id) for server, plan in rows]
            billed = stopped = 0
            for server_id, plan_id in candidates:
                server = await db.get(Server, server_id, populate_existing=True)
                plan = await db.get(ServerPlan, plan_id, populate_existing=True)
                if (
                    server is None
                    or server.status != "running"
                    or plan is None
                    or plan.cost_per_hour <= 0
                ):
                    continue
                owner_id, name, rate = server.user_id, server.name, plan.cost_per_hour
                balance = (
                    await db.execute(select(User.nuke_balance).where(User.id == owner_id))
                ).scalar_one_or_none() or 0
                if balance <= 0:
                    if settings.server_auto_stop_on_depletion:
                        try:
                            await db.commit()
                            await _stop_server_with_bookkeeping(
                                db,
                                resources.driver,
                                server_id,
                                expected_version=server.updated_at,
                                stop_reason="credit_depleted",
                                notification_reason="insufficient NUKE credits",
                            )
                            stopped += 1
                        except Exception:
                            await db.rollback()
                            logger.exception("Error stopping depleted server %s", server_id)
                    continue
                amount = max(1, int(rate * 0.25))
                try:
                    await CreditService(db).consume_credits(
                        user_id=str(owner_id),
                        amount=amount,
                        description=f"Server usage: '{name}' (15 min at {rate} NUKE/hour)",
                        server_id=str(server_id),
                    )
                    server.total_cost = (server.total_cost or 0) + amount
                    server.last_billed_at = utc_now()
                    await db.commit()
                    billed += 1
                    if balance - amount <= rate * 2:
                        await NotificationService(db).low_balance(
                            user_id=owner_id, balance=balance - amount
                        )
                except Exception:
                    await db.rollback()
                    logger.exception("Error billing server %s", server_id)
            await db.commit()
            return f"Billed {billed} servers, stopped {stopped} servers"

    try:
        return run_operation(bill, timeout_seconds=settings.server_launch_timeout_seconds)
    except Exception as exc:
        return f"Error in NUKE billing: {exc}"


@celery_app.task(bind=True)
def enforce_auto_stop(self):
    """Stop expired servers without releasing uncertain runtime reservations."""

    async def enforce():
        from sqlalchemy import select

        from app.models.server import Server

        async with operation_resources() as resources:
            db = resources.db
            rows = (
                (await db.execute(select(Server).where(Server.status == "running"))).scalars().all()
            )
            server_ids = [server.id for server in rows]
            stopped = 0
            for server_id in server_ids:
                server = await db.get(Server, server_id, populate_existing=True)
                if (
                    server is None
                    or server.status != "running"
                    or not server.expires_at
                    or utc_now() < server.expires_at
                ):
                    continue
                try:
                    await db.commit()
                    await _stop_server_with_bookkeeping(
                        db,
                        resources.driver,
                        server_id,
                        expected_version=server.updated_at,
                        stop_reason="max_runtime_exceeded",
                        notification_reason="exceeded the maximum runtime limit",
                        reconcile_billing=False,
                    )
                    stopped += 1
                except Exception:
                    await db.rollback()
                    logger.exception("Error auto-stopping expired server %s", server_id)
            return f"Stopped {stopped} servers"

    try:
        return run_operation(enforce, timeout_seconds=settings.server_launch_timeout_seconds)
    except Exception as exc:
        return f"Error in auto-stop enforcement: {exc}"


@celery_app.task(bind=True)
def process_server_queue(self):
    """Dispatch complete preserved requests through atomic shared admission."""
    try:
        result = run_queue_dispatch(
            timeout_seconds=settings.server_launch_timeout_seconds,
            batch_size=settings.queue_dispatch_batch_size,
        )
        return f"Started {result.started} queued servers, timed out {result.expired} entries"
    except Exception as exc:
        return f"Error processing queue: {exc}"


@celery_app.task(bind=True)
def evaluate_schedules(self):
    """Evaluate schedules within one joined loop-owned operation."""

    async def evaluate():
        from sqlalchemy import inspect

        from app.services.schedule_service import ScheduleService

        async with operation_resources() as resources:
            service = ScheduleService(resources.db)
            schedules = await service.get_due_schedules()
            candidates = [(inspect(schedule).identity[0], schedule) for schedule in schedules]
            executed = failed = 0
            for schedule_id, schedule in candidates:
                try:
                    result = await service.execute_schedule(schedule)
                    if result.get("success"):
                        executed += 1
                    else:
                        failed += 1
                        logger.error("Schedule %s failed: %s", schedule_id, result.get("error"))
                except Exception:
                    await resources.db.rollback()
                    failed += 1
                    logger.exception("Error executing schedule %s", schedule_id)
            return f"Executed {executed} schedules, {failed} failed"

    try:
        return run_operation(evaluate, timeout_seconds=settings.server_launch_timeout_seconds)
    except Exception as exc:
        return f"Error evaluating schedules: {exc}"


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

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.models.server import Server
        from app.models.server_plan import ServerPlan
        from app.models.server_volume import ServerVolume
        from app.models.user import User
        from app.services.notification_service import NotificationService
        from app.services.volume_service import VolumeService
        from app.services.xfs_quota_service import xfs_quota_service

        async with operation_resources() as resources:
            db = resources.db
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

            server_ids = [server.id for server, _, _ in servers]
            for server_id in server_ids:
                current = await db.execute(
                    select(Server, ServerPlan, User)
                    .join(ServerPlan, Server.plan_id == ServerPlan.id)
                    .join(User, Server.user_id == User.id)
                    .where(Server.id == server_id, Server.status.in_(["running", "healthy"]))
                    .options(selectinload(Server.volume_mounts).selectinload(ServerVolume.volume))
                    .execution_options(populate_existing=True)
                )
                row = current.one_or_none()
                if row is None:
                    continue
                server, plan, user = row
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
                    if plan_bytes and size_bytes > plan_bytes:
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

                # Preserve measured sizes/status before the lifecycle boundary
                # checks for unrelated pending changes and closes read transactions.
                await db.commit()
                if should_stop:
                    try:
                        await _stop_server_with_bookkeeping(
                            db,
                            resources.driver,
                            server_id,
                            expected_version=server.updated_at,
                            stop_reason="volume_quota_exceeded",
                            notification_reason=f"volume quota exceeded: {', '.join(over_limit_volumes)}",
                        )
                        stopped_count += 1
                    except Exception:
                        await db.rollback()
                        logger.exception(
                            "Error stopping server %s for volume quota violation", server_id
                        )

            await db.commit()
            method_summary = f"XFS={xfs_used} du={du_used}" if xfs_available else f"du={du_used}"
            return (
                f"Stopped {stopped_count} servers, warned {warned_count} volumes ({method_summary})"
            )

    try:
        return run_operation(_enforce, timeout_seconds=settings.server_launch_timeout_seconds)
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


def enqueue_volume_recovery(kind: str, operation_id: str):
    """Best-effort delivery; committed pending intents also have a bounded dispatcher."""
    if kind not in ("backup", "restore", "delete"):
        raise ValueError("Invalid recovery operation")
    return process_volume_recovery.delay(kind, operation_id)


@celery_app.task(bind=True)
def process_volume_recovery(self, kind: str, operation_id: str):
    import uuid

    async def execute():
        from app.services.volume_backup_service import VolumeBackupService
        from app.services.volume_recovery_runtime import VolumeRecoveryRuntime

        identifier = uuid.UUID(operation_id)
        async with operation_resources() as resources:
            service = VolumeBackupService(resources.db, VolumeRecoveryRuntime(resources.driver))
            from app.models.volume_backup import VolumeBackup
            from app.models.volume_restore import VolumeRestore

            model = VolumeRestore if kind == "restore" else VolumeBackup
            before = await resources.db.get(model, identifier)
            before_status = before.status if before else None
            operation = {
                "backup": service.execute_backup,
                "restore": service.execute_restore,
                "delete": service.execute_delete,
            }.get(kind)
            if operation is None:
                raise ValueError("Invalid recovery operation")
            result = await operation(identifier)
            if (
                result.status in ("completed", "failed", "recovery_required")
                and result.status != before_status
            ):
                try:
                    row = await resources.db.get(model, identifier, populate_existing=True)
                    if row is not None and row.user_id is not None:
                        from app.services.notification_service import NotificationService

                        await NotificationService(resources.db).create(
                            user_id=row.user_id,
                            title="Volume recovery completed"
                            if result.status == "completed"
                            else "Volume recovery needs attention",
                            message="Your volume recovery operation completed."
                            if result.status == "completed"
                            else "Inspect backup history for the recovery outcome.",
                            type="volume",
                            severity="info" if result.status == "completed" else "warning",
                            action_url="/volumes",
                            event_key="volume_recovery_completed"
                            if result.status == "completed"
                            else "volume_recovery_failed",
                        )
                except Exception:
                    logger.exception("Recovery notification delivery failed")
            return result.model_dump(mode="json")

    return run_operation(execute, timeout_seconds=settings.volume_backup_timeout_seconds + 30)


@celery_app.task(bind=True)
def dispatch_volume_recovery(self):
    """Deliver bounded pending work and expired unpinned artifacts without TTL takeover."""

    async def dispatch():
        from sqlalchemy import select

        from app.models.volume_backup import VolumeBackup
        from app.models.volume_restore import VolumeRestore
        from app.services.volume_backup_service import VolumeBackupService
        from app.services.volume_recovery_runtime import VolumeRecoveryRuntime

        if not settings.volume_backup_storage_path or not settings.volume_backup_host_path:
            return "Volume recovery is disabled"
        async with operation_resources() as resources:
            db = resources.db
            service = VolumeBackupService(db, VolumeRecoveryRuntime(resources.driver))
            expired = await service.retention_candidates(limit=20)
            for identifier in expired:
                try:
                    await service.expire_backup(identifier)
                except Exception:
                    await db.rollback()
                    logger.warning("Backup retention admission deferred")
            backups = list(
                (
                    await db.execute(
                        select(VolumeBackup.id, VolumeBackup.status)
                        .where(
                            VolumeBackup.status.in_(["pending", "deleting"]),
                            VolumeBackup.helper_identity.is_(None)
                            | ~VolumeBackup.helper_identity.startswith("delete:"),
                        )
                        .order_by(VolumeBackup.created_at, VolumeBackup.id)
                        .limit(20)
                    )
                ).all()
            )
            restores = list(
                await db.scalars(
                    select(VolumeRestore.id)
                    .where(VolumeRestore.status == "pending")
                    .order_by(VolumeRestore.created_at, VolumeRestore.id)
                    .limit(20)
                )
            )
        dispatched = 0
        for identifier, state in backups:
            try:
                enqueue_volume_recovery(
                    "delete" if state == "deleting" else "backup", str(identifier)
                )
                dispatched += 1
            except Exception:
                logger.warning("Durable backup remains pending delivery")
        for identifier in restores:
            try:
                enqueue_volume_recovery("restore", str(identifier))
                dispatched += 1
            except Exception:
                logger.warning("Durable restore remains pending delivery")
        return f"Dispatched {dispatched} volume recovery operations"

    return run_operation(dispatch, timeout_seconds=settings.volume_backup_timeout_seconds)


@celery_app.task(bind=True)
def reconcile_operations(self, jitter: bool = True):
    """Inspect active journal rows and apply only proof-backed outcomes.

    The task is deliberately idempotent and owns its DB/driver resources for
    one event loop. A broker or database failure leaves the durable rows for
    the next beat tick; no reservation is released from age or heartbeat
    absence alone.
    """
    if not ensure_journal_schema():
        logger.critical("Operation reconciliation refused: incompatible journal schema")
        return "Operation reconciliation blocked: incompatible journal schema"

    if jitter:
        time.sleep(random.uniform(0.0, RECOVERY_SCAN_JITTER_SECONDS))

    async def reconcile():
        async with operation_resources() as resources:
            session_factory = async_sessionmaker(resources.db.bind, expire_on_commit=False)
            reconciler = OperationReconciler(session_factory, resources.driver)
            return await reconciler.scan(limit=settings.recovery_scan_batch_size)

    # A pass is bounded by row count. Give runtime inspection a small multiple
    # of the beat interval before the joined loop is cancelled; the next tick
    # retries any rows the cancelled pass did not reach.
    timeout_seconds = min(
        float(settings.server_launch_timeout_seconds),
        max(30.0, float(settings.recovery_scan_interval_seconds) * 4.0),
    )
    try:
        report = run_operation(reconcile, timeout_seconds=timeout_seconds)
    except Exception as exc:
        logger.warning(
            "Operation reconciliation scan deferred",
            extra={"error_class": type(exc).__name__},
        )
        return "Operation reconciliation deferred"

    logger.info("Operation reconciliation task complete", extra=report.as_dict())
    return (
        f"Reconciled {report.scanned} operations: {report.finalized} finalized, "
        f"{report.deferred} deferred, {report.recovery_required} recovery required, "
        f"{report.errors} errors"
    )
