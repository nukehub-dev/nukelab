"""
Maintenance window service for scheduled platform maintenance.
Handles creation, updates, and evaluation of maintenance windows.
"""

import uuid
from datetime import datetime, timedelta, UTC
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.maintenance_window import MaintenanceWindow
from app.models.user import User
from app.services.notification_service import NotificationService
from app.services.setting_service import SettingService
from app.core.logging import get_logger

logger = get_logger(__name__)


class MaintenanceWindowService:
    """Business logic for maintenance windows."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_windows(
        self,
        active_only: bool = False,
        future_only: bool = False,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List maintenance windows, optionally filtered."""
        query = select(MaintenanceWindow).order_by(MaintenanceWindow.start_at.desc())

        if active_only:
            query = query.where(MaintenanceWindow.is_active == True)

        if future_only:
            query = query.where(MaintenanceWindow.end_at >= datetime.now(UTC).replace(tzinfo=None))

        query = query.limit(limit)

        result = await self.db.execute(query)
        windows = result.scalars().all()
        return [w.to_dict() for w in windows]

    async def get_window(self, window_id: str) -> Optional[MaintenanceWindow]:
        """Get a single maintenance window by ID."""
        result = await self.db.execute(
            select(MaintenanceWindow).where(MaintenanceWindow.id == uuid.UUID(window_id))
        )
        return result.scalar_one_or_none()

    async def create_window(
        self,
        title: str,
        message: str,
        start_at: datetime,
        end_at: datetime,
        created_by: Optional[str] = None,
        is_active: bool = True,
        notify_offsets: Optional[List[int]] = None,
    ) -> MaintenanceWindow:
        """Create a new maintenance window."""
        if end_at <= start_at:
            raise ValueError("End time must be after start time")

        if start_at < datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1):
            raise ValueError("Start time must be in the future")

        # Validate offsets — filter out any larger than time until start
        offsets = self._normalize_offsets(notify_offsets, start_at)

        window = MaintenanceWindow(
            title=title,
            message=message,
            start_at=start_at,
            end_at=end_at,
            is_active=is_active,
            notify_offsets=offsets,
            notified_offsets=[],
            created_by=uuid.UUID(created_by) if created_by else None,
        )

        self.db.add(window)
        await self.db.commit()
        await self.db.refresh(window)
        return window

    async def update_window(
        self,
        window_id: str,
        title: Optional[str] = None,
        message: Optional[str] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        is_active: Optional[bool] = None,
        notify_offsets: Optional[List[int]] = None,
    ) -> MaintenanceWindow:
        """Update an existing maintenance window."""
        window = await self.get_window(window_id)
        if not window:
            raise ValueError("Maintenance window not found")

        if title is not None:
            window.title = title
        if message is not None:
            window.message = message
        if start_at is not None:
            window.start_at = start_at
        if end_at is not None:
            window.end_at = end_at
        if is_active is not None:
            window.is_active = is_active
        if notify_offsets is not None:
            window.notify_offsets = self._normalize_offsets(notify_offsets, window.start_at)

        # Validate times if either changed
        if window.end_at <= window.start_at:
            raise ValueError("End time must be after start time")

        # Reset notification state if times changed or offsets changed
        if start_at is not None or end_at is not None or notify_offsets is not None:
            window.auto_enabled = False
            window.auto_disabled = False
            window.notified_offsets = []
            window.notified_at = None

        await self.db.commit()
        await self.db.refresh(window)
        return window

    async def delete_window(self, window_id: str) -> bool:
        """Delete a maintenance window."""
        window = await self.get_window(window_id)
        if not window:
            return False

        await self.db.delete(window)
        await self.db.commit()
        return True

    def _normalize_offsets(self, offsets: Optional[List[int]], start_at: datetime) -> List[int]:
        """Validate and normalize notification offsets.
        Filters out offsets that are larger than the time remaining until start.
        """
        if not offsets:
            return [15]
        now = datetime.now(UTC).replace(tzinfo=None)
        minutes_until_start = int((start_at - now).total_seconds() / 60)
        # Remove duplicates, filter out offsets larger than time until start, sort descending
        unique = sorted(
            set(int(o) for o in offsets if int(o) > 0 and int(o) < minutes_until_start),
            reverse=True
        )
        return unique if unique else [15]

    async def get_pending_notifications(self) -> List[tuple[MaintenanceWindow, int]]:
        """Get (window, offset_minutes) pairs that need notification sent."""
        now = datetime.now(UTC).replace(tzinfo=None)

        result = await self.db.execute(
            select(MaintenanceWindow).where(
                and_(
                    MaintenanceWindow.is_active == True,
                    MaintenanceWindow.start_at > now,
                    MaintenanceWindow.auto_enabled == False,
                )
            )
        )
        windows = result.scalars().all()

        pending: List[tuple[MaintenanceWindow, int]] = []
        for window in windows:
            offsets = window.notify_offsets or [15]
            notified = set(window.notified_offsets or [])
            for offset in offsets:
                if offset in notified:
                    continue
                # Skip if the ideal notification time (start_at - offset) is more than 1 hour in the past
                ideal_notify_time = window.start_at - timedelta(minutes=offset)
                if ideal_notify_time < now - timedelta(hours=1):
                    continue
                threshold = now + timedelta(minutes=offset)
                if window.start_at <= threshold:
                    pending.append((window, offset))
                    break  # Only one offset per window per evaluation cycle
        return pending

    async def get_windows_to_enable(self) -> List[MaintenanceWindow]:
        """Get active windows whose start time has arrived."""
        now = datetime.now(UTC).replace(tzinfo=None)
        result = await self.db.execute(
            select(MaintenanceWindow).where(
                and_(
                    MaintenanceWindow.is_active == True,
                    MaintenanceWindow.start_at <= now,
                    MaintenanceWindow.auto_enabled == False,
                )
            )
        )
        return result.scalars().all()

    async def get_windows_to_disable(self) -> List[MaintenanceWindow]:
        """Get active windows whose end time has passed."""
        now = datetime.now(UTC).replace(tzinfo=None)
        result = await self.db.execute(
            select(MaintenanceWindow).where(
                and_(
                    MaintenanceWindow.is_active == True,
                    MaintenanceWindow.end_at <= now,
                    MaintenanceWindow.auto_enabled == True,
                    MaintenanceWindow.auto_disabled == False,
                )
            )
        )
        return result.scalars().all()

    async def send_advance_notifications(self, window: MaintenanceWindow, offset_minutes: int) -> int:
        """Send advance notifications to all active users for a window."""
        # Get all active users
        result = await self.db.execute(
            select(User).where(User.is_active == True)
        )
        users = result.scalars().all()

        notif_service = NotificationService(self.db)
        sent_count = 0

        start_time_str = window.start_at.strftime("%Y-%m-%d %H:%M UTC")
        end_time_str = window.end_at.strftime("%Y-%m-%d %H:%M UTC")

        # Human-readable offset description
        offset_desc = self._format_offset(offset_minutes)

        for user in users:
            try:
                await notif_service.maintenance_window(
                    user_id=user.id,
                    title=f"Scheduled Maintenance: {window.title}",
                    message=(
                        f"The platform will enter maintenance mode at {start_time_str} "
                        f"until {end_time_str}. {window.message}"
                        f"\n\nReminder: {offset_desc} before start."
                    ),
                )
                sent_count += 1
            except Exception:
                # Continue notifying other users even if one fails
                pass

        # Track that this offset has been notified
        notified = list(window.notified_offsets or [])
        if offset_minutes not in notified:
            notified.append(offset_minutes)
        window.notified_offsets = notified
        window.notified_at = datetime.now(UTC).replace(tzinfo=None)
        await self.db.commit()
        return sent_count

    def _format_offset(self, minutes: int) -> str:
        """Format offset minutes into human-readable string."""
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        if minutes < 1440:
            hours = minutes // 60
            return f"{hours} hour{'s' if hours != 1 else ''}"
        days = minutes // 1440
        return f"{days} day{'s' if days != 1 else ''}"

    async def enable_maintenance(self, window: MaintenanceWindow) -> None:
        """Enable maintenance mode for a window."""
        setting_service = SettingService(self.db)
        await setting_service.save_maintenance(
            enabled=True,
            message=f"[{window.title}] {window.message}",
        )
        window.auto_enabled = True
        await self.db.commit()

    async def disable_maintenance(self, window: MaintenanceWindow) -> None:
        """Disable maintenance mode for a window."""
        setting_service = SettingService(self.db)
        await setting_service.save_maintenance(enabled=False)
        window.auto_disabled = True
        await self.db.commit()

    async def evaluate_windows(self) -> Dict[str, Any]:
        """Evaluate all maintenance windows and take appropriate actions."""
        notifications_sent = 0
        enabled_count = 0
        disabled_count = 0

        # 1. Send advance notifications
        pending = await self.get_pending_notifications()
        for window, offset in pending:
            try:
                sent = await self.send_advance_notifications(window, offset)
                notifications_sent += sent
            except Exception:
                logger.exception("Error sending notifications for window %s", window.id)

        # 2. Enable maintenance mode for windows that have started
        to_enable = await self.get_windows_to_enable()
        for window in to_enable:
            try:
                await self.enable_maintenance(window)
                enabled_count += 1
            except Exception:
                logger.exception("Error enabling maintenance for window %s", window.id)

        # 3. Disable maintenance mode for windows that have ended
        to_disable = await self.get_windows_to_disable()
        for window in to_disable:
            try:
                await self.disable_maintenance(window)
                disabled_count += 1
            except Exception:
                logger.exception("Error disabling maintenance for window %s", window.id)

        return {
            "notifications_sent": notifications_sent,
            "enabled_count": enabled_count,
            "disabled_count": disabled_count,
        }
