# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Admin dashboard API endpoints.
Provides statistics, user management, server management, and activity logs.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, limiter, require_jwt_auth
from app.config import settings
from app.core.cache import cache_get_or_set, cache_track_key
from app.core.permissions import Permission
from app.core.roles import ROLE_PERMISSIONS, VALID_ROLES, get_role_permissions
from app.db.session import get_db
from app.dependencies import require_permissions
from app.models.activity_log import ActivityLog
from app.models.credit_transaction import CreditTransaction
from app.models.server import Server
from app.models.user import User
from app.services.credit_service import CreditService
from app.services.notification_service import broadcast_server_status_change
from app.services.token_revocation_service import token_revocation_service
from app.services.user_service import UserService
from app.services.volume_service import VolumeService
from app.services.workspace_service import WorkspaceService

# Cache TTL for admin server lists (seconds)
_ADMIN_SERVER_LIST_CACHE_TTL = 30


def _admin_server_list_cache_key(
    page: int, limit: int, status: str | None, user_id: str | None
) -> str:
    return f"servers:list:admin:{page}:{limit}:{status or 'all'}:{user_id or 'all'}"


router = APIRouter()


# Request/Response Models
class BulkActionRequest(BaseModel):
    action: str  # disable, enable, delete
    user_ids: list[str]


class BulkServerActionRequest(BaseModel):
    action: str  # start, stop, delete
    server_ids: list[str]


class BulkCreditGrantRequest(BaseModel):
    user_ids: list[str]
    amount: int
    reason: str


# ========== Admin Statistics ==========


@router.get("/stats")
async def get_admin_stats(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get admin dashboard statistics"""

    # User stats
    total_users_result = await db.execute(select(func.count()).select_from(User))
    total_users = total_users_result.scalar()

    active_users_result = await db.execute(select(func.count()).where(User.is_active.is_(True)))
    active_users = active_users_result.scalar()

    disabled_users = total_users - active_users

    # Users by role
    result = await db.execute(select(User.role, func.count()).group_by(User.role))
    role_stats = dict(result.all())
    for role in ["super_admin", "admin", "moderator", "support", "user", "guest"]:
        role_stats.setdefault(role, 0)

    # Server stats
    total_servers_result = await db.execute(select(func.count()).select_from(Server))
    total_servers = total_servers_result.scalar()

    running_servers_result = await db.execute(
        select(func.count()).where(Server.status == "running")
    )
    running_servers = running_servers_result.scalar()

    stopped_servers = total_servers - running_servers

    # Credit stats (today)
    today_start = (
        datetime.now(UTC).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    )

    credits_granted_result = await db.execute(
        select(func.sum(CreditTransaction.amount)).where(
            and_(CreditTransaction.amount > 0, CreditTransaction.created_at >= today_start)
        )
    )
    credits_granted_today = credits_granted_result.scalar() or 0

    credits_consumed_result = await db.execute(
        select(func.sum(CreditTransaction.amount)).where(
            and_(CreditTransaction.amount < 0, CreditTransaction.created_at >= today_start)
        )
    )
    credits_consumed_today = abs(credits_consumed_result.scalar() or 0)

    # Low credit users
    low_credit_result = await db.execute(
        select(func.count()).where(and_(User.is_active.is_(True), User.nuke_balance <= 100))
    )
    low_credit_users = low_credit_result.scalar()

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "disabled": disabled_users,
            "by_role": role_stats,
        },
        "servers": {"total": total_servers, "running": running_servers, "stopped": stopped_servers},
        "credits": {
            "granted_today": credits_granted_today,
            "consumed_today": credits_consumed_today,
            "low_credit_users": low_credit_users,
        },
    }


# ========== User Management (Admin) ==========


@router.get("/users")
async def admin_list_users(
    role: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List all users with admin view"""
    service = UserService(db)
    result = await service.list_users(
        role=role, status=status, search=search, page=page, limit=limit
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
        "pagination": result["pagination"],
    }


@router.post("/users/bulk-action")
@limiter.limit("20/minute")
async def bulk_user_action(
    request: Request,
    body: BulkActionRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Perform bulk action on users (atomic batch operation)."""
    import os
    from uuid import UUID

    from app.config import settings

    results = {"success": [], "failed": []}

    # Convert and validate UUIDs
    try:
        user_uuids = [UUID(uid) for uid in body.user_ids]
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid user ID format: {e}"
        )

    # Batch fetch all users
    result = await db.execute(select(User).where(User.id.in_(user_uuids)))
    users = {str(u.id): u for u in result.scalars().all()}

    # Track missing users
    missing = set(body.user_ids) - set(users)
    for uid in missing:
        results["failed"].append({"user_id": uid, "error": "User not found"})

    deleted_users: list[User] = []

    if body.action == "delete":
        for uid, user in users.items():
            if uid in missing:
                continue
            try:
                await db.delete(user)
                results["success"].append(uid)
                deleted_users.append(user)
            except Exception as e:
                results["failed"].append({"user_id": uid, "error": str(e)})
    elif body.action in ("disable", "enable"):
        disabled = body.action == "disable"
        for uid, user in users.items():
            if uid in missing:
                continue
            try:
                user.is_active = not disabled
                security = dict(user.security or {})
                if disabled:
                    security["disabled_reason"] = None
                    security["disabled_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
                else:
                    security.pop("disabled_reason", None)
                    security.pop("disabled_at", None)
                user.security = security
                results["success"].append(uid)
            except Exception as e:
                results["failed"].append({"user_id": uid, "error": str(e)})
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown action: {body.action}"
        )

    # Single atomic commit for all successful changes
    await db.commit()

    # Clean up avatar files only after successful DB commit
    if body.action == "delete" and deleted_users:
        avatars_dir = os.path.join(settings.upload_dir, "avatars")
        if os.path.isdir(avatars_dir):
            for user in deleted_users:
                try:
                    for old_file in os.listdir(avatars_dir):
                        if old_file.startswith(str(user.id)):
                            os.remove(os.path.join(avatars_dir, old_file))
                except Exception:
                    pass

    return {
        "message": f"Processed {len(body.user_ids)} users",
        "action": body.action,
        "results": results,
    }


@router.post("/users/{username}/revoke-tokens")
async def admin_revoke_user_tokens(
    username: str,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all active access tokens for a user (admin kill-switch)."""
    service = UserService(db)
    user = await service.get_by_username(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await token_revocation_service.revoke_user_tokens(sub=user.username)

    return {
        "username": username,
        "revoked_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "message": f"All access tokens revoked for {username}",
    }


# ========== Server Management (Admin) ==========


@router.get("/servers")
async def admin_list_servers(
    status: str | None = Query(None),
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List all servers (admin view).

    Results are cached for 10 seconds to reduce DB load on the admin dashboard.
    """
    cache_key = _admin_server_list_cache_key(page, limit, status, user_id)

    async def _build_response():
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
                "total_pages": (total + limit - 1) // limit,
            },
        }

    response = await cache_get_or_set(cache_key, _build_response, _ADMIN_SERVER_LIST_CACHE_TTL)
    # Track this key so bulk invalidation can delete it without SCAN
    await cache_track_key("servers:list:admin:keys", cache_key)
    return response


@router.post("/servers/bulk-action")
@limiter.limit("20/minute")
async def bulk_server_action(
    request: Request,
    body: BulkServerActionRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Perform bulk action on servers (batch fetch, single commit)."""
    from uuid import UUID

    from app.container.spawner import spawner

    # Validate action up front
    if body.action not in ("start", "stop", "delete"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown action: {body.action}"
        )

    results = {"success": [], "failed": []}
    affected_user_ids: set[str] = set()
    status_changes: list[tuple[str, str, str]] = []  # (user_id, server_id, status)

    # Validate UUIDs
    try:
        server_uuids = [UUID(sid) for sid in body.server_ids]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid server ID format"
        )

    # Batch fetch all servers
    result = await db.execute(select(Server).where(Server.id.in_(server_uuids)))
    servers = {str(s.id): s for s in result.scalars().all()}

    # Track missing servers
    missing = set(body.server_ids) - set(servers)
    for sid in missing:
        results["failed"].append({"server_id": sid, "error": "Server not found"})

    # Process actions
    for server_id in body.server_ids:
        if server_id in missing:
            continue

        server = servers[server_id]
        try:
            if body.action == "start":
                if server.container_id:
                    await spawner.start(server.container_id)
                    server.status = "running"
                    status_changes.append((str(server.user_id), server_id, "running"))
            elif body.action == "stop":
                if server.container_id:
                    await spawner.stop(server.container_id)
                    server.status = "stopped"
                    status_changes.append((str(server.user_id), server_id, "stopped"))
            elif body.action == "delete":
                user_id = str(server.user_id)
                if server.container_id:
                    await spawner.delete(server.container_id)
                await db.delete(server)
                affected_user_ids.add(user_id)

            if body.action in ("start", "stop"):
                affected_user_ids.add(str(server.user_id))
            results["success"].append(server_id)
        except Exception as e:
            results["failed"].append({"server_id": server_id, "error": str(e)})

    # Single atomic commit for all successful DB changes
    await db.commit()

    # Broadcast status changes after successful commit
    for user_id, sid, srv_status in status_changes:
        await broadcast_server_status_change(user_id, sid, srv_status)

    # Invalidate caches for all affected users + admin lists
    from app.api.servers import _invalidate_server_list_cache

    for uid in affected_user_ids:
        await _invalidate_server_list_cache(uid)

    return {
        "message": f"Processed {len(body.server_ids)} servers",
        "action": body.action,
        "results": results,
    }


# ========== Credit Management (Admin) ==========
class UpdateSystemDailyAllowanceRequest(BaseModel):
    amount: int = Field(..., ge=0, description="System-wide default daily allowance")


@router.get("/credits/default-allowance")
async def get_system_daily_allowance(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get the system-wide default daily allowance"""
    from app.services.setting_service import SettingService

    service = SettingService(db)
    return {"default_daily_allowance": await service.get_daily_allowance()}


@router.put("/credits/default-allowance")
async def update_system_daily_allowance(
    request: UpdateSystemDailyAllowanceRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update the system-wide default daily allowance"""
    from app.services.activity_service import ActivityService
    from app.services.setting_service import SettingService

    service = SettingService(db)
    await service.set_daily_allowance(request.amount)

    activity_service = ActivityService(db)
    await activity_service.log(
        action="credits.update_system_daily_allowance",
        target_type="system",
        actor_id=str(current_user.id),
        details={"amount": request.amount},
    )

    return {"message": f"System default daily allowance updated to {request.amount}"}


class UpdateSystemMaxBalanceRequest(BaseModel):
    amount: int = Field(..., ge=0, description="System-wide max credit balance (0 = unlimited)")


@router.get("/credits/max-balance")
async def get_system_max_balance(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get the system-wide max credit balance cap"""
    from app.services.setting_service import SettingService

    service = SettingService(db)
    return {"max_balance": await service.get_max_balance()}


@router.put("/credits/max-balance")
async def update_system_max_balance(
    request: UpdateSystemMaxBalanceRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update the system-wide max credit balance cap (0 = unlimited)"""
    from app.services.activity_service import ActivityService
    from app.services.setting_service import SettingService

    service = SettingService(db)
    await service.set_max_balance(request.amount)

    activity_service = ActivityService(db)
    await activity_service.log(
        action="credits.update_system_max_balance",
        target_type="system",
        actor_id=str(current_user.id),
        details={"amount": request.amount},
    )

    return {"message": f"System max balance updated to {request.amount}"}


# ========== Default Resource Quotas (Admin) ==========
class DefaultQuotaLimitsRequest(BaseModel):
    max_cpu_total: float = Field(..., ge=0, description="Default CPU cores per user")
    max_memory_total: str = Field(..., min_length=1, description="Default memory limit (e.g. 16g)")
    max_disk_total: str = Field(..., min_length=1, description="Default disk limit (e.g. 100g)")
    max_gpu_total: int = Field(..., ge=0, description="Default GPUs per user")
    max_servers_total: int = Field(..., ge=0, description="Default servers per user")


@router.get("/quotas/default-limits")
async def get_default_quota_limits(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get the system-wide default resource quota limits applied to new users."""
    from app.services.setting_service import SettingService

    service = SettingService(db)
    return {"default_limits": await service.get_quota_defaults()}


@router.put("/quotas/default-limits")
async def update_default_quota_limits(
    request: DefaultQuotaLimitsRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update the system-wide default resource quota limits applied to new users."""
    from app.services.activity_service import ActivityService
    from app.services.setting_service import SettingService

    service = SettingService(db)
    await service.set_quota_defaults(request.model_dump())

    activity_service = ActivityService(db)
    await activity_service.log(
        action="quotas.update_default_limits",
        target_type="system",
        actor_id=str(current_user.id),
        details=request.model_dump(),
    )

    return {
        "message": "System default quota limits updated",
        "default_limits": await service.get_quota_defaults(),
    }


class BulkSetAllowanceRequest(BaseModel):
    user_ids: list[str] = Field(..., min_length=1, description="Users to update")
    amount: int = Field(..., ge=0, description="New daily allowance (NUKE / day)")


@router.post("/credits/bulk-allowance")
async def bulk_set_daily_allowance(
    body: BulkSetAllowanceRequest,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Set the daily allowance for many users at once. Requires
    CREDITS_GRANT (same permission as the single-user endpoint).
    Failures are reported per user and do not abort the batch.
    """
    from uuid import UUID

    from app.services.activity_service import ActivityService
    from app.services.user_service import UserService

    if not body.user_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No user IDs provided")

    results: dict[str, list[dict]] = {"success": [], "failed": []}

    try:
        user_uuids = [UUID(uid) for uid in body.user_ids]
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid user ID format: {e}"
        )

    result = await db.execute(select(User).where(User.id.in_(user_uuids)))
    users = {str(u.id): u for u in result.scalars().all()}

    missing = set(body.user_ids) - set(users)
    for uid in missing:
        results["failed"].append({"user_id": uid, "error": "User not found"})

    user_service = UserService(db)
    activity_service = ActivityService(db)
    actor_id = str(current_user.id)

    for uid, _user in users.items():
        try:
            updated = await user_service.update_user(
                user_id=uid,
                data={"daily_allowance": body.amount},
                updated_by=current_user,
            )
            await activity_service.log(
                action="credits.update_user_daily_allowance",
                target_type="user",
                target_id=uid,
                actor_id=actor_id,
                details={"amount": body.amount, "bulk": True},
            )
            results["success"].append({"user_id": uid, "daily_allowance": updated.daily_allowance})
        except HTTPException as e:
            results["failed"].append({"user_id": uid, "error": e.detail})
        except Exception as e:  # noqa: BLE001 — bulk must not abort on one user
            results["failed"].append({"user_id": uid, "error": str(e)})

    summary = (
        f"Bulk allowance update for {len(results['success'])}/{len(body.user_ids)} users "
        f"({len(results['failed'])} failed)"
    )
    return {"message": summary, "results": results}


@router.get("/credits/summary")
async def admin_credit_summary(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get credit system summary"""

    # Total credits in system
    total_credits_result = await db.execute(
        select(func.sum(User.nuke_balance)).where(User.is_active.is_(True))
    )
    total_credits = total_credits_result.scalar() or 0

    # Today's transactions
    today_start = (
        datetime.now(UTC).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    )

    today_granted = await db.execute(
        select(func.sum(CreditTransaction.amount)).where(
            and_(CreditTransaction.amount > 0, CreditTransaction.created_at >= today_start)
        )
    )

    today_consumed = await db.execute(
        select(func.sum(CreditTransaction.amount)).where(
            and_(CreditTransaction.amount < 0, CreditTransaction.created_at >= today_start)
        )
    )

    # Top users by balance
    top_users_result = await db.execute(
        select(User).where(User.is_active.is_(True)).order_by(desc(User.nuke_balance)).limit(10)
    )
    top_users = top_users_result.scalars().all()

    return {
        "total_credits_in_system": total_credits,
        "today_granted": today_granted.scalar() or 0,
        "today_consumed": abs(today_consumed.scalar() or 0),
        "top_users": [
            {"id": str(u.id), "username": u.username, "nuke_balance": u.nuke_balance}
            for u in top_users
        ],
    }


@router.post("/credits/grant-bulk")
async def bulk_grant_credits(
    request: BulkCreditGrantRequest,
    current_user: User = Depends(require_permissions(Permission.CREDITS_GRANT)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Grant credits to multiple users. Cap-aware: per-user results
    record the actual credited amount and a `capped` flag when the
    system max-balance cap reduced the grant. Each grant is linked to
    the credit ledger row via `transaction_id` in the activity log.
    Failures are reported per user and do not abort the batch.
    """
    from app.services.activity_service import ActivityService

    service = CreditService(db)
    activity_service = ActivityService(db)
    results: dict[str, list[dict]] = {"success": [], "failed": []}
    actor_id = str(current_user.id)

    for user_id in request.user_ids:
        try:
            tx = await service.grant_credits(
                user_id=user_id,
                amount=request.amount,
                actor_id=actor_id,
                reason=request.reason,
            )
            await activity_service.log(
                action="credits.grant",
                target_type="user",
                target_id=user_id,
                actor_id=actor_id,
                details={
                    "transaction_id": str(tx.id),
                    "requested_amount": request.amount,
                    "granted_amount": tx.amount,
                    "reason": request.reason,
                    "bulk": True,
                },
            )
            results["success"].append(
                {
                    "user_id": user_id,
                    "granted_amount": tx.amount,
                    "new_balance": tx.balance_after,
                    "capped": tx.amount != request.amount,
                }
            )
        except Exception as e:
            results["failed"].append({"user_id": user_id, "error": str(e)})

    summary = (
        f"Bulk grant to {len(results['success'])}/{len(request.user_ids)} users "
        f"({len(results['failed'])} failed)"
    )
    return {"message": summary, "results": results}


# ========== Activity Logs ==========


@router.get("/activity")
async def get_activity_logs(
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
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
            "total_pages": (total + limit - 1) // limit,
        },
    }


# ========== System Health ==========


@router.get("/system/health")
async def admin_system_health(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get system health status"""

    # Database connection check
    try:
        await db.execute(select(func.count()).select_from(User))
        db_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }


# ========== Audit Log Export ==========


@router.get("/activity/export")
async def export_activity_logs(
    format: str = Query("json", pattern="^(json|csv)$"),
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Export activity logs (admin only)"""

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
        writer.writerow(
            ["id", "actor_id", "action", "target_type", "target_id", "ip_address", "created_at"]
        )

        for log in logs:
            writer.writerow(
                [
                    str(log.id),
                    str(log.actor_id) if log.actor_id else "",
                    log.action,
                    log.target_type,
                    str(log.target_id) if log.target_id else "",
                    str(log.ip_address) if log.ip_address else "",
                    log.created_at.isoformat() if log.created_at else "",
                ]
            )

        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=activity_logs.csv"},
        )

    return {"logs": [log.to_dict() for log in logs], "count": len(logs)}


# ========== Permission Matrix ==========


@router.get("/permissions")
async def get_permission_matrix(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
):
    """Get current role-permission matrix"""
    matrix = {}
    for role in VALID_ROLES:
        matrix[role] = get_role_permissions(role)

    return {"roles": VALID_ROLES, "permissions": Permission.all_permissions(), "matrix": matrix}


class UpdateRolePermissionsRequest(BaseModel):
    permissions: list[str]


@router.put("/permissions/{role}")
async def update_role_permissions(
    role: str,
    request: UpdateRolePermissionsRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
):
    """Update permissions for a role (except super_admin which always has ALL)"""
    if role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify super_admin permissions"
        )

    if role not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {role}")

    # Validate all permissions
    all_perms = set(Permission.all_permissions())
    invalid_perms = [p for p in request.permissions if p not in all_perms and p != Permission.ALL]
    if invalid_perms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid permissions: {invalid_perms}"
        )

    # Update the role permissions in memory, rebuild the expansion cache, and persist
    ROLE_PERMISSIONS[role] = request.permissions

    from app.core.roles import _rebuild_expansion_cache

    _rebuild_expansion_cache()

    try:
        from app.core.roles import save_role_permissions_to_db

        await save_role_permissions_to_db()
    except Exception:
        pass

    return {
        "role": role,
        "permissions": request.permissions,
        "message": f"Permissions updated for role '{role}'",
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
    to_email: str | None = None


@router.get("/email-config", response_model=EmailConfigResponse)
async def get_email_config(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
):
    """Get current email/SMTP configuration (password hidden)"""
    import logging

    logger = logging.getLogger(__name__)
    logger.info(
        f"Email config request — host={settings.smtp_host!r}, port={settings.smtp_port}, user={settings.smtp_user!r}, from={settings.smtp_from!r}"
    )
    return EmailConfigResponse(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_user=settings.smtp_user,
        smtp_from=settings.smtp_from,
        smtp_from_name=settings.smtp_from_name,
        smtp_tls=settings.smtp_tls,
        smtp_verify_certs=settings.smtp_verify_certs,
        enabled=bool(settings.smtp_host),
        password_configured=bool(settings.smtp_password),
    )


@router.post("/email-test")
async def test_email(
    request: EmailTestRequest,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
):
    """Send a test email to verify SMTP configuration"""
    from app.services.email_service import EmailService

    service = EmailService()
    if not service.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SMTP is not configured. Set SMTP_HOST and other SMTP variables in your environment.",
        )

    to_email = request.to_email or current_user.email
    if not to_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No recipient email provided and current user has no email address.",
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
                <p style="margin: 4px 0 0;"><strong>Sent at:</strong> {datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
            </div>
            <p>If you received this email, your email notifications are ready to use.</p>
        </body>
        </html>
        """,
        text_body=f"SMTP Test from NukeLab\n\nHello {current_user.username},\n\nThis is a test email to verify your SMTP configuration is working.\n\nSMTP Host: {service.smtp_host}\nSMTP Port: {service.smtp_port}\nSent at: {datetime.now(UTC).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S UTC')}",
    )

    if not result["success"]:
        logger.error(f"Test email failed: {result['error']}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send test email. Please check your SMTP configuration and try again.",
        )

    logger.info(f"Test email sent successfully to {to_email}")
    return {"success": True, "message": f"Test email sent to {to_email}", "recipient": to_email}


@router.get("/email-status")
async def get_email_status(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
):
    """Check SMTP connectivity status"""
    from app.services.email_service import EmailService

    service = EmailService()
    if not service.enabled:
        return {"status": "disabled", "message": "SMTP is not configured", "configured": False}

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
            "port": service.smtp_port,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Could not connect to SMTP server: {str(e)}",
            "configured": True,
            "host": service.smtp_host,
            "port": service.smtp_port,
        }


# ========== Workspace Management (Admin) ==========


class UpdateWorkspaceRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


@router.get("/workspaces")
async def admin_list_workspaces(
    search: str | None = Query(None),
    status: str | None = Query(None),
    owner_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List all workspaces (admin view)"""
    service = WorkspaceService(db)
    result = await service.list_all_workspaces(
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        status=status,
        owner_id=owner_id,
    )

    return {
        "workspaces": result["workspaces"],
        "pagination": {
            "page": result["page"],
            "limit": result["limit"],
            "total": result["total"],
            "total_pages": (result["total"] + result["limit"] - 1) // result["limit"],
        },
    }


@router.get("/workspaces/{workspace_id}")
async def admin_get_workspace(
    workspace_id: str,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get workspace details (admin view)"""
    service = WorkspaceService(db)
    workspace = await service.get_workspace(workspace_id)

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return {
        "workspace": workspace.to_dict(),
        "members": [m.to_dict() for m in workspace.members] if workspace.members else [],
        "volumes": [v.to_dict() for v in workspace.volume_associations]
        if workspace.volume_associations
        else [],
        "invitations": [i.to_dict() for i in workspace.invitations]
        if workspace.invitations
        else [],
    }


@router.put("/workspaces/{workspace_id}")
async def admin_update_workspace(
    workspace_id: str,
    request: UpdateWorkspaceRequest,
    current_user: User = Depends(require_permissions(Permission.WORKSPACES_WRITE_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update workspace (admin)"""
    service = WorkspaceService(db)
    workspace = await service.update_workspace(
        workspace_id=workspace_id,
        name=request.name,
        description=request.description,
        is_active=request.is_active,
    )

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return {
        "success": True,
        "workspace": workspace.to_dict(),
        "message": "Workspace updated successfully",
    }


@router.delete("/workspaces/{workspace_id}")
async def admin_delete_workspace(
    workspace_id: str,
    current_user: User = Depends(require_permissions(Permission.WORKSPACES_WRITE_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Delete workspace (admin)"""
    service = WorkspaceService(db)
    workspace = await service.get_workspace(workspace_id)

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    success = await service.delete_workspace(workspace_id)

    return {"success": success, "message": "Workspace deleted successfully"}


@router.get("/workspaces/{workspace_id}/members")
async def admin_list_workspace_members(
    workspace_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    role: str | None = Query(None),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List workspace members (admin view)"""
    service = WorkspaceService(db)
    result = await service.list_workspace_members(
        workspace_id=workspace_id,
        page=page,
        limit=limit,
        search=search,
        role=role,
    )

    return {
        "members": result["members"],
        "pagination": {
            "page": result["page"],
            "limit": result["limit"],
            "total": result["total"],
            "total_pages": (result["total"] + result["limit"] - 1) // result["limit"],
        },
    }


@router.get("/workspaces/{workspace_id}/volumes")
async def admin_list_workspace_volumes(
    workspace_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List workspace volumes (admin view)"""
    service = WorkspaceService(db)
    result = await service.list_workspace_volumes(
        workspace_id=workspace_id,
        page=page,
        limit=limit,
        search=search,
    )

    return {
        "volumes": result["volumes"],
        "pagination": {
            "page": result["page"],
            "limit": result["limit"],
            "total": result["total"],
            "total_pages": (result["total"] + result["limit"] - 1) // result["limit"],
        },
    }


# ========== Volume Management (Admin) ==========


class UpdateVolumeRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    visibility: str | None = None
    status: str | None = None
    max_size_bytes: int | None = None


@router.get("/volumes")
async def admin_list_volumes(
    search: str | None = Query(None),
    status: str | None = Query(None),
    visibility: str | None = Query(None),
    owner_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """List all volumes (admin view)"""
    service = VolumeService(db)
    result = await service.list_all_volumes(
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        status=status,
        visibility=visibility,
        owner_id=owner_id,
    )

    return {
        "volumes": result["volumes"],
        "pagination": {
            "page": result["page"],
            "limit": result["limit"],
            "total": result["total"],
            "total_pages": (result["total"] + result["limit"] - 1) // result["limit"],
        },
    }


@router.get("/volumes/{volume_id}")
async def admin_get_volume(
    volume_id: str,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get volume details (admin view)"""
    service = VolumeService(db)
    volume = await service.get_volume(volume_id)

    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    return {
        "volume": volume.to_dict(),
    }


@router.put("/volumes/{volume_id}")
async def admin_update_volume(
    volume_id: str,
    request: UpdateVolumeRequest,
    current_user: User = Depends(require_permissions(Permission.VOLUMES_WRITE_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update volume (admin)"""
    service = VolumeService(db)
    volume = await service.get_volume(volume_id)
    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    # Validate max_size_bytes cannot be set below current size
    try:
        service.validate_max_size(volume, request.max_size_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    volume = await service.update_volume(
        volume_id=volume_id,
        display_name=request.display_name,
        description=request.description,
        visibility=request.visibility,
        status=request.status,
        max_size_bytes=request.max_size_bytes,
    )

    return {"success": True, "volume": volume.to_dict(), "message": "Volume updated successfully"}


@router.delete("/volumes/{volume_id}")
async def admin_delete_volume(
    volume_id: str,
    current_user: User = Depends(require_permissions(Permission.VOLUMES_WRITE_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Delete volume (admin)"""
    service = VolumeService(db)
    volume = await service.get_volume(volume_id)

    if not volume:
        raise HTTPException(status_code=404, detail="Volume not found")

    try:
        success = await service.delete_volume(volume_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"success": success, "message": "Volume deleted successfully"}


# ========== Retention Policy Management ==========

import contextlib

from app.services.retention_service import RetentionService


@router.get("/retention")
async def get_retention_policy(
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Get current data retention policy."""
    service = RetentionService(db)
    policy = await service.get_policy()
    return {"retention_policy": policy}


@router.put("/retention")
async def update_retention_policy(
    request: dict,
    current_user: User = Depends(require_permissions(Permission.ADMIN_ACCESS)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Update data retention policy."""
    service = RetentionService(db)
    try:
        policy = await service.set_policy(request)
        return {"retention_policy": policy, "success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========== Workspace Bulk Actions ==========


class BulkWorkspaceActionRequest(BaseModel):
    action: str  # delete, activate, deactivate
    workspace_ids: list[str]


@router.post("/workspaces/bulk-action")
@limiter.limit("20/minute")
async def bulk_workspace_action(
    request: Request,
    body: BulkWorkspaceActionRequest,
    current_user: User = Depends(require_permissions(Permission.WORKSPACES_WRITE_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Perform bulk action on workspaces."""
    valid_actions = ["delete", "activate", "deactivate"]
    if body.action not in valid_actions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action. Must be one of: {', '.join(valid_actions)}",
        )

    workspace_service = WorkspaceService(db)
    results = {"success": [], "failed": []}

    for workspace_id in body.workspace_ids:
        try:
            if body.action == "delete":
                await workspace_service.delete_workspace(workspace_id)
            elif body.action == "activate":
                await workspace_service.update_workspace(workspace_id, is_active=True)
            elif body.action == "deactivate":
                await workspace_service.update_workspace(workspace_id, is_active=False)

            results["success"].append(workspace_id)
        except Exception as e:
            results["failed"].append({"workspace_id": workspace_id, "error": str(e)})

    return {
        "message": f"Processed {len(body.workspace_ids)} workspaces",
        "action": body.action,
        "results": results,
    }


# ========== Volume Bulk Actions ==========


class BulkVolumeActionRequest(BaseModel):
    action: str  # delete, archive, activate
    volume_ids: list[str]


@router.post("/volumes/bulk-action")
@limiter.limit("20/minute")
async def bulk_volume_action(
    request: Request,
    body: BulkVolumeActionRequest,
    current_user: User = Depends(require_permissions(Permission.VOLUMES_WRITE_ALL)),
    _jwt=Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
):
    """Perform bulk action on volumes."""
    valid_actions = ["delete", "archive", "activate"]
    if body.action not in valid_actions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action. Must be one of: {', '.join(valid_actions)}",
        )

    volume_service = VolumeService(db)
    results = {"success": [], "failed": []}

    for volume_id in body.volume_ids:
        try:
            if body.action == "delete":
                await volume_service.delete_volume(volume_id)
            elif body.action == "archive":
                await volume_service.update_volume(volume_id, status="archived")
            elif body.action == "activate":
                await volume_service.update_volume(volume_id, status="active")

            results["success"].append(volume_id)
        except Exception as e:
            results["failed"].append({"volume_id": volume_id, "error": str(e)})

    return {
        "message": f"Processed {len(body.volume_ids)} volumes",
        "action": body.action,
        "results": results,
    }


# ========== Health Monitoring ==========


class HealthMonitoringResponse(BaseModel):
    system: dict
    containers: dict
    recent_restarts: list


@router.get("/health/monitoring")
async def get_health_monitoring(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.ADMIN_ACCESS)),
    db: AsyncSession = Depends(get_db),
):
    """Get comprehensive health monitoring data for admin dashboard.

    Production-ready:
    - Only queries currently RUNNING servers (not stale stopped records)
    - Paginated container health checks
    - Server-side filtering by status and search term
    - Composite index on (server_id, checked_at) for fast latest-check lookups
    """
    import time

    import psutil
    import redis.asyncio as redis
    from sqlalchemy import or_
    from sqlalchemy import text as sa_text

    from app.config import settings
    from app.container.client import container_client
    from app.models.health_check import HealthCheck
    from app.models.user import User as UserModel
    from app.services.email_service import EmailService

    # ------------------------------------------------------------------
    # System health (fast, always computed)
    # ------------------------------------------------------------------
    health_data = {"status": "healthy", "timestamp": time.time(), "services": {}, "resources": {}}

    # Database check
    try:
        start = time.time()
        await db.execute(sa_text("SELECT 1"))
        db_latency = (time.time() - start) * 1000
        health_data["services"]["database"] = {
            "status": "healthy",
            "latency_ms": round(db_latency, 2),
        }
    except Exception as e:
        health_data["services"]["database"] = {"status": "unhealthy", "error": str(e)}
        health_data["status"] = "degraded"

    # Redis check
    try:
        start = time.time()
        redis_client = redis.from_url(settings.redis_url)
        await redis_client.ping()
        redis_latency = (time.time() - start) * 1000
        await redis_client.aclose()
        health_data["services"]["redis"] = {
            "status": "healthy",
            "latency_ms": round(redis_latency, 2),
        }
    except Exception as e:
        health_data["services"]["redis"] = {"status": "unhealthy", "error": str(e)}
        health_data["status"] = "degraded"

    # Container runtime check
    try:
        await container_client.connect()
        version = await container_client.version()
        runtime_name = "Containers"
        components = version.get("Components", [])
        if components and isinstance(components, list):
            runtime_name = components[0].get("Name", "Containers").replace(" Engine", "")
        health_data["services"]["containers"] = {
            "status": "healthy",
            "version": version.get("Version", "unknown"),
            "runtime": runtime_name,
        }
    except Exception as e:
        health_data["services"]["containers"] = {"status": "unhealthy", "error": str(e)}
        health_data["status"] = "degraded"

    # SMTP check
    try:
        email_service = EmailService()
        if email_service.enabled:
            import aiosmtplib

            smtp = aiosmtplib.SMTP(
                hostname=email_service.smtp_host,
                port=email_service.smtp_port,
                timeout=3,
                start_tls=False,
                validate_certs=email_service.verify_certs,
            )
            await smtp.connect()
            if email_service.use_tls:
                await smtp.starttls(validate_certs=email_service.verify_certs)
            await smtp.quit()
            health_data["services"]["smtp"] = {
                "status": "healthy",
                "host": email_service.smtp_host,
                "port": email_service.smtp_port,
            }
        else:
            health_data["services"]["smtp"] = {
                "status": "disabled",
                "message": "SMTP not configured",
            }
    except Exception as e:
        health_data["services"]["smtp"] = {"status": "unhealthy", "error": str(e)}
        health_data["status"] = "degraded"

    # Partition check
    try:
        from app.db.partitioning import PartitionManager

        pm = PartitionManager(db)
        issues = []
        for table in pm.PARTITION_CONFIG:
            parts = await pm.list_partitions(table)
            month_parts = [p for p in parts if "_default" not in p["partition_name"]]
            if not month_parts:
                issues.append(f"{table}: no monthly partitions")
        if issues:
            health_data["services"]["partitions"] = {
                "status": "unhealthy",
                "error": "; ".join(issues),
            }
            health_data["status"] = "degraded"
        else:
            health_data["services"]["partitions"] = {
                "status": "healthy",
                "message": f"{len(pm.PARTITION_CONFIG)} tables OK",
            }
    except Exception as e:
        health_data["services"]["partitions"] = {"status": "unhealthy", "error": str(e)}
        health_data["status"] = "degraded"

    # System resources
    try:

        def get_disk_info(path: str):
            usage = psutil.disk_usage(path)
            return {
                "path": path,
                "percent": usage.percent,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
            }

        disk_info = get_disk_info("/")
        container_disk_info = None
        if settings.volume_storage_path:
            with contextlib.suppress(Exception):
                container_disk_info = get_disk_info(settings.volume_storage_path)

        fs_type = None
        try:
            for part in psutil.disk_partitions(all=False):
                if part.mountpoint == "/":
                    fs_type = part.fstype
                    break
        except Exception:
            pass

        # CPU details
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        cpu_count_logical = psutil.cpu_count(logical=True)

        # Memory details
        mem = psutil.virtual_memory()

        health_data["resources"] = {
            "cpu": {
                "percent": psutil.cpu_percent(interval=0.1),
                "count": cpu_count,
                "count_logical": cpu_count_logical,
                "freq_mhz": round(cpu_freq.current, 0) if cpu_freq else None,
            },
            "memory": {
                "percent": mem.percent,
                "total_bytes": mem.total,
                "available_bytes": mem.available,
                "used_bytes": mem.used,
            },
            "disk": {**disk_info, "fstype": fs_type},
            "load_average": psutil.getloadavg(),
        }
        if container_disk_info:
            container_fs_type = None
            try:
                for part in psutil.disk_partitions(all=False):
                    if part.mountpoint == settings.volume_storage_path:
                        container_fs_type = part.fstype
                        break
            except Exception:
                pass
            health_data["resources"]["container_disk"] = {
                **container_disk_info,
                "fstype": container_fs_type,
            }
    except Exception:
        health_data["resources"] = {
            "cpu": {"percent": 0, "count": 0, "count_logical": 0, "freq_mhz": None},
            "memory": {"percent": 0, "total_bytes": 0, "available_bytes": 0, "used_bytes": 0},
            "disk": {
                "path": "/",
                "percent": 0,
                "total_bytes": 0,
                "used_bytes": 0,
                "free_bytes": 0,
                "fstype": None,
            },
            "load_average": (0, 0, 0),
        }

    # ------------------------------------------------------------------
    # Container health — PRODUCTION: only RUNNING servers, paginated
    # ------------------------------------------------------------------
    offset = (page - 1) * limit
    recent = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)

    # Build the base server query — only RUNNING servers
    server_base = (
        select(Server.id)
        .join(UserModel, Server.user_id == UserModel.id)
        .where(Server.status == "running")
    )

    # Apply search filter
    if search:
        pattern = f"%{search}%"
        server_base = server_base.where(
            or_(Server.name.ilike(pattern), UserModel.username.ilike(pattern))
        )

    # Get total count of running servers matching filters
    total_result = await db.execute(select(func.count()).select_from(server_base.subquery()))
    total_running = total_result.scalar() or 0

    # Get paginated server IDs
    server_ids_result = await db.execute(
        server_base.order_by(Server.name).limit(limit).offset(offset)
    )
    server_ids = [row[0] for row in server_ids_result.all()]

    # Get latest health check for ONLY the servers on this page
    latest_checks = []
    if server_ids:
        subq = (
            select(HealthCheck.server_id, func.max(HealthCheck.checked_at).label("latest_check"))
            .where(HealthCheck.server_id.in_(server_ids))
            .group_by(HealthCheck.server_id)
            .subquery()
        )

        checks_query = (
            select(HealthCheck, Server, UserModel)
            .join(Server, HealthCheck.server_id == Server.id)
            .join(UserModel, Server.user_id == UserModel.id)
            .join(
                subq,
                and_(
                    HealthCheck.server_id == subq.c.server_id,
                    HealthCheck.checked_at == subq.c.latest_check,
                ),
            )
            .where(Server.id.in_(server_ids))
        )

        # Apply status filter to health checks
        if status_filter:
            checks_query = checks_query.where(HealthCheck.status == status_filter)

        checks_query = checks_query.order_by(Server.name)
        checks_result = await db.execute(checks_query)

        for hc, server, user_obj in checks_result.all():
            latest_checks.append(
                {
                    "id": str(hc.id),
                    "server_id": str(hc.server_id),
                    "server_name": server.name,
                    "username": user_obj.username if user_obj else "unknown",
                    "container_id": hc.container_id,
                    "status": hc.status,
                    "exit_code": hc.exit_code,
                    "output": hc.output,
                    "consecutive_failures": hc.consecutive_failures,
                    "last_success_at": hc.last_success_at.isoformat()
                    if hc.last_success_at
                    else None,
                    "checked_at": hc.checked_at.isoformat() if hc.checked_at else None,
                }
            )

    # Summary counts — count ALL running servers by their latest health status
    # Uses a window function to get the latest check per server entirely in SQL
    status_counts = {}
    unhealthy_count = 0
    unknown_count = 0
    restarting_count = 0
    restart_failed_count = 0

    # Pure SQL approach — no Python round-trip of server IDs
    latest_check_subq = (
        select(
            HealthCheck.server_id,
            HealthCheck.status,
            func.row_number()
            .over(partition_by=HealthCheck.server_id, order_by=desc(HealthCheck.checked_at))
            .label("rn"),
        )
        .join(Server, HealthCheck.server_id == Server.id)
        .where(Server.status == "running", HealthCheck.checked_at >= recent)
        .subquery()
    )

    summary_result = await db.execute(
        select(latest_check_subq.c.status, func.count())
        .where(latest_check_subq.c.rn == 1)
        .group_by(latest_check_subq.c.status)
    )
    status_counts = dict(summary_result.all())
    unhealthy_count = status_counts.get("unhealthy", 0)
    unknown_count = status_counts.get("unknown", 0)
    restarting_count = status_counts.get("restarting", 0)
    restart_failed_count = status_counts.get("restart_failed", 0)

    container_data = {
        "status_counts": status_counts,
        "latest_checks": latest_checks,
        "unhealthy_count": unhealthy_count,
        "unknown_count": unknown_count,
        "restarting_count": restarting_count,
        "restart_failed_count": restart_failed_count,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_running,
            "total_pages": (total_running + limit - 1) // limit,
        },
    }

    # ------------------------------------------------------------------
    # Recent auto-restart events (always limited to 50, no pagination)
    # ------------------------------------------------------------------
    restart_window = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
    restart_result = await db.execute(
        select(HealthCheck, Server, UserModel)
        .join(Server, HealthCheck.server_id == Server.id)
        .join(UserModel, Server.user_id == UserModel.id)
        .where(
            HealthCheck.status.in_(["restarting", "restart_failed"]),
            HealthCheck.checked_at >= restart_window,
        )
        .order_by(desc(HealthCheck.checked_at))
        .limit(50)
    )
    restart_events = restart_result.all()

    recent_restarts = []
    for hc, server, user_obj in restart_events:
        recent_restarts.append(
            {
                "id": str(hc.id),
                "server_id": str(hc.server_id),
                "server_name": server.name,
                "username": user_obj.username if user_obj else "unknown",
                "status": hc.status,
                "output": hc.output,
                "checked_at": hc.checked_at.isoformat() if hc.checked_at else None,
            }
        )

    return {
        "system": health_data,
        "containers": container_data,
        "recent_restarts": recent_restarts,
    }
