# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Server schedule service for cron-based server scheduling.
"""

import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container.factory import get_fresh_driver
from app.core.logging import get_logger
from app.models.notification import Notification
from app.models.server import Server
from app.models.server_schedule import ServerSchedule
from app.services.notification_service import broadcast_server_status_change
from app.services.server_lifecycle_service import ServerLifecycleService
from app.services.server_termination_service import ServerTerminationService

logger = get_logger(__name__)


def _validate_cron(cron_expression: str) -> None:
    """Validate a cron expression using croniter."""
    try:
        from croniter import croniter

        croniter(cron_expression)
    except Exception as e:
        raise ValueError(f"Invalid cron expression: {str(e)}")


def _get_next_run(cron_expression: str, timezone: str = "UTC") -> datetime:
    """Calculate next run time from cron expression."""
    from croniter import croniter

    base = datetime.now(UTC).replace(tzinfo=None)
    itr = croniter(cron_expression, base)
    next_dt = itr.get_next(datetime)
    return next_dt


class ScheduleService:
    """Server schedule business logic"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_schedules_for_server(
        self, server_id: str, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all schedules for a server"""
        query = select(ServerSchedule).where(ServerSchedule.server_id == uuid.UUID(server_id))

        if user_id:
            query = query.where(ServerSchedule.user_id == uuid.UUID(user_id))

        query = query.order_by(ServerSchedule.created_at.desc())

        result = await self.db.execute(query)
        schedules = result.scalars().all()

        return [s.to_dict() for s in schedules]

    async def create_schedule(
        self,
        server_id: str,
        user_id: str,
        action: str,
        cron_expression: str,
        timezone: str = "UTC",
        is_active: bool = True,
    ) -> ServerSchedule:
        """Create a new schedule for a server"""

        # Validate action
        if action not in ["start", "stop", "restart"]:
            raise ValueError(f"Invalid action: {action}. Must be start, stop, or restart")

        # Validate cron expression
        _validate_cron(cron_expression)

        schedule = ServerSchedule(
            server_id=uuid.UUID(server_id),
            user_id=uuid.UUID(user_id),
            action=action,
            cron_expression=cron_expression,
            timezone=timezone,
            is_active=is_active,
            next_run_at=_get_next_run(cron_expression, timezone),
        )

        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)

        return schedule

    async def update_schedule(
        self,
        schedule_id: str,
        user_id: str,
        action: str | None = None,
        cron_expression: str | None = None,
        timezone: str | None = None,
        is_active: bool | None = None,
    ) -> ServerSchedule:
        """Update an existing schedule"""

        result = await self.db.execute(
            select(ServerSchedule).where(
                and_(
                    ServerSchedule.id == uuid.UUID(schedule_id),
                    ServerSchedule.user_id == uuid.UUID(user_id),
                )
            )
        )
        schedule = result.scalar_one_or_none()

        if not schedule:
            raise ValueError("Schedule not found")

        if action is not None:
            if action not in ["start", "stop", "restart"]:
                raise ValueError(f"Invalid action: {action}")
            schedule.action = action

        if cron_expression is not None:
            _validate_cron(cron_expression)
            schedule.cron_expression = cron_expression

        if timezone is not None:
            schedule.timezone = timezone

        if is_active is not None:
            schedule.is_active = is_active

        schedule.next_run_at = _get_next_run(schedule.cron_expression, schedule.timezone)

        await self.db.commit()
        await self.db.refresh(schedule)

        return schedule

    async def delete_schedule(self, schedule_id: str, user_id: str) -> bool:
        """Delete a schedule"""
        result = await self.db.execute(
            select(ServerSchedule).where(
                and_(
                    ServerSchedule.id == uuid.UUID(schedule_id),
                    ServerSchedule.user_id == uuid.UUID(user_id),
                )
            )
        )
        schedule = result.scalar_one_or_none()

        if not schedule:
            return False

        await self.db.delete(schedule)
        await self.db.commit()
        return True

    async def get_due_schedules(self) -> list[ServerSchedule]:
        """Get all schedules that are due to run"""
        result = await self.db.execute(
            select(ServerSchedule).where(
                and_(
                    ServerSchedule.is_active,
                    ServerSchedule.next_run_at <= datetime.now(UTC).replace(tzinfo=None),
                )
            )
        )
        return result.scalars().all()

    async def execute_schedule(self, schedule: ServerSchedule) -> dict[str, Any]:
        """Execute through shared admission using one loop-owned runtime driver."""
        # Earlier actions may have rolled back read transactions, expiring every
        # ORM row in a scanner's list. ORM identity remains available without I/O.
        identity = inspect(schedule).identity
        schedule_id = identity[0] if identity else schedule.id
        schedule = await self.db.get(ServerSchedule, schedule_id, populate_existing=True)
        if schedule is None:
            return {"success": False, "error": "Schedule not found"}
        server_id, action = schedule.server_id, schedule.action
        cron, timezone = schedule.cron_expression, schedule.timezone
        result = await self.db.execute(
            select(Server).where(Server.id == server_id).execution_options(populate_existing=True)
        )
        server = result.scalar_one_or_none()
        if server is None:
            schedule.is_active = False
            schedule.error_message = "Server not found"
            await self.db.commit()
            return {"success": False, "error": "Server not found"}
        owner_id, server_name, plan_id = server.user_id, server.name, server.plan_id
        original_status = server.status
        success, message = False, ""
        runtime = None
        try:
            needs_action = (
                (action == "start" and original_status != "running")
                or (action == "stop" and original_status != "stopped")
                or (action == "restart" and original_status == "running")
            )
            if needs_action:
                runtime = await get_fresh_driver()
                if action == "stop":
                    server = await ServerTerminationService(self.db, runtime).stop(
                        server_id, owner_id
                    )
                    server.stop_reason = "scheduled_stop"
                    # Billing intentionally happens outside admission/runtime locks.
                    if plan_id:
                        from app.models.server_plan import ServerPlan
                        from app.services.credit_service import CreditService

                        plan = await self.db.get(ServerPlan, plan_id)
                        if plan:
                            await CreditService(self.db).reconcile_server_billing(server, plan)
                    status, verb = "stopped", "stopped"
                else:
                    lifecycle = ServerLifecycleService(self.db, runtime)
                    if action == "start":
                        server = await lifecycle.start(server_id, owner_id=owner_id)
                        verb = "started"
                    else:
                        server = await lifecycle.restart(server_id, owner_id=owner_id)
                        verb = "restarted"
                    status = "running"
                success = True
                message = f"Server '{server_name}' {verb} by schedule"
                self.db.add(
                    Notification(
                        user_id=owner_id,
                        title="Schedule Executed",
                        message=message,
                        type="server",
                        severity="info",
                    )
                )
                await self.db.commit()
                await broadcast_server_status_change(
                    owner_id,
                    str(server_id),
                    status,
                    *([{"stop_reason": "scheduled_stop"}] if action == "stop" else []),
                )
            # Refresh after the lifecycle boundary expired the scanner's ORM rows.
            current = await self.db.get(ServerSchedule, schedule_id, populate_existing=True)
            if current is not None:
                current.last_run_at = datetime.now(UTC).replace(tzinfo=None)
                current.run_count = (current.run_count or 0) + 1
                current.next_run_at = _get_next_run(cron, timezone)
                await self.db.commit()
            return {"success": success, "message": message}
        except Exception as exc:
            await self.db.rollback()
            logger.exception("Scheduled action failed", extra={"server_id": str(server_id)})
            return {"success": False, "error": getattr(exc, "code", "Scheduled action failed")}
        finally:
            if runtime is not None:
                with contextlib.suppress(Exception):
                    await runtime.close()
