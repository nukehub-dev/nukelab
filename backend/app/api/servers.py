"""
Server API endpoints with RBAC and ownership enforcement.
"""

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
    environment: str = "dev"
    cpu: float = 1.0
    memory: str = "2g"


class ServerResponse(BaseModel):
    id: str
    name: str
    status: str
    external_url: str
    created_at: str


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
    
    checker = PermissionChecker(current_user)
    
    # Check ownership or admin permission
    if require_ownership and str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_READ_ALL, Permission.SERVERS_MANAGE])
    
    return server


@router.get("/")
async def list_servers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List servers. Users see own servers, admins see all."""
    checker = PermissionChecker(current_user)
    
    if checker.is_admin():
        # Admin sees all servers
        result = await db.execute(select(Server))
    else:
        # User sees only own servers
        result = await db.execute(
            select(Server).where(Server.user_id == current_user.id)
        )
    
    servers = result.scalars().all()
    
    return {
        "servers": [
            {
                "id": str(s.id),
                "name": s.name,
                "status": s.status,
                "external_url": s.external_url,
                "user_id": str(s.user_id),
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in servers
        ]
    }


@router.post("/", response_model=ServerResponse)
async def create_server(
    request: ServerCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create and spawn a new server. Requires servers:start permission."""
    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_START)
    
    try:
        # Spawn the container
        server = await spawner.spawn(
            user_id=str(current_user.id),
            username=current_user.username,
            server_name=request.name,
            environment=request.environment,
            cpu=request.cpu,
            memory=request.memory,
        )
        
        # Save to database
        db.add(server)
        await db.commit()
        await db.refresh(server)
        
        return ServerResponse(
            id=str(server.id),
            name=server.name,
            status=server.status,
            external_url=server.external_url,
            created_at=server.created_at.isoformat() if server.created_at else None,
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to spawn server: {str(e)}"
        )


@router.get("/{server_id}")
async def get_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get server details. Users can view own, admins can view any."""
    server = await get_server_with_permission_check(server_id, current_user, db)
    
    return {
        "id": str(server.id),
        "name": server.name,
        "status": server.status,
        "container_id": server.container_id,
        "external_url": server.external_url,
        "allocated_cpu": server.allocated_cpu,
        "allocated_memory": server.allocated_memory,
        "started_at": server.started_at.isoformat() if server.started_at else None,
        "user_id": str(server.user_id),
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
            await spawner.start(server.container_id)
            server.status = "running"
            await db.commit()
            return {"message": "Server started", "server_id": server_id}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start server: {str(e)}"
            )
    else:
        # Recreate if no container_id
        return {"message": "Server recreation not yet implemented", "server_id": server_id}


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
            await spawner.stop(server.container_id)
            server.status = "stopped"
            await db.commit()
            return {"message": "Server stopped", "server_id": server_id}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to stop server: {str(e)}"
            )
    
    return {"message": "Server stopped", "server_id": server_id}


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
            await spawner.stop(server.container_id)
            await spawner.start(server.container_id)
            server.status = "running"
            await db.commit()
            return {"message": "Server restarted", "server_id": server_id}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to restart server: {str(e)}"
            )
    
    return {"message": "Server restart not available", "server_id": server_id}


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
