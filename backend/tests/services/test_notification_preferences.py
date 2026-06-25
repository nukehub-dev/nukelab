"""
Tests for NotificationService preference checking.

Ensures notifications respect user preferences for in_app and email channels.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.models.user import User
from app.models.notification import Notification
from app.services.notification_service import NotificationService


class TestNotificationPreferences:
    """Test that NotificationService respects user preferences."""

    @pytest.mark.asyncio
    async def test_default_behavior_creates_in_app_only(self, db_session, test_user):
        """With no preferences set, should create in-app notification but not email."""
        service = NotificationService(db_session)

        with patch.object(
            service, "_send_email_for_notification", new_callable=AsyncMock
        ) as mock_email:
            notif = await service.server_started(user_id=test_user.id, server_name="test-server")

        # Should create notification
        assert notif is not None
        assert notif.title == "Server Started"
        assert notif.type == "server"

        # Should NOT send email (default is email=False)
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_in_app_disabled_skips_notification(self, db_session, test_user):
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

        with patch.object(
            service, "_send_email_for_notification", new_callable=AsyncMock
        ) as mock_email:
            notif = await service.server_started(user_id=test_user.id, server_name="test-server")

        # Should NOT create notification
        assert notif is None
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_email_enabled_sends_email(self, db_session, test_user):
        """When email is enabled for an event, should send email."""
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

        with patch.object(
            service, "_send_email_for_notification", new_callable=AsyncMock
        ) as mock_email:
            notif = await service.server_started(user_id=test_user.id, server_name="test-server")

        # Should create notification
        assert notif is not None

        # Should send email
        mock_email.assert_awaited_once()
        call_args = mock_email.await_args
        assert call_args[0][0] == test_user.id  # user_id
        assert "Server Started" in call_args[0][1]  # title

    @pytest.mark.asyncio
    async def test_email_only_no_in_app(self, db_session, test_user):
        """When email=True but in_app=False, should send email without creating notification."""
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

        with patch.object(
            service, "_send_email_for_notification", new_callable=AsyncMock
        ) as mock_email:
            notif = await service.server_started(user_id=test_user.id, server_name="test-server")

        # Should NOT create notification
        assert notif is None

        # Should send email
        mock_email.assert_awaited_once()

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
    async def test_server_stopped_respects_stop_preferences(self, db_session, test_user):
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

        with patch.object(
            service, "_send_email_for_notification", new_callable=AsyncMock
        ) as mock_email:
            notif = await service.server_stopped(
                user_id=test_user.id, server_name="test-server", reason="idle timeout"
            )

        assert notif is None
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_credit_low_respects_preferences(self, db_session, test_user):
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

        with patch.object(
            service, "_send_email_for_notification", new_callable=AsyncMock
        ) as mock_email:
            notif = await service.low_balance(user_id=test_user.id, balance=10)

        assert notif is not None
        assert "Low Credit Balance" in notif.title
        mock_email.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_workspace_invitation_respects_preferences(self, db_session, test_user):
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

        with patch.object(
            service, "_send_email_for_notification", new_callable=AsyncMock
        ) as mock_email:
            notif = await service.workspace_invitation(
                user_id=test_user.id, workspace_name="Test Workspace", inviter_name="admin"
            )

        assert notif is not None
        assert "Workspace Invitation" in notif.title
        mock_email.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unmapped_event_defaults_to_in_app_only(self, db_session, test_user):
        """Events without explicit preferences should default to in_app=True, email=False."""
        service = NotificationService(db_session)

        with patch.object(
            service, "_send_email_for_notification", new_callable=AsyncMock
        ) as mock_email:
            notif = await service.create(
                user_id=test_user.id,
                title="Custom Event",
                message="Test message",
                type="system",
                event_key="nonexistent_event",
            )

        # Should create in-app notification (default)
        assert notif is not None
        # Should NOT send email (default)
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_event_key_defaults_to_in_app_only(self, db_session, test_user):
        """create() without event_key should default to in_app only."""
        service = NotificationService(db_session)

        with patch.object(
            service, "_send_email_for_notification", new_callable=AsyncMock
        ) as mock_email:
            notif = await service.create(
                user_id=test_user.id,
                title="System Alert",
                message="Something happened",
                type="system",
            )

        assert notif is not None
        mock_email.assert_not_awaited()
