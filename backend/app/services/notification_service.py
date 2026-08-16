# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Notification service for creating user notifications.
Centralizes notification creation to ensure consistency across the app.
Respects user notification preferences from user.preferences.notifications.events.
"""

import json
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.notification import Notification
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.tasks import send_notification_channels

logger = logging.getLogger(__name__)

# pywebpush is optional at import time so the backend can start without it.
# When unavailable, push notifications are silently skipped.
try:
    from pywebpush import WebPushException, webpush
except Exception:  # pragma: no cover - dependency may be missing
    WebPushException = Exception  # type: ignore[misc,assignment]
    webpush = None

# Maps backend method names to frontend event keys in user preferences
EVENT_KEY_MAP = {
    "server_started": "server_start",
    "server_stopped": "server_stop",
    "server_restarted": "server_start",
    "server_deleted": "server_stop",
    "server_ready": "server_ready",
    "server_failed": "server_failed",
    "server_idle_warning": "server_stop",
    "server_backup_completed": "server_backup_completed",
    "credits_granted": "credit_granted",
    "credits_deducted": "credit_low",
    "credit_request_rejected": "credit_request",
    "credit_request_created": "credit_request",
    "credit_request_message": "credit_request",
    "credit_request_allowance_approved": "credit_request",
    "credit_request_stale_reminder": "credit_request",
    "credit_request_block_changed": "credit_request",
    "daily_allowance": "daily_allowance",
    "low_balance": "credit_low",
    "workspace_invitation": "workspace_invite",
    "workspace_member_added": "workspace_member_added",
    "workspace_member_removed": "workspace_member_removed",
    "ownership_transferred": "ownership_transferred",
    "volume_created": "volume_created",
    "volume_near_limit": "volume_near_limit",
    "volume_deleted": "volume_deleted",
    "api_key_created": "api_key_created",
    "queue_timeout": "queue_position",
    "alert_fired": "alert_fired",
    "maintenance": "maintenance",
    "schedule_run": "schedule_run",
    "queue_position": "queue_position",
}

# Default channel settings when user has no preference for an event
DEFAULT_CHANNELS = {"email": False, "webhook": False, "in_app": True, "push": False}

# Maximum visible characters in a push payload body. The full notification
# message is available in-app; push payloads only need a short preview.
MAX_PUSH_BODY_LENGTH = 120

# Shared Redis client for WebSocket pub/sub. Lazily initialized so
# importing this module does not require a running Redis instance.
_redis_client = None


def _get_redis():
    """Return a shared redis.asyncio client for publishing."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as redis_client_lib

        _redis_client = redis_client_lib.from_url(settings.redis_url)
    return _redis_client


async def broadcast_server_status_change(
    user_id, server_id: str, status: str, extra_data: dict | None = None
):
    """Broadcast a server status change event to the user's WebSocket channel."""
    try:
        r = _get_redis()
        await r.publish(
            f"user:{user_id}",
            json.dumps(
                {
                    "event": "server:status_changed",
                    "user_id": str(user_id),
                    "data": {"server_id": server_id, "status": status, **(extra_data or {})},
                }
            ),
        )
    except Exception:
        pass


class NotificationService:
    """Service for creating and managing user notifications."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_user_notification_prefs(self, user_id) -> dict:
        """Fetch user notification preferences. Returns dict of event_key -> channels."""
        try:
            result = await self.db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user and user.preferences:
                notif_prefs = user.preferences.get("notifications", {})
                events = notif_prefs.get("events", [])
                if events:
                    # events is a list of {event, channels: {email, webhook, in_app}}
                    return {e["event"]: e.get("channels", DEFAULT_CHANNELS) for e in events}
        except Exception:
            pass
        return {}

    def _should_send(self, prefs: dict, event_key: str, channel: str) -> bool:
        """Check if a channel is enabled for an event. Defaults to in_app=True, others=False."""
        event_prefs = prefs.get(event_key, DEFAULT_CHANNELS)
        return event_prefs.get(channel, DEFAULT_CHANNELS.get(channel, False))

    async def _send_email_for_notification(
        self, user_id, title: str, message: str, type: str = "system"
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
                text_body=message,
            )
            if result["success"]:
                logger.info(f"Email sent to {user.email}: {title}")
            else:
                logger.warning(f"Email failed for {user.email}: {result.get('error')}")
        except Exception as e:
            logger.warning(f"Failed to send email notification: {e}")

    async def _send_webhook_for_notification(
        self,
        user_id,
        event_key: str,
        title: str,
        message: str,
        severity: str,
        notification_type: str,
        extra_data: dict,
    ):
        """Dispatch a signed webhook notification to the user's configured URL."""
        try:
            from app.services.webhook_service import WebhookService

            result = await WebhookService().dispatch_to_user(
                user_id=str(user_id),
                event=event_key,
                payload={
                    "title": title,
                    "message": message,
                    "severity": severity,
                    "type": notification_type,
                    "extra_data": extra_data,
                },
                db=self.db,
            )
            if not result["success"]:
                logger.debug("Webhook failed for user %s: %s", user_id, result.get("error"))
        except Exception as e:
            logger.warning("Failed to send webhook notification: %s", e)

    async def _send_push_for_notification(
        self,
        user_id,
        title: str,
        body: str,
        action_url: str | None = None,
    ) -> None:
        """Send a Web Push notification to all user subscriptions.

        Payload is capped to ~2 KB and contains only title, a short body, and
        the optional action_url. Endpoints are treated as secrets and are never
        logged. Dead subscriptions (404/410) are removed.
        """
        if (
            not settings.vapid_private_key
            or not settings.vapid_public_key
            or not settings.vapid_subject
        ):
            return

        if webpush is None:
            logger.warning("pywebpush is not installed; skipping push notification")
            return

        result = await self.db.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
        subscriptions = result.scalars().all()
        if not subscriptions:
            return

        # Push payloads are size-constrained and should not leak the full
        # notification message; keep a short preview and let the user open
        # the app (or action_url) for details.
        short_body = body
        if len(short_body) > MAX_PUSH_BODY_LENGTH:
            short_body = short_body[: MAX_PUSH_BODY_LENGTH - 1].rstrip() + "…"

        payload = {
            "title": title,
            "body": short_body,
        }
        if action_url:
            payload["action_url"] = action_url

        import json

        data = json.dumps(payload)
        if len(data.encode("utf-8")) > 2048:
            # Hard cap as a safety net; truncate body while keeping valid JSON.
            max_body = 1800
            payload["body"] = short_body[:max_body]
            data = json.dumps(payload)

        vapid_claims = {"sub": settings.vapid_subject}

        for subscription in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": subscription.keys,
                    },
                    data=data,
                    vapid_private_key=settings.vapid_private_key,
                    vapid_claims=vapid_claims,
                )
                subscription.last_used_at = utc_now()
            except WebPushException as e:
                status_code = getattr(e.response, "status_code", None)
                if status_code in (404, 410):
                    logger.debug("Removing dead push subscription for user %s", user_id)
                    await self.db.delete(subscription)
                else:
                    logger.warning("Push failed for user %s: %s", user_id, e)
            except Exception as e:
                logger.warning("Push failed for user %s: %s", user_id, e)

        await self.db.commit()

    async def _low_balance_notified_recently(
        self, user_id, event_key: str = "credit_low", hours: int = 24
    ) -> bool:
        """Return True if a credit-low notification was already sent recently."""
        cutoff = utc_now() - timedelta(hours=hours)
        result = await self.db.execute(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.type == "credit",
                Notification.severity == "warning",
                Notification.created_at >= cutoff,
                Notification.extra_data["event_key"].as_string() == event_key,
            )
        )
        return result.scalar_one_or_none() is not None

    async def _publish_to_websocket(self, user_id, notification: Notification):
        """Push notification to WebSocket subscribers via Redis pub/sub."""
        try:
            r = _get_redis()
            payload = {
                "event": "notification:new",
                "user_id": str(user_id),
                "data": notification.to_dict(),
            }
            await r.publish(f"user:{user_id}", json.dumps(payload))
            logger.info(
                "Published notification:new to user:%s notification=%s",
                user_id,
                notification.id,
            )
        except Exception as e:
            logger.warning("Failed to publish notification:new to user:%s: %s", user_id, e)

    async def create(
        self,
        user_id,
        title: str,
        message: str,
        type: str = "system",
        severity: str = "info",
        action_url: str | None = None,
        extra_data: dict | None = None,
        event_key: str | None = None,
    ) -> Notification | None:
        """Create a notification for a user, respecting their preferences.

        If event_key is provided, checks user preferences for in_app, email,
        and webhook channels. If no event_key is provided, defaults to in_app
        only (no email/webhook).
        """
        # Determine effective event key
        if event_key is None:
            event_key = "system"

        prefs = await self._get_user_notification_prefs(user_id)
        should_in_app = self._should_send(prefs, event_key, "in_app")
        should_email = self._should_send(prefs, event_key, "email")
        should_webhook = self._should_send(prefs, event_key, "webhook")
        should_push = self._should_send(prefs, event_key, "push")

        # Store the event key so we can throttle/audit later.
        merged_extra = {"event_key": event_key, **(extra_data or {})}

        notification = None

        if should_in_app:
            notification = Notification(
                user_id=user_id,
                title=title,
                message=message,
                type=type,
                severity=severity,
                action_url=action_url,
                extra_data=merged_extra,
            )
            self.db.add(notification)
            await self.db.commit()
            await self.db.refresh(notification)
            logger.info("Notification created: id=%s event=%s", notification.id, event_key)

            # Push to WebSocket subscribers for instant delivery
            await self._publish_to_websocket(user_id, notification)

        # Offload slower channels so the request/transaction isn't held up
        # by an external email server, webhook endpoint, or push service.
        if should_email or should_webhook or should_push:
            try:
                send_notification_channels.delay(
                    user_id=str(user_id),
                    event_key=event_key,
                    title=title,
                    message=message,
                    severity=severity,
                    notification_type=type,
                    action_url=action_url,
                    extra_data=merged_extra,
                )
            except Exception:
                logger.exception("Failed to enqueue notification channel task")

        return notification

    async def bulk_delete(
        self,
        user_id,
        notification_ids: list[str] | None = None,
        read_only: bool = False,
        all: bool = False,
    ) -> int:
        """Delete notifications scoped to a user.

        Explicit IDs take precedence; filters are ignored when ids are given.
        Returns the number of deleted rows.
        """
        from sqlalchemy import delete

        stmt = delete(Notification).where(Notification.user_id == user_id)

        if notification_ids:
            stmt = stmt.where(Notification.id.in_(notification_ids))
        else:
            if read_only:
                stmt = stmt.where(Notification.read.is_(True))
            if all:
                # all=true with no ids deletes every user notification
                pass

        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def server_started(
        self,
        user_id,
        server_name: str,
        action_url: str | None = None,
        server_id: str | None = None,
    ) -> Notification | None:
        """Notify user that their server has started."""
        return await self.create(
            user_id=user_id,
            title="Server Started",
            message=f"Your server '{server_name}' is now running.",
            type="server",
            severity="success",
            action_url=action_url or (f"/servers/{server_id}" if server_id else None),
            event_key="server_start",
        )

    async def server_ready(
        self,
        user_id,
        server_name: str,
        action_url: str | None = None,
        server_id: str | None = None,
    ) -> Notification | None:
        """Notify user that their server is ready to use."""
        return await self.create(
            user_id=user_id,
            title="Server Ready",
            message=f"Your server '{server_name}' is ready to use.",
            type="server",
            severity="success",
            action_url=action_url or (f"/servers/{server_id}" if server_id else None),
            event_key="server_ready",
        )

    async def server_idle_warning(
        self,
        user_id,
        server_name: str,
        idle_minutes: int,
        action_url: str | None = None,
        server_id: str | None = None,
    ) -> Notification | None:
        """Warn user that their server will stop soon due to inactivity."""
        return await self.create(
            user_id=user_id,
            title="Server Idle Warning",
            message=f"Server '{server_name}' will stop soon due to inactivity. Last activity: {idle_minutes} minutes ago.",
            type="server",
            severity="warning",
            action_url=action_url or (f"/servers/{server_id}" if server_id else None),
            event_key="server_stop",
        )

    async def server_stopped(
        self,
        user_id,
        server_name: str,
        reason: str | None = None,
        action_url: str | None = None,
        server_id: str | None = None,
    ) -> Notification | None:
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
            action_url=action_url or (f"/servers/{server_id}" if server_id else None),
            event_key="server_stop",
        )

    async def server_restarted(
        self,
        user_id,
        server_name: str,
        action_url: str | None = None,
        server_id: str | None = None,
    ) -> Notification | None:
        """Notify user that their server has been restarted."""
        return await self.create(
            user_id=user_id,
            title="Server Restarted",
            message=f"Your server '{server_name}' has been restarted.",
            type="server",
            severity="info",
            action_url=action_url or (f"/servers/{server_id}" if server_id else None),
            event_key="server_start",
        )

    async def server_deleted(
        self, user_id, server_name: str, server_id: str | None = None
    ) -> Notification | None:
        """Notify user that their server has been deleted."""
        return await self.create(
            user_id=user_id,
            title="Server Deleted",
            message=f"Your server '{server_name}' has been permanently deleted.",
            type="server",
            severity="warning",
            action_url=f"/servers/{server_id}" if server_id else None,
            event_key="server_stop",
        )

    async def credits_granted(
        self,
        user_id,
        amount: int,
        new_balance: int,
        reason: str | None = None,
        action_url: str | None = None,
    ) -> Notification | None:
        """Notify user that credits have been granted."""
        msg = f"{amount} NUKE credits have been added to your account. New balance: {new_balance}."
        if reason:
            msg = f"{amount} NUKE credits granted: {reason}. New balance: {new_balance}."
        return await self.create(
            user_id=user_id,
            title="Credits Received",
            message=msg,
            type="credit",
            severity="success",
            action_url=action_url,
            event_key="credit_granted",
        )

    async def credits_deducted(
        self, user_id, amount: int, new_balance: int, reason: str | None = None
    ) -> Notification | None:
        """Notify user that credits have been deducted."""
        msg = f"{amount} NUKE credits have been deducted from your account. New balance: {new_balance}."
        if reason:
            msg = f"{amount} NUKE credits deducted: {reason}. New balance: {new_balance}."
        return await self.create(
            user_id=user_id,
            title="Credits Deducted",
            message=msg,
            type="credit",
            severity="warning",
            event_key="credit_low",
        )

    async def credit_request_rejected(
        self, user_id, amount: int, note: str | None = None, action_url: str | None = None
    ) -> Notification | None:
        """Notify user that their credit request was rejected."""
        msg = f"Your request for {amount} NUKE credits was rejected."
        if note:
            msg = f"Your request for {amount} NUKE credits was rejected: {note}"
        return await self.create(
            user_id=user_id,
            title="Credit Request Rejected",
            message=msg,
            type="credit",
            severity="info",
            action_url=action_url,
            event_key="credit_request",
        )

    async def credit_request_created(
        self,
        user_id,
        amount: int,
        reason: str,
        action_url: str | None = None,
    ) -> Notification | None:
        """Notify a reviewer that a new credit request was submitted."""
        return await self.create(
            user_id=user_id,
            title="New Credit Request",
            message=f"A user requested {amount} NUKE credits: {reason}",
            type="credit",
            severity="info",
            action_url=action_url,
            event_key="credit_request",
        )

    async def credit_request_allowance_approved(
        self, user_id, allowance: int, action_url: str | None = None
    ) -> Notification | None:
        """Notify user that their allowance request was approved."""
        return await self.create(
            user_id=user_id,
            title="Credit Request Approved",
            message=f"Your daily allowance has been set to {allowance} NUKE credits per day.",
            type="credit",
            severity="success",
            action_url=action_url,
            event_key="credit_request",
        )

    async def credit_request_block_changed(
        self, user_id, blocked: bool, reason: str | None = None, until=None
    ) -> Notification | None:
        """Notify user that their ability to create credit requests changed."""
        if blocked:
            title = "Credit Requests Blocked"
            msg = "Your ability to request credits has been disabled."
            if until:
                expiry = until.strftime("%Y-%m-%d %H:%M UTC")
                msg = f"Your ability to request credits has been disabled until {expiry}."
            if reason:
                msg = f"{msg} Reason: {reason}"
            severity = "warning"
        else:
            title = "Credit Requests Unblocked"
            msg = "Your ability to request credits has been restored."
            if reason:
                msg = f"Your ability to request credits has been restored: {reason}"
            severity = "info"
        return await self.create(
            user_id=user_id,
            title=title,
            message=msg,
            type="credit",
            severity=severity,
            event_key="credit_request",
        )

    async def credit_request_stale_reminder(
        self,
        user_id,
        amount: int,
        requester_username: str,
        age_hours: int,
        request_id: str,
        action_url: str | None = None,
    ) -> Notification | None:
        """Remind a reviewer about a stale open credit request.

        The extra_data carries a distinct inner event_key
        ("credit_request_stale") plus the request_id so the reminder
        throttle can find prior reminders for the same request. The inner
        key overrides the preference channel key in merged extra_data; the
        preference lookup itself uses the outer "credit_request" key.
        """
        return await self.create(
            user_id=user_id,
            title="Stale Credit Request",
            message=(
                f"The credit request from {requester_username} for {amount} NUKE "
                f"credits has been waiting for {age_hours} hours."
            ),
            type="credit",
            severity="warning",
            action_url=action_url,
            event_key="credit_request",
            extra_data={"event_key": "credit_request_stale", "request_id": request_id},
        )

    async def credit_request_message(
        self,
        user_id,
        amount: int,
        preview: str,
        action_url: str | None = None,
    ) -> Notification | None:
        """Notify the counterpart of a new message on a credit request."""
        msg = f"New message on the credit request for {amount} NUKE credits."
        if preview:
            msg = f"New message on the credit request for {amount} NUKE credits: {preview}"
        return await self.create(
            user_id=user_id,
            title="Credit Request Update",
            message=msg,
            type="credit",
            severity="info",
            action_url=action_url,
            event_key="credit_request",
        )

    async def daily_allowance(self, user_id, amount: int, new_balance: int) -> Notification | None:
        """Notify user that daily allowance has been granted."""
        return await self.create(
            user_id=user_id,
            title="Daily Allowance",
            message=f"You received {amount} NUKE credits as your daily allowance. Balance: {new_balance}.",
            type="credit",
            severity="info",
            event_key="daily_allowance",
        )

    async def low_balance(self, user_id, balance: int, threshold: int = 50) -> Notification | None:
        """Warn user about low credit balance.

        Throttled to one notification per user per day so the 15-minute billing
        tick does not spam the user while their balance stays low.
        """
        if await self._low_balance_notified_recently(user_id, event_key="credit_low"):
            return None
        return await self.create(
            user_id=user_id,
            title="Low Credit Balance",
            message=f"Your NUKE credit balance is low: {balance} credits remaining. Top up to avoid service interruption.",
            type="credit",
            severity="warning",
            event_key="credit_low",
        )

    async def queue_timeout(
        self,
        user_id,
        server_name: str,
        action_url: str | None = None,
        server_id: str | None = None,
    ) -> Notification | None:
        """Notify user that their queued server timed out."""
        return await self.create(
            user_id=user_id,
            title="Queue Timeout",
            message=f"Server '{server_name}' was removed from the queue due to timeout.",
            type="server",
            severity="warning",
            action_url=action_url or (f"/servers/{server_id}" if server_id else None),
            event_key="queue_position",
        )

    async def server_failed(
        self,
        user_id,
        server_name: str,
        error: str,
        action_url: str | None = None,
        server_id: str | None = None,
    ) -> Notification | None:
        """Notify user that their server failed to start."""
        return await self.create(
            user_id=user_id,
            title="Server Start Failed",
            message=f"Failed to start server '{server_name}': {error}",
            type="server",
            severity="error",
            action_url=action_url or (f"/servers/{server_id}" if server_id else None),
            event_key="server_start",
        )

    async def workspace_invitation(
        self,
        user_id,
        workspace_name: str,
        inviter_name: str,
        action_url: str | None = None,
        workspace_id: str | None = None,
    ) -> Notification | None:
        """Notify user that they've been invited to a workspace."""
        return await self.create(
            user_id=user_id,
            title="Workspace Invitation",
            message=f"{inviter_name} invited you to join the workspace '{workspace_name}'.",
            type="workspace",
            severity="info",
            action_url=action_url or (f"/workspaces/{workspace_id}" if workspace_id else None),
            event_key="workspace_invite",
        )

    async def workspace_member_added(
        self,
        user_id,
        workspace_name: str,
        action_url: str | None = None,
        workspace_id: str | None = None,
    ) -> Notification | None:
        """Notify user that they've been added to a workspace."""
        return await self.create(
            user_id=user_id,
            title="Added to Workspace",
            message=f"You have been added to the workspace '{workspace_name}'.",
            type="workspace",
            severity="info",
            action_url=action_url or (f"/workspaces/{workspace_id}" if workspace_id else None),
            event_key="workspace_member_added",
        )

    async def workspace_member_removed(
        self,
        user_id,
        workspace_name: str,
        action_url: str | None = None,
        workspace_id: str | None = None,
    ) -> Notification | None:
        """Notify user that they've been removed from a workspace."""
        return await self.create(
            user_id=user_id,
            title="Removed from Workspace",
            message=f"You have been removed from the workspace '{workspace_name}'.",
            type="workspace",
            severity="warning",
            action_url=action_url or (f"/workspaces/{workspace_id}" if workspace_id else None),
            event_key="workspace_member_removed",
        )

    async def ownership_transferred(
        self,
        user_id,
        workspace_name: str,
        previous_owner: str,
        action_url: str | None = None,
        workspace_id: str | None = None,
    ) -> Notification | None:
        """Notify user that workspace ownership has been transferred to them."""
        return await self.create(
            user_id=user_id,
            title="Ownership Transferred",
            message=f"You are now the owner of workspace '{workspace_name}' (transferred from {previous_owner}).",
            type="workspace",
            severity="info",
            action_url=action_url or (f"/workspaces/{workspace_id}" if workspace_id else None),
            event_key="ownership_transferred",
        )

    async def volume_created(
        self, user_id, volume_name: str, action_url: str | None = None
    ) -> Notification | None:
        """Notify user that a volume has been created."""
        return await self.create(
            user_id=user_id,
            title="Volume Created",
            message=f"Your volume '{volume_name}' has been provisioned and is ready to use.",
            type="volume",
            severity="success",
            action_url=action_url,
            event_key="volume_created",
        )

    async def volume_near_limit(
        self, user_id, volume_name: str, usage_pct: int, action_url: str | None = None
    ) -> Notification | None:
        """Warn user that a volume is near its capacity limit."""
        return await self.create(
            user_id=user_id,
            title="Volume Near Limit",
            message=f"Your volume '{volume_name}' is at {usage_pct}% capacity. Consider freeing up space or expanding.",
            type="volume",
            severity="warning",
            action_url=action_url,
            event_key="volume_near_limit",
        )

    async def volume_deleted(
        self, user_id, volume_name: str, action_url: str | None = None
    ) -> Notification | None:
        """Notify user that a volume has been deleted."""
        return await self.create(
            user_id=user_id,
            title="Volume Deleted",
            message=f"Your volume '{volume_name}' has been permanently deleted.",
            type="volume",
            severity="warning",
            action_url=action_url,
            event_key="volume_deleted",
        )

    async def api_key_created(
        self, user_id, key_name: str, action_url: str | None = None
    ) -> Notification | None:
        """Notify user that a new API key has been created."""
        return await self.create(
            user_id=user_id,
            title="API Key Created",
            message=f"A new API key '{key_name}' was generated for your account.",
            type="security",
            severity="info",
            action_url=action_url,
            event_key="api_key_created",
        )

    async def maintenance_window(
        self, user_id, title: str, message: str, action_url: str | None = None
    ) -> Notification | None:
        """Notify user about a scheduled maintenance window."""
        return await self.create(
            user_id=user_id,
            title=title,
            message=message,
            type="system",
            severity="warning",
            action_url=action_url,
            event_key="maintenance",
        )

    async def server_backup_completed(
        self, user_id, server_name: str, backup_size: str, action_url: str | None = None
    ) -> Notification | None:
        """Notify user that a server backup has been completed."""
        return await self.create(
            user_id=user_id,
            title="Backup Completed",
            message=f"Backup for server '{server_name}' completed successfully ({backup_size}).",
            type="server",
            severity="success",
            action_url=action_url,
            event_key="server_backup_completed",
        )
