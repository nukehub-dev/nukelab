# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Transaction-owned action journal. No commit, lease expiry or executor takeover."""

import re
import uuid
from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utc_now
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.services.admission_service import acquire_admission_lock

ACTIVE_STATES = ("prepared", "executing", "uncertain")
ACTIONS = ("create", "start", "restart", "update", "stop", "delete")


class ServerOperationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def get_active(db: AsyncSession, server_id: uuid.UUID) -> ServerLaunchOperation | None:
    await acquire_admission_lock(db)
    return await db.scalar(
        select(ServerLaunchOperation)
        .where(
            ServerLaunchOperation.server_id == server_id,
            ServerLaunchOperation.state.in_(ACTIVE_STATES),
        )
        .execution_options(populate_existing=True)
    )


async def create_operation(
    db: AsyncSession,
    *,
    server_id: uuid.UUID,
    owner_id: uuid.UUID,
    action: str,
    username: str,
    resources: dict,
    operation_id: uuid.UUID | None = None,
    fencing_token: uuid.UUID | None = None,
    revision_id: uuid.UUID | None = None,
    request_payload: dict | None = None,
    mounts: list[dict] | None = None,
    previous_mounts: list[dict] | None = None,
    gpu_devices: list[str] | None = None,
    environment_slug: str | None = None,
    generation: int | None = None,
    previous_container_id: str | None = None,
    previous_status: str | None = None,
) -> ServerLaunchOperation:
    await acquire_admission_lock(db)
    if (
        action not in ACTIONS
        or not username
        or len(username) > 255
        or (generation is not None and generation < 1)
    ):
        raise ServerOperationError("invalid_operation")
    server = await db.scalar(
        select(Server)
        .where(Server.id == server_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if server is None or server.user_id != owner_id:
        raise ServerOperationError("server_unavailable")
    if await get_active(db, server_id) is not None:
        raise ServerOperationError("launch_in_progress")
    row = ServerLaunchOperation(
        id=operation_id or uuid.uuid4(),
        server_id=server_id,
        owner_id=owner_id,
        action=action,
        state="prepared",
        fencing_token=fencing_token or uuid.uuid4(),
        revision_id=revision_id,
        request_payload=deepcopy(request_payload),
        mounts=deepcopy(mounts or []),
        previous_mounts=deepcopy(previous_mounts or []),
        gpu_devices=list(gpu_devices or []),
        username=username,
        environment_slug=environment_slug,
        resources=deepcopy(resources),
        generation=generation,
        previous_container_id=previous_container_id,
        previous_status=previous_status,
    )
    db.add(row)
    await db.flush()
    return row


async def claim_operation(
    db: AsyncSession, operation_id: uuid.UUID, fencing_token: uuid.UUID
) -> ServerLaunchOperation | None:
    await acquire_admission_lock(db)
    return await db.scalar(
        update(ServerLaunchOperation)
        .where(
            ServerLaunchOperation.id == operation_id,
            ServerLaunchOperation.fencing_token == fencing_token,
            ServerLaunchOperation.state == "prepared",
        )
        .values(state="executing", updated_at=utc_now())
        .returning(ServerLaunchOperation)
        .execution_options(populate_existing=True)
    )


async def finish_operation(
    db: AsyncSession,
    operation_id: uuid.UUID,
    fencing_token: uuid.UUID,
    state: str,
    reason_code: str | None = None,
    *,
    runtime_verified: bool = False,
    executor_terminated: bool = False,
) -> ServerLaunchOperation | None:
    await acquire_admission_lock(db)
    if state not in ("succeeded", "uncertain", "failed") or (
        reason_code is not None and not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", reason_code)
    ):
        raise ServerOperationError("invalid_operation_state")
    row = await db.scalar(
        select(ServerLaunchOperation)
        .where(
            ServerLaunchOperation.id == operation_id,
            ServerLaunchOperation.fencing_token == fencing_token,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        return None
    if row.state == state:
        return row
    if row.state not in ACTIVE_STATES:
        return None
    if (state == "succeeded" and not runtime_verified) or (
        state == "failed" and not executor_terminated
    ):
        raise ServerOperationError("operation_outcome_unverified")
    if state == "succeeded" and row.state == "prepared":
        raise ServerOperationError("operation_not_executing")
    row.state = state
    row.reason_code = reason_code
    row.updated_at = utc_now()
    row.finished_at = utc_now() if state in ("succeeded", "failed") else None
    await db.flush()
    return row
