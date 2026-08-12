# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for CreditRequestService business logic."""

import uuid as uuid_mod

import pytest

from app.services.credit_request_service import CreditRequestService
from app.services.credit_service import CreditService


class TestCreditRequestCreate:
    """Tests for create_request."""

    @pytest.mark.asyncio
    async def test_create_request(self, db_session, test_user):
        """create_request should persist a pending request."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=100, reason="Need more credits"
        )

        assert request.status == "pending"
        assert request.amount == 100
        assert request.reason == "Need more credits"
        assert request.granted_amount is None
        assert request.transaction_id is None

        data = request.to_dict()
        assert data["user_id"] == str(test_user.id)
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_create_request_rejects_non_positive_amount(self, db_session, test_user):
        """create_request should reject amount <= 0."""
        service = CreditRequestService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.create_request(user_id=str(test_user.id), amount=0, reason="x")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_request_rejects_empty_reason(self, db_session, test_user):
        """create_request should reject a blank reason."""
        service = CreditRequestService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.create_request(user_id=str(test_user.id), amount=10, reason="   ")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_request_duplicate_open_rejected(self, db_session, test_user):
        """A second open request for the same user should be rejected."""
        service = CreditRequestService(db_session)
        await service.create_request(user_id=str(test_user.id), amount=100, reason="first")

        with pytest.raises(Exception) as exc_info:
            await service.create_request(user_id=str(test_user.id), amount=50, reason="second")
        assert exc_info.value.status_code == 400
        assert "open credit request" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_create_request_blocked_while_needs_info(self, db_session, test_user, admin_user):
        """The one-open-request rule also covers the needs_info state."""
        service = CreditRequestService(db_session)
        request = await service.create_request(user_id=str(test_user.id), amount=10, reason="q")
        # Reviewer message flips the request to needs_info
        await service.add_message(str(request.id), author=admin_user, body="Which project?")
        assert request.status == "needs_info"

        with pytest.raises(Exception) as exc_info:
            await service.create_request(user_id=str(test_user.id), amount=10, reason="again")
        assert exc_info.value.status_code == 400


class TestCreditRequestApprove:
    """Tests for approve."""

    @pytest.mark.asyncio
    async def test_approve_grants_credits(self, db_session, test_user, admin_user):
        """approve should grant the requested amount and stamp the request."""
        service = CreditRequestService(db_session)
        credit_service = CreditService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=100, reason="Bonus please"
        )
        initial = await credit_service.get_balance(str(test_user.id))

        approved = await service.approve(str(request.id), reviewer_id=str(admin_user.id))

        assert approved.status == "approved"
        assert approved.reviewed_by == admin_user.id
        assert approved.reviewed_at is not None
        assert approved.granted_amount == 100
        assert approved.transaction_id is not None
        assert await credit_service.get_balance(str(test_user.id)) == initial + 100

    @pytest.mark.asyncio
    async def test_approve_transaction_meta_marks_credit_request(
        self, db_session, test_user, admin_user
    ):
        """The grant transaction should record source=credit_request and request_id."""
        from sqlalchemy import select

        from app.models.credit_transaction import CreditTransaction

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=25, reason="meta check"
        )
        approved = await service.approve(str(request.id), reviewer_id=str(admin_user.id))

        result = await db_session.execute(
            select(CreditTransaction).where(CreditTransaction.id == approved.transaction_id)
        )
        tx = result.scalar_one()
        assert tx.meta["source"] == "credit_request"
        assert tx.meta["request_id"] == str(request.id)

    @pytest.mark.asyncio
    async def test_approve_with_adjusted_amount(self, db_session, test_user, admin_user):
        """approve should honor an admin-adjusted amount."""
        service = CreditRequestService(db_session)
        credit_service = CreditService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=100, reason="adjust me"
        )
        initial = await credit_service.get_balance(str(test_user.id))

        approved = await service.approve(
            str(request.id), reviewer_id=str(admin_user.id), amount=40, note="partial"
        )

        assert approved.granted_amount == 40
        assert approved.review_note == "partial"
        assert await credit_service.get_balance(str(test_user.id)) == initial + 40

    @pytest.mark.asyncio
    async def test_approve_respects_max_balance_cap(self, db_session, test_user, admin_user):
        """Granted amount should be clamped by the max-balance cap."""
        from app.config import settings

        service = CreditRequestService(db_session)
        test_user.nuke_balance = 4800
        await db_session.commit()

        request = await service.create_request(
            user_id=str(test_user.id), amount=500, reason="cap me"
        )

        original_max = settings.credits_max_balance
        settings.credits_max_balance = 5000
        try:
            approved = await service.approve(str(request.id), reviewer_id=str(admin_user.id))
        finally:
            settings.credits_max_balance = original_max

        assert approved.status == "approved"
        assert approved.granted_amount == 200  # 5000 - 4800
        assert approved.granted_amount < request.amount

    @pytest.mark.asyncio
    async def test_double_approve_rejected(self, db_session, test_user, admin_user):
        """Approving an already-approved request should 400."""
        service = CreditRequestService(db_session)
        request = await service.create_request(user_id=str(test_user.id), amount=10, reason="once")
        await service.approve(str(request.id), reviewer_id=str(admin_user.id))

        with pytest.raises(Exception) as exc_info:
            await service.approve(str(request.id), reviewer_id=str(admin_user.id))
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_approve_nonexistent_returns_404(self, db_session, admin_user):
        """Approving an unknown request should 404."""
        service = CreditRequestService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.approve(str(uuid_mod.uuid4()), reviewer_id=str(admin_user.id))
        assert exc_info.value.status_code == 404


class TestCreditRequestReject:
    """Tests for reject."""

    @pytest.mark.asyncio
    async def test_reject(self, db_session, test_user, admin_user):
        """reject should stamp the request without granting credits."""
        service = CreditRequestService(db_session)
        credit_service = CreditService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=100, reason="no thanks"
        )
        initial = await credit_service.get_balance(str(test_user.id))

        rejected = await service.reject(
            str(request.id), reviewer_id=str(admin_user.id), note="Not justified"
        )

        assert rejected.status == "rejected"
        assert rejected.reviewed_by == admin_user.id
        assert rejected.reviewed_at is not None
        assert rejected.review_note == "Not justified"
        assert rejected.granted_amount is None
        assert rejected.transaction_id is None
        assert await credit_service.get_balance(str(test_user.id)) == initial

    @pytest.mark.asyncio
    async def test_double_reject_rejected(self, db_session, test_user, admin_user):
        """Rejecting an already-rejected request should 400."""
        service = CreditRequestService(db_session)
        request = await service.create_request(user_id=str(test_user.id), amount=10, reason="twice")
        await service.reject(str(request.id), reviewer_id=str(admin_user.id))

        with pytest.raises(Exception) as exc_info:
            await service.reject(str(request.id), reviewer_id=str(admin_user.id))
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_reject_nonexistent_returns_404(self, db_session, admin_user):
        """Rejecting an unknown request should 404."""
        service = CreditRequestService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.reject(str(uuid_mod.uuid4()), reviewer_id=str(admin_user.id))
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_new_request_allowed_after_reject(self, db_session, test_user, admin_user):
        """A new request should be allowed once the previous one is resolved."""
        service = CreditRequestService(db_session)
        request = await service.create_request(user_id=str(test_user.id), amount=10, reason="first")
        await service.reject(str(request.id), reviewer_id=str(admin_user.id))

        second = await service.create_request(user_id=str(test_user.id), amount=20, reason="second")
        assert second.status == "pending"


class TestCreditRequestListing:
    """Tests for list_own, list_all, and pending_count."""

    @pytest.mark.asyncio
    async def test_list_own_pagination(self, db_session, test_user, admin_user):
        """list_own should paginate and only return the user's requests."""
        service = CreditRequestService(db_session)
        for i in range(3):
            request = await service.create_request(
                user_id=str(test_user.id), amount=10 + i, reason=f"r{i}"
            )
            # Resolve each one so the next pending request is allowed
            await service.reject(str(request.id), reviewer_id=str(admin_user.id))

        result = await service.list_own(str(test_user.id), page=1, limit=2)
        assert len(result["requests"]) == 2
        assert result["pagination"]["total"] == 3
        assert result["pagination"]["total_pages"] == 2

        result = await service.list_own(str(test_user.id), page=2, limit=2)
        assert len(result["requests"]) == 1

    @pytest.mark.asyncio
    async def test_list_own_status_filter(self, db_session, test_user, admin_user):
        """list_own should filter by status."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="filter"
        )
        await service.reject(str(request.id), reviewer_id=str(admin_user.id))
        await service.create_request(user_id=str(test_user.id), amount=20, reason="pending one")

        pending = await service.list_own(str(test_user.id), status="pending")
        assert pending["pagination"]["total"] == 1
        assert pending["requests"][0]["status"] == "pending"

        rejected = await service.list_own(str(test_user.id), status="rejected")
        assert rejected["pagination"]["total"] == 1

    @pytest.mark.asyncio
    async def test_list_all_includes_user_fields(self, db_session, test_user, admin_user):
        """list_all should include username and email per request."""
        service = CreditRequestService(db_session)
        await service.create_request(user_id=str(test_user.id), amount=10, reason="admin view")

        result = await service.list_all(status="pending")
        matching = [r for r in result["requests"] if r["user_id"] == str(test_user.id)]
        assert len(matching) == 1
        assert matching[0]["username"] == test_user.username
        assert matching[0]["email"] == test_user.email

    @pytest.mark.asyncio
    async def test_pending_count(self, db_session, test_user, admin_user):
        """pending_count should track created/resolved requests."""
        service = CreditRequestService(db_session)
        before = await service.pending_count()

        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="count me"
        )
        assert await service.pending_count() == before + 1

        await service.approve(str(request.id), reviewer_id=str(admin_user.id))
        assert await service.pending_count() == before


class TestCreditRequestMessages:
    """Tests for the conversation loop (add_message / list_messages)."""

    @pytest.mark.asyncio
    async def test_reviewer_message_flips_to_needs_info(self, db_session, test_user, admin_user):
        """A reviewer posting flips an open request to needs_info."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="question"
        )

        message = await service.add_message(
            str(request.id), author=admin_user, body="Which project?"
        )

        assert message.body == "Which project?"
        assert message.author_id == admin_user.id
        assert request.status == "needs_info"

    @pytest.mark.asyncio
    async def test_requester_message_flips_back_to_pending(self, db_session, test_user, admin_user):
        """The requester posting flips needs_info back to pending."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="question"
        )
        await service.add_message(str(request.id), author=admin_user, body="Which project?")
        assert request.status == "needs_info"

        await service.add_message(str(request.id), author=test_user, body="Project X")
        assert request.status == "pending"

    @pytest.mark.asyncio
    async def test_post_on_terminal_request_rejected(self, db_session, test_user, admin_user):
        """Posting on a terminal request should 400."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="terminal"
        )
        await service.reject(str(request.id), reviewer_id=str(admin_user.id))

        with pytest.raises(Exception) as exc_info:
            await service.add_message(str(request.id), author=test_user, body="too late")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_non_owner_without_grant_cannot_post(self, db_session, test_user, admin_user):
        """A third-party regular user should get 403 posting on the request."""
        from app.models.user import User

        other = User(
            username="otheruser",
            email="other@example.com",
            password_hash="hash",
            role="user",
            is_active=True,
        )
        db_session.add(other)
        await db_session.commit()

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="not yours"
        )

        with pytest.raises(Exception) as exc_info:
            await service.add_message(str(request.id), author=other, body="intruding")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_message_rejected(self, db_session, test_user):
        """A blank message body should 400."""
        service = CreditRequestService(db_session)
        request = await service.create_request(user_id=str(test_user.id), amount=50, reason="blank")

        with pytest.raises(Exception) as exc_info:
            await service.add_message(str(request.id), author=test_user, body="   ")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_list_messages_ordering_and_flags(self, db_session, test_user, admin_user):
        """list_messages should be ascending with author flags set."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="thread"
        )
        await service.add_message(str(request.id), author=admin_user, body="first")
        await service.add_message(str(request.id), author=test_user, body="second")

        messages = await service.list_messages(str(request.id), requesting_user=test_user)
        assert [m["body"] for m in messages] == ["first", "second"]
        assert messages[0]["is_admin"] is True
        assert messages[0]["author_username"] == admin_user.username
        assert messages[1]["is_admin"] is False
        assert messages[1]["author_username"] == test_user.username

    @pytest.mark.asyncio
    async def test_list_messages_forbidden_for_third_party(self, db_session, test_user, admin_user):
        """A non-owner without CREDITS_READ_ALL should get 403 viewing the thread."""
        from app.models.user import User

        other = User(
            username="otheruser",
            email="other@example.com",
            password_hash="hash",
            role="user",
            is_active=True,
        )
        db_session.add(other)
        await db_session.commit()

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="private"
        )

        with pytest.raises(Exception) as exc_info:
            await service.list_messages(str(request.id), requesting_user=other)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_messages_unknown_request_404(self, db_session, test_user):
        """Viewing messages on an unknown request should 404."""
        service = CreditRequestService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.list_messages(str(uuid_mod.uuid4()), requesting_user=test_user)
        assert exc_info.value.status_code == 404


class TestCreditRequestCancel:
    """Tests for cancel."""

    @pytest.mark.asyncio
    async def test_cancel_open_request(self, db_session, test_user):
        """The requester can cancel an open request."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="never mind"
        )

        cancelled = await service.cancel(str(request.id), user_id=str(test_user.id))
        assert cancelled.status == "cancelled"
        assert cancelled.reviewed_at is not None
        assert cancelled.granted_amount is None

    @pytest.mark.asyncio
    async def test_cancel_needs_info_request(self, db_session, test_user, admin_user):
        """Cancellation is allowed from needs_info too."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="cancel me"
        )
        await service.add_message(str(request.id), author=admin_user, body="details?")
        assert request.status == "needs_info"

        cancelled = await service.cancel(str(request.id), user_id=str(test_user.id))
        assert cancelled.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_terminal_request_rejected(self, db_session, test_user, admin_user):
        """Cancelling a terminal request should 400."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="already done"
        )
        await service.approve(str(request.id), reviewer_id=str(admin_user.id))

        with pytest.raises(Exception) as exc_info:
            await service.cancel(str(request.id), user_id=str(test_user.id))
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_cancel_by_non_owner_forbidden(self, db_session, test_user, admin_user):
        """Only the requester may cancel; others get 403."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=50, reason="hands off"
        )

        with pytest.raises(Exception) as exc_info:
            await service.cancel(str(request.id), user_id=str(admin_user.id))
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_new_request_allowed_after_cancel(self, db_session, test_user):
        """A new request should be allowed once the previous one is cancelled."""
        service = CreditRequestService(db_session)
        request = await service.create_request(user_id=str(test_user.id), amount=10, reason="first")
        await service.cancel(str(request.id), user_id=str(test_user.id))

        second = await service.create_request(user_id=str(test_user.id), amount=20, reason="second")
        assert second.status == "pending"


class TestNeedsInfoReview:
    """Approve/reject must work from needs_info as well as pending."""

    @pytest.mark.asyncio
    async def test_approve_from_needs_info(self, db_session, test_user, admin_user):
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=30, reason="approve later"
        )
        await service.add_message(str(request.id), author=admin_user, body="ok?")
        assert request.status == "needs_info"

        approved = await service.approve(str(request.id), reviewer_id=str(admin_user.id))
        assert approved.status == "approved"
        assert approved.granted_amount == 30

    @pytest.mark.asyncio
    async def test_reject_from_needs_info(self, db_session, test_user, admin_user):
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=30, reason="reject later"
        )
        await service.add_message(str(request.id), author=admin_user, body="hmm")
        assert request.status == "needs_info"

        rejected = await service.reject(str(request.id), reviewer_id=str(admin_user.id))
        assert rejected.status == "rejected"


class TestOpenStatusFilter:
    """The special status='open' filter covers pending + needs_info."""

    @pytest.mark.asyncio
    async def test_list_own_open_filter(self, db_session, test_user, admin_user):
        service = CreditRequestService(db_session)
        request = await service.create_request(user_id=str(test_user.id), amount=10, reason="one")
        await service.add_message(str(request.id), author=admin_user, body="info?")
        assert request.status == "needs_info"

        result = await service.list_own(str(test_user.id), status="open")
        assert result["pagination"]["total"] == 1
        assert result["requests"][0]["status"] == "needs_info"

    @pytest.mark.asyncio
    async def test_list_all_open_filter(self, db_session, test_user, admin_user):
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="admin open filter"
        )

        result = await service.list_all(status="open")
        matching = [r for r in result["requests"] if r["id"] == str(request.id)]
        assert len(matching) == 1

        await service.reject(str(request.id), reviewer_id=str(admin_user.id))
        result = await service.list_all(status="open")
        matching = [r for r in result["requests"] if r["id"] == str(request.id)]
        assert matching == []


class TestReviewerNotifications:
    """Reviewer notification fan-out rules."""

    @pytest.mark.asyncio
    async def test_create_notifies_reviewers_except_actor(self, db_session, test_user, admin_user):
        """Creating a request notifies all CREDITS_GRANT holders."""
        from unittest.mock import AsyncMock, patch

        service = CreditRequestService(db_session)
        with patch("app.services.credit_request_service.NotificationService") as mock_notif_cls:
            mock_notif = mock_notif_cls.return_value
            mock_notif.credit_request_created = AsyncMock()
            await service.create_request(user_id=str(test_user.id), amount=10, reason="notify")

        # admin_user (role=admin, CREDITS_GRANT) should be notified
        notified = {c.kwargs["user_id"] for c in mock_notif.credit_request_created.await_args_list}
        assert admin_user.id in notified
        assert test_user.id not in notified

    @pytest.mark.asyncio
    async def test_user_message_notifies_reviewers_not_self(
        self, db_session, test_user, admin_user
    ):
        """A requester message fans out to reviewers, never to the author."""
        from unittest.mock import AsyncMock, patch

        service = CreditRequestService(db_session)
        with patch("app.services.credit_request_service.NotificationService") as mock_notif_cls:
            mock_notif = mock_notif_cls.return_value
            mock_notif.credit_request_created = AsyncMock()
            mock_notif.credit_request_message = AsyncMock()

            request = await service.create_request(
                user_id=str(test_user.id), amount=10, reason="fan-out"
            )
            await service.add_message(str(request.id), author=test_user, body="ping")

        notified = {c.kwargs["user_id"] for c in mock_notif.credit_request_message.await_args_list}
        assert admin_user.id in notified
        assert test_user.id not in notified

    @pytest.mark.asyncio
    async def test_admin_message_notifies_requester_only(self, db_session, test_user, admin_user):
        """A reviewer message notifies the requester, not the reviewer."""
        from unittest.mock import AsyncMock, patch

        service = CreditRequestService(db_session)
        with patch("app.services.credit_request_service.NotificationService") as mock_notif_cls:
            mock_notif = mock_notif_cls.return_value
            mock_notif.credit_request_created = AsyncMock()
            mock_notif.credit_request_message = AsyncMock()

            request = await service.create_request(
                user_id=str(test_user.id), amount=10, reason="admin msg"
            )
            await service.add_message(str(request.id), author=admin_user, body="more info?")

        notified = {c.kwargs["user_id"] for c in mock_notif.credit_request_message.await_args_list}
        assert notified == {test_user.id}
