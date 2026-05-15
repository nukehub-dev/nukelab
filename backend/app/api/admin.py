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
from app.core.roles import ROLE_PERMISSIONS, get_role_permissions, VALID_ROLES
from app.config import settings

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


# ========== Audit Log Export ==========

@router.get("/activity/export")
async def export_activity_logs(
    format: str = Query("json", regex="^(json|csv)$"),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db)
):
    """Export activity logs (admin only)"""
    from app.api.auth import get_current_user
    
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
    
    query = query.order_by(desc(ActivityLog.created_at)).limit(limit)
    
    result = await db.execute(query)
    logs = result.scalars().all()
    
    if format == "csv":
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "actor_id", "action", "target_type", "target_id", "ip_address", "created_at"])
        
        for log in logs:
            writer.writerow([
                str(log.id),
                str(log.actor_id) if log.actor_id else "",
                log.action,
                log.target_type,
                str(log.target_id) if log.target_id else "",
                str(log.ip_address) if log.ip_address else "",
                log.created_at.isoformat() if log.created_at else ""
            ])
        
        from fastapi.responses import StreamingResponse
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=activity_logs.csv"}
        )
    
    return {
        "logs": [log.to_dict() for log in logs],
        "count": len(logs)
    }


# ========== Permission Matrix ==========

@router.get("/permissions")
async def get_permission_matrix(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS))
):
    """Get current role-permission matrix"""
    matrix = {}
    for role in VALID_ROLES:
        matrix[role] = get_role_permissions(role)
    
    return {
        "roles": VALID_ROLES,
        "permissions": Permission.all_permissions(),
        "matrix": matrix
    }


class UpdateRolePermissionsRequest(BaseModel):
    permissions: List[str]


@router.put("/permissions/{role}")
async def update_role_permissions(
    role: str,
    request: UpdateRolePermissionsRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS))
):
    """Update permissions for a role (except super_admin which always has ALL)"""
    if role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify super_admin permissions"
        )
    
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {role}"
        )
    
    # Validate all permissions
    all_perms = set(Permission.all_permissions())
    invalid_perms = [p for p in request.permissions if p not in all_perms and p != Permission.ALL]
    if invalid_perms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid permissions: {invalid_perms}"
        )
    
    # Update the role permissions in memory
    # Note: In a production system, this should persist to database
    ROLE_PERMISSIONS[role] = request.permissions
    
    return {
        "role": role,
        "permissions": request.permissions,
        "message": f"Permissions updated for role '{role}'"
    }


# ========== Email Configuration ==========

class EmailConfigResponse(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_from: str
    smtp_from_name: str
    smtp_tls: bool
    smtp_verify_certs: bool
    enabled: bool
    password_configured: bool


class EmailTestRequest(BaseModel):
    to_email: Optional[str] = None


@router.get("/email-config", response_model=EmailConfigResponse)
async def get_email_config(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS))
):
    """Get current email/SMTP configuration (password hidden)"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Email config request — host={settings.smtp_host!r}, port={settings.smtp_port}, user={settings.smtp_user!r}, from={settings.smtp_from!r}")
    return EmailConfigResponse(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=settings.smtp_user,
        smtp_from=settings.smtp_from,
        smtp_from_name=settings.smtp_from_name,
        smtp_tls=settings.smtp_tls,
        smtp_verify_certs=settings.smtp_verify_certs,
        enabled=bool(settings.smtp_host),
        password_configured=bool(settings.smtp_password)
    )


@router.post("/email-test")
async def test_email(
    request: EmailTestRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS))
):
    """Send a test email to verify SMTP configuration"""
    from app.services.email_service import EmailService

    service = EmailService()
    if not service.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SMTP is not configured. Set SMTP_HOST and other SMTP variables in your environment."
        )

    to_email = request.to_email or current_user.email
    if not to_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No recipient email provided and current user has no email address."
        )

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Sending test email to {to_email} via {service.smtp_host}:{service.smtp_port}")

    result = await service.send_email(
        to_email=to_email,
        subject="NukeLab SMTP Test",
        html_body=f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #4F46E5;">SMTP Test Successful</h2>
            <p>Hello {current_user.username},</p>
            <p>This is a test email from <strong>NukeLab</strong> to verify that your SMTP configuration is working correctly.</p>
            <div style="background: #f3f4f6; padding: 16px; border-radius: 8px; margin: 16px 0;">
                <p style="margin: 0;"><strong>SMTP Host:</strong> {service.smtp_host}</p>
                <p style="margin: 4px 0 0;"><strong>SMTP Port:</strong> {service.smtp_port}</p>
                <p style="margin: 4px 0 0;"><strong>Sent at:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            </div>
            <p>If you received this email, your email notifications are ready to use.</p>
        </body>
        </html>
        """,
        text_body=f"SMTP Test from NukeLab\n\nHello {current_user.username},\n\nThis is a test email to verify your SMTP configuration is working.\n\nSMTP Host: {service.smtp_host}\nSMTP Port: {service.smtp_port}\nSent at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )

    if not result["success"]:
        logger.error(f"Test email failed: {result['error']}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send test email: {result['error']}"
        )

    logger.info(f"Test email sent successfully to {to_email}")
    return {
        "success": True,
        "message": f"Test email sent to {to_email}",
        "recipient": to_email
    }


@router.get("/email-status")
async def get_email_status(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS))
):
    """Check SMTP connectivity status"""
    from app.services.email_service import EmailService

    service = EmailService()
    if not service.enabled:
        return {
            "status": "disabled",
            "message": "SMTP is not configured",
            "configured": False
        }

    # Try to connect to SMTP server without sending
    try:
        import aiosmtplib
        # Disable auto-TLS so we control it explicitly (avoid "already using TLS" on port 587)
        smtp = aiosmtplib.SMTP(
            hostname=service.smtp_host,
            port=service.smtp_port,
            timeout=5,
            start_tls=False,
            validate_certs=service.verify_certs,
        )
        await smtp.connect()
        if service.use_tls:
            await smtp.starttls(validate_certs=service.verify_certs)
        if service.smtp_user and service.smtp_password:
            await smtp.login(service.smtp_user, service.smtp_password)
        await smtp.quit()
        return {
            "status": "connected",
            "message": f"Successfully connected to {service.smtp_host}:{service.smtp_port}",
            "configured": True,
            "host": service.smtp_host,
            "port": service.smtp_port
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Could not connect to SMTP server: {str(e)}",
            "configured": True,
            "host": service.smtp_host,
            "port": service.smtp_port
        }
