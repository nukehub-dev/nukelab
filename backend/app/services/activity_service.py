"""
Activity logging service for audit trail.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from app.models.activity_log import ActivityLog


class ActivityService:
    """Activity logging business logic"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        action: str,
        target_type: str,
        target_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> ActivityLog:
        """Log an activity"""
        log = ActivityLog(
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            action=action,
            target_type=target_type,
            target_id=uuid.UUID(target_id) if target_id else None,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)

        return log

    async def get_logs(
        self,
        actor_id: Optional[str] = None,
        action: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ActivityLog]:
        """Get activity logs with filtering"""
        query = select(ActivityLog)

        if actor_id:
            query = query.where(ActivityLog.actor_id == uuid.UUID(actor_id))

        if action:
            query = query.where(ActivityLog.action == action)

        if target_type:
            query = query.where(ActivityLog.target_type == target_type)

        if target_id:
            query = query.where(ActivityLog.target_id == uuid.UUID(target_id))

        query = query.order_by(desc(ActivityLog.created_at)).offset(offset).limit(limit)

        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_user_activity(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> List[ActivityLog]:
        """Get activity for a specific user"""
        result = await self.db.execute(
            select(ActivityLog)
            .where(ActivityLog.actor_id == uuid.UUID(user_id))
            .order_by(desc(ActivityLog.created_at))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_workspace_activity(
        self, workspace_id: str, limit: int = 50, offset: int = 0
    ) -> List[ActivityLog]:
        """Get activity logs for a specific workspace"""
        result = await self.db.execute(
            select(ActivityLog)
            .where(
                and_(
                    ActivityLog.target_type == "workspace",
                    ActivityLog.target_id == uuid.UUID(workspace_id),
                )
            )
            .order_by(desc(ActivityLog.created_at))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()
