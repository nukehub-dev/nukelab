# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Web Push delivery in NotificationService."""

from unittest import mock

import pytest

from app.models.push_subscription import PushSubscription
from app.services.notification_service import NotificationService


class TestSendPushForNotification:
    @pytest.mark.asyncio
    async def test_noop_when_vapid_unconfigured(self, db_session, test_user):
        service = NotificationService(db_session)
        sub = PushSubscription(
            user_id=test_user.id,
            endpoint="https://push.example.com/sub",
            keys={"p256dh": "p256dh", "auth": "auth"},
        )
        db_session.add(sub)
        await db_session.commit()

        with mock.patch("app.services.notification_service.settings.vapid_private_key", ""):
            # Should not raise and should not call pywebpush.
            with mock.patch("app.services.notification_service.webpush") as mock_webpush:
                await service._send_push_for_notification(
                    test_user.id, "Title", "Body", action_url="/servers/1"
                )
                mock_webpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_payload_excludes_full_message(self, db_session, test_user, monkeypatch):
        monkeypatch.setattr(
            "app.services.notification_service.settings.vapid_private_key", "private-key"
        )
        monkeypatch.setattr(
            "app.services.notification_service.settings.vapid_public_key", "public-key"
        )
        monkeypatch.setattr(
            "app.services.notification_service.settings.vapid_subject", "mailto:test@example.com"
        )

        service = NotificationService(db_session)
        sub = PushSubscription(
            user_id=test_user.id,
            endpoint="https://push.example.com/sub",
            keys={"p256dh": "p256dh", "auth": "auth"},
        )
        db_session.add(sub)
        await db_session.commit()

        with mock.patch("app.services.notification_service.webpush") as mock_webpush:
            await service._send_push_for_notification(
                test_user.id,
                "Title",
                "This notification body is intentionally long and contains a great deal of extra wording so that the push service receives only a short preview and the full message text should not appear in the final payload",
                action_url="/servers/1",
            )

            mock_webpush.assert_called_once()
            call_data = mock_webpush.call_args.kwargs.get("data", "{}")
            import json

            payload = json.loads(call_data)
            assert payload["title"] == "Title"
            assert payload["action_url"] == "/servers/1"
            assert "full message text should not appear" not in payload["body"]

    @pytest.mark.asyncio
    async def test_dead_subscription_removed_on_410(self, db_session, test_user, monkeypatch):
        monkeypatch.setattr(
            "app.services.notification_service.settings.vapid_private_key", "private-key"
        )
        monkeypatch.setattr(
            "app.services.notification_service.settings.vapid_public_key", "public-key"
        )
        monkeypatch.setattr(
            "app.services.notification_service.settings.vapid_subject", "mailto:test@example.com"
        )

        service = NotificationService(db_session)
        sub = PushSubscription(
            user_id=test_user.id,
            endpoint="https://push.example.com/sub",
            keys={"p256dh": "p256dh", "auth": "auth"},
        )
        db_session.add(sub)
        await db_session.commit()

        from app.services import notification_service

        response = mock.Mock()
        response.status_code = 410
        exc = notification_service.WebPushException("gone")
        exc.response = response

        with mock.patch.object(notification_service, "webpush", side_effect=exc):
            await service._send_push_for_notification(test_user.id, "Title", "Body")

        from sqlalchemy import select

        result = await db_session.execute(
            select(PushSubscription).where(PushSubscription.id == sub.id)
        )
        assert result.scalar_one_or_none() is None
