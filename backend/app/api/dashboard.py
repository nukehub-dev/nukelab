"""
Dashboard API endpoints - Aggregated data for the frontend dashboard.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import Optional

from app.api.auth import get_current_user, require_scopes
from app.core.permissions import Permission
from app.core.security import has_permission
from app.dependencies import require_permissions
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.credit_transaction import CreditTransaction
from app.models.activity_log import ActivityLog

router = APIRouter()


@router.get("/")
async def get_dashboard(
    _ = Depends(require_scopes("dashboard:read")),
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
    
    # Calculate hourly cost from running servers' plans
    hourly_cost_result = await db.execute(
        select(func.coalesce(func.sum(ServerPlan.cost_per_hour), 0))
        .select_from(Server)
        .join(ServerPlan, Server.plan_id == ServerPlan.id)
        .where(
            and_(Server.user_id == current_user.id, Server.status == "running")
        )
    )
    hourly_cost = hourly_cost_result.scalar() or 0
    
    balance = current_user.nuke_balance or 0
    estimated_hours_left = int(balance / hourly_cost) if hourly_cost > 0 else 0
    
    dashboard_data = {
        "my_servers": {
            "total": total_servers,
            "running": running_servers,
            "stopped": total_servers - running_servers,
            "pending": 0
        },
        "my_nukes": {
            "balance": balance,
            "daily_allowance": current_user.daily_allowance,
            "hourly_cost": hourly_cost,
            "estimated_hours_left": estimated_hours_left
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
    
    # Admin stats (if has admin access)
    if has_permission(current_user, Permission.ADMIN_ACCESS):
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
        
        # Total nukes
        total_nukes_query = select(func.sum(User.nuke_balance)).select_from(User)
        total_nukes_result = await db.execute(total_nukes_query)
        total_nukes = total_nukes_result.scalar() or 0
        
        dashboard_data["platform_stats"] = {
            "total_users": total_users,
            "total_servers": all_servers,
            "active_servers": active_servers,
            "total_nukes": total_nukes,
            "system_health": "healthy"  # TODO: Implement health check
        }
    
    return dashboard_data


@router.get("/activity")
async def get_activity_feed(
    limit: int = 20,
    offset: int = 0,
    _ = Depends(require_scopes("dashboard:read")),
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