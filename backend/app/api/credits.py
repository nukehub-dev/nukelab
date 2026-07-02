# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Credit API endpoints with RBAC enforcement.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_jwt_auth
from app.core.permissions import Permission
from app.db.session import get_db
from app.dependencies import require_permissions
from app.models.user import User
from app.services.credit_service import CreditService
from app.services.notification_service import NotificationService

router = APIRouter()


class GrantCreditsRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount to grant")
    reason: str = Field(..., min_length=1, description="Reason for granting")


class DeductCreditsRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount to deduct")
    reason: str = Field(..., min_length=1, description="Reason for deduction")


# ========== User Credit Endpoints ==========


@router.get("/")
async def get_my_credits(
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.CREDITS_READ_OWN, Permission.CREDITS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's credit balance and summary"""
    service = CreditService(db)
    summary = await service.get_credit_summary(str(current_user.id))

    return {
        "user_id": str(current_user.id),
        "balance": current_user.nuke_balance,
        "daily_allowance": current_user.daily_allowance,
        "summary": summary,
    }


@router.get("/history")
async def get_my_credit_history(
    transaction_type: str | None = Query(None, description="Filter by type"),
    from_date: datetime | None = Query(None, description="From date"),
    to_date: datetime | None = Query(None, description="To date"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    sort_by: str = Query("created_at", description="Sort column"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.CREDITS_READ_OWN, Permission.CREDITS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's credit transaction history"""
    service = CreditService(db)
    result = await service.get_transaction_history(
        user_id=str(current_user.id),
        transaction_type=transaction_type,
        from_date=from_date,
        to_date=to_date,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return result


# ========== Admin Credit Management ==========
class UserDailyAllowanceRequest(BaseModel):
    amount: int = Field(..., ge=0, description="Daily allowance amount")


@router.put("/users/{user_id}/daily-allowance")
async def update_user_daily_allowance(
    user_id: str,
    request: UserDailyAllowanceRequest,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's daily credit allowance"""
    from app.services.activity_service import ActivityService
    from app.services.user_service import UserService

    service = UserService(db)
    user = await service.update_user(
        user_id=user_id,
        data={"daily_allowance": request.amount},
        updated_by=current_user,
    )

    activity_service = ActivityService(db)
    await activity_service.log(
        action="credits.update_user_daily_allowance",
        target_type="user",
        target_id=user_id,
        actor_id=str(current_user.id),
        details={"amount": request.amount},
    )

    return {"message": f"Updated daily allowance to {request.amount}", "user": user.to_dict()}


class AllowanceOverrideRequest(BaseModel):
    amount: int = Field(..., ge=0, description="Override allowance amount (NUKE / day)")
    until: datetime = Field(
        ..., description="ISO 8601 expiry timestamp (when the override reverts to base)"
    )


@router.put("/users/{user_id}/allowance-override")
async def set_user_allowance_override(
    user_id: str,
    request: AllowanceOverrideRequest,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Set a time-boxed daily-allowance override for a user.

    The user's effective allowance becomes `amount` until `until` (UTC),
    after which it automatically reverts to the base `daily_allowance`
    — no manual clear required at expiry.
    """
    from app.services.activity_service import ActivityService
    from app.services.user_service import UserService

    service = UserService(db)
    user = await service.update_user(
        user_id=user_id,
        data={
            "daily_allowance_override": request.amount,
            "daily_allowance_override_until": request.until.isoformat(),
        },
        updated_by=current_user,
    )

    activity_service = ActivityService(db)
    await activity_service.log(
        action="credits.set_allowance_override",
        target_type="user",
        target_id=user_id,
        actor_id=str(current_user.id),
        details={"amount": request.amount, "until": request.until.isoformat()},
    )

    return {
        "message": f"Override set: {request.amount} NUKE/day until {request.until.isoformat()}",
        "user": user.to_dict(),
    }


@router.delete("/users/{user_id}/allowance-override")
async def clear_user_allowance_override(
    user_id: str,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Clear a user's daily-allowance override immediately.
    Reverts the effective allowance to the base `daily_allowance`.
    """
    from app.services.activity_service import ActivityService
    from app.services.user_service import UserService

    service = UserService(db)
    user = await service.update_user(
        user_id=user_id,
        data={"daily_allowance_override": None},
        updated_by=current_user,
    )

    activity_service = ActivityService(db)
    await activity_service.log(
        action="credits.clear_allowance_override",
        target_type="user",
        target_id=user_id,
        actor_id=str(current_user.id),
        details={},
    )

    return {"message": "Allowance override cleared", "user": user.to_dict()}


@router.get("/users/{user_id}")
async def get_user_credits(
    user_id: str,
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get any user's credit balance"""
    service = CreditService(db)
    summary = await service.get_credit_summary(user_id)

    return {"user_id": user_id, "balance": summary["current_balance"], "summary": summary}


@router.get("/users/{user_id}/history")
async def get_user_credit_history(
    user_id: str,
    transaction_type: str | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get any user's credit transaction history"""
    service = CreditService(db)
    result = await service.get_transaction_history(
        user_id=user_id,
        transaction_type=transaction_type,
        from_date=from_date,
        to_date=to_date,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return result


@router.post("/users/{user_id}/grant")
async def grant_credits_to_user(
    user_id: str,
    request: GrantCreditsRequest,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Grant credits to a user"""
    service = CreditService(db)
    transaction = await service.grant_credits(
        user_id=user_id, amount=request.amount, actor_id=str(current_user.id), reason=request.reason
    )

    # Audit log — link to the ledger row so the two records are clearly
    # the same action rather than a duplicate; details carry the actual
    # credited amount (which may be lower than requested when the cap
    # applies).
    from app.services.activity_service import ActivityService

    activity_service = ActivityService(db)
    await activity_service.log(
        action="credits.grant",
        target_type="user",
        target_id=user_id,
        actor_id=str(current_user.id),
        details={
            "transaction_id": str(transaction.id),
            "requested_amount": request.amount,
            "granted_amount": transaction.amount,
            "reason": request.reason,
        },
    )

    # Notify the user (use the actual credited amount so the toast
    # matches the ledger, not the requested value)
    notif_service = NotificationService(db)
    await notif_service.credits_granted(
        user_id=user_id,
        amount=transaction.amount,
        new_balance=transaction.balance_after,
        reason=request.reason,
    )

    message = (
        f"Granted {transaction.amount} credits"
        if transaction.amount == request.amount
        else f"Granted {transaction.amount} credits (capped from {request.amount})"
    )
    return {"message": message, "transaction": transaction.to_dict()}


@router.post("/users/{user_id}/deduct")
async def deduct_credits_from_user(
    user_id: str,
    request: DeductCreditsRequest,
    current_user: User = Depends(require_permissions(Permission.CREDITS_DEDUCT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Deduct credits from a user"""
    service = CreditService(db)
    transaction = await service.deduct_credits(
        user_id=user_id, amount=request.amount, actor_id=str(current_user.id), reason=request.reason
    )

    # Audit log — link to the ledger row so the activity log and the
    # credit ledger are clearly the same action (transaction_id is the
    # shared key), not two parallel records of it.
    from app.services.activity_service import ActivityService

    activity_service = ActivityService(db)
    await activity_service.log(
        action="credits.deduct",
        target_type="user",
        target_id=user_id,
        actor_id=str(current_user.id),
        details={
            "transaction_id": str(transaction.id),
            "amount": request.amount,
            "reason": request.reason,
        },
    )

    # Notify the user
    notif_service = NotificationService(db)
    await notif_service.credits_deducted(
        user_id=user_id,
        amount=request.amount,
        new_balance=transaction.balance_after,
        reason=request.reason,
    )

    return {"message": f"Deducted {request.amount} credits", "transaction": transaction.to_dict()}


@router.get("/low-balance")
async def get_low_balance_users(
    threshold: int = Query(100, ge=0, description="Credit threshold"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=500, description="Items per page"),
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get users with low credit balance"""
    service = CreditService(db)
    result = await service.get_low_credit_users(threshold, page=page, limit=limit)

    return {
        "threshold": threshold,
        "count": result["count"],
        "users": result["users"],
        "pagination": result["pagination"],
    }
