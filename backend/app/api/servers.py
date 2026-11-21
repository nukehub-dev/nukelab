# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Server API endpoints with RBAC and ownership enforcement.
"""

import logging
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, limiter
from app.config import settings
from app.container.driver import ContainerDriverError
from app.container.factory import get_driver
from app.container.spawner import spawner
from app.core.cache import (
    cache_delete,
    cache_delete_tracked,
    cache_get_or_set,
)
from app.core.permissions import Permission
from app.core.security import has_any_permission
from app.db.session import get_db
from app.dependencies import PermissionChecker, require_permissions
from app.models.server import Server
from app.models.user import User
from app.schemas.server_queue import QueuedServerResponse
from app.services.activity_service import ActivityService
from app.services.environment_revision_service import ConfigurationChanged, RevisionUnavailable
from app.services.notification_service import NotificationService, broadcast_server_status_change
from app.services.server_launch_service import LaunchError, ServerLaunchService
from app.services.server_launch_validation import LaunchValidationError, normalize_launch_request
from app.services.server_lifecycle_service import ServerLifecycleService
from app.services.server_operation_service import ServerOperationError
from app.services.server_queue_service import QueueError
from app.services.server_termination_service import ServerTerminationService
from app.services.volume_operation_service import VolumeOperationError

logger = logging.getLogger(__name__)

router = APIRouter()

# Cache TTL for server lists (seconds)
_SERVER_LIST_CACHE_TTL = 30


def _server_list_cache_key(user_id: str) -> str:
    return f"servers:list:user:{user_id}"


def _admin_server_list_cache_key(
    page: int, limit: int, status: str | None, user_id: str | None
) -> str:
    return f"servers:list:admin:{page}:{limit}:{status or 'all'}:{user_id or 'all'}"


async def _invalidate_server_list_cache(user_id: str) -> None:
    """Invalidate cached server lists for a specific user and all admin lists."""
    await cache_delete(_server_list_cache_key(user_id))
    await cache_delete_tracked("servers:list:admin:keys")


def _set_server_expiry(server: Server, user: User) -> None:
    """Set or clear server.expires_at based on the user's max_server_runtime preference."""
    prefs = user.preferences or {}

    # If the user has disabled the runtime limit, clear any existing expiry.
    if not prefs.get("max_server_runtime_enabled", True):
        server.expires_at = None
        return

    max_runtime_minutes = prefs.get("max_server_runtime")
    if max_runtime_minutes is None:
        max_runtime_seconds = settings.server_max_runtime
    else:
        try:
            max_runtime_seconds = int(max_runtime_minutes) * 60
        except (TypeError, ValueError):
            max_runtime_seconds = settings.server_max_runtime

    if max_runtime_seconds > 0:
        server.expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
            seconds=max_runtime_seconds
        )
    else:
        server.expires_at = None


def _server_gpu_count(server: Server, plan) -> int:
    """GPU units a server needs: plan limit when known, else recorded allocation."""
    return (plan.gpu_limit or 0) if plan else (server.allocated_gpu or 0)


async def _gpu_requires_recreate(db: AsyncSession, server: Server, plan=None) -> bool:
    """True when a server must recreate its container instead of plain-starting it.

    A stopped container keeps its original GPU DeviceRequests baked in, but
    its exclusive gpu_allocations rows may have been released (stop-without-
    delete paths, or reconcile() reaping) and the device reassigned. Plain-
    starting would run two containers on one physical GPU despite exclusive
    mode, so GPU servers always go through spawner.spawn when the allocator
    is enabled. Non-GPU servers and allocator-disabled mode keep the cheap
    plain-start behavior.
    """
    from app.services.gpu_allocator import GpuAllocatorService

    if not GpuAllocatorService(db).enabled():
        return False
    return _server_gpu_count(server, plan) > 0


async def _respawn_server_container(
    server: Server, db: AsyncSession, fallback_username: str
) -> Server:
    return await ServerLifecycleService(db, await get_driver()).restart(server.id)


async def _ensure_gpu_devices(db: AsyncSession, server_id: str, gpu_count: int) -> list[str] | None:
    """Ensure a server holds ``gpu_count`` exclusive GPU devices.

    Returns the reserved CDI device names to forward to spawner.spawn, or
    None when the allocator is disabled or no GPU is needed (legacy shared
    mode). Raises HTTP 429 when the exclusive pool is exhausted.
    """
    from app.services.gpu_allocator import GpuAllocatorService

    allocator = GpuAllocatorService(db)
    if not allocator.enabled() or gpu_count <= 0:
        return None

    devices = await allocator.devices_for(server_id)
    if not devices:
        devices = await allocator.allocate(server_id, gpu_count)
        if devices is None:
            raise HTTPException(
                status_code=429,
                detail="No GPUs available on the host (all devices are in use). Please try again later.",
            )
    return devices


async def _release_gpu_devices(db: AsyncSession, server_id: str) -> None:
    """Release a server's exclusive GPU devices. Idempotent; never raises so
    stop/delete paths cannot be blocked by allocator errors (reconcile() is
    the safety net)."""
    try:
        from app.services.gpu_allocator import GpuAllocatorService

        await GpuAllocatorService(db).release(server_id)
    except Exception:
        logger.exception("Failed to release GPU devices for server %s", server_id)


class VolumeMountRequest(BaseModel):
    volume_id: str
    mount_path: str = "/data"
    mode: str = "read_write"  # read_write, read_only
    max_size_bytes: int | None = None  # For auto-created volumes when volume_id is empty


# Docker-compatible name pattern used for container and volume names
_SERVER_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


class ServerCreateRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$",
        description="Server name must start with alphanumeric and contain only letters, numbers, underscores, and hyphens",
    )
    plan_id: str
    environment_id: str
    volume_id: str | None = None  # Deprecated: use volume_mounts
    volume_mode: str | None = "read_write"  # Deprecated: use volume_mounts
    volume_mounts: list[VolumeMountRequest] | None = None


class ServerUpdateRequest(BaseModel):
    name: str | None = None
    plan_id: str | None = None
    environment_id: str | None = None
    volume_mounts: list[VolumeMountRequest] | None = None
    reason: str | None = None


class ReasonRequest(BaseModel):
    reason: str | None = None


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
    allocated_gpu: int | None = None
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
    admin_permissions: list[str] | None = None,
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
    result = await db.execute(select(Server).where(Server.id == server_id))
    server = result.scalar_one_or_none()

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    if require_ownership and str(server.user_id) != str(current_user.id):
        # Cross-user access requires JWT authentication — API tokens are not allowed
        auth_context = getattr(request.state, "auth_context", None)
        if not auth_context or auth_context.auth_method != "jwt":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-user server access requires JWT authentication. Please log in via the web interface.",
            )
        checker = PermissionChecker(current_user)
        perms_to_check = admin_permissions or [Permission.SERVERS_ACCESS_OTHERS]
        checker.require_any(perms_to_check)

    return server


async def _audit_cross_user_access(
    server: Server, current_user: User, db: AsyncSession, action: str, reason: str | None = None
):
    """Log audit trail and notify owner when admin accesses another user's server.
    Raises 400 if reason is not provided for cross-user access."""
    if str(server.user_id) == str(current_user.id):
        return

    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A reason is required for cross-user server access",
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

    result = await db.execute(select(ServerVolume).where(ServerVolume.server_id == server_id))
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
    for vm in getattr(server, "volume_mounts", []) or []:
        mounts.append(
            {
                "volume_id": str(vm.volume_id),
                "mount_path": vm.mount_path,
                "mode": vm.mode,
                "is_primary": vm.is_primary,
                "volume": {
                    "id": str(vm.volume.id),
                    "name": vm.volume.name,
                    "display_name": vm.volume.display_name,
                    "size_bytes": vm.volume.size_bytes,
                }
                if vm.volume
                else None,
            }
        )
    return mounts


async def _get_server_volume_mounts(db: AsyncSession, server_id: str) -> list:
    """Load volume mounts for a server."""
    from sqlalchemy.orm import selectinload

    from app.models.server_volume import ServerVolume

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
            }
            if m.volume
            else None,
        }
        for m in mounts
    ]


def _launch_http_error(error):
    if isinstance(error, ValidationError):
        return HTTPException(status_code=422, detail={"code": "invalid_request"})
    code = getattr(error, "code", "recovery_required")
    status_code = getattr(error, "status_code", 409)
    if isinstance(error, ContainerDriverError):
        status_code = 503
    if isinstance(error, ConfigurationChanged):
        code = "configuration_changed"
    if isinstance(error, RevisionUnavailable):
        code = error.code
    detail = {"code": code}
    if isinstance(error, QueueError) and error.queue_id is not None:
        detail["queue_id"] = str(error.queue_id)
    return HTTPException(status_code=status_code, detail=detail)


_LAUNCH_ERRORS = (
    LaunchError,
    LaunchValidationError,
    QueueError,
    RevisionUnavailable,
    ConfigurationChanged,
    ServerOperationError,
    VolumeOperationError,
    ContainerDriverError,
    ValidationError,
)


async def _launch_response(server: Server, db):
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
        allocated_gpu=server.allocated_gpu,
        health_status=server.health_status,
        status_reason=server.status_reason,
        user_id=str(server.user_id),
        plan_id=str(server.plan_id) if server.plan_id else None,
        environment_id=str(server.environment_id) if server.environment_id else None,
        created_at=server.created_at.isoformat() if server.created_at else None,
        started_at=server.started_at.isoformat() if server.started_at else None,
        stopped_at=server.stopped_at.isoformat() if server.stopped_at else None,
    )


@router.post("/", response_model=ServerResponse, responses={202: {"model": QueuedServerResponse}})
@limiter.limit("10/minute")
async def create_server(
    request: Request,
    body: ServerCreateRequest,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Reserve a validated launch or return a typed, complete queued acceptance."""
    owner_id, username = current_user.id, current_user.username
    from app.services.environment_service import EnvironmentService
    from app.services.plan_service import PlanService

    plan = await PlanService(db).get_by_id(body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    if not plan.is_active:
        raise HTTPException(status_code=400, detail="Plan is not active")
    if not await PlanService(db).can_user_use_plan(body.plan_id, current_user.role, str(owner_id)):
        raise HTTPException(status_code=403, detail="Plan not available for your role")
    if await EnvironmentService(db).get_by_id(body.environment_id) is None:
        raise HTTPException(status_code=404, detail="Environment not found")
    try:
        normalized = normalize_launch_request(body, username=username)
        service = ServerLaunchService(db, await get_driver())
        outcome = await service.submit(owner_id, normalized)
    except _LAUNCH_ERRORS as error:
        raise _launch_http_error(error) from error
    if isinstance(outcome, QueuedServerResponse):
        return JSONResponse(status_code=202, content=outcome.model_dump(mode="json"))
    await _invalidate_server_list_cache(str(owner_id))
    return await _launch_response(outcome, db)


async def _observe_server_runtime(server: Server, db: AsyncSession) -> None:
    """Apply a runtime observation only if its source state is still authoritative."""
    if not server.container_id or server.status in ("starting", "stopping"):
        return
    server_id, container_id, version = server.id, server.container_id, server.updated_at
    try:
        actual = await spawner.get_status(container_id)
    except Exception:
        logger.warning("Runtime observation unavailable for server %s", server_id)
        return
    if actual not in ("running", "stopped", "paused", "exited"):
        return
    from sqlalchemy.orm import joinedload, selectinload

    from app.models.server_volume import ServerVolume
    from app.services.admission_service import acquire_admission_lock
    from app.services.server_operation_service import get_active

    if not db.in_transaction():
        await db.begin()
    await acquire_admission_lock(db)
    current = await db.scalar(
        select(Server)
        .where(Server.id == server_id)
        .options(
            joinedload(Server.user),
            selectinload(Server.volume_mounts).selectinload(ServerVolume.volume),
        )
        .with_for_update(of=Server)
        .execution_options(populate_existing=True)
    )
    if (
        current is not None
        and current.container_id == container_id
        and current.updated_at == version
        and current.status not in ("starting", "stopping")
        and await get_active(db, server_id) is None
    ):
        if actual == "running" and current.status != "running":
            current.status = "running"
            current.started_at = datetime.now(UTC).replace(tzinfo=None)
            current.stop_reason = current.stopped_at = None
        elif actual in ("stopped", "exited") and current.status == "running":
            current.status = "stopped"
            current.stopped_at = datetime.now(UTC).replace(tzinfo=None)
    # Release admission before the next network probe in a list response.
    await db.commit()


@router.get("/")
async def list_servers(
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """List servers. Users see own servers, admins see all.

    Results are cached for 10 seconds to reduce DB + Docker API load.
    Real-time status updates are delivered via WebSocket.
    """
    cache_key = _server_list_cache_key(str(current_user.id))

    async def _build_response():
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
                select(Server)
                .where(Server.user_id == current_user.id)
                .options(joinedload(Server.user))
                .options(selectinload(Server.volume_mounts).selectinload(ServerVolume.volume))
            )

        servers = result.unique().scalars().all()

        for s in servers:
            await _observe_server_runtime(s, db)

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
                    "allocated_gpu": s.allocated_gpu,
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

    return await cache_get_or_set(cache_key, _build_response, _SERVER_LIST_CACHE_TTL)


@router.get("/{server_id}")
async def get_server(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Get server details. Users can view own, admins can view any."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        request,
        admin_permissions=[Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )

    await _observe_server_runtime(server, db)

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
        "allocated_gpu": server.allocated_gpu,
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
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Get server by username and server name. Used by server gateway page."""
    from sqlalchemy.orm import joinedload

    result = await db.execute(
        select(Server)
        .join(User)
        .where(User.username == username, Server.name == server_name)
        .options(joinedload(Server.user))
    )
    server = result.scalar_one_or_none()

    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Permission check - users can only access their own unless admin
    if str(server.user_id) != str(current_user.id):
        checker = PermissionChecker(current_user)
        checker.require_any([Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS])

    # Sync status with actual container state
    await _observe_server_runtime(server, db)

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
        "allocated_gpu": server.allocated_gpu,
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
    server: Server, db: AsyncSession, current_user: User, server_id: str
) -> dict:
    import uuid

    owner_id, name = server.user_id, server.name
    try:
        result = await ServerLifecycleService(db, await get_driver()).start(uuid.UUID(server_id))
    except _LAUNCH_ERRORS as error:
        raise _launch_http_error(error) from error
    await NotificationService(db).server_started(
        user_id=owner_id, server_name=name, action_url=f"/servers/{server_id}"
    )
    await broadcast_server_status_change(owner_id, server_id, result.status)
    return {"message": "Server started", "server_id": server_id, "status": result.status}


async def _perform_server_stop(server: Server, db: AsyncSession, server_id: str) -> dict:
    import uuid

    from app.models.server_plan import ServerPlan
    from app.services.credit_service import CreditService

    owner_id, name = server.user_id, server.name
    try:
        result = await ServerTerminationService(db, await get_driver()).stop(uuid.UUID(server_id))
    except _LAUNCH_ERRORS as error:
        raise _launch_http_error(error) from error
    if result.plan_id:
        plan = await db.get(ServerPlan, result.plan_id)
        if plan is not None:
            await CreditService(db).reconcile_server_billing(result, plan)
            await db.commit()
    await NotificationService(db).server_stopped(
        user_id=owner_id, server_name=name, action_url=f"/servers/{server_id}"
    )
    await broadcast_server_status_change(owner_id, server_id, "stopped")
    return {"message": "Server stopped", "server_id": server_id, "status": "stopped"}


async def _perform_server_restart(
    server: Server, db: AsyncSession, current_user: User, server_id: str
) -> dict:
    import uuid

    owner_id = server.user_id
    try:
        result = await ServerLifecycleService(db, await get_driver()).restart(uuid.UUID(server_id))
    except _LAUNCH_ERRORS as error:
        raise _launch_http_error(error) from error
    await broadcast_server_status_change(owner_id, server_id, result.status)
    return {"message": "Server restarted", "server_id": server_id, "status": result.status}


async def _perform_server_delete(server: Server, db: AsyncSession, server_id: str) -> dict:
    import uuid

    owner_id, name = server.user_id, server.name
    try:
        await ServerTerminationService(db, await get_driver()).delete(uuid.UUID(server_id))
    except _LAUNCH_ERRORS as error:
        raise _launch_http_error(error) from error
    await NotificationService(db).server_deleted(
        user_id=owner_id, server_name=name, server_id=server_id
    )
    return {"message": "Server deleted", "server_id": server_id}


@router.post("/{server_id}/start")
async def start_server(
    server_id: str,
    http_request: Request,
    body: ReasonRequest = ReasonRequest(),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Start a stopped server."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        http_request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS])
        await _audit_cross_user_access(server, current_user, db, "server.start", body.reason)

    result = await _perform_server_start(server, db, current_user, server_id)
    await _invalidate_server_list_cache(str(server.user_id))
    return result


@router.post("/{server_id}/stop")
async def stop_server(
    server_id: str,
    http_request: Request,
    body: ReasonRequest = ReasonRequest(),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Stop a server."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        http_request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS])
        await _audit_cross_user_access(server, current_user, db, "server.stop", body.reason)

    result = await _perform_server_stop(server, db, server_id)
    await _invalidate_server_list_cache(str(server.user_id))
    return result


@router.post("/{server_id}/restart")
async def restart_server(
    server_id: str,
    http_request: Request,
    body: ReasonRequest = ReasonRequest(),
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Restart a server."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        http_request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS])
        await _audit_cross_user_access(server, current_user, db, "server.restart", body.reason)

    result = await _perform_server_restart(server, db, current_user, server_id)
    await _invalidate_server_list_cache(str(server.user_id))
    return result


@router.delete("/{server_id}")
async def delete_server(
    server_id: str,
    request: Request,
    reason: str | None = None,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Delete a server."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )

    checker = PermissionChecker(current_user)
    checker.require(Permission.SERVERS_WRITE_OWN)

    if str(server.user_id) != str(current_user.id):
        checker.require_any([Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS])
        await _audit_cross_user_access(server, current_user, db, "server.delete", reason)

    result = await _perform_server_delete(server, db, server_id)
    await _invalidate_server_list_cache(str(server.user_id))
    return result


@router.get("/{server_id}/volumes")
async def get_server_volumes(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Get volume mounts for a server."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        request,
        admin_permissions=[Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )
    return {"volume_mounts": await _get_server_volume_mounts(db, str(server.id))}


@router.patch("/{server_id}", response_model=ServerResponse)
async def update_server(
    server_id: str,
    http_request: Request,
    body: ServerUpdateRequest,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Apply an offline selection or recreate a running generation under admission."""
    import uuid

    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        http_request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )
    from app.models.environment_template import EnvironmentTemplate
    from app.models.server_plan import ServerPlan

    if body.plan_id is not None and await db.get(ServerPlan, body.plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    if (
        body.environment_id is not None
        and await db.get(EnvironmentTemplate, body.environment_id) is None
    ):
        raise HTTPException(status_code=404, detail="Environment not found")
    owner_id = server.user_id
    if str(owner_id) != str(current_user.id):
        await _audit_cross_user_access(server, current_user, db, "server.update", body.reason)
    try:
        result = await ServerLifecycleService(db, await get_driver()).update(
            uuid.UUID(server_id), body.model_dump(mode="json", exclude_unset=True)
        )
    except _LAUNCH_ERRORS as error:
        raise _launch_http_error(error) from error
    await _invalidate_server_list_cache(str(owner_id))
    return await _launch_response(result, db)


@router.post("/{server_id}/test-metric")
async def test_metric(
    server_id: str,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
):
    """Send a test metric via Redis pub/sub to verify WebSocket pipeline."""
    import json

    from app.core.redis_client import get_redis_client
    from app.websocket.metrics_socket import connections

    r = get_redis_client()

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

    metric_json = json.dumps(test_metric)
    try:
        # Publish to specific channel
        await r.publish(f"metrics:server:{server_id}", metric_json)
        # Also publish to global
        await r.publish("metrics:all", metric_json)
    except Exception:
        logger.exception("Failed to publish test metric")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish test metric",
        )

    # Check active WebSocket connections
    room = f"server:{server_id}"
    active_connections = len(connections.get(room, set()))
    all_rooms = list(connections.keys())

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
    _=Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
):
    """Update last_activity timestamp for a server. Called when user accesses the server."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        request,
        admin_permissions=[Permission.SERVERS_WRITE_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )

    if server.status != "running":
        raise HTTPException(status_code=400, detail="Server is not running")

    server.last_activity = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    await _invalidate_server_list_cache(str(server.user_id))

    return {
        "message": "Activity recorded",
        "server_id": server_id,
        "last_activity": server.last_activity.isoformat(),
    }


@router.get("/{server_id}/queue-status")
async def get_server_queue_status(
    server_id: str,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Get queue status for a server that is waiting in queue."""
    from app.models.server_queue import ServerQueue
    from app.services.resource_pool_service import ResourcePoolService

    result = await db.execute(
        select(ServerQueue)
        .where(ServerQueue.user_id == current_user.id, ServerQueue.status == "pending")
        .order_by(ServerQueue.requested_at.desc())
    )
    entries = result.scalars().all()

    if not entries:
        return {"queued": False, "entries": []}

    resource_pool = ResourcePoolService(db)

    queue_data = []
    for entry in entries:
        position = await resource_pool.get_queue_position(str(entry.id))
        queue_data.append(
            {
                "id": str(entry.id),
                "server_name": entry.server_name,
                "status": entry.status,
                "priority": entry.priority,
                "position": position,
                "requested_at": entry.requested_at.isoformat() if entry.requested_at else None,
            }
        )

    return {
        "queued": True,
        "entries": queue_data,
    }


@router.get("/{server_id}/logs")
async def get_server_logs(
    server_id: str,
    request: Request,
    tail: int = 100,
    since: str | None = None,
    follow: bool = False,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Get server container logs."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        request,
        admin_permissions=[Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS],
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
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                since_timestamp = int(since_dt.timestamp())
            except ValueError:
                pass

        logs = await spawner.container_client.get_container_logs(
            container_id=server.container_id,
            tail=tail,
            since=since_timestamp,
            timestamps=True,
            stdout=True,
            stderr=True,
        )

        return {
            "server_id": server_id,
            "logs": logs,
            "tail": tail,
            "follow": follow,
            "status": "running",
        }
    except ContainerDriverError:
        # Container not found or runtime error — return empty logs gracefully
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
            detail="Failed to retrieve logs. Please try again or contact support.",
        )


def _parse_ps_time(value: str) -> int:
    """Parse a ps TIME column ([[dd-]hh:]mm:ss) into seconds."""
    try:
        days = 0
        if "-" in value:
            day_part, value = value.split("-", 1)
            days = int(day_part)
        parts = [int(p) for p in value.split(":")]
        if len(parts) == 2:
            hours, minutes, seconds = 0, parts[0], parts[1]
        elif len(parts) == 3:
            hours, minutes, seconds = parts
        else:
            return 0
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    except (TypeError, ValueError):
        return 0


def _normalize_top_tasks(top: dict) -> list[dict]:
    """Zip Docker-top Titles/Processes into a stable task schema.

    Rows are produced with ps_args="aux" (USER PID %CPU %MEM VSZ RSS TTY STAT
    START TIME COMMAND) but are mapped by title so column order does not
    matter. Short/malformed rows are tolerated with defaults.

    Note: %CPU/%MEM are ps lifetime averages relative to the *host* — the
    frontend derives current usage from cpu_time_seconds deltas and RSS
    against the server's allocation instead.
    """

    def _float(cols: dict, key: str) -> float:
        try:
            return float(cols.get(key, 0))
        except (TypeError, ValueError):
            return 0.0

    def _int(cols: dict, key: str) -> int:
        try:
            return int(cols.get(key, 0))
        except (TypeError, ValueError):
            return 0

    titles = [str(t) for t in top.get("Titles", [])]
    tasks = []
    for row in top.get("Processes", []):
        cols = {titles[i]: row[i] for i in range(min(len(titles), len(row)))}
        time_raw = str(cols.get("TIME", ""))
        tasks.append(
            {
                "pid": _int(cols, "PID"),
                "user": str(cols.get("USER", "")),
                "cpu_percent": _float(cols, "%CPU"),
                "mem_percent": _float(cols, "%MEM"),
                # ps reports RSS in KiB
                "rss_bytes": _int(cols, "RSS") * 1024,
                "stat": str(cols.get("STAT", "")),
                "time": time_raw,
                # Cumulative CPU seconds — delta between polls yields the
                # process's current core usage.
                "cpu_time_seconds": _parse_ps_time(time_raw),
                "command": str(cols.get("COMMAND", "")),
            }
        )
    return tasks


@router.get("/{server_id}/tasks")
async def get_server_tasks(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """List running processes inside the server container (read-only)."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        request,
        admin_permissions=[Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )

    if not server.container_id:
        return {"server_id": server_id, "tasks": [], "status": "stopped"}

    try:
        top = await spawner.container_client.get_container_top(server.container_id, ps_args="aux")
        return {
            "server_id": server_id,
            "tasks": _normalize_top_tasks(top),
            "status": "running",
        }
    except ContainerDriverError:
        # Container not found or runtime error — degrade gracefully
        return {"server_id": server_id, "tasks": [], "status": "error"}
    except Exception:
        logger.exception("Server tasks retrieval failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve tasks. Please try again or contact support.",
        )


# ── Server Access Token Endpoints ────────────────────────────────────────────


class ServerAccessTokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"
    server_id: str


class ServerAccessTokenRequest(BaseModel):
    reason: str | None = None


@router.post("/{server_id}/access-token")
async def create_server_access_token(
    server_id: str,
    request: Request,
    body: ServerAccessTokenRequest,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_WRITE_OWN)),
    db: AsyncSession = Depends(get_db),
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
            detail="Server must be running to generate access token",
        )

    # Audit cross-user access (enforces reason for non-owners)
    await _audit_cross_user_access(server, current_user, db, "server_access", body.reason)

    from app.services.server_auth_service import server_auth_service

    if not server_auth_service.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server authentication is not enabled",
        )

    try:
        from app.middleware.ip_restriction import _get_client_ip

        client_ip = _get_client_ip(request)
        user_agent = request.headers.get("user-agent")

        # Accessing a server is a strong activity signal; refresh idle timeout.
        server.last_activity = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()

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
            detail="Rate limit exceeded. Please try again later.",
        )
    except Exception:
        logger.exception("Access token generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate access token. Please try again or contact support.",
        )


@router.get("/{server_id}/access-stats")
async def get_server_access_stats(
    server_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    _=Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
    db: AsyncSession = Depends(get_db),
):
    """Get access statistics for a server."""
    server = await get_server_with_permission_check(
        server_id,
        current_user,
        db,
        request,
        admin_permissions=[Permission.SERVERS_READ_ALL, Permission.SERVERS_ACCESS_OTHERS],
    )
    from app.services.server_auth_service import server_auth_service

    stats = await server_auth_service.get_server_access_stats(db, server.id)
    return {"server_id": server_id, **stats}
