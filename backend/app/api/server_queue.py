# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Owner-only queue discovery and pending cancellation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_scopes
from app.core.permissions import Permission
from app.db.session import get_db
from app.dependencies import require_permissions
from app.models.user import User
from app.schemas.server_queue import QueueEntryResponse, QueuePageResponse, QueueStatus
from app.services.server_queue_service import QueueError, ServerQueueService

router = APIRouter()


def _http_error(exc: QueueError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code})


@router.get(
    "", response_model=QueuePageResponse, dependencies=[Depends(require_scopes("servers:read"))]
)
async def list_queue(
    current_user: Annotated[User, Depends(require_permissions(Permission.SERVERS_READ_OWN))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    status: Annotated[list[QueueStatus] | None, Query()] = None,
):
    return await ServerQueueService(db).list_owned(
        current_user.id,
        page=page,
        page_size=page_size,
        statuses=status,
    )


@router.get(
    "/{queue_id}",
    response_model=QueueEntryResponse,
    dependencies=[Depends(require_scopes("servers:read"))],
)
async def get_queue_entry(
    queue_id: UUID,
    current_user: Annotated[User, Depends(require_permissions(Permission.SERVERS_READ_OWN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = ServerQueueService(db)
    try:
        return await service.describe(await service.get_owned(queue_id, current_user.id))
    except QueueError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{queue_id}/cancel",
    response_model=QueueEntryResponse,
    dependencies=[Depends(require_scopes("servers:manage"))],
)
async def cancel_queue_entry(
    queue_id: UUID,
    current_user: Annotated[User, Depends(require_permissions(Permission.SERVERS_WRITE_OWN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = ServerQueueService(db)
    try:
        return await service.describe(await service.cancel(queue_id, current_user.id))
    except QueueError as exc:
        raise _http_error(exc) from exc
