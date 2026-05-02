from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings
from app.api import (
    auth, users, servers, tokens, credits, admin, 
    preferences, environments, plans, quotas, metrics,
    notifications, dashboard, bulk, health, system
)
from app.db.base import Base
from app.db.session import engine
from app.websocket.metrics_socket import manager

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=settings.app_name,
    description="NukeLab Platform v2.0 API",
    version="2.0.0",
    debug=settings.app_debug,
    root_path="/api",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

@app.exception_handler(429)
async def rate_limit_exceeded_handler(request: Request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"}
    )

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_debug else [settings.app_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(servers.router, prefix="/servers", tags=["servers"])
app.include_router(tokens.router, prefix="/tokens", tags=["tokens"])
app.include_router(credits.router, prefix="/credits", tags=["credits"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(preferences.router, prefix="/preferences", tags=["preferences"])
app.include_router(environments.router, prefix="/environments", tags=["environments"])
app.include_router(plans.router, prefix="/plans", tags=["plans"])
app.include_router(quotas.router, prefix="/quotas", tags=["quotas"])
app.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(bulk.router, prefix="/bulk", tags=["bulk"])
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(system.router, prefix="/system", tags=["system"])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time metrics"""
    await manager.handle_connection(websocket)


@app.on_event("startup")
async def startup():
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Seed default data
    try:
        from app.db.seed import seed_all
        await seed_all()
    except Exception as e:
        print(f"Warning: Failed to seed data: {e}")
    
    # Start Redis listener for metrics broadcasting
    try:
        import asyncio
        asyncio.create_task(manager.start_redis_listener())
    except Exception as e:
        print(f"Warning: Failed to start Redis listener: {e}")


@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.app_name} API", "version": "2.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
