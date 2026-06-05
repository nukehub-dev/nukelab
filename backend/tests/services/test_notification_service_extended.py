"""Extended tests for NotificationService (preferences, all convenience methods)."""

import pytest
from unittest import mock
from sqlalchemy import select

from app.services.notification_service import NotificationService
from app.models.notification import Notification
from app.models.user import User


class TestNotificationServiceCreate:
    """Tests for the core create method with preference handling."""

    @pytest.mark.asyncio
    async def test_create_basic(self, db_session, test_user):
        """Creating a notification with default prefs should succeed."""
        service = NotificationService(db_session)
        notif = await service.create(
            user_id=test_user.id,
            title="Test Title",
            message="Test message",
            type="system",
            severity="info",
        )
        assert notif is not None
        assert notif.title == "Test Title"
        assert notif.message == "Test message"
        assert notif.user_id == test_user.id

    @pytest.mark.asyncio
    async def test_create_with_preferences_in_app_disabled(self, db_session, test_user):
        """When in_app is disabled, no notification should be created."""
        test_user.preferences = {
            "notifications": {
                "events": [
                    {"event": "server_start", "channels": {"in_app": False, "email": False}}
                ]
            }
        }
        await db_session.commit()

        service = NotificationService(db_session)
        notif = await service.create(
            user_id=test_user.id,
            title="Server Started",
            message="Server is running",
            event_key="server_start",
        )
        assert notif is None

    @pytest.mark.asyncio
    async def test_create_with_preferences_in_app_enabled(self, db_session, test_user):
        """When in_app is enabled, notification should be created."""
        test_user.preferences = {
            "notifications": {
                "events": [
                    {"event": "server_start", "channels": {"in_app": True, "email": False}}
                ]
            }
        }
        await db_session.commit()

        service = NotificationService(db_session)
        notif = await service.create(
            user_id=test_user.id,
            title="Server Started",
            message="Server is running",
            event_key="server_start",
        )
        assert notif is not None
        assert notif.title == "Server Started"

    @pytest.mark.asyncio
    async def test_create_no_event_key(self, db_session, test_user):
        """Without event_key, notification defaults to in_app only."""
        service = NotificationService(db_session)
        notif = await service.create(
            user_id=test_user.id,
            title="System Alert",
            message="Something happened",
        )
        assert notif is not None

    @pytest.mark.asyncio
    async def test_create_with_extra_data(self, db_session, test_user):
        """Notification should store extra_data."""
        service = NotificationService(db_session)
        notif = await service.create(
            user_id=test_user.id,
            title="Alert",
            message="Details",
            extra_data={"server_id": "abc", "cpu": 90},
        )
        assert notif.extra_data == {"server_id": "abc", "cpu": 90}

    @pytest.mark.asyncio
    async def test_create_with_action_url(self, db_session, test_user):
        """Notification should store action_url."""
        service = NotificationService(db_session)
        notif = await service.create(
            user_id=test_user.id,
            title="Alert",
            message="Click here",
            action_url="/dashboard/servers/1",
        )
        assert notif.action_url == "/dashboard/servers/1"


class TestNotificationServiceServerMethods:
    """Tests for server-related notification convenience methods."""

    @pytest.mark.asyncio
    async def test_server_started(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.server_started(test_user.id, "my-server")
        assert notif is not None
        assert "my-server" in notif.message
        assert notif.type == "server"
        assert notif.severity == "success"

    @pytest.mark.asyncio
    async def test_server_ready(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.server_ready(test_user.id, "ready-srv", action_url="/url")
        assert notif is not None
        assert "ready" in notif.message.lower()
        assert notif.action_url == "/url"

    @pytest.mark.asyncio
    async def test_server_idle_warning(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.server_idle_warning(test_user.id, "idle-srv", 30)
        assert notif is not None
        assert "idle" in notif.message.lower()
        assert "30" in notif.message
        assert notif.severity == "warning"

    @pytest.mark.asyncio
    async def test_server_stopped(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.server_stopped(test_user.id, "stopped-srv", reason="maintenance")
        assert notif is not None
        assert "stopped" in notif.message.lower()
        assert "maintenance" in notif.message

    @pytest.mark.asyncio
    async def test_server_stopped_no_reason(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.server_stopped(test_user.id, "stopped-srv")
        assert notif is not None
        assert "stopped" in notif.message.lower()

    @pytest.mark.asyncio
    async def test_server_restarted(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.server_restarted(test_user.id, "restarted-srv")
        assert notif is not None
        assert "restarted" in notif.message.lower()

    @pytest.mark.asyncio
    async def test_server_deleted(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.server_deleted(test_user.id, "deleted-srv")
        assert notif is not None
        assert "deleted" in notif.message.lower()
        assert notif.severity == "warning"

    @pytest.mark.asyncio
    async def test_server_failed(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.server_failed(test_user.id, "fail-srv", "Out of memory")
        assert notif is not None
        assert "Failed" in notif.message
        assert "Out of memory" in notif.message
        assert notif.severity == "error"


class TestNotificationServiceCreditMethods:
    """Tests for credit-related notification convenience methods."""

    @pytest.mark.asyncio
    async def test_credits_granted(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.credits_granted(test_user.id, 100, 500)
        assert notif is not None
        assert "100" in notif.message
        assert "500" in notif.message
        assert notif.type == "credit"

    @pytest.mark.asyncio
    async def test_credits_granted_with_reason(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.credits_granted(test_user.id, 50, 200, reason="bonus")
        assert notif is not None
        assert "bonus" in notif.message

    @pytest.mark.asyncio
    async def test_credits_deducted(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.credits_deducted(test_user.id, 10, 90)
        assert notif is not None
        assert "deducted" in notif.message.lower()
        assert notif.severity == "warning"

    @pytest.mark.asyncio
    async def test_daily_allowance(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.daily_allowance(test_user.id, 20, 120)
        assert notif is not None
        assert "daily allowance" in notif.message.lower()

    @pytest.mark.asyncio
    async def test_low_balance(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.low_balance(test_user.id, 25)
        assert notif is not None
        assert "low" in notif.message.lower()
        assert "25" in notif.message
        assert notif.severity == "warning"


class TestNotificationServiceQueueMethods:
    """Tests for queue-related notification convenience methods."""

    @pytest.mark.asyncio
    async def test_queue_timeout(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.queue_timeout(test_user.id, "queued-srv")
        assert notif is not None
        assert "timeout" in notif.message.lower()
        assert notif.severity == "warning"


class TestNotificationServiceWorkspaceMethods:
    """Tests for workspace-related notification convenience methods."""

    @pytest.mark.asyncio
    async def test_workspace_invitation(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.workspace_invitation(test_user.id, "MyWorkspace", "Alice")
        assert notif is not None
        assert "invited" in notif.message.lower()
        assert "MyWorkspace" in notif.message
        assert "Alice" in notif.message

    @pytest.mark.asyncio
    async def test_workspace_member_added(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.workspace_member_added(test_user.id, "TeamSpace")
        assert notif is not None
        assert "added" in notif.message.lower()

    @pytest.mark.asyncio
    async def test_workspace_member_removed(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.workspace_member_removed(test_user.id, "TeamSpace")
        assert notif is not None
        assert "removed" in notif.message.lower()
        assert notif.severity == "warning"

    @pytest.mark.asyncio
    async def test_ownership_transferred(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.ownership_transferred(test_user.id, "TeamSpace", "Bob")
        assert notif is not None
        assert "owner" in notif.message.lower()
        assert "Bob" in notif.message


class TestNotificationServiceVolumeMethods:
    """Tests for volume-related notification convenience methods."""

    @pytest.mark.asyncio
    async def test_volume_created(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.volume_created(test_user.id, "vol1")
        assert notif is not None
        assert "provisioned" in notif.message.lower()
        assert notif.severity == "success"

    @pytest.mark.asyncio
    async def test_volume_near_limit(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.volume_near_limit(test_user.id, "vol1", 85)
        assert notif is not None
        assert "85%" in notif.message
        assert notif.severity == "warning"

    @pytest.mark.asyncio
    async def test_volume_deleted(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.volume_deleted(test_user.id, "vol1")
        assert notif is not None
        assert "deleted" in notif.message.lower()


class TestNotificationServiceSecurityMethods:
    """Tests for security-related notification convenience methods."""

    @pytest.mark.asyncio
    async def test_api_key_created(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.api_key_created(test_user.id, "prod-key")
        assert notif is not None
        assert "prod-key" in notif.message
        assert notif.type == "security"


class TestNotificationServiceSystemMethods:
    """Tests for system-related notification convenience methods."""

    @pytest.mark.asyncio
    async def test_maintenance_window(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.maintenance_window(test_user.id, "Upgrade", "System will be down for 1 hour")
        assert notif is not None
        assert "Upgrade" == notif.title
        assert "down for 1 hour" in notif.message

    @pytest.mark.asyncio
    async def test_server_backup_completed(self, db_session, test_user):
        service = NotificationService(db_session)
        notif = await service.server_backup_completed(test_user.id, "backup-srv", "1.2 GB")
        assert notif is not None
        assert "backup" in notif.message.lower()
        assert "1.2 GB" in notif.message
        assert notif.severity == "success"


class TestNotificationServicePrefs:
    """Tests for notification preference helpers."""

    @pytest.mark.asyncio
    async def test_get_user_notification_prefs_empty(self, db_session, test_user):
        """User with no preferences should return empty dict."""
        service = NotificationService(db_session)
        prefs = await service._get_user_notification_prefs(test_user.id)
        assert prefs == {}

    @pytest.mark.asyncio
    async def test_get_user_notification_prefs_with_events(self, db_session, test_user):
        """User with preferences should return mapped events."""
        test_user.preferences = {
            "notifications": {
                "events": [
                    {"event": "server_start", "channels": {"in_app": True, "email": True}}
                ]
            }
        }
        await db_session.commit()

        service = NotificationService(db_session)
        prefs = await service._get_user_notification_prefs(test_user.id)
        assert "server_start" in prefs
        assert prefs["server_start"]["email"] is True

    @pytest.mark.asyncio
    async def test_should_send_defaults(self, db_session):
        """Default channel settings should be respected."""
        service = NotificationService(db_session)
        assert service._should_send({}, "any", "in_app") is True
        assert service._should_send({}, "any", "email") is False
        assert service._should_send({}, "any", "webhook") is False

    @pytest.mark.asyncio
    async def test_should_send_custom_prefs(self, db_session):
        """Custom preferences should override defaults."""
        service = NotificationService(db_session)
        prefs = {"server_start": {"in_app": False, "email": True, "webhook": True}}
        assert service._should_send(prefs, "server_start", "in_app") is False
        assert service._should_send(prefs, "server_start", "email") is True
        assert service._should_send(prefs, "server_start", "webhook") is True
