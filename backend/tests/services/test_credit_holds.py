# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Credit hold ledger: spendable balance, release, settlement and idempotency."""

import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob
from app.models.credit_hold import CreditHold
from app.models.credit_transaction import CreditTransaction
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.services.credit_hold_service import (
    HELD,
    RELEASED,
    SETTLED,
    CreditHoldError,
    CreditHoldService,
)
from tests.conftest import test_engine
from tests.services.test_batch_job_service import (
    make_environment,
    make_plan,
    make_volume,
)


async def _make_job(db, owner, **overrides):
    _, revision = await make_environment(db)
    plan = await make_plan(db)
    volume = await make_volume(db, owner)
    now = utc_now()
    job = BatchJob(
        user_id=owner.id,
        name=f"hold-job-{uuid.uuid4().hex[:8]}",
        idempotency_key_hash=uuid.uuid4().hex * 2,
        request_fingerprint=uuid.uuid4().hex * 2,
        revision_id=revision.id,
        plan_id=plan.id,
        volume_id=volume.id,
        argv=["true"],
        max_runtime_seconds=1800,
        state="queued",
        state_changed_at=now,
        queue_expires_at=now + timedelta(days=1),
        revision_snapshot={},
        plan_snapshot={},
        volume_snapshot={},
        fencing_token=uuid.uuid4(),
        created_at=now,
        updated_at=now,
        **overrides,
    )
    db.add(job)
    await db.flush()
    return job


@pytest.mark.asyncio
async def test_spendable_balance_subtracts_active_holds(db_session, test_user):
    first_job = await _make_job(db_session, test_user)
    second_job = await _make_job(db_session, test_user)

    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 100
    first = await CreditHoldService.create_hold(
        db_session, user_id=test_user.id, job_id=first_job.id, amount=40
    )
    assert first.state == HELD
    assert await CreditHoldService.held_total(db_session, test_user.id) == 40
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 60

    await CreditHoldService.create_hold(
        db_session, user_id=test_user.id, job_id=second_job.id, amount=60
    )
    assert await CreditHoldService.held_total(db_session, test_user.id) == 100
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 0
    assert await CreditHoldService.spendable_balance(db_session, uuid.uuid4()) == 0


@pytest.mark.asyncio
async def test_create_hold_rejects_nonpositive_and_insufficient(db_session, test_user):
    job = await _make_job(db_session, test_user)

    with pytest.raises(CreditHoldError, match="invalid_amount"):
        await CreditHoldService.create_hold(
            db_session, user_id=test_user.id, job_id=job.id, amount=0
        )
    with pytest.raises(CreditHoldError, match="insufficient_credits"):
        await CreditHoldService.create_hold(
            db_session, user_id=test_user.id, job_id=job.id, amount=101
        )
    with pytest.raises(CreditHoldError, match="user_not_found"):
        await CreditHoldService.create_hold(
            db_session, user_id=uuid.uuid4(), job_id=job.id, amount=1
        )
    assert await db_session.scalar(select(func.count()).select_from(CreditHold)) == 0


@pytest.mark.asyncio
async def test_hold_requires_spendable_balance_under_concurrent_holds(db_session, test_user):
    first_job = await _make_job(db_session, test_user)
    second_job = await _make_job(db_session, test_user)
    await CreditHoldService.create_hold(
        db_session, user_id=test_user.id, job_id=first_job.id, amount=70
    )
    with pytest.raises(CreditHoldError, match="insufficient_credits"):
        await CreditHoldService.create_hold(
            db_session, user_id=test_user.id, job_id=second_job.id, amount=31
        )
    await CreditHoldService.create_hold(
        db_session, user_id=test_user.id, job_id=second_job.id, amount=30
    )
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 0


@pytest.mark.asyncio
async def test_release_is_idempotent_and_restores_spendable(db_session, test_user):
    job = await _make_job(db_session, test_user)
    hold = await CreditHoldService.create_hold(
        db_session, user_id=test_user.id, job_id=job.id, amount=25
    )

    assert await CreditHoldService.release(db_session, job.id) is True
    await db_session.flush()
    stored = await db_session.get(CreditHold, hold.id, populate_existing=True)
    assert stored.state == RELEASED
    assert stored.charged_credits == 0
    assert stored.settled_at is not None
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 100

    assert await CreditHoldService.release(db_session, job.id) is False
    assert await CreditHoldService.release(db_session, uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_settle_charges_actual_and_refunds_remainder(db_session, test_user):
    job = await _make_job(db_session, test_user)
    hold = await CreditHoldService.create_hold(
        db_session, user_id=test_user.id, job_id=job.id, amount=10
    )

    result = await CreditHoldService.settle(
        db_session,
        job_id=job.id,
        charge=4,
        description="Batch job usage",
        meta={
            "rate_per_hour": 10,
            "authorized_credits": 10,
            "observed_seconds": 1440,
        },
    )
    assert result.charged == 4
    assert result.refunded == 6
    assert result.unpaid == 0
    assert result.state == SETTLED
    assert result.transaction_id is not None

    user = await db_session.get(User, test_user.id, populate_existing=True)
    assert user.nuke_balance == 96
    stored = await db_session.get(CreditHold, hold.id, populate_existing=True)
    assert stored.state == SETTLED
    assert stored.charged_credits == 4
    assert stored.transaction_id == result.transaction_id
    assert stored.settled_at is not None

    transaction = await db_session.scalar(
        select(CreditTransaction).where(CreditTransaction.id == result.transaction_id)
    )
    assert transaction.type == "batch_job_usage"
    assert transaction.amount == -4
    assert transaction.balance_after == 96
    assert transaction.meta["job_id"] == str(job.id)
    assert transaction.meta["charged"] == 4
    assert transaction.meta["refunded"] == 6
    assert transaction.meta["unpaid"] == 0

    replay = await CreditHoldService.settle(
        db_session,
        job_id=job.id,
        charge=10,
        description="Duplicate settlement",
        meta={"rate_per_hour": 10},
    )
    assert replay == result
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.user_id == test_user.id)
        )
        == 1
    )
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 96
    assert await CreditHoldService.release(db_session, job.id) is False


@pytest.mark.asyncio
async def test_settle_zero_charge_creates_no_transaction(db_session, test_user):
    job = await _make_job(db_session, test_user)
    await CreditHoldService.create_hold(db_session, user_id=test_user.id, job_id=job.id, amount=5)

    result = await CreditHoldService.settle(
        db_session,
        job_id=job.id,
        charge=0,
        description="Never started",
        meta={"rate_per_hour": 10, "observed_seconds": 0},
    )
    assert result.charged == 0
    assert result.refunded == 5
    assert result.unpaid == 0
    assert result.transaction_id is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.user_id == test_user.id)
        )
        == 0
    )
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 100


@pytest.mark.asyncio
async def test_settle_partial_balance_keeps_refund_zero_and_records_unpaid(db_session, test_user):
    job = await _make_job(db_session, test_user)
    await CreditHoldService.create_hold(db_session, user_id=test_user.id, job_id=job.id, amount=10)
    user = await db_session.get(User, test_user.id, populate_existing=True)
    user.nuke_balance = 3
    await db_session.flush()

    result = await CreditHoldService.settle(
        db_session,
        job_id=job.id,
        charge=10,
        description="Partial balance",
        meta={"rate_per_hour": 10, "observed_seconds": 3600},
    )
    assert result.charged == 3
    assert result.refunded == 0
    assert result.unpaid == 7
    assert result.state == SETTLED
    stored_user = await db_session.get(User, test_user.id, populate_existing=True)
    assert stored_user.nuke_balance == 0
    hold = await db_session.scalar(select(CreditHold).where(CreditHold.job_id == job.id))
    assert hold.charged_credits == 3
    assert hold.unpaid_credits == 7
    transaction = await db_session.scalar(
        select(CreditTransaction).where(CreditTransaction.id == result.transaction_id)
    )
    assert transaction.amount == -3
    assert transaction.balance_after == 0
    assert transaction.meta["refunded"] == 0
    assert transaction.meta["unpaid"] == 7

    replay = await CreditHoldService.settle(
        db_session,
        job_id=job.id,
        charge=10,
        description="Replay",
        meta={},
    )
    assert replay.charged == 3
    assert replay.refunded == 0
    assert replay.unpaid == 7
    assert replay.transaction_id == result.transaction_id


@pytest.mark.asyncio
async def test_settle_clamps_charge_to_the_hold(db_session, test_user):
    job = await _make_job(db_session, test_user)
    await CreditHoldService.create_hold(db_session, user_id=test_user.id, job_id=job.id, amount=5)
    result = await CreditHoldService.settle(
        db_session,
        job_id=job.id,
        charge=50,
        description="Over authorization",
        meta={},
    )
    assert result.charged == 5
    assert result.refunded == 0
    assert result.unpaid == 0
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 95


@pytest.mark.asyncio
async def test_settle_without_a_hold_is_a_noop(db_session, test_user):
    result = await CreditHoldService.settle(
        db_session,
        job_id=uuid.uuid4(),
        charge=10,
        description="No hold",
        meta={},
    )
    assert result.charged == 0
    assert result.refunded == 0
    assert result.unpaid == 0
    assert result.state == "none"
    assert result.transaction_id is None


@pytest.mark.asyncio
async def test_settle_after_release_charges_nothing(db_session, test_user):
    job = await _make_job(db_session, test_user)
    await CreditHoldService.create_hold(db_session, user_id=test_user.id, job_id=job.id, amount=8)
    await CreditHoldService.release(db_session, job.id)

    result = await CreditHoldService.settle(
        db_session,
        job_id=job.id,
        charge=8,
        description="Released hold",
        meta={},
    )
    assert result.charged == 0
    assert result.refunded == 0
    assert result.unpaid == 0
    assert result.state == RELEASED
    assert result.transaction_id is None
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 100


@pytest_asyncio.fixture
async def committed_hold_world():
    """Two committed jobs and one committed owner for cross-session hold races."""
    marker = uuid.uuid4().hex
    owner_id = uuid.uuid4()
    async with AsyncSession(test_engine, expire_on_commit=False) as seed, seed.begin():
        owner = User(
            id=owner_id,
            username=f"hold_{marker}",
            email=f"{marker}@example.test",
            role="user",
            is_active=True,
            nuke_balance=100,
        )
        seed.add(owner)
        await seed.flush()
        _, revision = await make_environment(seed)
        plan = await make_plan(seed)
        volume = await make_volume(seed, owner)
        jobs = []
        for index in range(2):
            now = utc_now()
            job = BatchJob(
                user_id=owner_id,
                name=f"hold-race-{marker}-{index}",
                idempotency_key_hash=uuid.uuid4().hex * 2,
                request_fingerprint=uuid.uuid4().hex * 2,
                revision_id=revision.id,
                plan_id=plan.id,
                volume_id=volume.id,
                argv=["true"],
                max_runtime_seconds=1800,
                state="queued",
                state_changed_at=now,
                queue_expires_at=now + timedelta(days=1),
                revision_snapshot={},
                plan_snapshot={},
                volume_snapshot={},
                fencing_token=uuid.uuid4(),
                created_at=now,
                updated_at=now,
            )
            seed.add(job)
            await seed.flush()
            jobs.append(job.id)
    fixture = SimpleNamespace(
        owner_id=owner_id,
        job_ids=jobs,
        template_id=revision.template_id,
        plan_id=plan.id,
        volume_id=volume.id,
    )
    try:
        yield fixture
    finally:
        async with AsyncSession(test_engine) as cleanup, cleanup.begin():
            await cleanup.execute(delete(CreditHold).where(CreditHold.user_id == owner_id))
            await cleanup.execute(delete(BatchJob).where(BatchJob.user_id == owner_id))
            await cleanup.execute(delete(Volume).where(Volume.owner_id == owner_id))
            await cleanup.execute(
                delete(EnvironmentRevision).where(
                    EnvironmentRevision.template_id == fixture.template_id
                )
            )
            await cleanup.execute(
                delete(EnvironmentTemplate).where(EnvironmentTemplate.id == fixture.template_id)
            )
            await cleanup.execute(delete(ServerPlan).where(ServerPlan.id == fixture.plan_id))
            await cleanup.execute(delete(User).where(User.id == owner_id))


@pytest.mark.asyncio
async def test_concurrent_holds_serialize_on_the_user_row(committed_hold_world):
    fixture = committed_hold_world
    barrier = asyncio.Barrier(2)

    async def hold(job_id):
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            try:
                created = await CreditHoldService.create_hold(
                    db, user_id=fixture.owner_id, job_id=job_id, amount=60
                )
                await db.commit()
                return created.id
            except CreditHoldError as exc:
                await db.rollback()
                return exc.code

    results = await asyncio.wait_for(
        asyncio.gather(hold(fixture.job_ids[0]), hold(fixture.job_ids[1])),
        timeout=10,
    )
    assert sum(isinstance(result, uuid.UUID) for result in results) == 1
    assert results.count("insufficient_credits") == 1

    async with AsyncSession(test_engine) as verify:
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(CreditHold)
                .where(CreditHold.user_id == fixture.owner_id, CreditHold.state == HELD)
            )
            == 1
        )
        assert await CreditHoldService.spendable_balance(verify, fixture.owner_id) == 40
