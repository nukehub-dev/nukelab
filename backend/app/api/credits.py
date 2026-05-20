"""
Credit API endpoints with RBAC enforcement.
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_scopes
from app.core.permissions import Permission
from app.dependencies import PermissionChecker, require_permissions
from app.db.session import get_db
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
    _ = Depends(require_scopes("credits:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's credit balance and summary"""
    service = CreditService(db)
    summary = await service.get_credit_summary(str(current_user.id))
    
    return {
        "user_id": str(current_user.id),
        "balance": current_user.nuke_balance,
        "daily_allowance": current_user.daily_allowance,
        "summary": summary
    }


@router.get("/history")
async def get_my_credit_history(
    transaction_type: Optional[str] = Query(None, description="Filter by type"),
    from_date: Optional[datetime] = Query(None, description="From date"),
    to_date: Optional[datetime] = Query(None, description="To date"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    sort_by: str = Query("created_at", description="Sort column"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_scopes("credits:read")),
    db: AsyncSession = Depends(get_db)
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
        sort_order=sort_order
    )
    
    return result


# ========== Admin Credit Management ==========

@router.get("/users/{user_id}")
async def get_user_credits(
    user_id: str,
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ)),
    _scopes = Depends(require_scopes("credits:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get any user's credit balance (Admin only)"""
    service = CreditService(db)
    summary = await service.get_credit_summary(user_id)
    
    return {
        "user_id": user_id,
        "balance": summary["current_balance"],
        "summary": summary
    }


@router.get("/users/{user_id}/history")
async def get_user_credit_history(
    user_id: str,
    transaction_type: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ)),
    _scopes = Depends(require_scopes("credits:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get any user's credit transaction history (Admin only)"""
    service = CreditService(db)
    result = await service.get_transaction_history(
        user_id=user_id,
        transaction_type=transaction_type,
        from_date=from_date,
        to_date=to_date,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    return result


@router.post("/users/{user_id}/grant")
async def grant_credits_to_user(
    user_id: str,
    request: GrantCreditsRequest,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _scopes = Depends(require_scopes("admin:write")),
    db: AsyncSession = Depends(get_db)
):
    """Grant credits to a user (Admin only)"""
    service = CreditService(db)
    transaction = await service.grant_credits(
        user_id=user_id,
        amount=request.amount,
        actor_id=str(current_user.id),
        reason=request.reason
    )

    # Notify the user
    notif_service = NotificationService(db)
    await notif_service.credits_granted(
        user_id=user_id,
        amount=request.amount,
        new_balance=transaction.balance_after,
        reason=request.reason
    )

    return {
        "message": f"Granted {request.amount} credits",
        "transaction": transaction.to_dict()
    }


@router.post("/users/{user_id}/deduct")
async def deduct_credits_from_user(
    user_id: str,
    request: DeductCreditsRequest,
    current_user: User = Depends(require_permissions(Permission.CREDITS_DEDUCT)),
    _scopes = Depends(require_scopes("admin:write")),
    db: AsyncSession = Depends(get_db)
):
    """Deduct credits from a user (Admin only)"""
    service = CreditService(db)
    transaction = await service.deduct_credits(
        user_id=user_id,
        amount=request.amount,
        actor_id=str(current_user.id),
        reason=request.reason
    )

    # Notify the user
    notif_service = NotificationService(db)
    await notif_service.credits_deducted(
        user_id=user_id,
        amount=request.amount,
        new_balance=transaction.balance_after,
        reason=request.reason
    )

    return {
        "message": f"Deducted {request.amount} credits",
        "transaction": transaction.to_dict()
    }


@router.get("/low-balance")
async def get_low_balance_users(
    threshold: int = Query(100, ge=0, description="Credit threshold"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=500, description="Items per page"),
    current_user: User = Depends(require_permissions(Permission.CREDITS_READ)),
    _scopes = Depends(require_scopes("admin:read")),
    db: AsyncSession = Depends(get_db)
):
    """Get users with low credit balance (Admin only)"""
    service = CreditService(db)
    result = await service.get_low_credit_users(threshold, page=page, limit=limit)
    
    return {
        "threshold": threshold,
        "count": result["count"],
        "users": result["users"],
        "pagination": result["pagination"]
    }
