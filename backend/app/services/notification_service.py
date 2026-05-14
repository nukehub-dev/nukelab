"""
Notification service for creating user notifications.
Centralizes notification creation to ensure consistency across the app.
"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import Notification


class NotificationService:
    """Service for creating and managing user notifications."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(
        self,
        user_id,
        title: str,
        message: str,
        type: str = "system",
        severity: str = "info",
        action_url: Optional[str] = None,
        extra_data: Optional[dict] = None
    ) -> Notification:
        """Create a notification for a user."""
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=type,
            severity=severity,
            action_url=action_url,
            extra_data=extra_data or {}
        )
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification
    
    async def server_started(self, user_id, server_name: str, action_url: Optional[str] = None) -> Notification:
        """Notify user that their server has started."""
        return await self.create(
            user_id=user_id,
            title="Server Started",
            message=f"Your server '{server_name}' is now running.",
            type="server",
            severity="success",
            action_url=action_url
        )
    
    async def server_stopped(self, user_id, server_name: str, reason: Optional[str] = None, action_url: Optional[str] = None) -> Notification:
        """Notify user that their server has stopped."""
        msg = f"Your server '{server_name}' has been stopped."
        if reason:
            msg = f"Your server '{server_name}' has been stopped: {reason}."
        return await self.create(
            user_id=user_id,
            title="Server Stopped",
            message=msg,
            type="server",
            severity="info",
            action_url=action_url
        )
    
    async def server_restarted(self, user_id, server_name: str, action_url: Optional[str] = None) -> Notification:
        """Notify user that their server has been restarted."""
        return await self.create(
            user_id=user_id,
            title="Server Restarted",
            message=f"Your server '{server_name}' has been restarted.",
            type="server",
            severity="info",
            action_url=action_url
        )
    
    async def server_deleted(self, user_id, server_name: str) -> Notification:
        """Notify user that their server has been deleted."""
        return await self.create(
            user_id=user_id,
            title="Server Deleted",
            message=f"Your server '{server_name}' has been permanently deleted.",
            type="server",
            severity="warning"
        )
    
    async def credits_granted(self, user_id, amount: int, new_balance: int, reason: Optional[str] = None) -> Notification:
        """Notify user that credits have been granted."""
        msg = f"{amount} NUKE credits have been added to your account. New balance: {new_balance}."
        if reason:
            msg = f"{amount} NUKE credits granted: {reason}. New balance: {new_balance}."
        return await self.create(
            user_id=user_id,
            title="Credits Received",
            message=msg,
            type="credit",
            severity="success"
        )
    
    async def credits_deducted(self, user_id, amount: int, new_balance: int, reason: Optional[str] = None) -> Notification:
        """Notify user that credits have been deducted."""
        msg = f"{amount} NUKE credits have been deducted from your account. New balance: {new_balance}."
        if reason:
            msg = f"{amount} NUKE credits deducted: {reason}. New balance: {new_balance}."
        return await self.create(
            user_id=user_id,
            title="Credits Deducted",
            message=msg,
            type="credit",
            severity="warning"
        )
    
    async def daily_allowance(self, user_id, amount: int, new_balance: int) -> Notification:
        """Notify user that daily allowance has been granted."""
        return await self.create(
            user_id=user_id,
            title="Daily Allowance",
            message=f"You received {amount} NUKE credits as your daily allowance. Balance: {new_balance}.",
            type="credit",
            severity="info"
        )
    
    async def low_balance(self, user_id, balance: int, threshold: int = 50) -> Notification:
        """Warn user about low credit balance."""
        return await self.create(
            user_id=user_id,
            title="Low Credit Balance",
            message=f"Your NUKE credit balance is low: {balance} credits remaining. Top up to avoid service interruption.",
            type="credit",
            severity="warning"
        )
