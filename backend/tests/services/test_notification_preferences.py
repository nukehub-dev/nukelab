"""
Tests for NotificationService preference checking.

Ensures notifications respect user preferences for in_app and email channels.
"""

from unittest.mock import patch

import pytest

from app.services.notification_service import NotificationService


@pytest.fixture
def mock_send_channels():
    """Patch the Celery task that sends email/webhook channels."""
    with patch("app.services.notification_service.send_notification_channels") as m:
        yield m


class TestNotificationPreferences:
    """Test that NotificationService respects user preferences."""

    @pytest.mark.asyncio
    async def test_default_behavior_creates_in_app_only(
        self, db_session, test_user, mock_send_channels
    ):
        """With no preferences set, should create in-app notification but not email."""
        service = NotificationService(db_session)

        notif = await service.server_started(user_id=test_user.id, server_name="test-server")

        # Should create notification
        assert notif is not None
        assert notif.title == "Server Started"
        assert notif.type == "server"

        # Should NOT enqueue async channels (default is email=False, webhook=False)
        mock_send_channels.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_in_app_disabled_skips_notification(
        self, db_session, test_user, mock_send_channels
    ):
        """When in_app is disabled for an event, no notification should be created."""
        # Set preferences: in_app=False, email=False
        test_user.preferences = {
            "notifications": {
                "events": [
                    {
                        "event": "server_start",
                        "channels": {"email": False, "webhook": False, "in_app": False},
                    }
                ]
            }
        }
        await db_session.commit()

        service = NotificationService(db_session)

        notif = await service.server_started(user_id=test_user.id, server_name="test-server")

        # Should NOT create notification
        assert notif is None
        mock_send_channels.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_email_enabled_sends_email(self, db_session, test_user, mock_send_channels):
        """When email is enabled for an event, should enqueue async channels."""
        # Set preferences: in_app=True, email=True
        test_user.preferences = {
            "notifications": {
                "events": [
                    {
                        "event": "server_start",
                        "channels": {"email": True, "webhook": False, "in_app": True},
                    }
                ]
            }
        }
        await db_session.commit()

        service = NotificationService(db_session)

        notif = await service.server_started(user_id=test_user.id, server_name="test-server")

        # Should create notification
        assert notif is not None

        # Should enqueue email/webhook task
        mock_send_channels.delay.assert_called_once()
        call_kwargs = mock_send_channels.delay.call_args.kwargs
        assert call_kwargs["user_id"] == str(test_user.id)
        assert call_kwargs["event_key"] == "server_start"
        assert "Server Started" in call_kwargs["title"]

    @pytest.mark.asyncio
    async def test_email_only_no_in_app(self, db_session, test_user, mock_send_channels):
        """When email=True but in_app=False, should enqueue task without creating notification."""
        # Set preferences: in_app=False, email=True
        test_user.preferences = {
            "notifications": {
                "events": [
                    {
                        "event": "server_start",
                        "channels": {"email": True, "webhook": False, "in_app": False},
                    }
                ]
            }
        }
        await db_session.commit()

        service = NotificationService(db_session)

        notif = await service.server_started(user_id=test_user.id, server_name="test-server")

        # Should NOT create notification
        assert notif is None

        # Should still enqueue async email task
        mock_send_channels.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_key_mapping(self, db_session, test_user):
        """Backend method names should map to correct frontend event keys."""
        from app.services.notification_service import EVENT_KEY_MAP

        # Verify key mappings exist for main events
        assert EVENT_KEY_MAP["server_started"] == "server_start"
        assert EVENT_KEY_MAP["server_stopped"] == "server_stop"
        assert EVENT_KEY_MAP["low_balance"] == "credit_low"
        assert EVENT_KEY_MAP["credits_granted"] == "credit_granted"
        assert EVENT_KEY_MAP["workspace_invitation"] == "workspace_invite"

    @pytest.mark.asyncio
    async def test_server_stopped_respects_stop_preferences(
        self, db_session, test_user, mock_send_channels
    ):
        """server_stopped should check server_stop event preferences."""
        test_user.preferences = {
            "notifications": {
                "events": [
                    {
                        "event": "server_stop",
                        "channels": {"email": False, "webhook": False, "in_app": False},
                    }
                ]
            }
        }
        await db_session.commit()

        service = NotificationService(db_session)

        notif = await service.server_stopped(
            user_id=test_user.id, server_name="test-server", reason="idle timeout"
        )

        assert notif is None
        mock_send_channels.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_credit_low_respects_preferences(self, db_session, test_user, mock_send_channels):
        """low_balance should check credit_low event preferences."""
        test_user.preferences = {
            "notifications": {
                "events": [
                    {
                        "event": "credit_low",
                        "channels": {"email": True, "webhook": False, "in_app": True},
                    }
                ]
            }
        }
        await db_session.commit()

        service = NotificationService(db_session)

        notif = await service.low_balance(user_id=test_user.id, balance=10)

        assert notif is not None
        assert "Low Credit Balance" in notif.title
        mock_send_channels.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_workspace_invitation_respects_preferences(
        self, db_session, test_user, mock_send_channels
    ):
        """workspace_invitation should check workspace_invite event preferences."""
        test_user.preferences = {
            "notifications": {
                "events": [
                    {
                        "event": "workspace_invite",
                        "channels": {"email": True, "webhook": False, "in_app": True},
                    }
                ]
            }
        }
        await db_session.commit()

        service = NotificationService(db_session)

        notif = await service.workspace_invitation(
            user_id=test_user.id, workspace_name="Test Workspace", inviter_name="admin"
        )

        assert notif is not None
        assert "Workspace Invitation" in notif.title
        mock_send_channels.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_unmapped_event_defaults_to_in_app_only(
        self, db_session, test_user, mock_send_channels
    ):
        """Events without explicit preferences should default to in_app=True, email=False."""
        service = NotificationService(db_session)

        notif = await service.create(
            user_id=test_user.id,
            title="Custom Event",
            message="Test message",
            type="system",
            event_key="nonexistent_event",
        )

        # Should create in-app notification (default)
        assert notif is not None
        # Should NOT enqueue async channels (default)
        mock_send_channels.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_event_key_defaults_to_in_app_only(
        self, db_session, test_user, mock_send_channels
    ):
        """create() without event_key should default to in_app only."""
        service = NotificationService(db_session)

        notif = await service.create(
            user_id=test_user.id,
            title="System Alert",
            message="Something happened",
            type="system",
        )

        assert notif is not None
        mock_send_channels.delay.assert_not_called()
