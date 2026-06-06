from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)
from app.api import (
    auth, users, servers, tokens, credits, admin,
    preferences, environments, plans, quotas, metrics,
    notifications, dashboard, bulk, health, system, schedules, volumes, analytics, workspaces,
    ip_restriction
)
from app.db.base import Base
from app.db.session import engine
from app.websocket.metrics_socket import manager


async def startup():
    """Application startup logic (tables, seeding, background tasks)."""
    configure_logging()

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed default data
    try:
        from app.db.seed import seed_all
        await seed_all()
    except Exception as e:
        logger.warning(f"Failed to seed data: {e}")

    # Load dynamic system settings from database
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.setting_service import SettingService
        async with AsyncSessionLocal() as db:
            service = SettingService(db)
            await service.load_into_config()
    except Exception as e:
        logger.warning(f"Failed to load system settings from DB: {e}")

    # Load custom role permissions from database
    try:
        from app.core.roles import load_role_permissions_from_db
        await load_role_permissions_from_db()
    except Exception as e:
        logger.warning(f"Failed to load role permissions from DB: {e}")

    # Start Redis listener for metrics broadcasting
    try:
        import asyncio
        asyncio.create_task(manager.start_redis_listener())
    except Exception as e:
        logger.warning(f"Failed to start Redis listener: {e}")

    # Start periodic refresh token cleanup (prevents unbounded growth at scale)
    try:
        import asyncio
        from app.api.auth import run_periodic_refresh_token_cleanup
        asyncio.create_task(run_periodic_refresh_token_cleanup())
    except Exception as e:
        logger.warning(f"Failed to start refresh token cleanup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events (startup / shutdown)."""
    await startup()
    yield
    # Shutdown logic can be added here when needed


app = FastAPI(
    title=settings.app_name,
    description="NukeLab Platform v2.0 API",
    version="2.0.0",
    debug=settings.app_debug,
    root_path="/api",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

@app.exception_handler(429)
async def rate_limit_exceeded_handler(request: Request, exc):
    # Preserve the original error detail (quota reasons, rate limit info, etc.)
    detail = getattr(exc, 'detail', 'Rate limit exceeded')
    return JSONResponse(
        status_code=429,
        content={"detail": detail}
    )

# IP restriction middleware (runs first — blocks bad IPs at the edge)
from app.middleware.ip_restriction import IPRestrictionMiddleware
app.add_middleware(IPRestrictionMiddleware)

# Security headers middleware (exception-safe ASGI — runs early)
from app.core.security_headers_asgi import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

# CSRF protection middleware (runs before auth-dependent middleware)
from app.middleware.csrf import CSRFProtectMiddleware
app.add_middleware(CSRFProtectMiddleware)

# Maintenance middleware (must be before auth-dependent middleware)
from app.middleware.maintenance import MaintenanceMiddleware
app.add_middleware(MaintenanceMiddleware)

# Rate limit middleware (per-user, JWT-based — runs before expensive ops)
from app.middleware.rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# Request metrics middleware (captures total latency after rate limit)
from app.middleware.request_metrics import RequestMetricsMiddleware
app.add_middleware(RequestMetricsMiddleware)

# Audit middleware
from app.middleware.audit import AuditMiddleware
app.add_middleware(AuditMiddleware)

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
app.include_router(schedules.router, prefix="/schedules", tags=["schedules"])
app.include_router(volumes.router, prefix="/volumes", tags=["volumes"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
app.include_router(ip_restriction.router, prefix="/admin", tags=["admin"])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time metrics"""
    await manager.handle_connection(websocket)


@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.app_name} API", "version": "2.0.0"}


@app.get("/health")
async def health():
    if settings.maintenance_mode:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={
                "status": "maintenance",
                "message": settings.maintenance_message
            }
        )
    return {"status": "healthy"}
