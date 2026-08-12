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
    async def test_create_request_duplicate_pending_rejected(self, db_session, test_user):
        """A second pending request for the same user should be rejected."""
        service = CreditRequestService(db_session)
        await service.create_request(user_id=str(test_user.id), amount=100, reason="first")

        with pytest.raises(Exception) as exc_info:
            await service.create_request(user_id=str(test_user.id), amount=50, reason="second")
        assert exc_info.value.status_code == 400
        assert "pending credit request" in str(exc_info.value.detail)


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
