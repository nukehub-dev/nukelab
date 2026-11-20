# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""PostgreSQL journal state/fencing and immutable intent regressions."""

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.user import User
from app.services.server_operation_service import (
    ServerOperationError,
    claim_operation,
    create_operation,
    finish_operation,
    get_active,
)

RESOURCES = {"cpu": 1.0, "memory": "1g", "disk": "2g", "gpu": 0}


async def operation(db, owner):
    server = Server(
        id=uuid.uuid4(), name="journal-" + uuid.uuid4().hex, user_id=owner.id, status="starting"
    )
    db.add(server)
    await db.flush()
    row = await create_operation(
        db,
        server_id=server.id,
        owner_id=owner.id,
        action="start",
        username=owner.username,
        resources=RESOURCES,
        request_payload={"selection": "approved"},
        mounts=[],
        generation=1,
    )
    return server, row


@pytest.mark.asyncio
async def test_one_active_journal_and_exact_claim_fence(db_session, test_user):
    server, row = await operation(db_session, test_user)
    assert (await get_active(db_session, server.id)).id == row.id
    assert await claim_operation(db_session, row.id, uuid.uuid4()) is None
    assert (await claim_operation(db_session, row.id, row.fencing_token)).state == "executing"
    assert await claim_operation(db_session, row.id, row.fencing_token) is None
    with pytest.raises(ServerOperationError, match="launch_in_progress"):
        await create_operation(
            db_session,
            server_id=server.id,
            owner_id=test_user.id,
            action="stop",
            username=test_user.username,
            resources=RESOURCES,
        )


@pytest.mark.asyncio
async def test_terminal_outcomes_require_explicit_runtime_or_executor_proof(db_session, test_user):
    server, row = await operation(db_session, test_user)
    token = row.fencing_token
    await claim_operation(db_session, row.id, token)
    for target in ("succeeded", "failed"):
        with pytest.raises(ServerOperationError, match="outcome_unverified"):
            await finish_operation(db_session, row.id, token, target)
    assert (
        await finish_operation(db_session, row.id, token, "uncertain", "recovery_required")
    ).state == "uncertain"
    assert (await get_active(db_session, server.id)).id == row.id
    assert (
        await finish_operation(db_session, row.id, uuid.uuid4(), "succeeded", runtime_verified=True)
        is None
    )
    assert (
        await finish_operation(db_session, row.id, token, "succeeded", runtime_verified=True)
    ).state == "succeeded"
    finished_at = row.finished_at
    assert await get_active(db_session, server.id) is None
    assert (
        await finish_operation(db_session, row.id, token, "succeeded")
    ).finished_at == finished_at
    assert (
        await finish_operation(db_session, row.id, token, "failed", executor_terminated=True)
        is None
    )
    successor = await create_operation(
        db_session,
        server_id=server.id,
        owner_id=test_user.id,
        action="stop",
        username=test_user.username,
        resources=RESOURCES,
    )
    assert successor.id != row.id


@pytest.mark.asyncio
async def test_prepared_action_may_fail_only_with_known_executor_termination(db_session, test_user):
    _, row = await operation(db_session, test_user)
    with pytest.raises(ServerOperationError, match="not_executing"):
        await finish_operation(
            db_session, row.id, row.fencing_token, "succeeded", runtime_verified=True
        )
    assert (
        await finish_operation(
            db_session, row.id, row.fencing_token, "failed", executor_terminated=True
        )
    ).finished_at is not None


@pytest.mark.asyncio
async def test_intent_and_token_are_immutable_but_old_uncertainty_never_expires(
    db_session, test_user
):
    server, row = await operation(db_session, test_user)
    row_id = row.id
    for field, value in (
        ("resources", {"cpu": 99}),
        ("fencing_token", uuid.uuid4()),
        ("mounts", [{"volume_id": "changed"}]),
    ):
        with pytest.raises(ValueError, match="immutable"):
            async with db_session.begin_nested():
                setattr(row, field, value)
                await db_session.flush()
        row = await db_session.get(ServerLaunchOperation, row_id)
        await db_session.refresh(row)
    await claim_operation(db_session, row.id, row.fencing_token)
    await finish_operation(db_session, row.id, row.fencing_token, "uncertain")
    row.updated_at = datetime(2000, 1, 1)
    await db_session.flush()
    assert (await get_active(db_session, server.id)).id == row.id
    assert await claim_operation(db_session, row.id, row.fencing_token) is None


@pytest.mark.asyncio
async def test_partial_unique_index_blocks_uncoordinated_second_active_action(
    db_session, test_user
):
    server, _ = await operation(db_session, test_user)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ServerLaunchOperation(
                    server_id=server.id,
                    owner_id=test_user.id,
                    action="delete",
                    state="prepared",
                    username=test_user.username,
                    resources=RESOURCES,
                    mounts=[],
                    previous_mounts=[],
                    gpu_devices=[],
                )
            )
            await db_session.flush()


@pytest.mark.parametrize(
    "target,reason", [("prepared", None), ("failed", "private exception /host/path")]
)
@pytest.mark.asyncio
async def test_state_and_reason_codes_are_bounded_public_symbols(
    db_session, test_user, target, reason
):
    _, row = await operation(db_session, test_user)
    with pytest.raises(ServerOperationError, match="invalid_operation_state"):
        await finish_operation(
            db_session, row.id, row.fencing_token, target, reason, executor_terminated=True
        )


@pytest.mark.asyncio
async def test_independent_delivery_claims_commit_one_executor():
    from tests.conftest import test_engine

    owner_id, server_id = uuid.uuid4(), uuid.uuid4()
    operation_id, token = uuid.uuid4(), uuid.uuid4()
    marker = uuid.uuid4().hex
    try:
        async with AsyncSession(test_engine) as db, db.begin():
            owner = User(
                id=owner_id,
                username="journal_" + marker,
                email=marker + "@example.test",
                role="user",
                is_active=True,
            )
            db.add(owner)
            await db.flush()
            db.add(
                Server(id=server_id, user_id=owner_id, name="journal-" + marker, status="starting")
            )
            await db.flush()
            await create_operation(
                db,
                server_id=server_id,
                owner_id=owner_id,
                action="start",
                username=owner.username,
                resources=RESOURCES,
                operation_id=operation_id,
                fencing_token=token,
            )
        barrier = asyncio.Barrier(2)

        async def claim():
            async with AsyncSession(test_engine) as db:
                await barrier.wait()
                async with db.begin():
                    row = await claim_operation(db, operation_id, token)
                    return row is not None

        claims = await asyncio.wait_for(asyncio.gather(claim(), claim()), timeout=10)
        assert claims.count(True) == 1
        async with AsyncSession(test_engine) as db:
            assert (
                await db.scalar(
                    select(ServerLaunchOperation).where(ServerLaunchOperation.id == operation_id)
                )
            ).state == "executing"
    finally:
        async with AsyncSession(test_engine) as db, db.begin():
            await db.execute(delete(Server).where(Server.id == server_id))
            await db.execute(delete(User).where(User.id == owner_id))
