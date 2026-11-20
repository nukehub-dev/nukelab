# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Exercise durable volume exclusion using independently committed PostgreSQL sessions."""

import asyncio
import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.services.volume_operation_service import VolumeOperationError, acquire_volume_operations
from tests.conftest import test_engine


@dataclass(frozen=True)
class OwnedVolumes:
    owner_id: uuid.UUID
    volume_ids: tuple[uuid.UUID, uuid.UUID]


@pytest_asyncio.fixture
async def committed_volumes():
    """Rows are visible to competing connections and cleaned up only by their UUIDs."""
    owner_id = uuid.uuid4()
    volume_ids = (uuid.uuid4(), uuid.uuid4())
    marker = uuid.uuid4().hex
    async with AsyncSession(test_engine) as seed, seed.begin():
        seed.add(
            User(id=owner_id, username=f"volume-race-{marker}", email=f"{marker}@example.test")
        )
        await seed.flush()
        seed.add_all(
            [
                Volume(
                    id=volume_id,
                    owner_id=owner_id,
                    name=f"volume-race-{volume_id}",
                    display_name="Private volume",
                    visibility="private",
                    status="active",
                    max_size_bytes=1024,
                )
                for volume_id in volume_ids
            ]
        )
    try:
        yield OwnedVolumes(owner_id, volume_ids)
    finally:
        async with AsyncSession(test_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                delete(VolumeOperation).where(
                    VolumeOperation.volume_id.in_(volume_ids),
                    VolumeOperation.owner_id == owner_id,
                )
            )
            await cleanup.execute(
                delete(Volume).where(
                    Volume.id.in_(volume_ids),
                    Volume.owner_id == owner_id,
                )
            )
            await cleanup.execute(delete(User).where(User.id == owner_id))


async def compete(owner_id, requests):
    """Start both transactions before either acquires the admission lock.

    Each result reports only committed intent, so a successful flush followed by
    a failed commit cannot be mistaken for the winner. No shared ORM session or
    fake scheduler sleeps stand in for database synchronization.
    """
    barrier = asyncio.Barrier(2)

    async def reserve(operation_id, volume_ids, kind):
        try:
            async with AsyncSession(test_engine) as db, db.begin():
                # Force distinct connections and transactions before opening the gate.
                connection = await db.connection()
                backend_pid = await connection.scalar(select(func.pg_backend_pid()))
                await asyncio.wait_for(barrier.wait(), timeout=5)
                rows = await acquire_volume_operations(
                    db,
                    owner_id=owner_id,
                    operation_id=operation_id,
                    volume_ids=volume_ids,
                    kind=kind,
                )
                identities = [(row.operation_id, row.volume_id) for row in rows]
            return backend_pid, identities, None
        except VolumeOperationError as exc:
            return backend_pid, [], exc.code

    return await asyncio.wait_for(
        asyncio.gather(*(reserve(*request) for request in requests)),
        timeout=10,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("first_kind,second_kind", [("backup", "writer"), ("writer", "backup")])
async def test_backup_and_writer_cannot_both_commit(committed_volumes, first_kind, second_kind):
    owned = committed_volumes
    volume_id = owned.volume_ids[0]
    results = await compete(
        owned.owner_id,
        [
            (uuid.uuid4(), [volume_id], first_kind),
            (uuid.uuid4(), [volume_id], second_kind),
        ],
    )
    assert len({pid for pid, _, _ in results}) == 2
    assert sorted(code or "committed" for _, _, code in results) == ["committed", "volume_busy"]
    async with AsyncSession(test_engine) as verify:
        rows = (
            await verify.scalars(
                select(VolumeOperation).where(
                    VolumeOperation.volume_id == volume_id,
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].state == "reserved"
        assert rows[0].kind in {first_kind, second_kind}


@pytest.mark.asyncio
async def test_two_exclusive_operations_cannot_both_commit(committed_volumes):
    owned = committed_volumes
    volume_id = owned.volume_ids[0]
    results = await compete(
        owned.owner_id,
        [
            (uuid.uuid4(), [volume_id], "backup"),
            (uuid.uuid4(), [volume_id], "restore"),
        ],
    )
    assert len({pid for pid, _, _ in results}) == 2
    assert sorted(code or "committed" for _, _, code in results) == ["committed", "volume_busy"]
    async with AsyncSession(test_engine) as verify:
        rows = (
            await verify.scalars(
                select(VolumeOperation).where(
                    VolumeOperation.volume_id == volume_id,
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].kind in {"backup", "restore"}


@pytest.mark.asyncio
async def test_same_operation_id_rejects_concurrent_disjoint_volume_sets(committed_volumes):
    owned = committed_volumes
    operation_id = uuid.uuid4()
    results = await compete(
        owned.owner_id,
        [
            (operation_id, [owned.volume_ids[0]], "writer"),
            (operation_id, [owned.volume_ids[1]], "writer"),
        ],
    )
    assert len({pid for pid, _, _ in results}) == 2
    assert sorted(code or "committed" for _, _, code in results) == [
        "committed",
        "operation_conflict",
    ]
    async with AsyncSession(test_engine) as verify:
        rows = (
            await verify.scalars(
                select(VolumeOperation).where(
                    VolumeOperation.operation_id == operation_id,
                )
            )
        ).all()
        assert len(rows) == 1
        winner = next(identities for _, identities, code in results if code is None)
        assert winner == [(operation_id, rows[0].volume_id)]
