# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Credit request API endpoints with RBAC enforcement.
Users create and view their own requests; admins review them.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_jwt_auth
from app.core.permissions import Permission
from app.db.session import get_db
from app.dependencies import require_permissions
from app.models.user import User
from app.services.credit_request_service import CreditRequestService

router = APIRouter()


class CreateCreditRequestBody(BaseModel):
    amount: int = Field(..., gt=0, le=1_000_000, description="Amount of credits requested")
    reason: str = Field(..., min_length=1, max_length=2000, description="Reason for the request")
    request_type: Literal["top_up", "allowance"] = Field(
        "top_up", description="top_up = one-time grant; allowance = daily allowance change"
    )


class ApproveCreditRequestBody(BaseModel):
    amount: int | None = Field(
        None, gt=0, le=1_000_000, description="Override amount (defaults to requested amount)"
    )
    note: str | None = Field(None, max_length=2000, description="Review note")


class RejectCreditRequestBody(BaseModel):
    note: str | None = Field(None, max_length=2000, description="Review note")


class PostCreditRequestMessageBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000, description="Message text")
    internal: bool = Field(False, description="Reviewer-only internal note (no notification)")


# ========== User Endpoints ==========


@router.post("/")
async def create_credit_request(
    body: CreateCreditRequestBody,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.CREDITS_READ_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Create a credit request for the current user"""
    service = CreditRequestService(db)
    request = await service.create_request(
        user_id=str(current_user.id),
        amount=body.amount,
        reason=body.reason,
        request_type=body.request_type,
    )
    return {"message": "Credit request created", "request": request.to_dict()}


@router.get("/")
async def list_my_credit_requests(
    status: str | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.CREDITS_READ_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's credit requests"""
    service = CreditRequestService(db)
    return await service.list_own(
        user_id=str(current_user.id), status=status, page=page, limit=limit
    )


# ========== Admin Endpoints ==========
# NOTE: static paths (/all, /pending-count) must be declared before the
# /{request_id} routes below so they are not captured as path parameters.


@router.get("/all")
async def list_all_credit_requests(
    status: str | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    sort: str = Query("newest", description="Sort by creation: newest or oldest"),
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List all credit requests (admin)"""
    service = CreditRequestService(db)
    return await service.list_all(status=status, page=page, limit=limit, sort=sort)


@router.get("/pending-count")
async def get_pending_credit_request_count(
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Count of pending credit requests (admin)"""
    service = CreditRequestService(db)
    return {"pending": await service.pending_count()}


@router.get("/stats")
async def get_credit_request_stats(
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate credit request stats (admin)"""
    service = CreditRequestService(db)
    return await service.get_stats()


class BulkReviewBody(BaseModel):
    request_ids: list[str] = Field(..., min_length=1, max_length=50)
    action: Literal["approve", "reject"]
    note: str | None = Field(None, max_length=2000, description="Review note")


@router.post("/bulk-review")
async def bulk_review_credit_requests(
    body: BulkReviewBody,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject many credit requests at once (admin)"""
    service = CreditRequestService(db)
    results = await service.bulk_review(
        request_ids=body.request_ids,
        action=body.action,
        reviewer_id=str(current_user.id),
        note=body.note,
    )
    return {
        "message": (
            f"Bulk {body.action}: {len(results['success'])} succeeded, "
            f"{len(results['failed'])} failed"
        ),
        "results": results,
    }


class SetRequestBlockBody(BaseModel):
    blocked: bool = Field(..., description="Block or unblock credit requests for the user")
    reason: str | None = Field(None, max_length=2000, description="Reason for the change")


@router.put("/users/{user_id}/block")
async def set_credit_request_block(
    user_id: str,
    body: SetRequestBlockBody,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Block or unblock a user from creating credit requests (admin)"""
    service = CreditRequestService(db)
    await service.set_request_block(
        user_id=user_id,
        blocked=body.blocked,
        actor_id=str(current_user.id),
        reason=body.reason,
    )
    state = "blocked" if body.blocked else "unblocked"
    return {
        "message": f"Credit requests {state} for user {user_id}",
        "user_id": user_id,
        "blocked": body.blocked,
    }


@router.post("/{request_id}/approve")
async def approve_credit_request(
    request_id: str,
    body: ApproveCreditRequestBody,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Approve a credit request and grant the credits (admin)"""
    service = CreditRequestService(db)
    request = await service.approve(
        request_id=request_id,
        reviewer_id=str(current_user.id),
        amount=body.amount,
        note=body.note,
    )
    return {
        "message": f"Credit request approved; granted {request.granted_amount} credits",
        "request": request.to_dict(),
    }


@router.post("/{request_id}/reject")
async def reject_credit_request(
    request_id: str,
    body: RejectCreditRequestBody,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Reject a credit request (admin)"""
    service = CreditRequestService(db)
    request = await service.reject(
        request_id=request_id,
        reviewer_id=str(current_user.id),
        note=body.note,
    )
    return {"message": "Credit request rejected", "request": request.to_dict()}


# ========== Conversation & Cancellation ==========
# Static admin paths (/all, /pending-count) are declared above; the routes
# below all hang off /{request_id}.


@router.post("/{request_id}/cancel")
async def cancel_credit_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.CREDITS_READ_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an open credit request (requester only)"""
    service = CreditRequestService(db)
    request = await service.cancel(
        request_id=request_id,
        user_id=str(current_user.id),
    )
    return {"message": "Credit request cancelled", "request": request.to_dict()}


@router.get("/{request_id}/messages")
async def list_credit_request_messages(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List a credit request's conversation (requester or CREDITS_READ_ALL)"""
    service = CreditRequestService(db)
    messages = await service.list_messages(
        request_id=request_id,
        requesting_user=current_user,
    )
    return {"messages": messages}


@router.post("/{request_id}/messages")
async def post_credit_request_message(
    request_id: str,
    body: PostCreditRequestMessageBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Post a message on an open credit request (requester or CREDITS_GRANT)"""
    service = CreditRequestService(db)
    message = await service.add_message(
        request_id=request_id,
        author=current_user,
        body=body.body,
        internal=body.internal,
    )
    return {"message": message.to_dict()}
