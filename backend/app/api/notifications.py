"""
Notifications API endpoints.
"""

from typing import Optional, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from datetime import datetime

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.notification import Notification

router = APIRouter()


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    message: str
    severity: str
    read: bool
    read_at: Optional[str]
    action_url: Optional[str]
    extra_data: dict
    created_at: str


class NotificationListResponse(BaseModel):
    notifications: List[NotificationResponse]
    unread_count: int
    total: int
    page: int
    page_size: int


class MarkReadRequest(BaseModel):
    notification_ids: List[str]


def serialize_notification(notification: Notification) -> dict:
    return {
        "id": str(notification.id),
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "severity": notification.severity,
        "read": notification.read,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "action_url": notification.action_url,
        "extra_data": notification.extra_data or {},
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }


@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    unread_only: bool = Query(False, description="Only unread notifications"),
    type: Optional[str] = Query(None, description="Filter by type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current user's notifications"""
    
    # Build query
    query = select(Notification).where(Notification.user_id == current_user.id)
    
    if unread_only:
        query = query.where(Notification.read == False)
    
    if type:
        query = query.where(Notification.type == type)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Get unread count
    unread_query = select(func.count()).where(
        and_(Notification.user_id == current_user.id, Notification.read == False)
    )
    unread_result = await db.execute(unread_query)
    unread_count = unread_result.scalar()
    
    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(Notification.created_at.desc()).offset(offset).limit(page_size)
    
    result = await db.execute(query)
    notifications = result.scalars().all()
    
    return {
        "notifications": [serialize_notification(n) for n in notifications],
        "unread_count": unread_count,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/unread-count")
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get unread notification count"""
    query = select(func.count()).where(
        and_(Notification.user_id == current_user.id, Notification.read == False)
    )
    result = await db.execute(query)
    count = result.scalar()
    
    return {"unread_count": count}


@router.put("/{notification_id}/read")
async def mark_as_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a notification as read"""
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.id == notification_id,
                Notification.user_id == current_user.id
            )
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notification.read = True
    notification.read_at = datetime.utcnow()
    await db.commit()
    
    return serialize_notification(notification)


@router.put("/read-all")
async def mark_all_as_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all notifications as read"""
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.user_id == current_user.id,
                Notification.read == False
            )
        )
    )
    notifications = result.scalars().all()
    
    now = datetime.utcnow()
    for notification in notifications:
        notification.read = True
        notification.read_at = now
    
    await db.commit()
    
    return {"message": f"Marked {len(notifications)} notifications as read"}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a notification"""
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.id == notification_id,
                Notification.user_id == current_user.id
            )
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    await db.delete(notification)
    await db.commit()
    
    return None


# Admin endpoint to create notifications
@router.post("/", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def create_notification(
    user_id: str,
    type: str,
    title: str,
    message: str,
    severity: str = "info",
    action_url: Optional[str] = None,
    extra_data: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a notification for a user (Admin only)"""
    from app.dependencies import PermissionChecker
    from app.core.permissions import Permission
    
    checker = PermissionChecker(current_user)
    checker.require(Permission.ADMIN_ACCESS)
    
    import uuid
    notification = Notification(
        user_id=uuid.UUID(user_id),
        type=type,
        title=title,
        message=message,
        severity=severity,
        action_url=action_url,
        extra_data=extra_data or {}
    )
    
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    
    return serialize_notification(notification)