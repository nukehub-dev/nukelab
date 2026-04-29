"""
Admin dashboard API endpoints.
Provides statistics, user management, server management, and activity logs.
"""

from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.dependencies import require_permissions, PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server
from app.models.credit_transaction import CreditTransaction
from app.models.activity_log import ActivityLog
from app.services.user_service import UserService
from app.services.credit_service import CreditService

router = APIRouter()


# Request/Response Models
class BulkActionRequest(BaseModel):
    action: str  # disable, enable, delete
    user_ids: List[str]


class BulkServerActionRequest(BaseModel):
    action: str  # start, stop, delete
    server_ids: List[str]


class BulkCreditGrantRequest(BaseModel):
    user_ids: List[str]
    amount: int
    reason: str


# ========== Admin Statistics ==========

@router.get("/stats")
async def get_admin_stats(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Get admin dashboard statistics"""
    
    # User stats
    total_users_result = await db.execute(select(func.count()).select_from(User))
    total_users = total_users_result.scalar()
    
    active_users_result = await db.execute(
        select(func.count()).where(User.is_active == True)
    )
    active_users = active_users_result.scalar()
    
    disabled_users = total_users - active_users
    
    # Users by role
    role_stats = {}
    for role in ["super_admin", "admin", "moderator", "support", "user", "guest"]:
        result = await db.execute(
            select(func.count()).where(User.role == role)
        )
        role_stats[role] = result.scalar()
    
    # Server stats
    total_servers_result = await db.execute(select(func.count()).select_from(Server))
    total_servers = total_servers_result.scalar()
    
    running_servers_result = await db.execute(
        select(func.count()).where(Server.status == "running")
    )
    running_servers = running_servers_result.scalar()
    
    stopped_servers = total_servers - running_servers
    
    # Credit stats (today)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    credits_granted_result = await db.execute(
        select(func.sum(CreditTransaction.amount)).where(
            and_(
                CreditTransaction.amount > 0,
                CreditTransaction.created_at >= today_start
            )
        )
    )
    credits_granted_today = credits_granted_result.scalar() or 0
    
    credits_consumed_result = await db.execute(
        select(func.sum(CreditTransaction.amount)).where(
            and_(
                CreditTransaction.amount < 0,
                CreditTransaction.created_at >= today_start
            )
        )
    )
    credits_consumed_today = abs(credits_consumed_result.scalar() or 0)
    
    # Low credit users
    low_credit_result = await db.execute(
        select(func.count()).where(
            and_(
                User.is_active == True,
                User.nuke_balance <= 100
            )
        )
    )
    low_credit_users = low_credit_result.scalar()
    
    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "disabled": disabled_users,
            "by_role": role_stats
        },
        "servers": {
            "total": total_servers,
            "running": running_servers,
            "stopped": stopped_servers
        },
        "credits": {
            "granted_today": credits_granted_today,
            "consumed_today": credits_consumed_today,
            "low_credit_users": low_credit_users
        }
    }


# ========== User Management (Admin) ==========

@router.get("/users")
async def admin_list_users(
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """List all users with admin view"""
    service = UserService(db)
    result = await service.list_users(
        role=role,
        status=status,
        search=search,
        page=page,
        limit=limit
    )
    
    return {
        "users": [
            {
                "id": str(u.id),
                "username": u.username,
                "email": u.email,
                "full_name": u.full_name,
                "role": u.role,
                "nuke_balance": u.nuke_balance,
                "is_active": u.is_active,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in result["users"]
        ],
        "pagination": result["pagination"]
    }


@router.post("/users/bulk-action")
async def bulk_user_action(
    request: BulkActionRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Perform bulk action on users"""
    service = UserService(db)
    results = {"success": [], "failed": []}
    
    for user_id in request.user_ids:
        try:
            if request.action == "disable":
                await service.disable_user(user_id, disabled=True)
            elif request.action == "enable":
                await service.disable_user(user_id, disabled=False)
            elif request.action == "delete":
                await service.delete_user(user_id)
            else:
                raise ValueError(f"Unknown action: {request.action}")
            
            results["success"].append(user_id)
        except Exception as e:
            results["failed"].append({"user_id": user_id, "error": str(e)})
    
    return {
        "message": f"Processed {len(request.user_ids)} users",
        "action": request.action,
        "results": results
    }


# ========== Server Management (Admin) ==========

@router.get("/servers")
async def admin_list_servers(
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """List all servers (admin view)"""
    query = select(Server)
    
    if status:
        query = query.where(Server.status == status)
    
    if user_id:
        query = query.where(Server.user_id == user_id)
    
    # Count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()
    
    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit).order_by(desc(Server.created_at))
    
    result = await db.execute(query)
    servers = result.scalars().all()
    
    return {
        "servers": [
            {
                "id": str(s.id),
                "name": s.name,
                "user_id": str(s.user_id),
                "status": s.status,
                "container_id": s.container_id,
                "external_url": s.external_url,
                "allocated_cpu": s.allocated_cpu,
                "allocated_memory": s.allocated_memory,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "started_at": s.started_at.isoformat() if s.started_at else None,
            }
            for s in servers
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


@router.post("/servers/bulk-action")
async def bulk_server_action(
    request: BulkServerActionRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Perform bulk action on servers"""
    from app.docker.spawner import spawner
    
    results = {"success": [], "failed": []}
    
    for server_id in request.server_ids:
        try:
            result = await db.execute(
                select(Server).where(Server.id == server_id)
            )
            server = result.scalar_one_or_none()
            
            if not server:
                results["failed"].append({"server_id": server_id, "error": "Server not found"})
                continue
            
            if request.action == "start":
                if server.container_id:
                    await spawner.start(server.container_id)
                    server.status = "running"
            elif request.action == "stop":
                if server.container_id:
                    await spawner.stop(server.container_id)
                    server.status = "stopped"
            elif request.action == "delete":
                if server.container_id:
                    await spawner.delete(server.container_id)
                await db.delete(server)
            else:
                raise ValueError(f"Unknown action: {request.action}")
            
            await db.commit()
            results["success"].append(server_id)
        except Exception as e:
            results["failed"].append({"server_id": server_id, "error": str(e)})
    
    return {
        "message": f"Processed {len(request.server_ids)} servers",
        "action": request.action,
        "results": results
    }


# ========== Credit Management (Admin) ==========

@router.get("/credits/summary")
async def admin_credit_summary(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Get credit system summary"""
    
    # Total credits in system
    total_credits_result = await db.execute(
        select(func.sum(User.nuke_balance)).where(User.is_active == True)
    )
    total_credits = total_credits_result.scalar() or 0
    
    # Today's transactions
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    today_granted = await db.execute(
        select(func.sum(CreditTransaction.amount)).where(
            and_(
                CreditTransaction.amount > 0,
                CreditTransaction.created_at >= today_start
            )
        )
    )
    
    today_consumed = await db.execute(
        select(func.sum(CreditTransaction.amount)).where(
            and_(
                CreditTransaction.amount < 0,
                CreditTransaction.created_at >= today_start
            )
        )
    )
    
    # Top users by balance
    top_users_result = await db.execute(
        select(User).where(User.is_active == True)
        .order_by(desc(User.nuke_balance))
        .limit(10)
    )
    top_users = top_users_result.scalars().all()
    
    return {
        "total_credits_in_system": total_credits,
        "today_granted": today_granted.scalar() or 0,
        "today_consumed": abs(today_consumed.scalar() or 0),
        "top_users": [
            {
                "id": str(u.id),
                "username": u.username,
                "nuke_balance": u.nuke_balance
            }
            for u in top_users
        ]
    }


@router.post("/credits/grant-bulk")
async def bulk_grant_credits(
    request: BulkCreditGrantRequest,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    db: AsyncSession = Depends(get_db)
):
    """Grant credits to multiple users"""
    service = CreditService(db)
    results = {"success": [], "failed": []}
    
    for user_id in request.user_ids:
        try:
            await service.grant_credits(
                user_id=user_id,
                amount=request.amount,
                actor_id=str(current_user.id),
                reason=request.reason
            )
            results["success"].append(user_id)
        except Exception as e:
            results["failed"].append({"user_id": user_id, "error": str(e)})
    
    return {
        "message": f"Granted {request.amount} credits to {len(request.user_ids)} users",
        "results": results
    }


# ========== Activity Logs ==========

@router.get("/activity")
async def get_activity_logs(
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Get activity logs with filtering"""
    query = select(ActivityLog)
    
    if user_id:
        query = query.where(ActivityLog.actor_id == user_id)
    
    if action:
        query = query.where(ActivityLog.action == action)
    
    if target_type:
        query = query.where(ActivityLog.target_type == target_type)
    
    if from_date:
        query = query.where(ActivityLog.created_at >= from_date)
    
    if to_date:
        query = query.where(ActivityLog.created_at <= to_date)
    
    # Count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()
    
    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit).order_by(desc(ActivityLog.created_at))
    
    result = await db.execute(query)
    logs = result.scalars().all()
    
    return {
        "logs": [log.to_dict() for log in logs],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


# ========== System Health ==========

@router.get("/system/health")
async def admin_system_health(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Get system health status"""
    
    # Database connection check
    try:
        result = await db.execute(select(func.count()).select_from(User))
        db_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": datetime.utcnow().isoformat()
    }
