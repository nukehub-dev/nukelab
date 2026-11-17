# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Verified launch history, sanitized export and explicit approved recreation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import limiter, require_scopes
from app.api.servers import (
    _LAUNCH_ERRORS,
    ServerResponse,
    _audit_cross_user_access,
    _invalidate_server_list_cache,
    _launch_http_error,
    _launch_response,
    get_server_with_permission_check,
)
from app.container.factory import get_driver
from app.core.permissions import Permission
from app.db.session import get_db
from app.dependencies import require_permissions
from app.models.user import User
from app.schemas.server_provenance import (
    RecreationPreviewResponse,
    RecreationSource,
    ServerProvenanceResponse,
    ServerRecreateRequest,
)
from app.schemas.server_queue import QueuedServerResponse
from app.services.server_launch_service import ServerLaunchService
from app.services.server_recreation_service import (
    ProvenanceError,
    ServerRecreationService,
)

router = APIRouter()
ReadActor = Annotated[
    User,
    Depends(require_permissions(Permission.SERVERS_READ_OWN, Permission.SERVERS_READ_ALL)),
]
WriteActor = Annotated[User, Depends(require_permissions(Permission.SERVERS_WRITE_OWN))]
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("/provenance-capabilities", dependencies=[Depends(require_scopes("servers:read"))])
async def provenance_capabilities(current_user: ReadActor):
    return {"enabled": True}


@router.post(
    "/recreate/validate",
    response_model=RecreationPreviewResponse,
    dependencies=[Depends(require_scopes("servers:read", "servers:manage"))],
)
async def validate_recreation(
    body: RecreationSource,
    current_user: WriteActor,
    _read_actor: ReadActor,
    response: Response,
    db: Database,
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await ServerRecreationService(db, current_user.id).preview(body)
    except (*_LAUNCH_ERRORS, ProvenanceError) as error:
        raise _launch_http_error(error) from error


@router.post(
    "/recreate",
    response_model=ServerResponse,
    responses={202: {"model": QueuedServerResponse}},
    dependencies=[Depends(require_scopes("servers:manage"))],
)
@limiter.limit("10/minute")
async def recreate_server(
    request: Request,
    body: ServerRecreateRequest,
    current_user: WriteActor,
    db: Database,
):
    owner_id = current_user.id
    try:
        normalized, revision_id = await ServerRecreationService(db, owner_id).prepare(body)
        outcome = await ServerLaunchService(db, await get_driver()).submit_pinned(
            owner_id, normalized, revision_id
        )
    except (*_LAUNCH_ERRORS, ProvenanceError) as error:
        raise _launch_http_error(error) from error
    if isinstance(outcome, QueuedServerResponse):
        return JSONResponse(status_code=202, content=outcome.model_dump(mode="json"))
    await _invalidate_server_list_cache(str(owner_id))
    return await _launch_response(outcome, db)


async def _history_owner(server_id, request, current_user, db, reason, action):
    server = await get_server_with_permission_check(
        str(server_id),
        current_user,
        db,
        request,
        admin_permissions=[
            Permission.SERVERS_READ_ALL,
            Permission.SERVERS_ACCESS_OTHERS,
        ],
    )
    owner_id = server.user_id
    await _audit_cross_user_access(server, current_user, db, action, reason)
    return owner_id


@router.get(
    "/{server_id}/provenance",
    response_model=ServerProvenanceResponse,
    dependencies=[Depends(require_scopes("servers:read"))],
)
async def get_provenance(
    server_id: UUID,
    request: Request,
    response: Response,
    current_user: ReadActor,
    db: Database,
    launch_id: UUID | None = None,
    reason: Annotated[str | None, Query(max_length=1000)] = None,
):
    actor_id = current_user.id
    owner_id = await _history_owner(
        server_id, request, current_user, db, reason, "server.provenance.read"
    )
    response.headers["Cache-Control"] = "private, no-store"
    try:
        result = await ServerRecreationService(db, actor_id).history(server_id, owner_id, launch_id)
    except (*_LAUNCH_ERRORS, ProvenanceError) as error:
        raise _launch_http_error(error) from error
    if result.can_recreate:
        try:
            await require_scopes("servers:manage")(request, current_user)
        except HTTPException as error:
            if error.status_code != 403:
                raise
            result = result.model_copy(
                update={"can_recreate": False, "recreation_reason_code": "insufficient_scope"}
            )
    return result


@router.get(
    "/{server_id}/environment-manifest",
    response_model=None,
    dependencies=[Depends(require_scopes("servers:read"))],
)
async def export_environment_manifest(
    server_id: UUID,
    request: Request,
    current_user: ReadActor,
    db: Database,
    launch_id: UUID | None = None,
    reason: Annotated[str | None, Query(max_length=1000)] = None,
):
    actor_id = current_user.id
    owner_id = await _history_owner(
        server_id, request, current_user, db, reason, "server.environment.export"
    )
    try:
        record_id, manifest = await ServerRecreationService(db, actor_id).export(
            server_id, owner_id, launch_id
        )
    except (*_LAUNCH_ERRORS, ProvenanceError) as error:
        raise _launch_http_error(error) from error
    return Response(
        manifest.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="nukelab-environment-{record_id}.json"',
            "Cache-Control": "private, no-store",
        },
    )
