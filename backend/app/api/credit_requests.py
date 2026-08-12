# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Credit request API endpoints with RBAC enforcement.
Users create and view their own requests; admins review them.
"""

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


class ApproveCreditRequestBody(BaseModel):
    amount: int | None = Field(
        None, gt=0, le=1_000_000, description="Override amount (defaults to requested amount)"
    )
    note: str | None = Field(None, max_length=2000, description="Review note")


class RejectCreditRequestBody(BaseModel):
    note: str | None = Field(None, max_length=2000, description="Review note")


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
        user_id=str(current_user.id), amount=body.amount, reason=body.reason
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
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List all credit requests (admin)"""
    service = CreditRequestService(db)
    return await service.list_all(status=status, page=page, limit=limit)


@router.get("/pending-count")
async def get_pending_credit_request_count(
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Count of pending credit requests (admin)"""
    service = CreditRequestService(db)
    return {"pending": await service.pending_count()}


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
