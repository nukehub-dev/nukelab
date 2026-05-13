"""
Server API endpoints with RBAC and ownership enforcement.
"""

from datetime import datetime, timedelta
from typing import Optional
from app.config import settings
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.api.auth import get_current_user
from app.core.permissions import Permission
from app.core.security import has_any_permission
from app.dependencies import PermissionChecker
from app.db.session import get_db
from app.models.user import User
from app.models.server import Server
from app.docker.spawner import spawner

router = APIRouter()


class ServerCreateRequest(BaseModel):
    name: str
    plan_id: str
    environment_id: str
    volume_id: Optional[str] = None
    volume_mode: Optional[str] = "read_write"  # read_write, read_only


class ServerResponse(BaseModel):
    id: str
    name: str
    status: str
    container_id: str | None = None
    volume_id: str | None = None
    volume_mode: str | None = None
    external_url: str | None = None
    allocated_cpu: float | None = None
    allocated_memory: str | None = None
    allocated_disk: str | None = None
    health_status: str | None = None
    status_reason: str | None = None
    user_id: str | None = None
    username: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None


async def get_server_with_permission_check(
    server_id: str,
    current_user: User,
    db: AsyncSession,
    require_ownership: bool = True
) -> Server:
    """
    Get server and check permissions.
    Admins can access any server, users can only access their own.
    """
    result = await db.execute(
        select(Server).where(Server.id == server_id)
    )
    server = result.scalar_one_or_none()
    
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    if require_ownership and str(server.user_id) != str(current_user.id):
        checker = PermissionChecker(current_user)
        checker.require(Permission.SERVERS_MANAGE)
    
    return server


@router.post("/", response_model=ServerResponse)
async def create_server(
    request: ServerCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create and spawn a new server using a plan and environment template."""
    from app.services.quota_service import QuotaService
    from app.services.plan_service import PlanService
    from app.services.environment_service import EnvironmentService
    import uuid
    
    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_START)
    
    # Validate plan exists and user can use it
    plan_service = PlanService(db)
    plan = await plan_service.get_by_id(request.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Check role-based plan access
    if plan.allowed_roles and current_user.role not in plan.allowed_roles:
        raise HTTPException(status_code=403, detail="Plan not available for your role")
    
    if not plan.is_active:
        raise HTTPException(status_code=400, detail="Plan is not active")
    
    # Validate environment exists
    env_service = EnvironmentService(db)
    environment = await env_service.get_by_id(request.environment_id)
    if not environment:
        raise HTTPException(status_code=404, detail="Environment not found")
    
    # Check quota before spawning
    quota_service = QuotaService(db)
    quota_check = await quota_service.check_spawn_allowed(
        user_id=str(current_user.id),
        plan_id=request.plan_id
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
    can_fit = await resource_pool.can_fit(request.plan_id)
    
    if not can_fit:
        # Queue the server instead of rejecting
        from app.models.server_queue import ServerQueue
        
        queue_entry = ServerQueue(
            user_id=current_user.id,
            environment_id=uuid.UUID(request.environment_id),
            plan_id=uuid.UUID(request.plan_id),
            status="pending",
            priority=plan.priority,
            server_name=request.name,
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
        
        volume_service = VolumeService(db)
        volume_access = VolumeAccessService(db)
        
        # Handle volume selection
        volume_id = request.volume_id
        volume_mode = request.volume_mode or "read_write"
        
        if volume_id:
            # Validate volume access
            if not await volume_access.can_access_volume(volume_id, str(current_user.id), volume_mode):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to use this volume"
                )
            
            # Check quota
            quota_check = await volume_service.check_quota(volume_id, plan.disk_limit)
            if not quota_check["allowed"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=quota_check["reason"]
                )
        else:
            # Auto-create volume with plan limit
            volume_name = f"nukelab-server-{current_user.username}-{request.name}-data"
            new_volume = await volume_service.create_volume(
                name=volume_name,
                display_name=f"{request.name} Data",
                owner_id=str(current_user.id),
                max_size_bytes=volume_service._parse_memory(plan.disk_limit),
            )
            volume_id = str(new_volume.id)
        
        # Deduct 1 hour of plan cost on spawn
        if settings.credits_enabled and plan.cost_per_hour > 0:
            await credit_service.consume_credits(
                user_id=str(current_user.id),
                amount=plan.cost_per_hour,
                description=f"Initial spawn cost for server '{request.name}' (1 hour at {plan.cost_per_hour} NUKE/hour)",
            )
        
        # Spawn the container using plan resources + environment image
        server = await spawner.spawn(
            user_id=str(current_user.id),
            username=current_user.username,
            server_name=request.name,
            environment=environment.slug,
            environment_id=request.environment_id,
            image=environment.image,
            cpu=plan.cpu_limit,
            memory=plan.memory_limit,
            disk=plan.disk_limit,
            volume_id=volume_id,
            volume_mode=volume_mode,
        )
        
        # Store plan reference
        server.plan_id = uuid.UUID(request.plan_id)
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
        
        # Increment volume server count
        if server.volume_id:
            await volume_service.increment_server_count(str(server.volume_id))
        
        # Increment quota usage
        await quota_service.increment_usage(
            user_id=str(current_user.id),
            plan_id=request.plan_id
        )
        
        return ServerResponse(
            id=str(server.id),
            name=server.name,
            status=server.status,
            container_id=server.container_id,
            volume_id=str(server.volume_id) if server.volume_id else None,
            volume_mode=server.volume_mode,
            external_url=server.external_url,
            allocated_cpu=server.allocated_cpu,
            allocated_memory=server.allocated_memory,
            allocated_disk=server.allocated_disk,
            health_status=server.health_status,
            status_reason=server.status_reason,
            user_id=str(server.user_id),
            created_at=server.created_at.isoformat() if server.created_at else None,
            started_at=server.started_at.isoformat() if server.started_at else None,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        import traceback
        print(f"ERROR spawning server: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to spawn server: {str(e)}"
        )


@router.get("/")
async def list_servers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List servers. Users see own servers, admins see all."""
    from sqlalchemy.orm import joinedload
    checker = PermissionChecker(current_user)
    
    if checker.is_admin() or has_any_permission(current_user, [Permission.SERVERS_READ_ALL]):
        result = await db.execute(select(Server).options(joinedload(Server.user)))
    else:
        result = await db.execute(
            select(Server).where(Server.user_id == current_user.id).options(joinedload(Server.user))
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
                "external_url": s.external_url,
                "allocated_cpu": s.allocated_cpu,
                "allocated_memory": s.allocated_memory,
                "allocated_disk": s.allocated_disk,
                "health_status": s.health_status,
                "status_reason": s.status_reason,
                "stop_reason": s.stop_reason,
                "user_id": str(s.user_id),
                "username": s.user.username if s.user else None,
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get server details. Users can view own, admins can view any."""
    server = await get_server_with_permission_check(server_id, current_user, db)

    if server.container_id:
        try:
            actual = await spawner.get_status(server.container_id)
            if actual == "running" and server.status != "running":
                server.status = "running"
                server.started_at = datetime.utcnow()
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
    }


@router.get("/by-path/{username}/{server_name}")
async def get_server_by_path(
    username: str,
    server_name: str,
    current_user: User = Depends(get_current_user),
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
        checker.require(Permission.SERVERS_MANAGE)

    # Sync status with actual container state
    if server.container_id:
        try:
            actual = await spawner.get_status(server.container_id)
            if actual == "running" and server.status != "running":
                server.status = "running"
                server.started_at = datetime.utcnow()
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
    }


@router.post("/{server_id}/start")
async def start_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Start a stopped server."""
    server = await get_server_with_permission_check(server_id, current_user, db)
    
    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_START)
    
    # Check if trying to start someone else's server
    if str(server.user_id) != str(current_user.id):
        checker.require(Permission.SERVERS_MANAGE)
    
    # Check volume quota before starting
    if server.volume_id and server.plan_id:
        from app.services.volume_service import VolumeService
        from app.services.plan_service import PlanService
        
        volume_service = VolumeService(db)
        plan_service = PlanService(db)
        plan = await plan_service.get_by_id(str(server.plan_id))
        
        if plan:
            quota_check = await volume_service.check_quota(str(server.volume_id), plan.disk_limit)
            if not quota_check["allowed"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=quota_check["reason"]
                )
    
    if server.container_id:
        try:
            actual_status = await spawner.get_status(server.container_id)
            if actual_status == "running":
                return {"message": "Server already running", "server_id": server_id, "status": "running"}
            
            if actual_status in ("unknown", "stopped"):
                from app.services.environment_service import EnvironmentService
                from app.services.plan_service import PlanService
                
                if actual_status == "unknown":
                    print(f"Container {server.container_id} not found, recreating...")
                else:
                    print(f"Container {server.container_id} is stopped, deleting and recreating...")
                    # Delete stale container to avoid broken mounts after reboots
                    try:
                        await spawner.delete(server.container_id)
                    except Exception as e:
                        print(f"Warning: failed to delete stale container: {e}")
                
                env_service = EnvironmentService(db)
                environment = await env_service.get_by_id(str(server.environment_id)) if server.environment_id else None
                plan_service = PlanService(db)
                plan = await plan_service.get_by_id(str(server.plan_id)) if server.plan_id else None
                
                # Get server owner's username, not current user's
                server_owner = server.user if hasattr(server, 'user') and server.user else current_user
                
                new_server = await spawner.spawn(
                    user_id=str(server.user_id),
                    username=server_owner.username,
                    server_name=server.name,
                    environment=environment.slug if environment else "dev",
                    environment_id=str(server.environment_id) if server.environment_id else None,
                    image=environment.image if environment else None,
                    cpu=plan.cpu_limit if plan else server.allocated_cpu,
                    memory=plan.memory_limit if plan else server.allocated_memory,
                    disk=plan.disk_limit if plan else server.allocated_disk,
                    volume_id=str(server.volume_id) if server.volume_id else None,
                    volume_mode=server.volume_mode,
                    server_id=str(server.id),
                )
                
                server.container_id = new_server.container_id
                server.image = new_server.image
                server.volume_id = new_server.volume_id
                server.volume_mode = new_server.volume_mode
                server.status = "running"
                server.started_at = datetime.utcnow()
                server.external_url = new_server.external_url
                
                # Increment volume server count
                if server.volume_id:
                    from app.services.volume_service import VolumeService
                    volume_service = VolumeService(db)
                    await volume_service.increment_server_count(str(server.volume_id))
                
                await db.commit()
                return {"message": "Server container recreated and started", "server_id": server_id, "status": "running"}
            
            success = await spawner.start(server.container_id)
            if not success:
                raise Exception("Failed to start container - check container logs")
            
            server.status = "running"
            server.started_at = datetime.utcnow()
            
            # Increment volume server count
            if server.volume_id:
                from app.services.volume_service import VolumeService
                volume_service = VolumeService(db)
                await volume_service.increment_server_count(str(server.volume_id))
            
            await db.commit()
            return {"message": "Server started", "server_id": server_id, "status": "running"}
        except Exception as e:
            import traceback
            print(f"Start server error: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start server: {str(e)}"
            )
    else:
        from app.services.environment_service import EnvironmentService
        from app.services.plan_service import PlanService
        
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
            # Get server owner's username via explicit query to avoid lazy loading issues
            from sqlalchemy import select as sa_select
            from app.models.user import User
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
                volume_id=str(server.volume_id) if server.volume_id else None,
                volume_mode=server.volume_mode,
                server_id=str(server.id),
            )
            
            server.container_id = new_server.container_id
            server.image = new_server.image
            server.volume_id = new_server.volume_id
            server.volume_mode = new_server.volume_mode
            server.status = "running"
            server.external_url = new_server.external_url
            server.started_at = datetime.utcnow()
            server.allocated_cpu = new_server.allocated_cpu
            server.allocated_memory = new_server.allocated_memory
            await db.commit()
            
            return {"message": "Server started", "server_id": server_id, "status": "running"}
        except Exception as e:
            import traceback
            print(f"Spawn server error: {traceback.format_exc()}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to spawn server: {str(e)}"
            )


@router.post("/{server_id}/stop")
async def stop_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Stop a server."""
    server = await get_server_with_permission_check(server_id, current_user, db)

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_STOP)

    # Check if trying to stop someone else's server
    if str(server.user_id) != str(current_user.id):
        checker.require(Permission.SERVERS_MANAGE)

    if server.container_id:
        try:
            actual_status = await spawner.get_status(server.container_id)
            if actual_status == "stopped" or actual_status == "unknown":
                server.status = "stopped"
                server.container_id = None
                await db.commit()
                return {"message": "Server already stopped", "server_id": server_id, "status": "stopped"}

            # Delete container to remove Traefik route so frontend catch-all handles it
            await spawner.delete(server.container_id)
            server.container_id = None
            server.status = "stopped"
            server.stopped_at = datetime.utcnow()
            
            # Decrement quota usage
            if server.plan_id:
                from app.services.quota_service import QuotaService
                quota_service = QuotaService(db)
                await quota_service.decrement_usage(
                    user_id=str(server.user_id),
                    plan_id=str(server.plan_id)
                )
            
            # Decrement volume server count
            if server.volume_id:
                from app.services.volume_service import VolumeService
                volume_service = VolumeService(db)
                await volume_service.decrement_server_count(str(server.volume_id))
            
            await db.commit()
            return {"message": "Server stopped", "server_id": server_id, "status": "stopped"}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to stop server: {str(e)}"
            )

    server.status = "stopped"
    await db.commit()
    return {"message": "Server stopped", "server_id": server_id, "status": "stopped"}


@router.post("/{server_id}/restart")
async def restart_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Restart a server."""
    server = await get_server_with_permission_check(server_id, current_user, db)
    
    checker = PermissionChecker(current_user)
    checker.require_any([Permission.SERVERS_STOP, Permission.SERVERS_START])
    
    # Check if trying to restart someone else's server
    if str(server.user_id) != str(current_user.id):
        checker.require(Permission.SERVERS_MANAGE)
    
    # Check volume quota before restarting
    if server.volume_id and server.plan_id:
        from app.services.volume_service import VolumeService
        from app.services.plan_service import PlanService
        
        volume_service = VolumeService(db)
        plan_service = PlanService(db)
        plan = await plan_service.get_by_id(str(server.plan_id))
        
        if plan:
            quota_check = await volume_service.check_quota(str(server.volume_id), plan.disk_limit)
            if not quota_check["allowed"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=quota_check["reason"]
                )
    
    if server.container_id:
        try:
            actual_status = await spawner.get_status(server.container_id)
            if actual_status == "unknown":
                from app.services.environment_service import EnvironmentService
                from app.services.plan_service import PlanService
                
                print(f"Container {server.container_id} not found, recreating...")
                
                env_service = EnvironmentService(db)
                environment = await env_service.get_by_id(str(server.environment_id)) if server.environment_id else None
                plan_service = PlanService(db)
                plan = await plan_service.get_by_id(str(server.plan_id)) if server.plan_id else None
                
                # Get server owner's username via explicit query to avoid lazy loading issues
                from sqlalchemy import select as sa_select
                from app.models.user import User
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
                    volume_id=str(server.volume_id) if server.volume_id else None,
                    volume_mode=server.volume_mode,
                    server_id=str(server.id),
                )
                
                server.container_id = new_server.container_id
                server.image = new_server.image
                server.volume_id = new_server.volume_id
                server.volume_mode = new_server.volume_mode
                server.status = "running"
                server.started_at = datetime.utcnow()
                server.external_url = new_server.external_url
                await db.commit()
                return {"message": "Server container recreated and started", "server_id": server_id, "status": "running"}
            
            await spawner.stop(server.container_id)
            await spawner.start(server.container_id)
            server.status = "running"
            server.started_at = datetime.utcnow()
            await db.commit()
            return {"message": "Server restarted", "server_id": server_id, "status": "running"}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restart server: {str(e)}"
            )
    
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No container associated with this server"
    )


@router.delete("/{server_id}")
async def delete_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a server."""
    server = await get_server_with_permission_check(server_id, current_user, db)
    
    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_DELETE)
    
    # Check if trying to delete someone else's server
    if str(server.user_id) != str(current_user.id):
        checker.require(Permission.SERVERS_MANAGE)
    
    if server.container_id:
        try:
            await spawner.delete(server.container_id)
        except Exception as e:
            # Log but continue to delete from DB
            print(f"Warning: Failed to delete container: {e}")
    
    # Decrement volume server count
    if server.volume_id:
        from app.services.volume_service import VolumeService
        volume_service = VolumeService(db)
        await volume_service.decrement_server_count(str(server.volume_id))
    
    # Delete associated credit transactions to avoid FK constraint
    from app.models.credit_transaction import CreditTransaction
    from sqlalchemy import delete
    await db.execute(
        delete(CreditTransaction).where(CreditTransaction.server_id == server.id)
    )
    
    await db.delete(server)
    await db.commit()
    
    return {"message": "Server deleted", "server_id": server_id}


@router.post("/{server_id}/test-metric")
async def test_metric(
    server_id: str,
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update last_activity timestamp for a server. Called when user accesses the server."""
    server = await get_server_with_permission_check(server_id, current_user, db)
    
    if server.status != "running":
        raise HTTPException(status_code=400, detail="Server is not running")
    
    server.last_activity = datetime.utcnow()
    await db.commit()
    
    return {"message": "Activity recorded", "server_id": server_id, "last_activity": server.last_activity.isoformat()}


@router.get("/{server_id}/queue-status")
async def get_server_queue_status(
    server_id: str,
    current_user: User = Depends(get_current_user),
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
    tail: int = 100,
    since: Optional[str] = None,
    follow: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get server container logs."""
    server = await get_server_with_permission_check(server_id, current_user, db)
    
    if not server.container_id:
        raise HTTPException(status_code=400, detail="Server has no running container")
    
    try:
        # Parse since timestamp
        since_timestamp = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
                since_timestamp = int(since_dt.timestamp())
            except ValueError:
                pass
        
        logs = await spawner.docker.get_container_logs(
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
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get logs: {str(e)}"
        )


# ── Server Access Token Endpoints ────────────────────────────────────────────

class ServerAccessTokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"
    server_id: str


@router.post("/{server_id}/access-token")
async def create_server_access_token(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate a short-lived access token for direct server access.
    
    Returns the token as an HttpOnly cookie for secure browser access.
    The cookie is scoped to path=/ and expires with the token (5 minutes default).
    """
    server = await get_server_with_permission_check(server_id, current_user, db)
    
    if server.status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Server must be running to generate access token"
        )
    
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
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate access token: {str(e)}"
        )


@router.get("/{server_id}/access-stats")
async def get_server_access_stats(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get access statistics for a server."""
    server = await get_server_with_permission_check(server_id, current_user, db)
    from app.services.server_auth_service import server_auth_service
    stats = await server_auth_service.get_server_access_stats(db, server.id)
    return {"server_id": server_id, **stats}
