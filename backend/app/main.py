from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from app.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.sentry import init_sentry
from app.core.tracing import init_tracing, is_tracing_enabled

logger = get_logger(__name__)
from app.api import (
    auth, users, servers, tokens, credits, admin,
    preferences, environments, plans, quotas, metrics,
    notifications, dashboard, bulk, health, system, schedules, volumes, analytics, workspaces,
    ip_restriction
)
from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.websocket.metrics_socket import manager
from app.core.shutdown import get_shutdown_coordinator
from app.middleware.request_metrics import _metrics_buffer


async def startup():
    """Application startup logic (tables, seeding, background tasks)."""
    configure_logging()
    init_tracing()
    init_sentry()

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure partitions exist for time-series tables (safety net if Celery Beat is down)
    try:
        from app.db.partitioning import PartitionManager
        async with AsyncSessionLocal() as db:
            pm = PartitionManager(db)
            for table in pm.PARTITION_CONFIG:
                await pm.ensure_partitions(table, months_ahead=3)
            await db.commit()
    except Exception as e:
        logger.warning(f"Failed to ensure partitions: {e}")

    # Seed default data
    try:
        from app.db.seed import seed_all
        await seed_all()
    except Exception as e:
        logger.warning(f"Failed to seed data: {e}")

    # Load dynamic system settings from database
    try:
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

    coordinator = get_shutdown_coordinator()

    # Start Redis listener for metrics broadcasting
    try:
        import asyncio
        redis_task = asyncio.create_task(manager.start_redis_listener())
        coordinator.register_background_task(redis_task)
    except Exception as e:
        logger.warning(f"Failed to start Redis listener: {e}")

    # Start periodic refresh token cleanup (prevents unbounded growth at scale)
    try:
        import asyncio
        from app.api.auth import run_periodic_refresh_token_cleanup
        cleanup_task = asyncio.create_task(run_periodic_refresh_token_cleanup())
        coordinator.register_background_task(cleanup_task)
    except Exception as e:
        logger.warning(f"Failed to start refresh token cleanup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events (startup / shutdown)."""
    await startup()
    yield
    # Graceful shutdown
    from app.core.redis_client import get_redis_client
    coordinator = get_shutdown_coordinator()
    await coordinator.shutdown(
        websocket_manager=manager,
        metrics_buffer=_metrics_buffer,
        db_engine=engine,
        redis_client=get_redis_client(),
    )


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


from app.middleware.request_size_limit import RequestBodyTooLarge
from app.middleware.tracing import TracingEnrichmentMiddleware


@app.exception_handler(RequestBodyTooLarge)
async def request_body_too_large_handler(request: Request, exc: RequestBodyTooLarge):
    """Convert RequestBodyTooLarge into a clean 413 response."""
    return JSONResponse(
        status_code=413,
        content={
            "detail": f"Request body too large. Maximum allowed is {exc.max_size} bytes.",
            "max_size": exc.max_size,
        },
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

# Request body size limit (runs first — rejects oversized payloads before any processing)
from app.middleware.request_size_limit import RequestSizeLimitMiddleware
app.add_middleware(RequestSizeLimitMiddleware, max_size=settings.max_request_body_size)

# CORS — strict in production, permissive but safe in development
_cors_origins_list = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

if settings.app_debug:
    # Debug mode: use configured origins (default includes localhost dev servers).
    # Wildcard + credentials is invalid per CORS spec, so we avoid it.
    _cors_origins = list(_cors_origins_list)
    # Auto-include frontend_url if set (e.g., Vite dev server on a non-standard port)
    frontend_origin = settings.frontend_url.rstrip("/") if settings.frontend_url else ""
    if frontend_origin and frontend_origin not in _cors_origins:
        _cors_origins.append(frontend_origin)
    _cors_methods = ["*"]
    _cors_headers = ["*"]
    _cors_credentials = settings.cors_allow_credentials
else:
    # Production: explicit whitelist only
    _cors_origins = _cors_origins_list
    _cors_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    _cors_headers = [
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "X-Correlation-ID",
        "X-CSRF-Token",
    ]
    _cors_credentials = settings.cors_allow_credentials

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=_cors_methods,
    allow_headers=_cors_headers,
    expose_headers=["X-Correlation-ID"],
    max_age=settings.cors_max_age,
)

# OpenTelemetry span enrichment (runs inside the span created by FastAPIInstrumentor)
app.add_middleware(TracingEnrichmentMiddleware)

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
    from app.core.shutdown import is_shutting_down
    from fastapi.responses import JSONResponse

    if is_shutting_down():
        return JSONResponse(
            status_code=503,
            content={"status": "shutting_down", "message": "Server is shutting down"}
        )

    if settings.maintenance_mode:
        return JSONResponse(
            status_code=503,
            content={
                "status": "maintenance",
                "message": settings.maintenance_message
            }
        )
    return {"status": "healthy"}


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    """Prometheus metrics endpoint.

    This endpoint is intentionally unauthenticated at the application layer.
    External access is gated by Traefik ForwardAuth on /api/metrics; Prometheus
    scrapes the backend container directly inside the Docker network.
    """
    if not settings.prometheus_enabled:
        raise HTTPException(status_code=404, detail="Prometheus metrics disabled")

    from app.core.prometheus_metrics import get_metrics_output

    data, content_type = await get_metrics_output()
    return Response(content=data, media_type=content_type)


# Apply OpenTelemetry instrumentation after all middleware and routes are registered.
# This places the OTel middleware outermost so every other middleware runs inside
# the request span. Skip entirely when tracing is disabled to avoid any overhead.
# Initialize the tracer provider before instrumenting so the middleware gets a
# real tracer rather than a no-op one.
init_tracing()
if is_tracing_enabled():
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/api/health,/api/metrics,/api/docs,/api/openapi.json",
    )
