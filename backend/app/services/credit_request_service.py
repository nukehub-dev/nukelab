# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Credit request service: users request credits, admins approve or reject.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.credit_request import CreditRequest
from app.models.user import User
from app.services.activity_service import ActivityService
from app.services.credit_service import CreditService
from app.services.notification_service import NotificationService

logger = get_logger(__name__)

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

_DUPLICATE_PENDING_DETAIL = "You already have a pending credit request"


class CreditRequestService:
    """Credit request business logic"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_request(self, user_id: str, amount: int, reason: str) -> CreditRequest:
        """Create a credit request for a user.

        Idempotent per user: at most one pending request at a time. The cheap
        pre-check below is backed by the partial unique index
        uq_credit_requests_pending_per_user; if a concurrent insert wins the
        race, the resulting IntegrityError maps to the same 400 response.
        """
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount must be positive",
            )
        if not reason or not reason.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reason must not be empty",
            )

        # Cheap pre-check: pending request already exists?
        result = await self.db.execute(
            select(CreditRequest.id).where(
                CreditRequest.user_id == uuid.UUID(user_id),
                CreditRequest.status == STATUS_PENDING,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_DUPLICATE_PENDING_DETAIL,
            )

        request = CreditRequest(
            user_id=uuid.UUID(user_id),
            amount=amount,
            reason=reason,
            status=STATUS_PENDING,
        )
        try:
            self.db.add(request)
            await self.db.commit()
        except IntegrityError:
            # The partial unique index fired — a concurrent request was
            # created first. Roll back and surface the same 400.
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_DUPLICATE_PENDING_DETAIL,
            ) from None
        await self.db.refresh(request)

        await ActivityService(self.db).log(
            action="credit_requests.create",
            target_type="credit_request",
            target_id=str(request.id),
            actor_id=user_id,
            details={"amount": amount, "reason": reason},
        )

        return request

    def _pagination(self, page: int, limit: int, total: int) -> dict[str, Any]:
        return {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit,
        }

    async def list_own(
        self, user_id: str, status: str | None = None, page: int = 1, limit: int = 50
    ) -> dict[str, Any]:
        """List the user's own credit requests, newest first."""
        query = select(CreditRequest).where(CreditRequest.user_id == uuid.UUID(user_id))
        if status:
            query = query.where(CreditRequest.status == status)
        query = query.order_by(CreditRequest.created_at.desc())

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        offset = (page - 1) * limit
        result = await self.db.execute(query.offset(offset).limit(limit))
        requests = result.scalars().all()

        return {
            "requests": [r.to_dict() for r in requests],
            "pagination": self._pagination(page, limit, total),
        }

    async def list_all(
        self, status: str | None = None, page: int = 1, limit: int = 50
    ) -> dict[str, Any]:
        """List all credit requests (admin), joined with the requesting user."""
        query = select(CreditRequest, User.username, User.email).join(
            User, CreditRequest.user_id == User.id
        )
        if status:
            query = query.where(CreditRequest.status == status)
        query = query.order_by(CreditRequest.created_at.desc())

        count_query = select(func.count()).select_from(CreditRequest)
        if status:
            count_query = count_query.where(CreditRequest.status == status)
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        offset = (page - 1) * limit
        result = await self.db.execute(query.offset(offset).limit(limit))

        requests = []
        for request, username, email in result.all():
            data = request.to_dict()
            data["username"] = username
            data["email"] = email
            requests.append(data)

        return {
            "requests": requests,
            "pagination": self._pagination(page, limit, total),
        }

    async def pending_count(self) -> int:
        """Count of pending requests (admin badge)."""
        result = await self.db.execute(
            select(func.count())
            .select_from(CreditRequest)
            .where(CreditRequest.status == STATUS_PENDING)
        )
        return result.scalar() or 0

    async def _get_pending_for_update(self, request_id: str) -> CreditRequest:
        """Lock a request row and require it to be pending."""
        try:
            request_uuid = uuid.UUID(request_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Credit request {request_id} not found",
            ) from None

        result = await self.db.execute(
            select(CreditRequest).where(CreditRequest.id == request_uuid).with_for_update()
        )
        request = result.scalar_one_or_none()
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Credit request {request_id} not found",
            )
        if request.status != STATUS_PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Credit request is already {request.status}",
            )
        return request

    async def approve(
        self,
        request_id: str,
        reviewer_id: str,
        amount: int | None = None,
        note: str | None = None,
    ) -> CreditRequest:
        """Approve a pending request and grant the credits.

        The granted amount defaults to the requested amount and is clamped to
        the max-balance cap inside CreditService.grant_credits; the request
        records the *actual* granted amount and links the ledger transaction.
        """
        request = await self._get_pending_for_update(request_id)

        reason = f"Credit request approved: {note or request.reason}"
        transaction = await CreditService(self.db).grant_credits(
            user_id=str(request.user_id),
            amount=amount or request.amount,
            actor_id=reviewer_id,
            reason=reason,
            source="credit_request",
            meta_extra={"request_id": str(request.id)},
        )

        request.status = STATUS_APPROVED
        request.reviewed_by = uuid.UUID(reviewer_id)
        request.reviewed_at = utc_now()
        request.granted_amount = transaction.amount
        request.transaction_id = transaction.id
        request.review_note = note
        await self.db.commit()
        await self.db.refresh(request)

        await NotificationService(self.db).credits_granted(
            user_id=str(request.user_id),
            amount=transaction.amount,
            new_balance=transaction.balance_after,
            reason=reason,
        )

        await ActivityService(self.db).log(
            action="credit_requests.approve",
            target_type="credit_request",
            target_id=str(request.id),
            actor_id=reviewer_id,
            details={
                "transaction_id": str(transaction.id),
                "requested_amount": request.amount,
                "granted_amount": transaction.amount,
            },
        )

        return request

    async def reject(
        self, request_id: str, reviewer_id: str, note: str | None = None
    ) -> CreditRequest:
        """Reject a pending request (no credits granted)."""
        request = await self._get_pending_for_update(request_id)

        request.status = STATUS_REJECTED
        request.reviewed_by = uuid.UUID(reviewer_id)
        request.reviewed_at = utc_now()
        request.review_note = note
        await self.db.commit()
        await self.db.refresh(request)

        await NotificationService(self.db).credit_request_rejected(
            user_id=str(request.user_id),
            amount=request.amount,
            note=note,
        )

        await ActivityService(self.db).log(
            action="credit_requests.reject",
            target_type="credit_request",
            target_id=str(request.id),
            actor_id=reviewer_id,
            details={"amount": request.amount, "note": note},
        )

        return request
