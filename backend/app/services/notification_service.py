"""
Notification service for creating user notifications.
Centralizes notification creation to ensure consistency across the app.
"""

import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.notification import Notification
from app.models.user import User
from app.config import settings


async def broadcast_server_status_change(user_id, server_id: str, status: str, extra_data: Optional[dict] = None):
    """Broadcast a server status change event to the user's WebSocket channel."""
    try:
        import redis.asyncio as redis_client
        r = redis_client.from_url(settings.redis_url)
        await r.publish(
            f"user:{user_id}",
            json.dumps({
                "event": "server:status_changed",
                "user_id": str(user_id),
                "data": {
                    "server_id": server_id,
                    "status": status,
                    **(extra_data or {})
                }
            })
        )
        await r.close()
    except Exception:
        pass


class NotificationService:
    """Service for creating and managing user notifications."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def _send_email_for_notification(
        self,
        user_id,
        title: str,
        message: str,
        type: str = "system"
    ):
        """Send an email notification to the user. Silently logs errors."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            from app.services.email_service import EmailService
            email_service = EmailService()
            if not email_service.enabled:
                return
            
            # Fetch user email
            result = await self.db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user or not user.email:
                return
            
            # Build simple HTML email body
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #4F46E5;">{title}</h2>
                    <p>{message}</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="font-size: 12px; color: #666;">
                        This is an automated notification from NukeLab.<br>
                        You can manage your notification preferences in your account settings.
                    </p>
                </div>
            </body>
            </html>
            """
            
            result = await email_service.send_email(
                to_email=user.email,
                subject=f"[NukeLab] {title}",
                html_body=html_body,
                text_body=message
            )
            if result["success"]:
                logger.info(f"Email sent to {user.email}: {title}")
            else:
                logger.warning(f"Email failed for {user.email}: {result.get('error')}")
        except Exception as e:
            logger.warning(f"Failed to send email notification: {e}")
    
    async def _publish_to_websocket(self, user_id, notification: Notification):
        """Push notification to WebSocket subscribers via Redis pub/sub."""
        try:
            import redis.asyncio as redis_client
            r = redis_client.from_url(settings.redis_url)
            await r.publish(
                f"user:{user_id}",
                json.dumps({
                    "event": "notification:new",
                    "user_id": str(user_id),
                    "data": notification.to_dict()
                })
            )
            await r.close()
        except Exception:
            pass

    async def create(
        self,
        user_id,
        title: str,
        message: str,
        type: str = "system",
        severity: str = "info",
        action_url: Optional[str] = None,
        extra_data: Optional[dict] = None,
        send_email: bool = False
    ) -> Notification:
        """Create a notification for a user."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Creating notification for user={user_id}: {title}")
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
        logger.info(f"Notification created: id={notification.id}")

        # Push to WebSocket subscribers for instant delivery
        await self._publish_to_websocket(user_id, notification)

        if send_email:
            await self._send_email_for_notification(user_id, title, message, type)

        return notification
    
    async def server_started(self, user_id, server_name: str, action_url: Optional[str] = None) -> Notification:
        """Notify user that their server has started."""
        return await self.create(
            user_id=user_id,
            title="Server Started",
            message=f"Your server '{server_name}' is now running.",
            type="server",
            severity="success",
            action_url=action_url,
            send_email=True
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
            action_url=action_url,
            send_email=True
        )
    
    async def server_restarted(self, user_id, server_name: str, action_url: Optional[str] = None) -> Notification:
        """Notify user that their server has been restarted."""
        return await self.create(
            user_id=user_id,
            title="Server Restarted",
            message=f"Your server '{server_name}' has been restarted.",
            type="server",
            severity="info",
            action_url=action_url,
            send_email=True
        )
    
    async def server_deleted(self, user_id, server_name: str) -> Notification:
        """Notify user that their server has been deleted."""
        return await self.create(
            user_id=user_id,
            title="Server Deleted",
            message=f"Your server '{server_name}' has been permanently deleted.",
            type="server",
            severity="warning",
            send_email=True
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
    
    async def workspace_invitation(self, user_id, workspace_name: str, inviter_name: str, action_url: Optional[str] = None) -> Notification:
        """Notify user that they've been invited to a workspace."""
        return await self.create(
            user_id=user_id,
            title="Workspace Invitation",
            message=f"{inviter_name} invited you to join the workspace '{workspace_name}'.",
            type="workspace",
            severity="info",
            action_url=action_url
        )
