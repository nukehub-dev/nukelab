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
from datetime import timedelta
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

# top_up = one-time grant on approval; allowance = approval sets the
# user's base daily_allowance instead (no ledger transaction).
TYPE_TOP_UP = "top_up"
TYPE_ALLOWANCE = "allowance"
REQUEST_TYPES = (TYPE_TOP_UP, TYPE_ALLOWANCE)

# Roles that may hold CREDITS_GRANT; used as a cheap candidate filter before
# the authoritative has_permission check (which respects runtime overrides).
_REVIEWER_ROLES = ("admin", "moderator", "support", "super_admin")

_DUPLICATE_OPEN_DETAIL = "You already have an open credit request"


class CreditRequestService:
    """Credit request business logic"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _check_cooldown(self, user_id: str) -> None:
        """Raise 400 if the user's latest rejection is still within the
        cooldown window (credits_request_cooldown_hours; 0 = off)."""
        from app.services.setting_service import SettingService

        hours = await SettingService(self.db).get_request_cooldown_hours()
        if hours <= 0:
            return

        result = await self.db.execute(
            select(CreditRequest)
            .where(
                CreditRequest.user_id == uuid.UUID(user_id),
                CreditRequest.status == STATUS_REJECTED,
                CreditRequest.reviewed_at.isnot(None),
            )
            .order_by(CreditRequest.reviewed_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest is None:
            return

        window = timedelta(hours=hours)
        now = utc_now()
        if latest.reviewed_at + window > now:
            remaining_seconds = (latest.reviewed_at + window - now).total_seconds()
            remaining_hours = max(1, int(remaining_seconds // 3600) + 1)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Your previous credit request was rejected recently. "
                    f"You can submit a new request in approximately {remaining_hours} hour(s)."
                ),
            )

    async def create_request(
        self, user_id: str, amount: int, reason: str, request_type: str = TYPE_TOP_UP
    ) -> CreditRequest:
        """Create a credit request for a user.

        Idempotent per user: at most one open (pending/needs_info) request at
        a time. The cheap pre-check below is backed by the partial unique
        index uq_credit_requests_pending_per_user; if a concurrent insert
        wins the race, the resulting IntegrityError maps to the same 400.

        Top-up requests at or below the auto-approve threshold
        (credits_auto_approve_max, 0 = off) are approved immediately.
        """
        # Per-user block: an admin can disable credit requests for an
        # account. Checked before everything else, including validation.
        result = await self.db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one_or_none()
        if user is not None and user.credit_requests_blocked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Credit requests are disabled for your account",
            )

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
        if request_type not in REQUEST_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown request type: {request_type}",
            )

        await self._check_cooldown(user_id)

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
            request_type=request_type,
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
            details={"amount": amount, "reason": reason, "request_type": request_type},
        )

        if request_type == TYPE_TOP_UP and await self._try_auto_approve(request):
            # Auto-approved: no reviewer notification.
            return request

        await self._notify_reviewers(
            request,
            exclude_user_id=user_id,
            kind="created",
        )

        return request

    async def _try_auto_approve(self, request: CreditRequest) -> bool:
        """Auto-approve a top_up request at/below the configured threshold.

        Grants immediately (cap clamping still applies), stamps the request
        approved with no reviewer, and notifies the requester. Returns True
        when the request was auto-approved.
        """
        from app.services.setting_service import SettingService

        threshold = await SettingService(self.db).get_auto_approve_max()
        if threshold <= 0 or request.amount > threshold:
            return False

        reason = "Credit request auto-approved"
        transaction = await CreditService(self.db).grant_credits(
            user_id=str(request.user_id),
            amount=request.amount,
            actor_id=None,
            reason=reason,
            source="auto_approve",
            meta_extra={"request_id": str(request.id)},
        )

        request.status = STATUS_APPROVED
        request.reviewed_by = None
        request.reviewed_at = utc_now()
        request.granted_amount = transaction.amount
        request.transaction_id = transaction.id
        await self.db.commit()
        await self.db.refresh(request)

        await NotificationService(self.db).credits_granted(
            user_id=str(request.user_id),
            amount=transaction.amount,
            new_balance=transaction.balance_after,
            reason=reason,
        )

        await ActivityService(self.db).log(
            action="credit_requests.auto_approve",
            target_type="credit_request",
            target_id=str(request.id),
            actor_id=str(request.user_id),
            details={
                "transaction_id": str(transaction.id),
                "requested_amount": request.amount,
                "granted_amount": transaction.amount,
            },
        )

        return True

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
        self, status: str | None = None, page: int = 1, limit: int = 50, sort: str = "newest"
    ) -> dict[str, Any]:
        """List all credit requests (admin), joined with the requesting user.

        ``sort`` is "newest" (default) or "oldest" by created_at.
        """
        query = select(CreditRequest, User.username, User.email).join(
            User, CreditRequest.user_id == User.id
        )
        query = self._status_filter(query, status, CreditRequest.status)
        if sort == "oldest":
            query = query.order_by(CreditRequest.created_at.asc())
        else:
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
        requester_username: str | None = None,
        age_hours: int | None = None,
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
            elif kind == "stale":
                await notif_service.credit_request_stale_reminder(
                    user_id=reviewer.id,
                    amount=request.amount,
                    requester_username=requester_username or "unknown",
                    age_hours=age_hours or 0,
                    request_id=str(request.id),
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
        """Approve an open request.

        top_up: grants credits (clamped to the max-balance cap inside
        CreditService.grant_credits); the request records the *actual*
        granted amount and links the ledger transaction.

        allowance: sets the user's base daily_allowance instead — no
        ledger transaction, transaction_id stays null, granted_amount
        records the new allowance.
        """
        request = await self._get_open_for_update(request_id)
        if request.request_type == TYPE_ALLOWANCE:
            return await self._approve_allowance(request, reviewer_id, amount, note)
        return await self._approve_top_up(request, reviewer_id, amount, note)

    async def _approve_top_up(
        self,
        request: CreditRequest,
        reviewer_id: str,
        amount: int | None,
        note: str | None,
    ) -> CreditRequest:
        """Approve a top_up request: grant credits via the ledger."""
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
                "request_type": request.request_type,
            },
        )

        return request

    async def _approve_allowance(
        self,
        request: CreditRequest,
        reviewer_id: str,
        amount: int | None,
        note: str | None,
    ) -> CreditRequest:
        """Approve an allowance request: set the user's base daily_allowance.

        Mirrors the admin daily-allowance endpoint (UserService.update_user
        + its activity log); no ledger transaction is created.
        """
        from app.services.user_service import UserService

        result = await self.db.execute(select(User).where(User.id == uuid.UUID(reviewer_id)))
        reviewer = result.scalar_one_or_none()
        if reviewer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Reviewer {reviewer_id} not found",
            )

        new_allowance = amount or request.amount
        await UserService(self.db).update_user(
            user_id=str(request.user_id),
            data={"daily_allowance": new_allowance},
            updated_by=reviewer,
        )

        # Mirror the admin daily-allowance endpoint's audit entry so both
        # paths record the same user-facing change identically.
        await ActivityService(self.db).log(
            action="credits.update_user_daily_allowance",
            target_type="user",
            target_id=str(request.user_id),
            actor_id=reviewer_id,
            details={"amount": new_allowance},
        )

        request.status = STATUS_APPROVED
        request.reviewed_by = uuid.UUID(reviewer_id)
        request.reviewed_at = utc_now()
        request.granted_amount = new_allowance
        request.transaction_id = None
        request.review_note = note
        await self.db.commit()
        await self.db.refresh(request)

        await NotificationService(self.db).credit_request_allowance_approved(
            user_id=str(request.user_id),
            allowance=new_allowance,
        )

        await ActivityService(self.db).log(
            action="credit_requests.approve",
            target_type="credit_request",
            target_id=str(request.id),
            actor_id=reviewer_id,
            details={
                "requested_amount": request.amount,
                "granted_amount": new_allowance,
                "request_type": request.request_type,
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

    async def add_message(
        self, request_id: str, author: User, body: str, internal: bool = False
    ) -> CreditRequestMessage:
        """Post a message on an open request and flip the ball-in-court state.

        The requester posting flips the request back to ``pending``; a
        reviewer (CREDITS_GRANT) posting flips it to ``needs_info``.

        Internal notes (``internal=True``) are reviewer-only: they require
        CREDITS_GRANT, do not flip the status, and never notify the
        requester.
        """
        if not body or not body.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message body must not be empty",
            )

        request = await self._get_open_for_update(request_id)

        is_requester = request.user_id == author.id
        is_reviewer = has_permission(author, Permission.CREDITS_GRANT)
        if not is_requester and not is_reviewer:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot post on this credit request",
            )
        if internal and not is_reviewer:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Internal notes require review permissions",
            )

        message = CreditRequestMessage(
            request_id=request.id,
            author_id=author.id,
            body=body,
            is_internal=internal,
        )
        self.db.add(message)
        if not internal:
            request.status = STATUS_PENDING if is_requester else STATUS_NEEDS_INFO
        await self.db.commit()
        await self.db.refresh(message)

        # Notify the counterpart, never the author. Internal notes notify no one.
        if not internal:
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
            details={
                "message_id": str(message.id),
                "is_requester": is_requester,
                "internal": internal,
            },
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

        query = (
            select(CreditRequestMessage, User.username)
            .outerjoin(User, CreditRequestMessage.author_id == User.id)
            .where(CreditRequestMessage.request_id == request.id)
        )
        # Internal reviewer notes are visible only to CREDITS_READ_ALL holders.
        if not has_permission(requesting_user, Permission.CREDITS_READ_ALL):
            query = query.where(CreditRequestMessage.is_internal.is_(False))
        query = query.order_by(CreditRequestMessage.created_at.asc())

        result = await self.db.execute(query)

        messages = []
        for message, author_username in result.all():
            data = message.to_dict()
            data["author_username"] = author_username
            data["is_admin"] = message.author_id != request.user_id
            messages.append(data)
        return messages

    async def _was_reminded_recently(self, request_id: uuid.UUID, hours: int = 24) -> bool:
        """Return True if a stale reminder for this request went out recently."""
        from app.models.notification import Notification

        cutoff = utc_now() - timedelta(hours=hours)
        result = await self.db.execute(
            select(Notification.id).where(
                Notification.type == "credit",
                Notification.created_at >= cutoff,
                Notification.extra_data["event_key"].as_string() == "credit_request_stale",
                Notification.extra_data["request_id"].as_string() == str(request_id),
            )
        )
        return result.scalar_one_or_none() is not None

    async def remind_stale_requests(self, hours: int = 24) -> int:
        """Re-notify reviewers about open requests older than ``hours``.

        Throttled to at most one reminder per request per 24h via the
        notification's extra_data markers. Returns the number of requests
        reminded (for the Celery task's log line).
        """
        cutoff = utc_now() - timedelta(hours=hours)
        result = await self.db.execute(
            select(CreditRequest, User.username)
            .join(User, CreditRequest.user_id == User.id)
            .where(
                CreditRequest.status.in_(OPEN_STATUSES),
                CreditRequest.created_at < cutoff,
            )
        )

        reminded = 0
        for request, requester_username in result.all():
            if await self._was_reminded_recently(request.id):
                continue
            age_hours = int((utc_now() - request.created_at).total_seconds() // 3600)
            await self._notify_reviewers(
                request,
                exclude_user_id=None,
                kind="stale",
                requester_username=requester_username,
                age_hours=age_hours,
            )
            reminded += 1
        return reminded

    async def get_stats(self) -> dict[str, Any]:
        """Aggregate credit request stats for the admin dashboard."""
        counts = {
            STATUS_PENDING: 0,
            STATUS_NEEDS_INFO: 0,
            STATUS_APPROVED: 0,
            STATUS_REJECTED: 0,
            STATUS_CANCELLED: 0,
        }
        result = await self.db.execute(
            select(CreditRequest.status, func.count()).group_by(CreditRequest.status)
        )
        for status_value, count in result.all():
            counts[status_value] = counts.get(status_value, 0) + count

        decided = counts[STATUS_APPROVED] + counts[STATUS_REJECTED]
        approval_rate = counts[STATUS_APPROVED] / decided if decided else 0

        # Mean decision latency over decided rows, in hours.
        result = await self.db.execute(
            select(func.avg(CreditRequest.reviewed_at - CreditRequest.created_at)).where(
                CreditRequest.status.in_((STATUS_APPROVED, STATUS_REJECTED)),
                CreditRequest.reviewed_at.isnot(None),
            )
        )
        avg_interval = result.scalar()
        avg_decision_hours = (
            round(avg_interval.total_seconds() / 3600, 2) if avg_interval is not None else None
        )

        result = await self.db.execute(
            select(func.min(CreditRequest.created_at)).where(
                CreditRequest.status.in_(OPEN_STATUSES)
            )
        )
        oldest_open = result.scalar()
        oldest_open_hours = (
            round((utc_now() - oldest_open).total_seconds() / 3600, 2)
            if oldest_open is not None
            else None
        )

        return {
            "counts": counts,
            "decided": decided,
            "approval_rate": approval_rate,
            "avg_decision_hours": avg_decision_hours,
            "oldest_open_hours": oldest_open_hours,
        }

    async def bulk_review(
        self,
        request_ids: list[str],
        action: str,
        reviewer_id: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Approve or reject many requests, capturing per-item failures.

        Approvals use each request's own requested amount (cap clamping
        still applies per grant). Mirrors the admin bulk-grant result shape.
        """
        results: dict[str, Any] = {"success": [], "failed": []}
        for request_id in request_ids:
            try:
                if action == "approve":
                    await self.approve(request_id, reviewer_id=reviewer_id, note=note)
                else:
                    await self.reject(request_id, reviewer_id=reviewer_id, note=note)
                results["success"].append({"request_id": request_id})
            except HTTPException as e:
                results["failed"].append({"request_id": request_id, "error": e.detail})
        return results

    async def set_request_block(
        self, user_id: str, blocked: bool, actor_id: str, reason: str | None = None
    ) -> User:
        """Block or unblock a user from creating credit requests (admin).

        Flips users.credit_requests_blocked via UserService (which enforces
        CREDITS_GRANT on the actor), audit-logs the change, and notifies
        the user both ways.
        """
        from app.services.user_service import UserService

        result = await self.db.execute(select(User).where(User.id == uuid.UUID(actor_id)))
        actor = result.scalar_one_or_none()
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Actor {actor_id} not found",
            )

        user = await UserService(self.db).update_user(
            user_id=user_id,
            data={"credit_requests_blocked": blocked},
            updated_by=actor,
        )

        await ActivityService(self.db).log(
            action="credit_requests.block" if blocked else "credit_requests.unblock",
            target_type="user",
            target_id=user_id,
            actor_id=actor_id,
            details={"blocked": blocked, "reason": reason},
        )

        await NotificationService(self.db).credit_request_block_changed(
            user_id=user.id,
            blocked=blocked,
            reason=reason,
        )

        return user
