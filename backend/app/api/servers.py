from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.api.auth import get_current_user
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

@router.get("/")
async def list_servers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List user's servers"""
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
    """Create and spawn a new server"""
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
    """Get server details"""
    result = await db.execute(
        select(Server).where(
            Server.id == server_id,
            Server.user_id == current_user.id
        )
    )
    server = result.scalar_one_or_none()
    
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    return {
        "id": str(server.id),
        "name": server.name,
        "status": server.status,
        "container_id": server.container_id,
        "external_url": server.external_url,
        "allocated_cpu": server.allocated_cpu,
        "allocated_memory": server.allocated_memory,
        "started_at": server.started_at.isoformat() if server.started_at else None,
    }

@router.post("/{server_id}/stop")
async def stop_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Stop a server"""
    result = await db.execute(
        select(Server).where(
            Server.id == server_id,
            Server.user_id == current_user.id
        )
    )
    server = result.scalar_one_or_none()
    
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    if server.container_id:
        await spawner.stop(server.container_id)
        server.status = "stopped"
        await db.commit()
    
    return {"message": "Server stopped", "server_id": server_id}

@router.post("/{server_id}/start")
async def start_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Start a stopped server"""
    result = await db.execute(
        select(Server).where(
            Server.id == server_id,
            Server.user_id == current_user.id
        )
    )
    server = result.scalar_one_or_none()
    
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    # For now, recreate the server if needed
    # In production, would start the existing container
    return {"message": "Server start not yet implemented", "server_id": server_id}

@router.delete("/{server_id}")
async def delete_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a server"""
    result = await db.execute(
        select(Server).where(
            Server.id == server_id,
            Server.user_id == current_user.id
        )
    )
    server = result.scalar_one_or_none()
    
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    if server.container_id:
        await spawner.delete(server.container_id)
    
    await db.delete(server)
    await db.commit()
    
    return {"message": "Server deleted", "server_id": server_id}
