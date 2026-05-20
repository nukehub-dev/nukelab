"""
Health and Status API endpoints.
"""

import asyncio
import time
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import redis.asyncio as redis
import psutil

from app.api.auth import require_scopes, get_current_user, require_jwt_auth
from app.core.permissions import Permission
from app.dependencies import require_permissions
from app.db.session import get_db
from app.config import settings

router = APIRouter()


@router.get("/")
async def health_check():
    """Basic health check"""
    return {"status": "healthy", "timestamp": time.time()}


@router.get("/detailed")
async def detailed_health_check(
    _jwt = Depends(require_jwt_auth()),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permissions(Permission.ADMIN_ACCESS))
):
    """Detailed health check with service status"""
    
    health_data = {
        "status": "healthy",
        "timestamp": time.time(),
        "services": {},
        "resources": {}
    }
    
    # Database check
    try:
        start = time.time()
        await db.execute(text("SELECT 1"))
        db_latency = (time.time() - start) * 1000
        health_data["services"]["database"] = {
            "status": "healthy",
            "latency_ms": round(db_latency, 2)
        }
    except Exception as e:
        health_data["services"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_data["status"] = "degraded"
    
    # Redis check
    try:
        start = time.time()
        redis_client = redis.from_url(settings.redis_url)
        await redis_client.ping()
        redis_latency = (time.time() - start) * 1000
        await redis_client.close()
        health_data["services"]["redis"] = {
            "status": "healthy",
            "latency_ms": round(redis_latency, 2)
        }
    except Exception as e:
        health_data["services"]["redis"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_data["status"] = "degraded"
    
    # Docker check
    try:
        from app.docker.client import docker_client
        version = await docker_client.version()
        health_data["services"]["docker"] = {
            "status": "healthy",
            "version": version.get("Version", "unknown")
        }
    except Exception as e:
        health_data["services"]["docker"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_data["status"] = "degraded"
    
    # SMTP check
    try:
        from app.services.email_service import EmailService
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
                "port": email_service.smtp_port
            }
        else:
            health_data["services"]["smtp"] = {
                "status": "disabled",
                "message": "SMTP not configured"
            }
    except Exception as e:
        health_data["services"]["smtp"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_data["status"] = "degraded"
    
    # System resources
    try:
        health_data["resources"] = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent,
            "load_average": psutil.getloadavg()
        }
    except Exception:
        health_data["resources"] = {
            "cpu_percent": 0,
            "memory_percent": 0,
            "disk_percent": 0
        }
    
    return health_data


@router.get("/status")
async def platform_status():
    """Get platform status and feature flags"""
    from app.services.oauth_service import oauth_service
    
    return {
        "version": "2.0.0",
        "features": {
            "auth_mode": settings.auth_mode,
            "oauth_enabled": oauth_service.is_configured and settings.auth_mode in ("oauth", "both"),
            "oauth_provider_name": settings.oauth_provider_name if oauth_service.is_configured else None,
            "registration_enabled": True,  # TODO: Add to settings
            "credit_system_enabled": True,
            "websocket_enabled": True,
            "gravatar_enabled": True,
            "themes_enabled": True,
            "notifications_enabled": True
        },
        "limits": {
            "max_servers_per_user": 10,  # TODO: Add to settings
            "max_file_upload_size": 10485760,  # 10MB
            "api_rate_limit": 1000  # requests per hour
        }
    }