"""
Server schedule service for cron-based server scheduling.
"""

import uuid
from datetime import datetime, timedelta, UTC
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.server_schedule import ServerSchedule
from app.models.server import Server
from app.models.notification import Notification
from app.core.time_utils import parse_duration
from app.services.notification_service import broadcast_server_status_change


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
        self, server_id: str, user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
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
        action: Optional[str] = None,
        cron_expression: Optional[str] = None,
        timezone: Optional[str] = None,
        is_active: Optional[bool] = None,
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

    async def get_due_schedules(self) -> List[ServerSchedule]:
        """Get all schedules that are due to run"""
        result = await self.db.execute(
            select(ServerSchedule).where(
                and_(
                    ServerSchedule.is_active == True,
                    ServerSchedule.next_run_at <= datetime.now(UTC).replace(tzinfo=None),
                )
            )
        )
        return result.scalars().all()

    async def execute_schedule(self, schedule: ServerSchedule) -> Dict[str, Any]:
        """Execute a schedule action on a server"""
        from app.container.spawner import spawner
        from app.services.quota_service import QuotaService

        # Get server
        result = await self.db.execute(select(Server).where(Server.id == schedule.server_id))
        server = result.scalar_one_or_none()

        if not server:
            schedule.is_active = False
            schedule.error_message = "Server not found"
            await self.db.commit()
            return {"success": False, "error": "Server not found"}

        success = False
        message = ""

        try:
            if schedule.action == "start":
                if server.container_id:
                    actual = await spawner.get_status(server.container_id)
                    if actual == "stopped":
                        await spawner.start(server.container_id)
                        server.status = "running"
                        server.started_at = datetime.now(UTC).replace(tzinfo=None)
                        server.last_activity = datetime.now(UTC).replace(tzinfo=None)
                        success = True
                        message = f"Server '{server.name}' started by schedule"
                        await broadcast_server_status_change(
                            server.user_id, str(server.id), "running"
                        )
                else:
                    # Need to respawn - this is complex, skip for now
                    message = "Server container missing, cannot auto-start"

            elif schedule.action == "stop":
                if server.container_id and server.status == "running":
                    await spawner.delete(server.container_id)
                    server.container_id = None
                    server.status = "stopped"
                    server.stopped_at = datetime.now(UTC).replace(tzinfo=None)
                    server.stop_reason = "scheduled_stop"
                    await broadcast_server_status_change(
                        server.user_id, str(server.id), "stopped", {"stop_reason": "scheduled_stop"}
                    )

                    # Reconcile exact billing for final partial interval
                    if server.plan_id:
                        from app.services.credit_service import CreditService
                        from app.models.server_plan import ServerPlan

                        credit_service = CreditService(self.db)
                        plan_result = await self.db.execute(
                            select(ServerPlan).where(ServerPlan.id == server.plan_id)
                        )
                        plan = plan_result.scalar_one_or_none()
                        if plan:
                            await credit_service.reconcile_server_billing(server, plan)

                    # Decrement quota
                    if server.plan_id:
                        quota_service = QuotaService(self.db)
                        await quota_service.decrement_usage(
                            user_id=str(server.user_id), plan_id=str(server.plan_id)
                        )

                    success = True
                    message = f"Server '{server.name}' stopped by schedule"

            elif schedule.action == "restart":
                if server.container_id and server.status == "running":
                    await spawner.stop(server.container_id)
                    await spawner.start(server.container_id)
                    server.started_at = datetime.now(UTC).replace(tzinfo=None)
                    server.last_activity = datetime.now(UTC).replace(tzinfo=None)
                    success = True
                    message = f"Server '{server.name}' restarted by schedule"
                    await broadcast_server_status_change(server.user_id, str(server.id), "running")

            if success:
                # Create notification
                notification = Notification(
                    user_id=server.user_id,
                    title="Schedule Executed",
                    message=message,
                    type="server",
                    severity="info",
                )
                self.db.add(notification)

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            return {"success": False, "error": str(e)}

        # Update schedule
        schedule.last_run_at = datetime.now(UTC).replace(tzinfo=None)
        schedule.run_count += 1
        schedule.next_run_at = _get_next_run(schedule.cron_expression, schedule.timezone)
        await self.db.commit()

        return {"success": success, "message": message}
