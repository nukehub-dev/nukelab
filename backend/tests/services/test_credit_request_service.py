# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for CreditRequestService business logic."""

import uuid as uuid_mod
from datetime import datetime, timedelta

import pytest

from app.core.time_utils import utc_now
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


class TestCreditRequestTypes:
    """request_type persistence and defaults."""

    @pytest.mark.asyncio
    async def test_request_type_defaults_to_top_up(self, db_session, test_user):
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="default type"
        )
        assert request.request_type == "top_up"
        assert request.to_dict()["request_type"] == "top_up"

    @pytest.mark.asyncio
    async def test_allowance_type_persisted(self, db_session, test_user):
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id),
            amount=500,
            reason="raise my allowance",
            request_type="allowance",
        )
        assert request.request_type == "allowance"

    @pytest.mark.asyncio
    async def test_unknown_type_rejected(self, db_session, test_user):
        service = CreditRequestService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.create_request(
                user_id=str(test_user.id), amount=10, reason="bad", request_type="bogus"
            )
        assert exc_info.value.status_code == 400


class TestAutoApprove:
    """Auto-approve of top_up requests at/below the threshold."""

    @pytest.mark.asyncio
    async def test_auto_approve_fires(self, db_session, test_user, admin_user):
        """At/below threshold: approved immediately, credits granted, no reviewer ping."""
        from unittest.mock import AsyncMock, patch

        from app.services.credit_service import CreditService
        from app.services.setting_service import SettingService

        await SettingService(db_session).set_auto_approve_max(100)
        service = CreditRequestService(db_session)
        initial = await CreditService(db_session).get_balance(str(test_user.id))

        with patch("app.services.credit_request_service.NotificationService") as mock_notif_cls:
            mock_notif = mock_notif_cls.return_value
            mock_notif.credit_request_created = AsyncMock()
            mock_notif.credits_granted = AsyncMock()

            request = await service.create_request(
                user_id=str(test_user.id), amount=50, reason="auto me"
            )

        assert request.status == "approved"
        assert request.reviewed_by is None
        assert request.reviewed_at is not None
        assert request.granted_amount == 50
        assert request.transaction_id is not None
        assert await CreditService(db_session).get_balance(str(test_user.id)) == initial + 50
        # Reviewers are NOT notified; the requester is.
        mock_notif.credit_request_created.assert_not_awaited()
        mock_notif.credits_granted.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_approve_disabled_at_zero(self, db_session, test_user):
        """Threshold 0 means off: request stays pending."""
        from app.services.setting_service import SettingService

        await SettingService(db_session).set_auto_approve_max(0)
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=1, reason="still pending"
        )
        assert request.status == "pending"

    @pytest.mark.asyncio
    async def test_above_threshold_stays_pending(self, db_session, test_user):
        """Above the threshold the request goes through normal review."""
        from app.services.setting_service import SettingService

        await SettingService(db_session).set_auto_approve_max(100)
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=101, reason="too big"
        )
        assert request.status == "pending"

    @pytest.mark.asyncio
    async def test_auto_approve_respects_max_balance_cap(self, db_session, test_user):
        """Auto-approved grants are still clamped by the max-balance cap."""
        from app.config import settings
        from app.services.setting_service import SettingService

        service = CreditRequestService(db_session)
        test_user.nuke_balance = 4800
        await db_session.commit()
        await SettingService(db_session).set_auto_approve_max(1000)

        original_max = settings.credits_max_balance
        settings.credits_max_balance = 5000
        try:
            request = await service.create_request(
                user_id=str(test_user.id), amount=500, reason="clamp me"
            )
        finally:
            settings.credits_max_balance = original_max

        assert request.status == "approved"
        assert request.granted_amount == 200  # 5000 - 4800

    @pytest.mark.asyncio
    async def test_allowance_requests_never_auto_approve(self, db_session, test_user):
        """Auto-approve only applies to top_up requests."""
        from app.services.setting_service import SettingService

        await SettingService(db_session).set_auto_approve_max(1000)
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id),
            amount=50,
            reason="allowance auto?",
            request_type="allowance",
        )
        assert request.status == "pending"


class TestAllowanceApproval:
    """Approving an allowance request sets daily_allowance, no ledger tx."""

    @pytest.mark.asyncio
    async def test_approve_allowance_updates_daily_allowance(
        self, db_session, test_user, admin_user
    ):
        from app.services.credit_service import CreditService

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id),
            amount=750,
            reason="allowance bump",
            request_type="allowance",
        )
        initial_balance = await CreditService(db_session).get_balance(str(test_user.id))

        approved = await service.approve(str(request.id), reviewer_id=str(admin_user.id))

        assert approved.status == "approved"
        assert approved.granted_amount == 750
        assert approved.transaction_id is None
        await db_session.refresh(test_user)
        assert test_user.daily_allowance == 750
        # No credits were granted
        assert await CreditService(db_session).get_balance(str(test_user.id)) == initial_balance

    @pytest.mark.asyncio
    async def test_approve_allowance_with_adjusted_amount(self, db_session, test_user, admin_user):
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id),
            amount=750,
            reason="adjust allowance",
            request_type="allowance",
        )

        approved = await service.approve(
            str(request.id), reviewer_id=str(admin_user.id), amount=400
        )

        assert approved.granted_amount == 400
        await db_session.refresh(test_user)
        assert test_user.daily_allowance == 400

    @pytest.mark.asyncio
    async def test_approve_allowance_notifies_user(self, db_session, test_user, admin_user):
        from unittest.mock import AsyncMock, patch

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id),
            amount=750,
            reason="notify allowance",
            request_type="allowance",
        )

        with patch("app.services.credit_request_service.NotificationService") as mock_notif_cls:
            mock_notif = mock_notif_cls.return_value
            mock_notif.credit_request_allowance_approved = AsyncMock()
            await service.approve(str(request.id), reviewer_id=str(admin_user.id))

        mock_notif.credit_request_allowance_approved.assert_awaited_once()
        kwargs = mock_notif.credit_request_allowance_approved.await_args.kwargs
        assert kwargs["user_id"] == str(test_user.id)
        assert kwargs["allowance"] == 750


class TestRequestCooldown:
    """Post-rejection cooldown window."""

    @pytest.mark.asyncio
    async def test_cooldown_blocks_within_window(self, db_session, test_user, admin_user):
        from app.services.setting_service import SettingService

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="reject me"
        )
        await service.reject(str(request.id), reviewer_id=str(admin_user.id))

        await SettingService(db_session).set_request_cooldown_hours(24)

        with pytest.raises(Exception) as exc_info:
            await service.create_request(user_id=str(test_user.id), amount=10, reason="too soon")
        assert exc_info.value.status_code == 400
        assert "hour" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_cooldown_allows_after_expiry(self, db_session, test_user, admin_user):
        from datetime import timedelta

        from app.core.time_utils import utc_now
        from app.services.setting_service import SettingService

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="old rejection"
        )
        rejected = await service.reject(str(request.id), reviewer_id=str(admin_user.id))

        # Push the rejection outside the cooldown window
        rejected.reviewed_at = utc_now() - timedelta(hours=25)
        await db_session.commit()
        await SettingService(db_session).set_request_cooldown_hours(24)

        second = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="cooled off"
        )
        assert second.status == "pending"

    @pytest.mark.asyncio
    async def test_cooldown_disabled_at_zero(self, db_session, test_user, admin_user):
        from app.services.setting_service import SettingService

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="reject me"
        )
        await service.reject(str(request.id), reviewer_id=str(admin_user.id))

        await SettingService(db_session).set_request_cooldown_hours(0)

        second = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="no cooldown"
        )
        assert second.status == "pending"


class TestStaleRequestReminders:
    """remind_stale_requests fan-out and throttling."""

    @pytest.mark.asyncio
    async def test_stale_open_request_reminds_reviewers(self, db_session, test_user, admin_user):
        """An open request older than the window re-notifies reviewers."""
        from datetime import timedelta

        from app.core.time_utils import utc_now

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="stale one"
        )
        request.created_at = utc_now() - timedelta(hours=30)
        await db_session.commit()

        reminded = await service.remind_stale_requests(hours=24)
        assert reminded == 1

        # Reviewer received a stale reminder notification
        from sqlalchemy import select

        from app.models.notification import Notification

        result = await db_session.execute(
            select(Notification).where(
                Notification.user_id == admin_user.id,
                Notification.title == "Stale Credit Request",
            )
        )
        notif = result.scalar_one()
        assert notif.severity == "warning"
        assert notif.extra_data["event_key"] == "credit_request_stale"
        assert notif.extra_data["request_id"] == str(request.id)

    @pytest.mark.asyncio
    async def test_stale_reminder_throttled_within_24h(self, db_session, test_user, admin_user):
        """A second run within 24h sends nothing for the same request."""
        from datetime import timedelta

        from app.core.time_utils import utc_now

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="throttle me"
        )
        request.created_at = utc_now() - timedelta(hours=30)
        await db_session.commit()

        assert await service.remind_stale_requests(hours=24) == 1
        # Second run: the reminder from the first run is still fresh
        assert await service.remind_stale_requests(hours=24) == 0

    @pytest.mark.asyncio
    async def test_terminal_requests_not_reminded(self, db_session, test_user, admin_user):
        """Approved/rejected requests are never reminded, however old."""
        from datetime import timedelta

        from app.core.time_utils import utc_now

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="decided"
        )
        await service.approve(str(request.id), reviewer_id=str(admin_user.id))
        request.created_at = utc_now() - timedelta(hours=72)
        await db_session.commit()

        assert await service.remind_stale_requests(hours=24) == 0

    @pytest.mark.asyncio
    async def test_fresh_requests_not_reminded(self, db_session, test_user):
        """Open requests younger than the window are not reminded."""
        service = CreditRequestService(db_session)
        await service.create_request(user_id=str(test_user.id), amount=10, reason="fresh")

        assert await service.remind_stale_requests(hours=24) == 0


class TestInternalNotes:
    """Internal reviewer notes."""

    @pytest.mark.asyncio
    async def test_internal_note_no_flip_no_notify(self, db_session, test_user, admin_user):
        """Internal notes leave status untouched and notify no one."""
        from unittest.mock import AsyncMock, patch

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="internal test"
        )
        assert request.status == "pending"

        with patch("app.services.credit_request_service.NotificationService") as mock_notif_cls:
            mock_notif = mock_notif_cls.return_value
            mock_notif.credit_request_message = AsyncMock()
            message = await service.add_message(
                str(request.id), author=admin_user, body="suspicious pattern", internal=True
            )

        assert message.is_internal is True
        assert request.status == "pending"  # no flip to needs_info
        mock_notif.credit_request_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internal_note_hidden_from_owner(self, db_session, test_user, admin_user):
        """The requester sees only public messages."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="hidden note"
        )
        await service.add_message(str(request.id), author=admin_user, body="public question")
        await service.add_message(
            str(request.id), author=admin_user, body="internal note", internal=True
        )

        owner_view = await service.list_messages(str(request.id), requesting_user=test_user)
        assert [m["body"] for m in owner_view] == ["public question"]

    @pytest.mark.asyncio
    async def test_internal_note_visible_to_reviewers(self, db_session, test_user, admin_user):
        """CREDITS_READ_ALL holders see internal notes."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="visible note"
        )
        await service.add_message(
            str(request.id), author=admin_user, body="internal note", internal=True
        )

        admin_view = await service.list_messages(str(request.id), requesting_user=admin_user)
        assert len(admin_view) == 1
        assert admin_view[0]["is_internal"] is True

    @pytest.mark.asyncio
    async def test_non_reviewer_cannot_post_internal(self, db_session, test_user):
        """The requester (no CREDITS_GRANT) gets 403 with internal=True."""
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="sneaky"
        )

        with pytest.raises(Exception) as exc_info:
            await service.add_message(
                str(request.id), author=test_user, body="fake internal", internal=True
            )
        assert exc_info.value.status_code == 403


class TestCreditRequestStats:
    """get_stats aggregation."""

    @pytest.mark.asyncio
    async def test_stats_on_seeded_mix(self, db_session, test_user, admin_user):
        from datetime import timedelta

        from app.core.time_utils import utc_now
        from app.models.credit_request import CreditRequest

        now = utc_now()
        rows = [
            # approved after 2h
            CreditRequest(
                user_id=test_user.id,
                amount=10,
                reason="a",
                status="approved",
                created_at=now - timedelta(hours=10),
                reviewed_at=now - timedelta(hours=8),
            ),
            # rejected after 4h
            CreditRequest(
                user_id=test_user.id,
                amount=10,
                reason="b",
                status="rejected",
                created_at=now - timedelta(hours=10),
                reviewed_at=now - timedelta(hours=6),
            ),
            # open pending, 10h old
            CreditRequest(
                user_id=test_user.id,
                amount=10,
                reason="c",
                status="pending",
                created_at=now - timedelta(hours=10),
            ),
            # cancelled (terminal, not decided)
            CreditRequest(
                user_id=test_user.id,
                amount=10,
                reason="d",
                status="cancelled",
                created_at=now - timedelta(hours=5),
                reviewed_at=now - timedelta(hours=4),
            ),
        ]
        db_session.add_all(rows)
        await db_session.commit()

        service = CreditRequestService(db_session)
        stats = await service.get_stats()

        assert stats["counts"]["pending"] == 1
        assert stats["counts"]["approved"] == 1
        assert stats["counts"]["rejected"] == 1
        assert stats["counts"]["cancelled"] == 1
        assert stats["counts"]["needs_info"] == 0
        assert stats["decided"] == 2
        assert stats["approval_rate"] == 0.5
        assert stats["avg_decision_hours"] == 3.0
        assert stats["oldest_open_hours"] == pytest.approx(10.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_stats_empty(self, db_session):
        """No requests: zero counts, 0 approval rate, null latencies."""
        service = CreditRequestService(db_session)
        stats = await service.get_stats()

        assert stats["decided"] == 0
        assert stats["approval_rate"] == 0
        assert stats["avg_decision_hours"] is None
        assert stats["oldest_open_hours"] is None


class TestBulkReview:
    """bulk_review result capture."""

    @pytest.mark.asyncio
    async def test_bulk_approve_all_success(self, db_session, test_user, admin_user):
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=25, reason="bulk me"
        )

        results = await service.bulk_review(
            [str(request.id)], action="approve", reviewer_id=str(admin_user.id)
        )

        assert results["success"] == [{"request_id": str(request.id)}]
        assert results["failed"] == []

    @pytest.mark.asyncio
    async def test_bulk_review_partial_failure(self, db_session, test_user, admin_user):
        """A terminal request in the batch fails without blocking the rest."""
        service = CreditRequestService(db_session)
        open_request = await service.create_request(
            user_id=str(test_user.id), amount=25, reason="open one"
        )
        await service.reject(str(open_request.id), reviewer_id=str(admin_user.id))
        terminal_id = str(open_request.id)

        second = await service.create_request(
            user_id=str(test_user.id), amount=25, reason="second one"
        )

        results = await service.bulk_review(
            [str(second.id), terminal_id], action="approve", reviewer_id=str(admin_user.id)
        )

        assert results["success"] == [{"request_id": str(second.id)}]
        assert len(results["failed"]) == 1
        assert results["failed"][0]["request_id"] == terminal_id
        assert "already" in results["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_bulk_reject(self, db_session, test_user, admin_user):
        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=25, reason="bulk reject"
        )

        results = await service.bulk_review(
            [str(request.id)], action="reject", reviewer_id=str(admin_user.id), note="no"
        )

        assert results["success"] == [{"request_id": str(request.id)}]
        await db_session.refresh(request)
        assert request.status == "rejected"
        assert request.review_note == "no"


class TestCreditRequestBlock:
    """Per-user credit request block."""

    @pytest.mark.asyncio
    async def test_blocked_user_create_forbidden(self, db_session, test_user, admin_user):
        """A blocked user gets 403 with the documented detail."""
        service = CreditRequestService(db_session)
        await service.set_request_block(
            str(test_user.id), blocked=True, actor_id=str(admin_user.id), reason="abuse"
        )

        with pytest.raises(Exception) as exc_info:
            await service.create_request(user_id=str(test_user.id), amount=10, reason="please")
        assert exc_info.value.status_code == 403
        assert "disabled for your account" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_unblock_re_allows_creation(self, db_session, test_user, admin_user):
        """Unblocking restores the ability to create requests and clears both columns."""
        service = CreditRequestService(db_session)
        await service.set_request_block(
            str(test_user.id),
            blocked=True,
            actor_id=str(admin_user.id),
            until=utc_now() + timedelta(hours=6),
        )
        user = await service.set_request_block(
            str(test_user.id), blocked=False, actor_id=str(admin_user.id)
        )

        assert user.credit_requests_blocked is False
        assert user.credit_requests_blocked_until is None
        assert user.has_active_credit_request_block is False

        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="back in"
        )
        assert request.status == "pending"

    @pytest.mark.asyncio
    async def test_timeboxed_block_forbids_creation(self, db_session, test_user, admin_user):
        """A block with a future expiry behaves like an indefinite block."""
        service = CreditRequestService(db_session)
        until = utc_now() + timedelta(hours=12)
        user = await service.set_request_block(
            str(test_user.id), blocked=True, actor_id=str(admin_user.id), until=until
        )

        assert user.credit_requests_blocked_until == until
        assert user.has_active_credit_request_block is True

        with pytest.raises(Exception) as exc_info:
            await service.create_request(user_id=str(test_user.id), amount=10, reason="please")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_expired_block_allows_creation(self, db_session, test_user):
        """A block whose expiry has passed expires implicitly."""
        test_user.credit_requests_blocked = True
        test_user.credit_requests_blocked_until = utc_now() - timedelta(hours=1)
        await db_session.commit()

        assert test_user.has_active_credit_request_block is False

        service = CreditRequestService(db_session)
        request = await service.create_request(
            user_id=str(test_user.id), amount=10, reason="expired block"
        )
        assert request.status == "pending"

    @pytest.mark.asyncio
    async def test_past_until_rejected(self, db_session, test_user, admin_user):
        """Setting a block with a past expiry returns 400."""
        service = CreditRequestService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.set_request_block(
                str(test_user.id),
                blocked=True,
                actor_id=str(admin_user.id),
                until=utc_now() - timedelta(hours=1),
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_tz_aware_until_converted_to_naive_utc(self, db_session, test_user, admin_user):
        """A tz-aware expiry is normalized to naive UTC."""
        from datetime import UTC

        service = CreditRequestService(db_session)
        aware = datetime.now(UTC) + timedelta(hours=3)
        user = await service.set_request_block(
            str(test_user.id), blocked=True, actor_id=str(admin_user.id), until=aware
        )

        assert user.credit_requests_blocked_until is not None
        assert user.credit_requests_blocked_until.tzinfo is None
        assert user.credit_requests_blocked_until == aware.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_block_and_unblock_log_and_notify(self, db_session, test_user, admin_user):
        """Both directions write an activity log and notify the user."""
        from unittest.mock import AsyncMock, patch

        from sqlalchemy import select

        from app.models.activity_log import ActivityLog

        service = CreditRequestService(db_session)
        with patch("app.services.credit_request_service.NotificationService") as mock_notif_cls:
            mock_notif = mock_notif_cls.return_value
            mock_notif.credit_request_block_changed = AsyncMock()

            await service.set_request_block(
                str(test_user.id), blocked=True, actor_id=str(admin_user.id), reason="spam"
            )
            await service.set_request_block(
                str(test_user.id), blocked=False, actor_id=str(admin_user.id), reason="appeal"
            )

        calls = mock_notif.credit_request_block_changed.await_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["blocked"] is True
        assert calls[0].kwargs["reason"] == "spam"
        assert calls[1].kwargs["blocked"] is False

        result = await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.target_id == test_user.id,
                ActivityLog.action.in_(["credit_requests.block", "credit_requests.unblock"]),
            )
        )
        actions = [log.action for log in result.scalars().all()]
        assert "credit_requests.block" in actions
        assert "credit_requests.unblock" in actions

    @pytest.mark.asyncio
    async def test_block_flag_visible_in_user_dict(self, db_session, test_user, admin_user):
        """The flag flips on the User row and is exposed via to_dict()."""
        service = CreditRequestService(db_session)
        assert test_user.to_dict()["credit_requests_blocked"] is False

        user = await service.set_request_block(
            str(test_user.id), blocked=True, actor_id=str(admin_user.id)
        )
        assert user.credit_requests_blocked is True
        assert user.to_dict()["credit_requests_blocked"] is True

    @pytest.mark.asyncio
    async def test_block_unknown_user_404(self, db_session, admin_user):
        """Blocking an unknown user returns 404."""
        service = CreditRequestService(db_session)
        with pytest.raises(Exception) as exc_info:
            await service.set_request_block(
                str(uuid_mod.uuid4()), blocked=True, actor_id=str(admin_user.id)
            )
        assert exc_info.value.status_code == 404
