# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Caller-transaction volume intents; authorization and runtime inspection stay upstream.

Callers must commit acquisition before external I/O and retain the intent until all
handles/helpers terminate. Every writer, mount and metadata/delete operation must
participate before recovery can be enabled. Expiry never releases protection.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utc_now
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.services.admission_service import acquire_admission_lock

ACTIVE_STATES = ("reserved", "running", "recovery_required")
EXCLUSIVE_KINDS = ("backup", "restore", "job_writer")
KINDS = (*EXCLUSIVE_KINDS, "writer", "mount")


class VolumeOperationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def _require_transaction(db: AsyncSession):
    if not db.in_transaction():
        raise VolumeOperationError("transaction_required")
    connection = await db.connection()
    if (await connection.get_isolation_level()).upper() != "READ COMMITTED":
        raise VolumeOperationError("read_committed_required")


async def acquire_volume_operations(
    db: AsyncSession,
    *,
    volume_ids: list[uuid.UUID],
    owner_id: uuid.UUID,
    operation_id: uuid.UUID,
    kind: str,
) -> list[VolumeOperation]:
    """Lock rows in UUID order; flush intents atomically without committing.

    Use Read Committed: accounting is a separate statement after row locks.
    A repeated operation ID must have exactly the same owner, kind and volume set.
    """
    await _require_transaction(db)
    await acquire_admission_lock(db)
    if kind not in KINDS or not volume_ids:
        raise VolumeOperationError("invalid_operation")
    ids = sorted(set(volume_ids))
    volumes = (
        (
            await db.execute(
                select(Volume)
                .where(Volume.id.in_(ids))
                .order_by(Volume.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    if {v.id for v in volumes} != set(ids):
        raise VolumeOperationError("volume_unavailable")
    existing = (
        (
            await db.execute(
                select(VolumeOperation)
                .where(VolumeOperation.operation_id == operation_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    if existing:
        if {row.volume_id for row in existing} != set(ids) or any(
            row.owner_id != owner_id or row.kind != kind for row in existing
        ):
            raise VolumeOperationError("operation_conflict")
        return existing
    active = (
        (
            await db.execute(
                select(VolumeOperation)
                .where(VolumeOperation.volume_id.in_(ids), VolumeOperation.state.in_(ACTIVE_STATES))
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    if any(kind in EXCLUSIVE_KINDS or row.kind in EXCLUSIVE_KINDS for row in active):
        raise VolumeOperationError("volume_busy")
    rows = [
        VolumeOperation(
            operation_id=operation_id,
            volume_id=volume_id,
            owner_id=owner_id,
            kind=kind,
            state="reserved",
            fencing_token=uuid.uuid4(),
        )
        for volume_id in ids
    ]
    db.add_all(rows)
    await db.flush()
    return rows


async def transition_volume_operation(
    db: AsyncSession,
    *,
    operation_id: uuid.UUID,
    volume_id: uuid.UUID,
    fencing_token: uuid.UUID,
    state: str,
    executor_terminated: bool = False,
    helper_identity: str | None = None,
) -> VolumeOperation:
    """Terminal transitions require confirmed executor/handle termination.

    Tokens fence database updates only; they cannot stop a still-running helper.
    Runtime inspection/termination is required even after a lease/deadline expires.
    """
    await _require_transaction(db)
    await acquire_admission_lock(db)
    await db.execute(select(Volume.id).where(Volume.id == volume_id).with_for_update())
    row = (
        await db.execute(
            select(VolumeOperation)
            .where(
                VolumeOperation.operation_id == operation_id,
                VolumeOperation.volume_id == volume_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None or row.fencing_token != fencing_token:
        raise VolumeOperationError("operation_conflict")
    if state not in (*ACTIVE_STATES, "succeeded", "failed"):
        raise VolumeOperationError("invalid_operation")
    if row.state == state:
        return row
    if row.state not in ACTIVE_STATES:
        raise VolumeOperationError("operation_conflict")
    if state in ("succeeded", "failed") and not executor_terminated:
        raise VolumeOperationError("executor_unconfirmed")
    if state == "reserved" or (row.state == "recovery_required" and state == "running"):
        raise VolumeOperationError("operation_conflict")
    if helper_identity is not None:
        if row.helper_identity is not None and row.helper_identity != helper_identity:
            raise VolumeOperationError("operation_conflict")
        row.helper_identity = helper_identity
    row.state = state
    row.updated_at = utc_now()
    if state in ("succeeded", "failed"):
        row.completed_at = utc_now()
    await db.flush()
    return row
