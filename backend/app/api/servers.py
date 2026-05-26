"""
Server API endpoints with RBAC and ownership enforcement.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from app.config import settings
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.api.auth import get_current_user, limiter
from app.core.permissions import Permission
from app.core.security import has_any_permission
from app.dependencies import PermissionChecker, require_permissions
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server
from app.container.spawner import spawner
import aiodocker
from app.services.notification_service import NotificationService, broadcast_server_status_change
from app.services.activity_service import ActivityService

logger = logging.getLogger(__name__)

router = APIRouter()


class VolumeMountRequest(BaseModel):
    volume_id: str
    mount_path: str = "/data"
    mode: str = "read_write"  # read_write, read_only
    max_size_bytes: Optional[int] = None  # For auto-created volumes when volume_id is empty


# Docker-compatible name pattern used for container and volume names
_SERVER_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')

class ServerCreateRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$',
        description="Server name must start with alphanumeric and contain only letters, numbers, underscores, and hyphens",
    )
    plan_id: str
    environment_id: str
    volume_id: Optional[str] = None  # Deprecated: use volume_mounts
    volume_mode: Optional[str] = "read_write"  # Deprecated: use volume_mounts
    volume_mounts: Optional[list[VolumeMountRequest]] = None


class ServerUpdateRequest(BaseModel):
    name: Optional[str] = None
    plan_id: Optional[str] = None
    environment_id: Optional[str] = None
    volume_mounts: Optional[list[VolumeMountRequest]] = None
    reason: Optional[str] = None


class ReasonRequest(BaseModel):
    reason: Optional[str] = None


class ServerResponse(BaseModel):
    id: str
    name: str
    status: str
    container_id: str | None = None
    volume_id: str | None = None
    volume_mode: str | None = None
    volume_mounts: list[dict] | None = None
    external_url: str | None = None
    allocated_cpu: float | None = None
    allocated_memory: str | None = None
    allocated_disk: str | None = None
    health_status: str | None = None
    status_reason: str | None = None
    user_id: str | None = None
    username: str | None = None
    plan_id: str | None = None
    environment_id: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None


async def get_server_with_permission_check(
    server_id: str,
    current_user: User,
    db: AsyncSession,
    request: Request,
    require_ownership: bool = True,
    admin_permissions: list[str] | None = None
) -> Server:
    """
    Get server and check permissions.
    Admins can access any server via JWT only, users can only access their own.
    API tokens cannot be used for cross-user server access.
    
    admin_permissions: list of permissions that grant cross-user access.
        Defaults to [SERVERS_ACCESS_OTHERS].
        For read operations, use [SERVERS_READ_ALL, SERVERS_ACCESS_OTHERS].
        For write operations, use [SERVERS_WRITE_ALL, SERVERS_ACCESS_OTHERS].
    """
    result = await db.execute(
        select(Server).where(Server.id == server_id)
    )
    server = result.scalar_one_or_none()
    
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    if require_ownership and str(server.user_id) != str(current_user.id):
        # Cross-user access requires JWT authentication — API tokens are not allowed
        auth_context = getattr(request.state, "auth_context", None)
        if not auth_context or auth_context.auth_method != "jwt":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-user server access requires JWT authentication. Please log in via the web interface."
            )
        checker = PermissionChecker(current_user)
        perms_to_check = admin_permissions or [Permission.SERVERS_ACCESS_OTHERS]
        checker.require_any(perms_to_check)
    
    return server


async def _audit_cross_user_access(
    server: Server,
    current_user: User,
    db: AsyncSession,
    action: str,
    reason: Optional[str] = None
):
    """Log audit trail and notify owner when admin accesses another user's server.
    Raises 400 if reason is not provided for cross-user access."""
    if str(server.user_id) == str(current_user.id):
        return
    
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A reason is required for cross-user server access"
        )
    
    activity_service = ActivityService(db)
    await activity_service.log(
        action=action,
        target_type="server",
        target_id=str(server.id),
        actor_id=str(current_user.id),
        details={"reason": reason, "server_name": server.name},
    )
    
    notif_service = NotificationService(db)
    await notif_service.create(
        user_id=server.user_id,
        title="Server Accessed",
        message=f"{current_user.username or 'An admin'} accessed your server '{server.name}' with reason: {reason or 'No reason provided'}",
        type="server",
        severity="warning",
        action_url=f"/servers/{server.id}",
        event_key="server_accessed",
    )


async def _load_server_volume_mounts(db: AsyncSession, server_id: str) -> list:
    """Load volume mounts for spawning a server."""
    from app.models.server_volume import ServerVolume
    
    result = await db.execute(
        select(ServerVolume).where(ServerVolume.server_id == server_id)
    )
    mounts = result.scalars().all()
    
    if not mounts:
        # Fallback to legacy single volume
        return []
    
    return [
        {
            "volume_id": str(m.volume_id),
            "mount_path": m.mount_path,
            "mode": m.mode,
            "is_primary": m.is_primary,
        }
        for m in mounts
    ]


def _serialize_volume_mounts(server: Server) -> list:
    """Serialize server volume mounts for API response."""
    mounts = []
    for vm in getattr(server, 'volume_mounts', []) or []:
        mounts.append({
            "volume_id": str(vm.volume_id),
            "mount_path": vm.mount_path,
            "mode": vm.mode,
            "is_primary": vm.is_primary,
            "volume": {
                "id": str(vm.volume.id),
                "name": vm.volume.name,
                "display_name": vm.volume.display_name,
                "size_bytes": vm.volume.size_bytes,
            } if vm.volume else None,
        })
    return mounts


async def _get_server_volume_mounts(db: AsyncSession, server_id: str) -> list:
    """Load volume mounts for a server."""
    from sqlalchemy.orm import selectinload
    from app.models.server_volume import ServerVolume
    from app.models.volume import Volume
    
    result = await db.execute(
        select(ServerVolume)
        .where(ServerVolume.server_id == server_id)
        .options(selectinload(ServerVolume.volume))
    )
    mounts = result.scalars().all()
    return [
        {
            "volume_id": str(m.volume_id),
            "mount_path": m.mount_path,
            "mode": m.mode,
            "is_primary": m.is_primary,
            "volume": {
                "id": str(m.volume.id),
                "name": m.volume.name,
                "display_name": m.volume.display_name,
                "size_bytes": m.volume.size_bytes,
            } if m.volume else None,
        }
        for m in mounts
    ]


@router.post("/", response_model=ServerResponse)
@limiter.limit("10/minute")
async def create_server(
    request: Request,
    body: ServerCreateRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Create and spawn a new server using a plan and environment template."""
    from app.services.quota_service import QuotaService
    from app.services.plan_service import PlanService
    from app.services.environment_service import EnvironmentService
    import uuid
    
    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)
    
    # Validate plan exists and user can use it
    plan_service = PlanService(db)
    plan = await plan_service.get_by_id(body.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Check plan access (public, role-based, direct, or workspace)
    can_use = await plan_service.can_user_use_plan(
        str(plan.id), current_user.role, str(current_user.id)
    )
    if not can_use:
        raise HTTPException(status_code=403, detail="Plan not available for your role")
    
    if not plan.is_active:
        raise HTTPException(status_code=400, detail="Plan is not active")
    
    # Validate environment exists
    env_service = EnvironmentService(db)
    environment = await env_service.get_by_id(body.environment_id)
    if not environment:
        raise HTTPException(status_code=404, detail="Environment not found")
    
    # Check quota before spawning
    quota_service = QuotaService(db)
    quota_check = await quota_service.check_spawn_allowed(
        user_id=str(current_user.id),
        plan_id=body.plan_id
    )
    
    if not quota_check["allowed"]:
        raise HTTPException(status_code=429, detail=quota_check["reason"])
    
    # Check sufficient NUKE credits
    from app.services.credit_service import CreditService
    credit_service = CreditService(db)
    
    if settings.credits_enabled:
        has_credits = await credit_service.check_sufficient_credits(
            user_id=str(current_user.id),
            required=plan.cost_per_hour
        )
        if not has_credits:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Insufficient NUKE credits. Required: {plan.cost_per_hour} for 1 hour"
            )
    
    # Check global resource pool
    from app.services.resource_pool_service import ResourcePoolService
    resource_pool = ResourcePoolService(db)
    can_fit = await resource_pool.can_fit(body.plan_id)
    
    if not can_fit:
        # Queue the server instead of rejecting
        from app.models.server_queue import ServerQueue
        
        queue_entry = ServerQueue(
            user_id=current_user.id,
            environment_id=uuid.UUID(body.environment_id),
            plan_id=uuid.UUID(body.plan_id),
            status="pending",
            priority=plan.priority,
            server_name=body.name,
            requested_cpu=plan.cpu_limit,
            requested_memory=plan.memory_limit,
            requested_disk=plan.disk_limit,
        )
        db.add(queue_entry)
        await db.commit()
        await db.refresh(queue_entry)
        
        queue_position = await resource_pool.get_queue_position(str(queue_entry.id))
        
        return {
            "queued": True,
            "queue_id": str(queue_entry.id),
            "queue_position": queue_position,
            "message": "Server queued due to resource scarcity. It will start automatically when resources are available.",
        }
    
    try:
        from app.services.volume_service import VolumeService
        from app.services.volume_access_service import VolumeAccessService
        from app.models.server_volume import ServerVolume
        
        volume_service = VolumeService(db)
        volume_access = VolumeAccessService(db)
        
        # Build volume_mounts list from new or legacy format
        volume_mounts = []
        
        if body.volume_mounts:
            for idx, vm in enumerate(body.volume_mounts):
                mount_data = {
                    "volume_id": vm.volume_id,
                    "mount_path": vm.mount_path or "/data",
                    "mode": vm.mode or "read_write",
                    "max_size_bytes": vm.max_size_bytes,
                }
                # Auto-create volume for empty volume_id mounts
                if not vm.volume_id:
                    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '-', body.name).lower()
                    suffix = "data" if idx == 0 else f"data-{idx}"
                    volume_name = f"nukelab-server-{current_user.username}-{safe_name}-{suffix}"
                    new_vol = await volume_service.create_volume(
                        name=volume_name,
                        display_name=f"{body.name} {suffix.title()}",
                        owner_id=str(current_user.id),
                        max_size_bytes=vm.max_size_bytes or volume_service._parse_memory(plan.disk_limit),
                    )
                    mount_data["volume_id"] = str(new_vol.id)
                volume_mounts.append(mount_data)
        elif body.volume_id:
            # Legacy single-volume support
            volume_mounts.append({
                "volume_id": body.volume_id,
                "mount_path": f"/home/{current_user.username}",
                "mode": body.volume_mode or "read_write",
            })
        
        # Auto-create primary volume if none provided
        auto_created_volume = None
        auto_created_volume_name = None
        if not volume_mounts:
            # Sanitize volume name to ensure Docker compatibility
            safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '-', body.name).lower()
            volume_name = f"nukelab-server-{current_user.username}-{safe_name}-data"
            auto_created_volume_name = volume_name
            auto_created_volume = await volume_service.create_volume(
                name=volume_name,
                display_name=f"{body.name} Data",
                owner_id=str(current_user.id),
                max_size_bytes=volume_service._parse_memory(plan.disk_limit),
            )
            volume_mounts.append({
                "volume_id": str(auto_created_volume.id),
                "mount_path": f"/home/{current_user.username}",
                "mode": "read_write",
                "is_primary": True,
            })
        else:
            # Mark first mount as primary if none marked
            has_primary = any(m.get("is_primary") for m in volume_mounts)
            if not has_primary:
                volume_mounts[0]["is_primary"] = True
        
        # Validate each volume mount
        for vm in volume_mounts:
            vol_id = vm["volume_id"]
            mode = vm["mode"]
            
            if not await volume_access.can_access_volume(vol_id, str(current_user.id), mode):
                vol = await volume_service.get_volume(vol_id)
                vol_name = vol.display_name if vol else vol_id
                mode_label = "read-write" if mode == "read_write" else "read-only"
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Volume '{vol_name}' cannot be mounted as {mode_label}. "
                        f"You may have read-only access via a shared workspace. "
                        f"Contact the workspace owner to request write access."
                    )
                )
            
            # Check quota for each volume
            quota_check = await volume_service.check_quota(vol_id, plan.disk_limit)
            if not quota_check["allowed"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Volume {vol_id}: {quota_check['reason']}"
                )
        
        # Check aggregate volume quota — total of all mounted volumes must fit within plan
        all_volume_ids = [vm["volume_id"] for vm in volume_mounts]
        aggregate_check = await volume_service.check_aggregate_quota(all_volume_ids, plan.disk_limit)
        if not aggregate_check["allowed"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=aggregate_check["reason"]
            )
        
        # Spawn the container using plan resources + environment image
        server = await spawner.spawn(
            user_id=str(current_user.id),
            username=current_user.username,
            server_name=body.name,
            environment=environment.slug,
            environment_id=body.environment_id,
            image=environment.image,
            cpu=plan.cpu_limit,
            memory=plan.memory_limit,
            disk=plan.disk_limit,
            volume_mounts=volume_mounts,
        )
        
        # Store plan reference
        server.plan_id = uuid.UUID(body.plan_id)
        server.last_activity = datetime.utcnow()
        
        # Set expiration based on max_runtime
        from app.core.time_utils import parse_duration
        max_runtime_seconds = parse_duration(plan.max_runtime)
        if max_runtime_seconds > 0:
            server.expires_at = datetime.utcnow() + timedelta(seconds=max_runtime_seconds)
        
        # Save to database
        db.add(server)
        await db.commit()
        await db.refresh(server)
        
        # Create ServerVolume rows
        for vm in volume_mounts:
            sv = ServerVolume(
                server_id=server.id,
                volume_id=uuid.UUID(vm["volume_id"]),
                mount_path=vm["mount_path"],
                mode=vm["mode"],
                is_primary=vm.get("is_primary", False),
            )
            db.add(sv)
            # Update volume last mounted time
            await volume_service.record_mount(vm["volume_id"])
            # Persist home-directory flag for privacy warnings even after deletion
            home_mount_path = f"/home/{current_user.username}"
            if vm["mount_path"] == home_mount_path:
                await volume_service.mark_home_volume(vm["volume_id"])
        
        await db.commit()
        
        # Increment quota usage
        await quota_service.increment_usage(
            user_id=str(current_user.id),
            plan_id=body.plan_id
        )
        
        # Build volume_mounts response
        vm_response = [
            {
                "volume_id": vm["volume_id"],
                "mount_path": vm["mount_path"],
                "mode": vm["mode"],
                "is_primary": vm.get("is_primary", False),
            }
            for vm in volume_mounts
        ]
        
        return ServerResponse(
            id=str(server.id),
            name=server.name,
            status=server.status,
            container_id=server.container_id,
            volume_id=str(server.volume_id) if server.volume_id else None,
            volume_mode=server.volume_mode,
            volume_mounts=vm_response,
            external_url=server.external_url,
            allocated_cpu=server.allocated_cpu,
            allocated_memory=server.allocated_memory,
            allocated_disk=server.allocated_disk,
            health_status=server.health_status,
            status_reason=server.status_reason,
            user_id=str(server.user_id),
            plan_id=str(server.plan_id) if server.plan_id else None,
            environment_id=str(server.environment_id) if server.environment_id else None,
            created_at=server.created_at.isoformat() if server.created_at else None,
            started_at=server.started_at.isoformat() if server.started_at else None,
        )
        
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        
        # Clean up auto-created Docker volume on failure to allow retries.
        # DB record is rolled back automatically by db.rollback() above.
        if auto_created_volume_name:
            try:
                from app.container.client import get_container_client
                container_client = await get_container_client()
                try:
                    vol = await container_client.client.volumes.get(auto_created_volume_name)
                    await vol.delete()
                    logger.info(f"Cleaned up Docker volume: {auto_created_volume_name}")
                except Exception as e:
                    logger.warning(f"Failed to delete Docker volume {auto_created_volume_name}: {e}")
            except Exception as e:
                logger.warning(f"Failed to clean up auto-created volume: {e}")
        
        # Delete orphaned DB volume record using a fresh session to avoid greenlet issues
        if auto_created_volume_name:
            try:
                from app.db.session import async_session
                from app.models.volume import Volume
                async with async_session() as cleanup_db:
                    result = await cleanup_db.execute(
                        select(Volume).where(Volume.name == auto_created_volume_name)
                    )
                    vol = result.scalar_one_or_none()
                    if vol:
                        await cleanup_db.delete(vol)
                        await cleanup_db.commit()
                        logger.info(f"Cleaned up DB volume record: {auto_created_volume_name}")
            except Exception as e:
                logger.warning(f"Failed to clean up DB volume record: {e}")
        
        # Also clean up any container that may have been created
        try:
            from app.container.client import get_container_client
            container_client = await get_container_client()
            container_name = f"nukelab-server-{current_user.username}-{body.name}"
            try:
                container = await container_client.client.containers.get(container_name)
                await container.delete(force=True)
            except Exception:
                pass
        except Exception:
            pass
        
        logger.exception("Server creation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create server. Please try again or contact support."
        )


@router.get("/")
async def list_servers(
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """List servers. Users see own servers, admins see all."""
    from sqlalchemy.orm import joinedload
    checker = PermissionChecker(current_user)
    
    from sqlalchemy.orm import selectinload
    from app.models.server_volume import ServerVolume
    
    if checker.is_admin() or has_any_permission(current_user, [Permission.SERVERS_READ_ALL]):
        result = await db.execute(
            select(Server)
            .options(joinedload(Server.user))
            .options(selectinload(Server.volume_mounts).selectinload(ServerVolume.volume))
        )
    else:
        result = await db.execute(
            select(Server).where(Server.user_id == current_user.id)
            .options(joinedload(Server.user))
            .options(selectinload(Server.volume_mounts).selectinload(ServerVolume.volume))
        )
    
    servers = result.unique().scalars().all()
    
    for s in servers:
        if s.container_id:
            try:
                actual = await spawner.get_status(s.container_id)
                if actual == "running" and s.status != "running":
                    s.status = "running"
                    s.started_at = datetime.utcnow()
                elif actual in ("stopped", "paused", "exited") and s.status == "running":
                    s.status = "stopped"
                    s.stopped_at = datetime.utcnow()
                elif actual == "running" and s.status == "pending":
                    s.status = "running"
                    s.started_at = datetime.utcnow()
            except Exception:
                pass
    
    await db.commit()
    
    return {
        "servers": [
            {
                "id": str(s.id),
                "name": s.name,
                "status": s.status,
                "container_id": s.container_id,
                "volume_id": str(s.volume_id) if s.volume_id else None,
                "volume_mode": s.volume_mode,
                "volume_mounts": _serialize_volume_mounts(s),
                "external_url": s.external_url,
                "allocated_cpu": s.allocated_cpu,
                "allocated_memory": s.allocated_memory,
                "allocated_disk": s.allocated_disk,
                "health_status": s.health_status,
                "status_reason": s.status_reason,
                "stop_reason": s.stop_reason,
                "user_id": str(s.user_id),
                "username": s.user.username if s.user else None,
                "plan_id": str(s.plan_id) if s.plan_id else None,
                "environment_id": str(s.environment_id) if s.environment_id else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "stopped_at": s.stopped_at.isoformat() if s.stopped_at else None,
                "last_activity": s.last_activity.isoformat() if s.last_activity else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "total_cost": s.total_cost,
                "last_billed_at": s.last_billed_at.isoformat() if s.last_billed_at else None,
            }
            for s in servers
        ]
    }


@router.get("/{server_id}")
async def get_server(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """Get server details. Users can view own, admins can view any."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, request,
        admin_permissions=[Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )

    if server.container_id:
        try:
            actual = await spawner.get_status(server.container_id)
            if actual == "running" and server.status != "running":
                server.status = "running"
                server.started_at = datetime.utcnow()
                server.stop_reason = None
                server.stopped_at = None
            elif actual in ("stopped", "paused", "exited") and server.status == "running":
                server.status = "stopped"
                server.stopped_at = datetime.utcnow()
            await db.commit()
        except Exception:
            pass

    return {
        "id": str(server.id),
        "name": server.name,
        "status": server.status,
        "container_id": server.container_id,
        "volume_id": str(server.volume_id) if server.volume_id else None,
        "volume_mode": server.volume_mode,
        "volume_mounts": await _get_server_volume_mounts(db, str(server.id)),
        "external_url": server.external_url,
        "allocated_cpu": server.allocated_cpu,
        "allocated_memory": server.allocated_memory,
        "allocated_disk": server.allocated_disk,
        "health_status": server.health_status,
        "status_reason": server.status_reason,
        "stop_reason": server.stop_reason,
        "started_at": server.started_at.isoformat() if server.started_at else None,
        "stopped_at": server.stopped_at.isoformat() if server.stopped_at else None,
        "last_activity": server.last_activity.isoformat() if server.last_activity else None,
        "expires_at": server.expires_at.isoformat() if server.expires_at else None,
        "total_cost": server.total_cost,
        "last_billed_at": server.last_billed_at.isoformat() if server.last_billed_at else None,
        "user_id": str(server.user_id),
        "plan_id": str(server.plan_id) if server.plan_id else None,
        "environment_id": str(server.environment_id) if server.environment_id else None,
    }


@router.get("/by-path/{username}/{server_name}")
async def get_server_by_path(
    username: str,
    server_name: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """Get server by username and server name. Used by server gateway page."""
    from sqlalchemy.orm import joinedload

    result = await db.execute(
        select(Server).join(User).where(
            User.username == username,
            Server.name == server_name
        ).options(joinedload(Server.user))
    )
    server = result.scalar_one_or_none()

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Permission check - users can only access their own unless admin
    if str(server.user_id) != str(current_user.id):
        checker = PermissionChecker(current_user)
        checker.require_any([Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS])

    # Sync status with actual container state
    if server.container_id:
        try:
            actual = await spawner.get_status(server.container_id)
            if actual == "running" and server.status != "running":
                server.status = "running"
                server.started_at = datetime.utcnow()
                server.stop_reason = None
                server.stopped_at = None
            elif actual in ("stopped", "paused", "exited") and server.status == "running":
                server.status = "stopped"
                server.stopped_at = datetime.utcnow()
            await db.commit()
        except Exception:
            pass

    return {
        "id": str(server.id),
        "name": server.name,
        "status": server.status,
        "container_id": server.container_id,
        "volume_id": str(server.volume_id) if server.volume_id else None,
        "volume_mode": server.volume_mode,
        "volume_mounts": await _get_server_volume_mounts(db, str(server.id)),
        "external_url": server.external_url,
        "allocated_cpu": server.allocated_cpu,
        "allocated_memory": server.allocated_memory,
        "allocated_disk": server.allocated_disk,
        "health_status": server.health_status,
        "status_reason": server.status_reason,
        "stop_reason": server.stop_reason,
        "started_at": server.started_at.isoformat() if server.started_at else None,
        "stopped_at": server.stopped_at.isoformat() if server.stopped_at else None,
        "last_activity": server.last_activity.isoformat() if server.last_activity else None,
        "expires_at": server.expires_at.isoformat() if server.expires_at else None,
        "total_cost": server.total_cost,
        "last_billed_at": server.last_billed_at.isoformat() if server.last_billed_at else None,
        "user_id": str(server.user_id),
        "username": server.user.username if server.user else None,
        "plan_id": str(server.plan_id) if server.plan_id else None,
        "environment_id": str(server.environment_id) if server.environment_id else None,
    }


async def _perform_server_start(
    server: Server,
    db: AsyncSession,
    current_user: User,
    server_id: str,
) -> dict:
    """Execute server start logic. Raises HTTPException on failure."""
    from app.services.plan_service import PlanService
    from app.services.credit_service import CreditService
    from app.services.volume_service import VolumeService
    from app.services.environment_service import EnvironmentService
    from sqlalchemy import select as sa_select
    from app.models.user import User

    # Check plan access — user may have lost access since creation
    if server.plan_id:
        plan_service = PlanService(db)
        can_use = await plan_service.can_user_use_plan(
            str(server.plan_id), current_user.role, str(current_user.id)
        )
        if not can_use:
            raise HTTPException(status_code=403, detail="Plan no longer available for your account")

    # Check NUKE credits before starting
    if settings.credits_enabled and server.plan_id:
        plan_service = PlanService(db)
        plan = await plan_service.get_by_id(str(server.plan_id))
        if plan and plan.cost_per_hour > 0:
            credit_service = CreditService(db)
            has_credits = await credit_service.check_sufficient_credits(
                user_id=str(server.user_id),
                required=plan.cost_per_hour
            )
            if not has_credits:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Insufficient NUKE credits. Required: {plan.cost_per_hour} for 1 hour"
                )

    # Load volume mounts
    volume_mounts = await _load_server_volume_mounts(db, str(server.id))

    # Check volume quota before starting
    if volume_mounts and server.plan_id:
        volume_service = VolumeService(db)
        plan_service = PlanService(db)
        plan = await plan_service.get_by_id(str(server.plan_id))
        if plan:
            for vm in volume_mounts:
                quota_check = await volume_service.check_quota(vm["volume_id"], plan.disk_limit)
                if not quota_check["allowed"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=quota_check["reason"]
                    )
            all_volume_ids = [vm["volume_id"] for vm in volume_mounts]
            aggregate_check = await volume_service.check_aggregate_quota(all_volume_ids, plan.disk_limit)
            if not aggregate_check["allowed"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=aggregate_check["reason"]
                )

    if server.container_id:
        try:
            actual_status = await spawner.get_status(server.container_id)
            if actual_status == "running":
                await broadcast_server_status_change(server.user_id, server_id, "running")
                return {"message": "Server already running", "server_id": server_id, "status": "running"}

            if actual_status in ("unknown", "stopped"):
                if actual_status == "unknown":
                    print(f"Container {server.container_id} not found, recreating...")
                else:
                    print(f"Container {server.container_id} is stopped, deleting and recreating...")
                    try:
                        await spawner.delete(server.container_id)
                    except Exception as e:
                        print(f"Warning: failed to delete stale container: {e}")

                env_service = EnvironmentService(db)
                environment = await env_service.get_by_id(str(server.environment_id)) if server.environment_id else None
                plan_service = PlanService(db)
                plan = await plan_service.get_by_id(str(server.plan_id)) if server.plan_id else None

                result = await db.execute(sa_select(User).where(User.id == server.user_id))
                server_owner = result.scalar_one_or_none()
                owner_username = server_owner.username if server_owner else current_user.username

                new_server = await spawner.spawn(
                    user_id=str(server.user_id),
                    username=owner_username,
                    server_name=server.name,
                    environment=environment.slug if environment else "dev",
                    environment_id=str(server.environment_id) if server.environment_id else None,
                    image=environment.image if environment else None,
                    cpu=plan.cpu_limit if plan else server.allocated_cpu,
                    memory=plan.memory_limit if plan else server.allocated_memory,
                    disk=plan.disk_limit if plan else server.allocated_disk,
                    volume_mounts=volume_mounts or None,
                    server_id=str(server.id),
                )

                server.container_id = new_server.container_id
                server.image = new_server.image
                server.volume_id = new_server.volume_id
                server.status = "running"
                server.started_at = datetime.utcnow()
                server.external_url = new_server.external_url
                server.stop_reason = None
                server.stopped_at = None

                await db.commit()
                await broadcast_server_status_change(server.user_id, server_id, "running")
                return {"message": "Server container recreated and started", "server_id": server_id, "status": "running"}

            success = await spawner.start(server.container_id)
            if not success:
                raise Exception("Failed to start container - check container logs")

            server.status = "running"
            server.started_at = datetime.utcnow()
            server.stop_reason = None
            server.stopped_at = None

            if volume_mounts:
                volume_service = VolumeService(db)
                for vm in volume_mounts:
                    await volume_service.record_mount(vm["volume_id"])
            elif server.volume_id:
                volume_service = VolumeService(db)
                await volume_service.record_mount(str(server.volume_id))

            notif_service = NotificationService(db)
            await notif_service.server_started(
                user_id=server.user_id,
                server_name=server.name,
                action_url=f"/servers/{server_id}"
            )

            await db.commit()
            await broadcast_server_status_change(server.user_id, server_id, "running")
            return {"message": "Server started", "server_id": server_id, "status": "running"}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Server start failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start server. Please try again or contact support."
            )
    else:
        if not server.environment_id or not server.plan_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Server configuration incomplete"
            )

        env_service = EnvironmentService(db)
        environment = await env_service.get_by_id(str(server.environment_id))
        if not environment:
            raise HTTPException(status_code=404, detail="Environment not found")

        plan_service = PlanService(db)
        plan = await plan_service.get_by_id(str(server.plan_id))
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        try:
            result = await db.execute(sa_select(User).where(User.id == server.user_id))
            server_owner = result.scalar_one_or_none()
            owner_username = server_owner.username if server_owner else current_user.username

            new_server = await spawner.spawn(
                user_id=str(server.user_id),
                username=owner_username,
                server_name=server.name,
                environment=environment.slug if environment else "dev",
                environment_id=str(server.environment_id) if server.environment_id else None,
                image=environment.image if environment else None,
                cpu=plan.cpu_limit if plan else server.allocated_cpu,
                memory=plan.memory_limit if plan else server.allocated_memory,
                disk=plan.disk_limit if plan else server.allocated_disk,
                volume_mounts=volume_mounts or None,
                server_id=str(server.id),
            )

            server.container_id = new_server.container_id
            server.image = new_server.image
            server.volume_id = new_server.volume_id
            server.status = "running"
            server.external_url = new_server.external_url
            server.started_at = datetime.utcnow()
            server.stop_reason = None
            server.stopped_at = None
            server.allocated_cpu = new_server.allocated_cpu
            server.allocated_memory = new_server.allocated_memory
            await db.commit()

            if volume_mounts:
                volume_service = VolumeService(db)
                for vm in volume_mounts:
                    await volume_service.record_mount(vm["volume_id"])
            elif server.volume_id:
                volume_service = VolumeService(db)
                await volume_service.record_mount(str(server.volume_id))

            notif_service = NotificationService(db)
            await notif_service.server_started(
                user_id=server.user_id,
                server_name=server.name,
                action_url=f"/servers/{server_id}"
            )

            await broadcast_server_status_change(server.user_id, server_id, "running")
            return {"message": "Server started", "server_id": server_id, "status": "running"}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Server spawn failed during restart")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to restart server. Please try again or contact support."
            )


async def _perform_server_stop(
    server: Server,
    db: AsyncSession,
    server_id: str,
) -> dict:
    """Execute server stop logic. Raises HTTPException on failure."""
    from app.services.credit_service import CreditService
    from app.models.server_plan import ServerPlan
    from app.services.quota_service import QuotaService
    from app.services.volume_service import VolumeService

    volume_mounts = await _load_server_volume_mounts(db, str(server.id))

    if server.container_id:
        try:
            actual_status = await spawner.get_status(server.container_id)
            if actual_status == "stopped" or actual_status == "unknown":
                server.status = "stopped"
                server.container_id = None
                await db.commit()
                await broadcast_server_status_change(server.user_id, server_id, "stopped")
                return {"message": "Server already stopped", "server_id": server_id, "status": "stopped"}

            await spawner.delete(server.container_id)
            server.container_id = None
            server.status = "stopped"
            server.stopped_at = datetime.utcnow()

            if server.plan_id:
                credit_service = CreditService(db)
                plan_result = await db.execute(
                    select(ServerPlan).where(ServerPlan.id == server.plan_id)
                )
                plan = plan_result.scalar_one_or_none()
                if plan:
                    await credit_service.reconcile_server_billing(server, plan)

            if server.plan_id:
                quota_service = QuotaService(db)
                await quota_service.decrement_usage(
                    user_id=str(server.user_id),
                    plan_id=str(server.plan_id)
                )

            await db.commit()

            notif_service = NotificationService(db)
            await notif_service.server_stopped(
                user_id=server.user_id,
                server_name=server.name,
                action_url=f"/servers/{server_id}"
            )

            await broadcast_server_status_change(server.user_id, server_id, "stopped")
            return {"message": "Server stopped", "server_id": server_id, "status": "stopped"}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Server stop failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to stop server. Please try again or contact support."
            )

    server.status = "stopped"
    await db.commit()

    notif_service = NotificationService(db)
    await notif_service.server_stopped(
        user_id=server.user_id,
        server_name=server.name,
        action_url=f"/servers/{server_id}"
    )

    await broadcast_server_status_change(server.user_id, server_id, "stopped")
    return {"message": "Server stopped", "server_id": server_id, "status": "stopped"}


async def _perform_server_restart(
    server: Server,
    db: AsyncSession,
    current_user: User,
    server_id: str,
) -> dict:
    """Execute server restart logic. Raises HTTPException on failure."""
    from app.services.plan_service import PlanService
    from app.services.credit_service import CreditService
    from app.services.volume_service import VolumeService
    from app.services.environment_service import EnvironmentService
    from sqlalchemy import select as sa_select
    from app.models.user import User

    if server.plan_id:
        plan_service = PlanService(db)
        can_use = await plan_service.can_user_use_plan(
            str(server.plan_id), current_user.role, str(current_user.id)
        )
        if not can_use:
            raise HTTPException(status_code=403, detail="Plan no longer available for your account")

    if settings.credits_enabled and server.plan_id:
        plan_service = PlanService(db)
        plan = await plan_service.get_by_id(str(server.plan_id))
        if plan and plan.cost_per_hour > 0:
            credit_service = CreditService(db)
            has_credits = await credit_service.check_sufficient_credits(
                user_id=str(server.user_id),
                required=plan.cost_per_hour
            )
            if not has_credits:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Insufficient NUKE credits. Required: {plan.cost_per_hour} for 1 hour"
                )

    volume_mounts = await _load_server_volume_mounts(db, str(server.id))

    if volume_mounts and server.plan_id:
        volume_service = VolumeService(db)
        plan_service = PlanService(db)
        plan = await plan_service.get_by_id(str(server.plan_id))
        if plan:
            for vm in volume_mounts:
                quota_check = await volume_service.check_quota(vm["volume_id"], plan.disk_limit)
                if not quota_check["allowed"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=quota_check["reason"]
                    )
            all_volume_ids = [vm["volume_id"] for vm in volume_mounts]
            aggregate_check = await volume_service.check_aggregate_quota(all_volume_ids, plan.disk_limit)
            if not aggregate_check["allowed"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=aggregate_check["reason"]
                )

    if server.container_id:
        try:
            actual_status = await spawner.get_status(server.container_id)
            if actual_status == "unknown":
                env_service = EnvironmentService(db)
                environment = await env_service.get_by_id(str(server.environment_id)) if server.environment_id else None
                plan_service = PlanService(db)
                plan = await plan_service.get_by_id(str(server.plan_id)) if server.plan_id else None

                result = await db.execute(sa_select(User).where(User.id == server.user_id))
                server_owner = result.scalar_one_or_none()
                owner_username = server_owner.username if server_owner else current_user.username

                new_server = await spawner.spawn(
                    user_id=str(server.user_id),
                    username=owner_username,
                    server_name=server.name,
                    environment=environment.slug if environment else "dev",
                    environment_id=str(server.environment_id) if server.environment_id else None,
                    image=environment.image if environment else None,
                    cpu=plan.cpu_limit if plan else server.allocated_cpu,
                    memory=plan.memory_limit if plan else server.allocated_memory,
                    disk=plan.disk_limit if plan else server.allocated_disk,
                    volume_mounts=volume_mounts or None,
                    server_id=str(server.id),
                )

                server.container_id = new_server.container_id
                server.image = new_server.image
                server.volume_id = new_server.volume_id
                server.status = "running"
                server.started_at = datetime.utcnow()
                server.external_url = new_server.external_url
                server.stop_reason = None
                server.stopped_at = None
                await db.commit()

                notif_service = NotificationService(db)
                await notif_service.server_restarted(
                    user_id=server.user_id,
                    server_name=server.name,
                    action_url=f"/servers/{server_id}"
                )

                await broadcast_server_status_change(server.user_id, server_id, "running")
                return {"message": "Server container recreated and started", "server_id": server_id, "status": "running"}

            await spawner.stop(server.container_id)
            await spawner.start(server.container_id)
            server.status = "running"
            server.started_at = datetime.utcnow()
            server.stop_reason = None
            server.stopped_at = None
            await db.commit()

            notif_service = NotificationService(db)
            await notif_service.server_restarted(
                user_id=server.user_id,
                server_name=server.name,
                action_url=f"/servers/{server_id}"
            )

            await broadcast_server_status_change(server.user_id, server_id, "running")
            return {"message": "Server restarted", "server_id": server_id, "status": "running"}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Server restart failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to restart server. Please try again or contact support."
            )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No container associated with this server"
    )


async def _perform_server_delete(
    server: Server,
    db: AsyncSession,
    server_id: str,
) -> dict:
    """Execute server delete logic. Raises HTTPException on failure."""
    from app.services.volume_service import VolumeService
    from app.models.credit_transaction import CreditTransaction
    from sqlalchemy import delete

    volume_mounts = await _load_server_volume_mounts(db, str(server.id))

    if server.container_id:
        try:
            await spawner.delete(server.container_id)
        except Exception as e:
            print(f"Warning: Failed to delete container: {e}")

    await db.execute(
        delete(CreditTransaction).where(CreditTransaction.server_id == server.id)
    )

    user_id = server.user_id
    server_name = server.name

    await db.delete(server)
    await db.commit()

    notif_service = NotificationService(db)
    await notif_service.server_deleted(
        user_id=user_id,
        server_name=server_name
    )

    return {"message": "Server deleted", "server_id": server_id}


@router.post("/{server_id}/start")
async def start_server(
    server_id: str,
    http_request: Request,
    body: ReasonRequest = ReasonRequest(),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Start a stopped server."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, http_request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS])
        await _audit_cross_user_access(server, current_user, db, "server.start", body.reason)

    return await _perform_server_start(server, db, current_user, server_id)


@router.post("/{server_id}/stop")
async def stop_server(
    server_id: str,
    http_request: Request,
    body: ReasonRequest = ReasonRequest(),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Stop a server."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, http_request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS])
        await _audit_cross_user_access(server, current_user, db, "server.stop", body.reason)

    return await _perform_server_stop(server, db, server_id)


@router.post("/{server_id}/restart")
async def restart_server(
    server_id: str,
    http_request: Request,
    body: ReasonRequest = ReasonRequest(),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Restart a server."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, http_request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS])
        await _audit_cross_user_access(server, current_user, db, "server.restart", body.reason)

    return await _perform_server_restart(server, db, current_user, server_id)


@router.delete("/{server_id}")
async def delete_server(
    server_id: str,
    request: Request,
    reason: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Delete a server."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS])
        await _audit_cross_user_access(server, current_user, db, "server.delete", reason)

    return await _perform_server_delete(server, db, server_id)


@router.get("/{server_id}/volumes")
async def get_server_volumes(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """Get volume mounts for a server."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, request,
        admin_permissions=[Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )
    return {"volume_mounts": await _get_server_volume_mounts(db, str(server.id))}


@router.patch("/{server_id}", response_model=ServerResponse)
async def update_server(
    server_id: str,
    http_request: Request,
    body: ServerUpdateRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_WRITE_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """Update server configuration. Any config change that affects the container
    triggers a recreate (stop → delete → spawn with new config)."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, http_request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )
    
    # Audit cross-user config updates
    if str(server.user_id) != str(current_user.id):
        await _audit_cross_user_access(server, current_user, db, "server.update", body.reason)
    
    from app.services.quota_service import QuotaService
    from app.services.plan_service import PlanService
    from app.services.environment_service import EnvironmentService
    from app.services.volume_service import VolumeService
    from app.services.volume_access_service import VolumeAccessService
    from app.models.server_volume import ServerVolume
    from sqlalchemy import delete as sa_delete
    import uuid
    
    volume_service = VolumeService(db)
    volume_access = VolumeAccessService(db)
    
    # Track if we need to recreate the container
    needs_recreate = False
    
    # Validate and apply name change (no recreate needed)
    if request.name is not None:
        server.name = request.name
    
    # Validate and apply plan change
    if request.plan_id is not None:
        plan_service = PlanService(db)
        plan = await plan_service.get_by_id(request.plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        can_use = await plan_service.can_user_use_plan(
            str(plan.id), current_user.role, str(current_user.id)
        )
        if not can_use:
            raise HTTPException(status_code=403, detail="Plan not available for your role")
        if not plan.is_active:
            raise HTTPException(status_code=400, detail="Plan is not active")
        
        # Check quota - exclude current server since we're replacing its resources
        quota_service = QuotaService(db)
        quota_check = await quota_service.check_spawn_allowed(
            user_id=str(current_user.id),
            plan_id=request.plan_id,
            exclude_server_id=str(server.id)
        )
        if not quota_check["allowed"]:
            raise HTTPException(status_code=429, detail=quota_check["reason"])
        
        server.plan_id = uuid.UUID(request.plan_id)
        server.allocated_cpu = plan.cpu_limit
        server.allocated_memory = plan.memory_limit
        server.allocated_disk = plan.disk_limit
        needs_recreate = True
    
    # Validate and apply environment change
    if request.environment_id is not None:
        env_service = EnvironmentService(db)
        environment = await env_service.get_by_id(request.environment_id)
        if not environment:
            raise HTTPException(status_code=404, detail="Environment not found")
        server.environment_id = uuid.UUID(request.environment_id)
        needs_recreate = True
    
    # Validate and apply volume mounts change
    new_volume_mounts = None
    disk_limit = None
    if request.volume_mounts is not None:
        new_volume_mounts = []
        plan = None
        if server.plan_id:
            plan_service = PlanService(db)
            plan = await plan_service.get_by_id(str(server.plan_id))
        disk_limit = plan.disk_limit if plan else server.allocated_disk
        
        for idx, vm in enumerate(request.volume_mounts):
            mount_data = {
                "volume_id": vm.volume_id,
                "mount_path": vm.mount_path or "/data",
                "mode": vm.mode or "read_write",
            }
            
            # Auto-create volume for empty volume_id mounts
            if not vm.volume_id:
                safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '-', server.name).lower()
                suffix = "data" if idx == 0 else f"data-{idx}"
                volume_name = f"nukelab-server-{current_user.username}-{safe_name}-{suffix}"
                new_vol = await volume_service.create_volume(
                    name=volume_name,
                    display_name=f"{server.name} {suffix.title()}",
                    owner_id=str(current_user.id),
                    max_size_bytes=vm.max_size_bytes or volume_service._parse_memory(disk_limit) if disk_limit else None,
                )
                mount_data["volume_id"] = str(new_vol.id)
            else:
                if not await volume_access.can_access_volume(vm.volume_id, str(current_user.id), vm.mode):
                    vol = await volume_service.get_volume(vm.volume_id)
                    vol_name = vol.display_name if vol else vm.volume_id
                    mode_label = "read-write" if vm.mode == "read_write" else "read-only"
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Volume '{vol_name}' cannot be mounted as {mode_label}. "
                            f"You may have read-only access via a shared workspace. "
                            f"Contact the workspace owner to request write access."
                        )
                    )
                # Check quota for each volume
                quota_check = await volume_service.check_quota(vm.volume_id, disk_limit)
                if not quota_check["allowed"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Volume {vm.volume_id}: {quota_check['reason']}"
                    )
            
            new_volume_mounts.append(mount_data)
        
        # Check aggregate volume quota for the updated mount set
        if new_volume_mounts and disk_limit:
            all_volume_ids = [vm["volume_id"] for vm in new_volume_mounts]
            aggregate_check = await volume_service.check_aggregate_quota(all_volume_ids, disk_limit)
            if not aggregate_check["allowed"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=aggregate_check["reason"]
                )
        
        # Mark first as primary if none specified
        has_primary = any(m.get("is_primary") for m in new_volume_mounts)
        if not has_primary and new_volume_mounts:
            new_volume_mounts[0]["is_primary"] = True
        
        needs_recreate = True
    
    # If server is running and needs recreate, stop and delete it first
    if needs_recreate and server.container_id:
        try:
            actual_status = await spawner.get_status(server.container_id)
            if actual_status == "running":
                await spawner.stop(server.container_id)
            await spawner.delete(server.container_id)
        except Exception as e:
            print(f"Warning: failed to stop/delete container during update: {e}")
        
        server.container_id = None
        server.status = "stopped"
        server.stopped_at = datetime.utcnow()
    
    # Apply volume mount changes in DB
    if new_volume_mounts is not None:
        # Delete old mounts
        await db.execute(
            sa_delete(ServerVolume).where(ServerVolume.server_id == server.id)
        )
        
        # Create new mounts
        for vm in new_volume_mounts:
            sv = ServerVolume(
                server_id=server.id,
                volume_id=uuid.UUID(vm["volume_id"]),
                mount_path=vm["mount_path"],
                mode=vm["mode"],
                is_primary=vm.get("is_primary", False),
            )
            db.add(sv)
            # Persist home-directory flag for privacy warnings even after deletion
            if 'server_owner' not in locals():
                from sqlalchemy import select as sa_select
                from app.models.user import User
                result = await db.execute(sa_select(User).where(User.id == server.user_id))
                server_owner = result.scalar_one_or_none()
            owner = server_owner or current_user
            home_mount_path = f"/home/{owner.username}"
            if vm["mount_path"] == home_mount_path:
                await volume_service.mark_home_volume(vm["volume_id"])
        
        # Update legacy fields
        primary = next((m for m in new_volume_mounts if m.get("is_primary")), new_volume_mounts[0] if new_volume_mounts else None)
        if primary:
            server.volume_id = uuid.UUID(primary["volume_id"])
    
    await db.commit()
    if needs_recreate and server.status == "stopped":
        await broadcast_server_status_change(server.user_id, str(server.id), "stopped")
    await db.refresh(server)
    
    # If container was deleted, respawn with new config
    if needs_recreate and not server.container_id:
        env_service = EnvironmentService(db)
        environment = await env_service.get_by_id(str(server.environment_id)) if server.environment_id else None
        plan_service = PlanService(db)
        plan = await plan_service.get_by_id(str(server.plan_id)) if server.plan_id else None
        
        # Get server owner's username
        from sqlalchemy import select as sa_select
        from app.models.user import User
        result = await db.execute(sa_select(User).where(User.id == server.user_id))
        server_owner = result.scalar_one_or_none()
        owner_username = server_owner.username if server_owner else current_user.username
        
        # Load current volume mounts for spawn
        spawn_mounts = await _load_server_volume_mounts(db, str(server.id))
        
        try:
            new_server_container = await spawner.spawn(
                user_id=str(server.user_id),
                username=owner_username,
                server_name=server.name,
                environment=environment.slug if environment else "dev",
                environment_id=str(server.environment_id) if server.environment_id else None,
                image=environment.image if environment else None,
                cpu=plan.cpu_limit if plan else server.allocated_cpu,
                memory=plan.memory_limit if plan else server.allocated_memory,
                disk=plan.disk_limit if plan else server.allocated_disk,
                volume_mounts=spawn_mounts or None,
                server_id=str(server.id),
            )
            
            server.container_id = new_server_container.container_id
            server.image = new_server_container.image
            server.volume_id = new_server_container.volume_id
            server.status = "running"
            server.started_at = datetime.utcnow()
            server.external_url = new_server_container.external_url
            server.stop_reason = None
            server.stopped_at = None
            
            await db.commit()
            await broadcast_server_status_change(server.user_id, str(server.id), "running")
        except Exception:
            logger.exception("Server recreate failed during update")
            server.status = "stopped"
            server.status_reason = "Failed to recreate container with new configuration. Please try starting the server again."
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to apply configuration changes. Please try again or contact support."
            )
    
    return ServerResponse(
        id=str(server.id),
        name=server.name,
        status=server.status,
        container_id=server.container_id,
        volume_id=str(server.volume_id) if server.volume_id else None,
        volume_mode=server.volume_mode,
        volume_mounts=await _get_server_volume_mounts(db, str(server.id)),
        external_url=server.external_url,
        allocated_cpu=server.allocated_cpu,
        allocated_memory=server.allocated_memory,
        allocated_disk=server.allocated_disk,
        health_status=server.health_status,
        status_reason=server.status_reason,
        user_id=str(server.user_id),
        plan_id=str(server.plan_id) if server.plan_id else None,
        environment_id=str(server.environment_id) if server.environment_id else None,
        created_at=server.created_at.isoformat() if server.created_at else None,
        started_at=server.started_at.isoformat() if server.started_at else None,
    )


@router.post("/{server_id}/test-metric")
async def test_metric(
    server_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
):
    """Send a test metric via Redis pub/sub to verify WebSocket pipeline."""
    import json
    import redis.asyncio as redis_client
    from app.config import settings
    from app.websocket.metrics_socket import connections
    
    r = redis_client.from_url(settings.redis_url)
    
    test_metric = {
        "server_id": server_id,
        "cpu_percent": 50.0,
        "memory_percent": 75.0,
        "disk_read_bytes": 1024,
        "disk_write_bytes": 2048,
        "network_rx_bytes": 1000,
        "network_tx_bytes": 2000,
        "test": True,
    }
    
    # Publish to specific channel
    await r.publish(f"metrics:server:{server_id}", json.dumps(test_metric))
    # Also publish to global
    await r.publish("metrics:all", json.dumps(test_metric))
    
    # Check active WebSocket connections
    room = f"server:{server_id}"
    active_connections = len(connections.get(room, set()))
    all_rooms = list(connections.keys())
    
    await r.close()
    
    return {
        "message": "Test metric published",
        "server_id": server_id,
        "active_ws_connections": active_connections,
        "all_rooms": all_rooms,
        "metric": test_metric,
    }


@router.post("/{server_id}/activity")
async def ping_server_activity(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Update last_activity timestamp for a server. Called when user accesses the server."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )
    
    if server.status != "running":
        raise HTTPException(status_code=400, detail="Server is not running")
    
    server.last_activity = datetime.utcnow()
    await db.commit()
    
    return {"message": "Activity recorded", "server_id": server_id, "last_activity": server.last_activity.isoformat()}


@router.get("/{server_id}/queue-status")
async def get_server_queue_status(
    server_id: str,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """Get queue status for a server that is waiting in queue."""
    from app.models.server_queue import ServerQueue
    from app.services.resource_pool_service import ResourcePoolService
    
    result = await db.execute(
        select(ServerQueue).where(
            ServerQueue.user_id == current_user.id,
            ServerQueue.status == "pending"
        ).order_by(ServerQueue.requested_at.desc())
    )
    entries = result.scalars().all()
    
    if not entries:
        return {"queued": False, "entries": []}
    
    resource_pool = ResourcePoolService(db)
    
    queue_data = []
    for entry in entries:
        position = await resource_pool.get_queue_position(str(entry.id))
        queue_data.append({
            "id": str(entry.id),
            "server_name": entry.server_name,
            "status": entry.status,
            "priority": entry.priority,
            "position": position,
            "requested_at": entry.requested_at.isoformat() if entry.requested_at else None,
        })
    
    return {
        "queued": True,
        "entries": queue_data,
    }


@router.get("/{server_id}/logs")
async def get_server_logs(
    server_id: str,
    request: Request,
    tail: int = 100,
    since: Optional[str] = None,
    follow: bool = False,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """Get server container logs."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, request,
        admin_permissions=[Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )
    
    if not server.container_id:
        return {
            "server_id": server_id,
            "logs": "",
            "tail": tail,
            "follow": follow,
            "status": "stopped",
        }
    
    try:
        # Parse since timestamp
        since_timestamp = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
                since_timestamp = int(since_dt.timestamp())
            except ValueError:
                pass
        
        logs = await spawner.container_client.get_container_logs(
            container_id=server.container_id,
            tail=tail,
            since=since_timestamp,
            timestamps=True,
            stdout=True,
            stderr=True
        )
        
        return {
            "server_id": server_id,
            "logs": logs,
            "tail": tail,
            "follow": follow,
            "status": "running",
        }
    except aiodocker.DockerError as e:
        # Container not found or Docker error — return empty logs gracefully
        return {
            "server_id": server_id,
            "logs": "",
            "tail": tail,
            "follow": follow,
            "status": "error",
        }
    except Exception:
        logger.exception("Server logs retrieval failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve logs. Please try again or contact support."
        )


# ── Server Access Token Endpoints ────────────────────────────────────────────

class ServerAccessTokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"
    server_id: str


class ServerAccessTokenRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/{server_id}/access-token")
async def create_server_access_token(
    server_id: str,
    request: Request,
    body: ServerAccessTokenRequest,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db)
):
    """Generate a short-lived access token for direct server access.
    
    Returns the token as an HttpOnly cookie for secure browser access.
    The cookie is scoped to path=/ and expires with the token (5 minutes default).
    A reason is required for cross-user access.
    """
    server = await get_server_with_permission_check(server_id, current_user, db, request)
    
    if server.status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server must be running to generate access token"
        )
    
    # Audit cross-user access (enforces reason for non-owners)
    await _audit_cross_user_access(server, current_user, db, "server_access", body.reason)
    
    from app.services.server_auth_service import server_auth_service
    
    if not server_auth_service.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server authentication is not enabled"
        )
    
    try:
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        token = await server_auth_service.generate_access_token(
            db=db,
            server_id=server.id,
            user_id=current_user.id,
            client_ip=client_ip,
            user_agent=user_agent,
            token_type="session",
        )
        
        # Return token as HttpOnly cookie - more secure than JSON body
        # Cookie is automatically sent by browser on subsequent requests
        response = Response(status_code=200)
        response.set_cookie(
            key="nukelab_server_token",
            value=token,
            max_age=settings.server_auth_token_ttl,
            path="/",
            httponly=True,
            secure=False,  # Set to True in production (HTTPS only)
            samesite="lax",
        )
        
        return response
        
    except ValueError:
        logger.exception("Access token rate limit exceeded")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later."
        )
    except Exception:
        logger.exception("Access token generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate access token. Please try again or contact support."
        )


@router.get("/{server_id}/access-stats")
async def get_server_access_stats(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    _ = Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db)
):
    """Get access statistics for a server."""
    server = await get_server_with_permission_check(
        server_id, current_user, db, request,
        admin_permissions=[Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS]
    )
    from app.services.server_auth_service import server_auth_service
    stats = await server_auth_service.get_server_access_stats(db, server.id)
    return {"server_id": server_id, **stats}
