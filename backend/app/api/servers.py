"""
Server API endpoints with RBAC and ownership enforcement.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.api.auth import get_current_user
from app.core.permissions import Permission
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


class ServerResponse(BaseModel):
    id: str
    name: str
    status: str
    container_id: str | None = None
    external_url: str | None = None
    allocated_cpu: float | None = None
    allocated_memory: str | None = None
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
    
    try:
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
        )
        
        # Store plan reference
        server.plan_id = uuid.UUID(request.plan_id)
        
        # Save to database
        db.add(server)
        await db.commit()
        await db.refresh(server)
        
        return ServerResponse(
            id=str(server.id),
            name=server.name,
            status=server.status,
            container_id=server.container_id,
            external_url=server.external_url,
            allocated_cpu=server.allocated_cpu,
            allocated_memory=server.allocated_memory,
            health_status=server.health_status,
            status_reason=server.status_reason,
            user_id=str(server.user_id),
            created_at=server.created_at.isoformat() if server.created_at else None,
            started_at=server.started_at.isoformat() if server.started_at else None,
        )
        
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
    
    if checker.is_admin():
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
                "external_url": s.external_url,
                "allocated_cpu": s.allocated_cpu,
                "allocated_memory": s.allocated_memory,
                "health_status": s.health_status,
                "status_reason": s.status_reason,
                "user_id": str(s.user_id),
                "username": s.user.username if s.user else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "stopped_at": s.stopped_at.isoformat() if s.stopped_at else None,
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
        "external_url": server.external_url,
        "allocated_cpu": server.allocated_cpu,
        "allocated_memory": server.allocated_memory,
        "health_status": server.health_status,
        "status_reason": server.status_reason,
        "started_at": server.started_at.isoformat() if server.started_at else None,
        "stopped_at": server.stopped_at.isoformat() if server.stopped_at else None,
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
        "external_url": server.external_url,
        "allocated_cpu": server.allocated_cpu,
        "allocated_memory": server.allocated_memory,
        "health_status": server.health_status,
        "status_reason": server.status_reason,
        "started_at": server.started_at.isoformat() if server.started_at else None,
        "stopped_at": server.stopped_at.isoformat() if server.stopped_at else None,
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
    
    if server.container_id:
        try:
            actual_status = await spawner.get_status(server.container_id)
            if actual_status == "running":
                return {"message": "Server already running", "server_id": server_id, "status": "running"}
            
            if actual_status == "unknown":
                from app.services.environment_service import EnvironmentService
                from app.services.plan_service import PlanService
                
                print(f"Container {server.container_id} not found, recreating...")
                
                env_service = EnvironmentService(db)
                environment = await env_service.get_by_id(str(server.environment_id)) if server.environment_id else None
                plan_service = PlanService(db)
                plan = await plan_service.get_by_id(str(server.plan_id)) if server.plan_id else None
                
                new_server = await spawner.spawn(
                    user_id=str(server.user_id),
                    username=current_user.username,
                    server_name=server.name,
                    environment=environment.slug if environment else "dev",
                    environment_id=str(server.environment_id) if server.environment_id else None,
                    image=environment.image if environment else None,
                    cpu=plan.cpu_limit if plan else server.allocated_cpu,
                    memory=plan.memory_limit if plan else server.allocated_memory,
                    disk=plan.disk_limit if plan else server.allocated_disk,
                )
                
                server.container_id = new_server.container_id
                server.image = new_server.image
                server.status = "running"
                server.started_at = datetime.utcnow()
                server.external_url = new_server.external_url
                await db.commit()
                return {"message": "Server container recreated and started", "server_id": server_id, "status": "running"}
            
            success = await spawner.start(server.container_id)
            if not success:
                raise Exception("Failed to start container - check container logs")
            
            server.status = "running"
            server.started_at = datetime.utcnow()
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
            new_server = await spawner.spawn(
                user_id=str(server.user_id),
                username=current_user.username,
                server_name=server.name,
                environment=environment.slug,
                environment_id=str(server.environment_id),
                image=environment.image,
                cpu=plan.cpu_limit,
                memory=plan.memory_limit,
                disk=plan.disk_limit,
            )
            
            server.container_id = new_server.container_id
            server.image = new_server.image
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
                
                new_server = await spawner.spawn(
                    user_id=str(server.user_id),
                    username=current_user.username,
                    server_name=server.name,
                    environment=environment.slug if environment else "dev",
                    environment_id=str(server.environment_id) if server.environment_id else None,
                    image=environment.image if environment else None,
                    cpu=plan.cpu_limit if plan else server.allocated_cpu,
                    memory=plan.memory_limit if plan else server.allocated_memory,
                    disk=plan.disk_limit if plan else server.allocated_disk,
                )
                
                server.container_id = new_server.container_id
                server.image = new_server.image
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
    
    await db.delete(server)
    await db.commit()
    
    return {"message": "Server deleted", "server_id": server_id}
