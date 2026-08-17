# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Web Push subscription management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.config import settings
from app.db.session import get_db
from app.models.push_subscription import PushSubscription
from app.models.user import User

router = APIRouter()


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionRequest(BaseModel):
    endpoint: str = Field(..., min_length=1)
    keys: SubscriptionKeys


class SubscriptionResponse(BaseModel):
    id: str
    endpoint: str
    created_at: str


@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """Return the VAPID public key used for push subscription."""
    if not settings.vapid_public_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Push notifications are not configured",
        )
    return {"public_key": settings.vapid_public_key}


@router.post(
    "/subscriptions", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED
)
async def subscribe_push(
    request: SubscriptionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store or update a push subscription for the current user."""
    # Capture the id up front: after a rollback (see the race recovery below)
    # the ORM user object is expired, and accessing current_user.id would
    # trigger a lazy load that fails in async context.
    user_id = current_user.id

    # Look for an existing subscription with the same endpoint for this user.
    result = await db.execute(
        select(PushSubscription).where(
            and_(
                PushSubscription.user_id == user_id,
                PushSubscription.endpoint == request.endpoint,
            )
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.keys = request.keys.model_dump()
        await db.commit()
        await db.refresh(existing)
        return {
            "id": str(existing.id),
            "endpoint": existing.endpoint,
            "created_at": existing.created_at.isoformat() if existing.created_at else "",
        }

    subscription = PushSubscription(
        user_id=user_id,
        endpoint=request.endpoint,
        keys=request.keys.model_dump(),
    )
    db.add(subscription)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent subscribe inserted the same endpoint first (the
        # uq_push_subscriptions_endpoint_per_user index fired). Update that
        # row instead of surfacing a 500.
        await db.rollback()
        result = await db.execute(
            select(PushSubscription).where(
                and_(
                    PushSubscription.user_id == user_id,
                    PushSubscription.endpoint == request.endpoint,
                )
            )
        )
        subscription = result.scalar_one()
        subscription.keys = request.keys.model_dump()
        await db.commit()
    await db.refresh(subscription)

    return {
        "id": str(subscription.id),
        "endpoint": subscription.endpoint,
        "created_at": subscription.created_at.isoformat() if subscription.created_at else "",
    }


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_push(
    endpoint: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a push subscription for the current user."""
    result = await db.execute(
        select(PushSubscription).where(
            and_(
                PushSubscription.user_id == current_user.id,
                PushSubscription.endpoint == endpoint,
            )
        )
    )
    subscription = result.scalar_one_or_none()

    if subscription:
        await db.delete(subscription)
        await db.commit()

    return None
