"""
Audit middleware for automatic activity logging.
"""

import uuid
from typing import Any

import jwt
from fastapi import Request, Response
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings
from app.core.context import correlation_id
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.user import User

logger = get_logger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Middleware that automatically logs state-changing requests.
    Captures: actor_id, action, target_type, target_id, IP, user_agent,
    before_state, after_state
    """

    # Skip these paths
    SKIP_PATHS = [
        "/api/health",
        "/api/docs",
        "/api/openapi.json",
        "/api/ws",
        "/api/metrics",
    ]

    # Skip these methods
    SKIP_METHODS = ["GET", "HEAD", "OPTIONS"]

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # Skip if method or path should not be logged
        if request.method in self.SKIP_METHODS:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(skip) for skip in self.SKIP_PATHS):
            return await call_next(request)

        # Capture before state for PUT/DELETE
        before_state = {}
        if request.method in ["PUT", "DELETE"]:
            before_state = await self._capture_before_state(request)

        # Process request
        response = await call_next(request)

        # Log after response (for successful requests)
        if response.status_code < 400:
            try:
                await self._log_activity(request, response, before_state)
            except Exception:
                # Don't fail the request if logging fails
                logger.exception("Audit logging error")

        return response

    async def _capture_before_state(self, request: Request) -> dict[str, Any]:
        """Capture state before modification"""
        path = request.url.path

        # Try to extract target info from path
        # e.g., /api/users/{id} or /api/servers/{id}
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "api":
            target_type = parts[1]
            target_id = parts[2] if len(parts) > 2 else None

            if target_id:
                try:
                    # Try to fetch the record before modification
                    return await self._fetch_record(target_type, target_id)
                except Exception:
                    pass

        return {}

    async def _fetch_record(self, target_type: str, target_id: str) -> dict[str, Any]:
        """Fetch record from database before modification"""
        async with AsyncSessionLocal() as db:
            if target_type == "users":
                from app.models.user import User

                result = await db.execute(select(User).where(User.id == uuid.UUID(target_id)))
                user = result.scalar_one_or_none()
                if user:
                    return {
                        "id": str(user.id),
                        "username": user.username,
                        "email": user.email,
                        "role": user.role,
                        "is_active": user.is_active,
                    }
            elif target_type == "servers":
                from app.models.server import Server

                result = await db.execute(select(Server).where(Server.id == uuid.UUID(target_id)))
                server = result.scalar_one_or_none()
                if server:
                    return {
                        "id": str(server.id),
                        "name": server.name,
                        "status": server.status,
                        "plan_id": str(server.plan_id) if server.plan_id else None,
                    }

        return {}

    async def _get_user_from_token(self, request: Request) -> User | None:
        """Decode JWT from Authorization header to get the user."""
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            username = payload.get("sub")
            if not username:
                return None
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(User).where(User.username == username))
                return result.scalar_one_or_none()
        except jwt.InvalidTokenError:
            return None

    def _get_auth_info(self, request: Request) -> dict[str, Any]:
        """Extract authentication method and scopes from request state."""
        auth_context = getattr(request.state, "auth_context", None)
        if not auth_context:
            return {"auth_method": "anonymous"}
        info = {"auth_method": auth_context.auth_method}
        if auth_context.auth_method == "api_token":
            info["token_scopes"] = auth_context.token_scopes
            info["api_token_id"] = auth_context.api_token_id
        return info

    async def _log_activity(
        self, request: Request, response: Response, before_state: dict[str, Any]
    ):
        """Log the activity"""

        # Get user from JWT token in Authorization header
        user = await self._get_user_from_token(request)
        user_id = str(user.id) if user else None

        # Extract target info from path
        path = request.url.path
        parts = path.strip("/").split("/")

        target_type = "unknown"
        target_id = None
        action = request.method.lower()

        if len(parts) >= 2 and parts[0] == "api":
            target_type = parts[1]
            if len(parts) >= 3:
                try:
                    target_id = uuid.UUID(parts[2])
                except ValueError:
                    target_id = None

            # Refine action based on HTTP method and path
            if request.method == "POST":
                if len(parts) > 3:
                    action = f"{parts[3]}_{target_type}"
                elif len(parts) == 3 and target_id is None:
                    # e.g., /api/users/bulk-action where parts[2] is not a UUID
                    action = f"{parts[2]}_{target_type}"
                else:
                    action = f"create_{target_type}"
            elif request.method == "PUT":
                action = f"update_{target_type}"
            elif request.method == "DELETE":
                action = f"delete_{target_type}"

        # Get client info
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        # Build details
        details = {
            "method": request.method,
            "path": path,
            "status_code": response.status_code,
        }

        # Enrich with auth info
        details.update(self._get_auth_info(request))

        # Enrich with actor info if available
        if user:
            details["actor_username"] = user.username
            details["actor_role"] = user.role
            if user.email:
                details["actor_email"] = user.email

        # Get correlation ID from context
        cid = correlation_id.get("")
        request_id = uuid.UUID(cid) if cid else None

        # Log to database
        async with AsyncSessionLocal() as db:
            log = ActivityLog(
                actor_id=uuid.UUID(user_id) if user_id else None,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details,
                before_state=before_state,
                after_state={},  # Would need to capture after state
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
            )
            db.add(log)
            await db.commit()
