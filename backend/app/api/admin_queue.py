# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Read-only admin queue visibility.

Cancellation remains owner-only and pending-only. This router exposes no
mutation: ``starting`` or ambiguous work is resolved through the operation
reconciliation path rather than an admin cancel or retry action.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_jwt_auth
from app.core.permissions import Permission
from app.db.session import get_db
from app.dependencies import PermissionChecker, get_current_active_user, no_store_cache
from app.models.user import User
from app.schemas.admin_queue import AdminQueuePage
from app.schemas.server_queue import QueueStatus
from app.services.server_queue_service import ServerQueueService

router = APIRouter(prefix="/server-queue")

Database = Annotated[AsyncSession, Depends(get_db)]


async def require_queue_read(
    current_user: User = Depends(get_current_active_user),
    _jwt=Depends(require_jwt_auth()),
) -> User:
    """Require cross-user server read, admin access, and a JWT session."""
    PermissionChecker(current_user).require_all(
        [Permission.ADMIN_ACCESS, Permission.SERVERS_READ_ALL]
    )
    return current_user


@router.get("", response_model=AdminQueuePage)
async def list_server_queue(
    response: Response,
    db: Database,
    _current_user: User = Depends(require_queue_read),
    status: Annotated[list[QueueStatus] | None, Query()] = None,
    owner_id: UUID | None = Query(None),
    age_days: int | None = Query(None, ge=0, le=3650),
    older_than: datetime | None = Query(None),
    recovery_required: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000),
):
    """List queue requests across owners in stable oldest-first order."""
    no_store_cache(response)
    return await ServerQueueService(db).list_for_admin(
        statuses=status,
        owner_id=owner_id,
        age_days=age_days,
        older_than=older_than,
        recovery_required=recovery_required,
        limit=limit,
        offset=offset,
    )
