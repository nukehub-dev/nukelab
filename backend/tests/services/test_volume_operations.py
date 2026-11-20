# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.services.volume_operation_service import (
    VolumeOperationError,
    acquire_volume_operations,
    transition_volume_operation,
)


def result(rows):
    value = MagicMock()
    value.scalars.return_value.all.return_value = rows
    value.scalar_one_or_none.return_value = rows[0] if rows else None
    return value


def session(*results):
    connection = MagicMock(get_isolation_level=AsyncMock(return_value="READ COMMITTED"))
    return MagicMock(
        in_transaction=MagicMock(return_value=True),
        connection=AsyncMock(return_value=connection),
        execute=AsyncMock(side_effect=[result([]), *results]),
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_missing_transaction_rejected_before_queries():
    db = session()
    db.in_transaction.return_value = False
    with pytest.raises(VolumeOperationError, match="transaction_required"):
        await acquire_volume_operations(
            db,
            volume_ids=[uuid.uuid4()],
            owner_id=uuid.uuid4(),
            operation_id=uuid.uuid4(),
            kind="writer",
        )
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeatable_read_rejected_before_queries():
    db = session()
    connection = await db.connection()
    connection.get_isolation_level.return_value = "REPEATABLE READ"
    with pytest.raises(VolumeOperationError, match="read_committed_required"):
        await acquire_volume_operations(
            db,
            volume_ids=[uuid.uuid4()],
            owner_id=uuid.uuid4(),
            operation_id=uuid.uuid4(),
            kind="writer",
        )
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_lock_then_fresh_read_and_flush_without_commit():
    ids = [uuid.UUID(int=2), uuid.UUID(int=1)]
    db = session(result([Volume(id=id_) for id_ in ids]), result([]), result([]))
    rows = await acquire_volume_operations(
        db, volume_ids=ids, owner_id=uuid.uuid4(), operation_id=uuid.uuid4(), kind="writer"
    )
    assert [row.volume_id for row in rows] == sorted(ids)
    statements = [call.args[0] for call in db.execute.call_args_list]
    assert "FOR UPDATE" in str(statements[1])
    assert "ORDER BY volumes.id" in str(statements[1])
    assert all(
        statement.get_execution_options()["populate_existing"] for statement in statements[1:]
    )
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind, active_kind", [("backup", "writer"), ("mount", "backup"), ("restore", "mount")]
)
async def test_active_intent_blocks_conflicting_operation(kind, active_kind):
    id_ = uuid.uuid4()
    active = VolumeOperation(volume_id=id_, kind=active_kind, state="recovery_required")
    db = session(result([Volume(id=id_)]), result([]), result([active]))
    with pytest.raises(VolumeOperationError, match="volume_busy"):
        await acquire_volume_operations(
            db, volume_ids=[id_], owner_id=uuid.uuid4(), operation_id=uuid.uuid4(), kind=kind
        )
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_redelivery_returns_same_terminal_operation():
    id_, owner, operation = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    existing = VolumeOperation(
        volume_id=id_, operation_id=operation, owner_id=owner, kind="backup", state="succeeded"
    )
    db = session(result([Volume(id=id_)]), result([existing]))
    assert await acquire_volume_operations(
        db, volume_ids=[id_], owner_id=owner, operation_id=operation, kind="backup"
    ) == [existing]
    db.add_all.assert_not_called()


@pytest.mark.asyncio
async def test_uncertain_executor_never_releases_guard():
    id_, operation, token = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    existing = VolumeOperation(
        volume_id=id_,
        operation_id=operation,
        fencing_token=token,
        kind="backup",
        state="recovery_required",
    )
    db = session(result([]), result([existing]))
    with pytest.raises(VolumeOperationError, match="executor_unconfirmed"):
        await transition_volume_operation(
            db, volume_id=id_, operation_id=operation, fencing_token=token, state="failed"
        )
    assert existing.state == "recovery_required"


@pytest.mark.asyncio
async def test_fenced_token_cannot_release_guard():
    id_, operation = uuid.uuid4(), uuid.uuid4()
    existing = VolumeOperation(
        volume_id=id_,
        operation_id=operation,
        fencing_token=uuid.uuid4(),
        kind="backup",
        state="running",
    )
    db = session(result([]), result([existing]))
    with pytest.raises(VolumeOperationError, match="operation_conflict"):
        await transition_volume_operation(
            db,
            volume_id=id_,
            operation_id=operation,
            fencing_token=uuid.uuid4(),
            state="succeeded",
            executor_terminated=True,
        )
    assert existing.state == "running"


@pytest.mark.asyncio
async def test_confirmed_termination_finishes_with_refreshed_state():
    id_, operation, token = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    existing = VolumeOperation(
        volume_id=id_,
        operation_id=operation,
        fencing_token=token,
        kind="backup",
        state="running",
        helper_identity="helper-1",
    )
    db = session(result([]), result([existing]))
    row = await transition_volume_operation(
        db,
        volume_id=id_,
        operation_id=operation,
        fencing_token=token,
        state="succeeded",
        executor_terminated=True,
    )
    assert row.completed_at is not None
    assert row.state == "succeeded"
    assert db.execute.call_args.args[0].get_execution_options()["populate_existing"]
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_previously_loaded_operation_is_refreshed(db_session, test_user):
    from sqlalchemy import update

    volume = Volume(
        name=f"operation-{uuid.uuid4()}",
        display_name="Private data",
        owner_id=test_user.id,
        visibility="private",
        status="active",
    )
    db_session.add(volume)
    await db_session.flush()
    operation_id = uuid.uuid4()
    rows = await acquire_volume_operations(
        db_session,
        volume_ids=[volume.id],
        owner_id=test_user.id,
        operation_id=operation_id,
        kind="backup",
    )
    row = rows[0]
    await db_session.execute(
        update(VolumeOperation)
        .where(VolumeOperation.operation_id == operation_id)
        .values(state="succeeded")
        .execution_options(synchronize_session=False)
    )
    assert row.state == "reserved"
    with pytest.raises(VolumeOperationError, match="operation_conflict"):
        await transition_volume_operation(
            db_session,
            volume_id=volume.id,
            operation_id=operation_id,
            fencing_token=row.fencing_token,
            state="failed",
            executor_terminated=True,
        )
    assert row.state == "succeeded"
