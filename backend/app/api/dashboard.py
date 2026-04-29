"""
Dashboard API endpoints - Aggregated data for the frontend dashboard.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import Optional

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.dependencies import require_permissions
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server
from app.models.credit_transaction import CreditTransaction
from app.models.activity_log import ActivityLog

router = APIRouter()


@router.get("/")
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get dashboard data for current user"""
    
    # User stats
    server_count_query = select(func.count()).where(Server.user_id == current_user.id)
    server_count_result = await db.execute(server_count_query)
    total_servers = server_count_result.scalar()
    
    running_servers_query = select(func.count()).where(
        and_(Server.user_id == current_user.id, Server.status == "running")
    )
    running_result = await db.execute(running_servers_query)
    running_servers = running_result.scalar()
    
    # Recent activity
    activity_query = select(ActivityLog).where(
        ActivityLog.actor_id == current_user.id
    ).order_by(ActivityLog.created_at.desc()).limit(10)
    activity_result = await db.execute(activity_query)
    recent_activity = activity_result.scalars().all()
    
    dashboard_data = {
        "my_servers": {
            "total": total_servers,
            "running": running_servers,
            "stopped": total_servers - running_servers,
            "pending": 0  # TODO: Add pending status count
        },
        "my_credits": {
            "balance": current_user.credit_balance,
            "daily_allowance": current_user.daily_allowance,
            "hourly_cost": 0,  # TODO: Calculate from active servers
            "estimated_hours_left": 0  # TODO: Calculate
        },
        "recent_activity": [
            {
                "id": str(a.id),
                "action": a.action,
                "target_type": a.target_type,
                "target_id": str(a.target_id) if a.target_id else None,
                "timestamp": a.created_at.isoformat() if a.created_at else None,
            }
            for a in recent_activity
        ]
    }
    
    # Admin stats (if admin)
    if current_user.role in ["admin", "super_admin"]:
        # Total users
        total_users_query = select(func.count()).select_from(User)
        total_users_result = await db.execute(total_users_query)
        total_users = total_users_result.scalar()
        
        # Total servers across all users
        all_servers_query = select(func.count()).select_from(Server)
        all_servers_result = await db.execute(all_servers_query)
        all_servers = all_servers_result.scalar()
        
        active_servers_query = select(func.count()).where(Server.status == "running")
        active_servers_result = await db.execute(active_servers_query)
        active_servers = active_servers_result.scalar()
        
        # Total credits
        total_credits_query = select(func.sum(User.credit_balance)).select_from(User)
        total_credits_result = await db.execute(total_credits_query)
        total_credits = total_credits_result.scalar() or 0
        
        dashboard_data["platform_stats"] = {
            "total_users": total_users,
            "total_servers": all_servers,
            "active_servers": active_servers,
            "total_credits": total_credits,
            "system_health": "healthy"  # TODO: Implement health check
        }
    
    return dashboard_data


@router.get("/activity")
async def get_activity_feed(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get activity feed"""
    
    query = select(ActivityLog).order_by(ActivityLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    activities = result.scalars().all()
    
    return {
        "activities": [
            {
                "id": str(a.id),
                "actor_id": str(a.actor_id) if a.actor_id else None,
                "action": a.action,
                "target_type": a.target_type,
                "target_id": str(a.target_id) if a.target_id else None,
                "timestamp": a.created_at.isoformat() if a.created_at else None,
                "details": a.details or {}
            }
            for a in activities
        ],
        "has_more": len(activities) == limit
    }