# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests that credit-request notifications carry the correct action_url."""

import pytest

from app.models.credit_request import CreditRequest
from app.services.credit_request_service import CreditRequestService


class TestCreditRequestNotificationActionUrls:
    @pytest.mark.asyncio
    async def test_approve_top_up_notifies_requester_with_settings_url(
        self, db_session, test_user, admin_user, admin_token
    ):
        request = CreditRequest(user_id=test_user.id, amount=100, reason="test", status="pending")
        db_session.add(request)
        await db_session.commit()

        service = CreditRequestService(db_session)
        await service.approve(str(request.id), str(admin_user.id))

        from sqlalchemy import select

        from app.models.notification import Notification

        result = await db_session.execute(
            select(Notification)
            .where(Notification.user_id == test_user.id)
            .order_by(Notification.created_at.desc())
        )
        notif = result.scalar_one()
        assert notif.action_url == f"/settings/credits?request={request.id}"

    @pytest.mark.asyncio
    async def test_reject_notifies_requester_with_settings_url(
        self, db_session, test_user, admin_user
    ):
        request = CreditRequest(user_id=test_user.id, amount=100, reason="test", status="pending")
        db_session.add(request)
        await db_session.commit()

        service = CreditRequestService(db_session)
        await service.reject(str(request.id), str(admin_user.id), note="no")

        from sqlalchemy import select

        from app.models.notification import Notification

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == test_user.id)
        )
        notif = result.scalar_one()
        assert notif.action_url == f"/settings/credits?request={request.id}"

    @pytest.mark.asyncio
    async def test_new_request_notifies_reviewer_with_admin_url(
        self, db_session, test_user, admin_user
    ):
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=100, reason="please"
        )

        from sqlalchemy import select

        from app.models.notification import Notification

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == admin_user.id)
        )
        notif = result.scalar_one()
        assert notif.action_url == f"/admin/credits?request={request.id}"

    @pytest.mark.asyncio
    async def test_requester_message_notifies_reviewer_with_admin_url(
        self, db_session, test_user, admin_user
    ):
        request = CreditRequest(user_id=test_user.id, amount=100, reason="test", status="pending")
        db_session.add(request)
        await db_session.commit()

        service = CreditRequestService(db_session)
        await service.add_message(str(request.id), test_user, "more info")

        from sqlalchemy import select

        from app.models.notification import Notification

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == admin_user.id)
        )
        notif = result.scalar_one()
        assert notif.action_url == f"/admin/credits?request={request.id}"

    @pytest.mark.asyncio
    async def test_reviewer_message_notifies_requester_with_settings_url(
        self, db_session, test_user, admin_user
    ):
        request = CreditRequest(user_id=test_user.id, amount=100, reason="test", status="pending")
        db_session.add(request)
        await db_session.commit()

        service = CreditRequestService(db_session)
        await service.add_message(str(request.id), admin_user, "please clarify")

        from sqlalchemy import select

        from app.models.notification import Notification

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == test_user.id)
        )
        notif = result.scalar_one()
        assert notif.action_url == f"/settings/credits?request={request.id}"
