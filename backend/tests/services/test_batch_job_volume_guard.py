# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Exclusive batch job writer guards conflict with every active volume intent."""

import uuid

import pytest

from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.services.volume_operation_service import (
    VolumeOperationError,
    acquire_volume_operations,
    transition_volume_operation,
)


async def make_volume(db, owner, *, marker=None):
    suffix = marker or uuid.uuid4().hex[:12]
    volume = Volume(
        name=f"guard-volume-{suffix}",
        display_name="Guard data",
        owner_id=owner.id,
        visibility="private",
        max_size_bytes=1024**3,
        status="active",
    )
    db.add(volume)
    await db.flush()
    return volume


async def add_guard(db, volume, owner, kind, *, state="reserved"):
    guard = VolumeOperation(
        operation_id=uuid.uuid4(),
        volume_id=volume.id,
        owner_id=owner.id,
        kind=kind,
        state=state,
        fencing_token=uuid.uuid4(),
    )
    db.add(guard)
    await db.flush()
    return guard


async def acquire_job_writer(db, volume, owner, *, operation_id=None):
    return await acquire_volume_operations(
        db,
        volume_ids=[volume.id],
        owner_id=owner.id,
        operation_id=operation_id or uuid.uuid4(),
        kind="job_writer",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("active_kind", ["writer", "mount", "backup", "restore", "job_writer"])
async def test_job_writer_conflicts_with_every_active_guard(db_session, test_user, active_kind):
    volume = await make_volume(db_session, test_user)
    await add_guard(db_session, volume, test_user, active_kind)

    with pytest.raises(VolumeOperationError, match="volume_busy"):
        await acquire_job_writer(db_session, volume, test_user)


@pytest.mark.asyncio
@pytest.mark.parametrize("active_kind", ["writer", "mount"])
async def test_existing_writer_or_mount_conflicts_with_active_job_writer(
    db_session, test_user, active_kind
):
    volume = await make_volume(db_session, test_user)
    await acquire_job_writer(db_session, volume, test_user)

    with pytest.raises(VolumeOperationError, match="volume_busy"):
        await acquire_volume_operations(
            db_session,
            volume_ids=[volume.id],
            owner_id=test_user.id,
            operation_id=uuid.uuid4(),
            kind=active_kind,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("active_kind", ["backup", "restore"])
async def test_backup_and_restore_remain_mutually_exclusive(db_session, test_user, active_kind):
    volume = await make_volume(db_session, test_user)
    await add_guard(
        db_session, volume, test_user, "backup" if active_kind == "restore" else "restore"
    )

    with pytest.raises(VolumeOperationError, match="volume_busy"):
        await acquire_volume_operations(
            db_session,
            volume_ids=[volume.id],
            owner_id=test_user.id,
            operation_id=uuid.uuid4(),
            kind=active_kind,
        )


@pytest.mark.asyncio
async def test_job_writer_on_an_unrelated_volume_succeeds(db_session, test_user):
    busy_volume = await make_volume(db_session, test_user, marker="busy-" + uuid.uuid4().hex[:8])
    free_volume = await make_volume(db_session, test_user, marker="free-" + uuid.uuid4().hex[:8])
    await add_guard(db_session, busy_volume, test_user, "writer")

    rows = await acquire_job_writer(db_session, free_volume, test_user)
    assert len(rows) == 1
    assert rows[0].volume_id == free_volume.id
    assert rows[0].kind == "job_writer"
    assert rows[0].state == "reserved"


@pytest.mark.asyncio
async def test_repeated_job_writer_operation_id_is_idempotent(db_session, test_user):
    volume = await make_volume(db_session, test_user)
    operation_id = uuid.uuid4()

    first = await acquire_job_writer(db_session, volume, test_user, operation_id=operation_id)
    second = await acquire_job_writer(db_session, volume, test_user, operation_id=operation_id)

    assert [row.operation_id for row in second] == [row.operation_id for row in first]
    assert second[0].fencing_token == first[0].fencing_token
    with pytest.raises(VolumeOperationError, match="operation_conflict"):
        await acquire_volume_operations(
            db_session,
            volume_ids=[volume.id],
            owner_id=test_user.id,
            operation_id=operation_id,
            kind="writer",
        )


@pytest.mark.asyncio
async def test_terminal_transition_requires_termination_proof_and_releases(db_session, test_user):
    volume = await make_volume(db_session, test_user)
    rows = await acquire_job_writer(db_session, volume, test_user)
    guard = rows[0]

    with pytest.raises(VolumeOperationError, match="executor_unconfirmed"):
        await transition_volume_operation(
            db_session,
            operation_id=guard.operation_id,
            volume_id=volume.id,
            fencing_token=guard.fencing_token,
            state="succeeded",
            executor_terminated=False,
        )
    assert guard.state == "reserved"
    with pytest.raises(VolumeOperationError, match="volume_busy"):
        await acquire_job_writer(db_session, volume, test_user)

    released = await transition_volume_operation(
        db_session,
        operation_id=guard.operation_id,
        volume_id=volume.id,
        fencing_token=guard.fencing_token,
        state="succeeded",
        executor_terminated=True,
    )
    assert released.state == "succeeded"
    assert released.completed_at is not None

    next_rows = await acquire_job_writer(db_session, volume, test_user)
    assert len(next_rows) == 1
    assert next_rows[0].state == "reserved"
