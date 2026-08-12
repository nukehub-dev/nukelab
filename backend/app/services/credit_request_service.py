# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Credit request service: users request credits, admins approve or reject,
and both sides converse via per-request messages.

Status machine: open states are ``pending`` and ``needs_info``; terminal
states are ``approved``, ``rejected``, and ``cancelled``. The ball-in-court
state flips automatically with each message: a reviewer posting on an open
request flips it to ``needs_info``; the requester posting flips it back to
``pending``.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.permissions import Permission
from app.core.security import has_permission
from app.core.time_utils import utc_now
from app.models.credit_request import CreditRequest, CreditRequestMessage
from app.models.user import User
from app.services.activity_service import ActivityService
from app.services.credit_service import CreditService
from app.services.notification_service import NotificationService

logger = get_logger(__name__)

STATUS_PENDING = "pending"
STATUS_NEEDS_INFO = "needs_info"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"

OPEN_STATUSES = (STATUS_PENDING, STATUS_NEEDS_INFO)

# Roles that may hold CREDITS_GRANT; used as a cheap candidate filter before
# the authoritative has_permission check (which respects runtime overrides).
_REVIEWER_ROLES = ("admin", "moderator", "support", "super_admin")

_DUPLICATE_OPEN_DETAIL = "You already have an open credit request"


class CreditRequestService:
    """Credit request business logic"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_request(self, user_id: str, amount: int, reason: str) -> CreditRequest:
        """Create a credit request for a user.

        Idempotent per user: at most one open (pending/needs_info) request at
        a time. The cheap pre-check below is backed by the partial unique
        index uq_credit_requests_pending_per_user; if a concurrent insert
        wins the race, the resulting IntegrityError maps to the same 400.
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

        # Cheap pre-check: open request already exists?
        result = await self.db.execute(
            select(CreditRequest.id).where(
                CreditRequest.user_id == uuid.UUID(user_id),
                CreditRequest.status.in_(OPEN_STATUSES),
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_DUPLICATE_OPEN_DETAIL,
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
                detail=_DUPLICATE_OPEN_DETAIL,
            ) from None
        await self.db.refresh(request)

        await ActivityService(self.db).log(
            action="credit_requests.create",
            target_type="credit_request",
            target_id=str(request.id),
            actor_id=user_id,
            details={"amount": amount, "reason": reason},
        )

        await self._notify_reviewers(
            request,
            exclude_user_id=user_id,
            kind="created",
        )

        return request

    def _pagination(self, page: int, limit: int, total: int) -> dict[str, Any]:
        return {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit,
        }

    def _status_filter(self, query, status_filter: str | None, column):
        """Apply the status filter; the special value 'open' means any open state."""
        if status_filter == "open":
            return query.where(column.in_(OPEN_STATUSES))
        if status_filter:
            return query.where(column == status_filter)
        return query

    async def list_own(
        self, user_id: str, status: str | None = None, page: int = 1, limit: int = 50
    ) -> dict[str, Any]:
        """List the user's own credit requests, newest first."""
        query = select(CreditRequest).where(CreditRequest.user_id == uuid.UUID(user_id))
        query = self._status_filter(query, status, CreditRequest.status)
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
        query = self._status_filter(query, status, CreditRequest.status)
        query = query.order_by(CreditRequest.created_at.desc())

        count_query = select(func.count()).select_from(CreditRequest)
        count_query = self._status_filter(count_query, status, CreditRequest.status)
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

    async def _get_open_for_update(self, request_id: str) -> CreditRequest:
        """Lock a request row and require it to be in an open state."""
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
        if request.status not in OPEN_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Credit request is already {request.status}",
            )
        return request

    async def _notify_reviewers(
        self,
        request: CreditRequest,
        exclude_user_id: str | None,
        kind: str,
        preview: str | None = None,
    ) -> None:
        """Notify every active user holding CREDITS_GRANT (except the actor).

        Candidates are cheaply filtered by role first; has_permission is the
        authoritative check so runtime role overrides are respected.
        """
        result = await self.db.execute(
            select(User).where(
                User.is_active.is_(True),
                User.role.in_(_REVIEWER_ROLES),
            )
        )
        candidates = result.scalars().all()

        notif_service = NotificationService(self.db)
        for reviewer in candidates:
            if exclude_user_id and str(reviewer.id) == exclude_user_id:
                continue
            if not has_permission(reviewer, Permission.CREDITS_GRANT):
                continue
            if kind == "created":
                await notif_service.credit_request_created(
                    user_id=reviewer.id,
                    amount=request.amount,
                    reason=request.reason,
                )
            else:
                await notif_service.credit_request_message(
                    user_id=reviewer.id,
                    amount=request.amount,
                    preview=preview or "",
                )

    async def approve(
        self,
        request_id: str,
        reviewer_id: str,
        amount: int | None = None,
        note: str | None = None,
    ) -> CreditRequest:
        """Approve an open request and grant the credits.

        The granted amount defaults to the requested amount and is clamped to
        the max-balance cap inside CreditService.grant_credits; the request
        records the *actual* granted amount and links the ledger transaction.
        """
        request = await self._get_open_for_update(request_id)

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
        """Reject an open request (no credits granted)."""
        request = await self._get_open_for_update(request_id)

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

    async def cancel(self, request_id: str, user_id: str) -> CreditRequest:
        """Cancel an open request. Only the requester may cancel."""
        request = await self._get_open_for_update(request_id)

        if str(request.user_id) != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the requester can cancel a credit request",
            )

        request.status = STATUS_CANCELLED
        request.reviewed_at = utc_now()
        await self.db.commit()
        await self.db.refresh(request)

        await ActivityService(self.db).log(
            action="credit_requests.cancel",
            target_type="credit_request",
            target_id=str(request.id),
            actor_id=user_id,
            details={"amount": request.amount},
        )

        return request

    async def add_message(self, request_id: str, author: User, body: str) -> CreditRequestMessage:
        """Post a message on an open request and flip the ball-in-court state.

        The requester posting flips the request back to ``pending``; a
        reviewer (CREDITS_GRANT) posting flips it to ``needs_info``.
        """
        if not body or not body.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message body must not be empty",
            )

        request = await self._get_open_for_update(request_id)

        is_requester = request.user_id == author.id
        if not is_requester and not has_permission(author, Permission.CREDITS_GRANT):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot post on this credit request",
            )

        message = CreditRequestMessage(
            request_id=request.id,
            author_id=author.id,
            body=body,
        )
        self.db.add(message)
        request.status = STATUS_PENDING if is_requester else STATUS_NEEDS_INFO
        await self.db.commit()
        await self.db.refresh(message)

        # Notify the counterpart, never the author.
        notif_service = NotificationService(self.db)
        if is_requester:
            await self._notify_reviewers(
                request,
                exclude_user_id=str(author.id),
                kind="message",
                preview=body[:200],
            )
        else:
            await notif_service.credit_request_message(
                user_id=request.user_id,
                amount=request.amount,
                preview=body[:200],
            )

        await ActivityService(self.db).log(
            action="credit_requests.message",
            target_type="credit_request",
            target_id=str(request.id),
            actor_id=str(author.id),
            details={"message_id": str(message.id), "is_requester": is_requester},
        )

        return message

    async def list_messages(self, request_id: str, requesting_user: User) -> list[dict[str, Any]]:
        """List a request's conversation, oldest first.

        Visible to the requester and to anyone holding CREDITS_READ_ALL.
        """
        try:
            request_uuid = uuid.UUID(request_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Credit request {request_id} not found",
            ) from None

        result = await self.db.execute(
            select(CreditRequest).where(CreditRequest.id == request_uuid)
        )
        request = result.scalar_one_or_none()
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Credit request {request_id} not found",
            )

        if request.user_id != requesting_user.id and not has_permission(
            requesting_user, Permission.CREDITS_READ_ALL
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot view this credit request",
            )

        result = await self.db.execute(
            select(CreditRequestMessage, User.username)
            .outerjoin(User, CreditRequestMessage.author_id == User.id)
            .where(CreditRequestMessage.request_id == request.id)
            .order_by(CreditRequestMessage.created_at.asc())
        )

        messages = []
        for message, author_username in result.all():
            data = message.to_dict()
            data["author_username"] = author_username
            data["is_admin"] = message.author_id != request.user_id
            messages.append(data)
        return messages
