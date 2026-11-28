# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Paid batch job authorization, admission, settlement and refund contracts."""

import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob
from app.models.credit_hold import CreditHold
from app.models.credit_transaction import CreditTransaction
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.resource_quota import ResourceQuota
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.schemas.batch_job import BatchJobSubmitRequest
from app.services.batch_job_admission_service import (
    BatchJobAdmissionService,
    JobAdmission,
)
from app.services.batch_job_finalizer import BatchJobFinalizer
from app.services.batch_job_service import BatchJobService, JobError
from app.services.credit_hold_service import (
    HELD,
    RELEASED,
    SETTLED,
    CreditHoldService,
)
from app.services.credit_service import CreditService
from tests.conftest import test_engine

IMAGE_ID = "sha256:" + "a" * 64


def local_identity():
    return {
        "requested_reference": "approved:latest",
        "local_id": IMAGE_ID,
        "repository_digests": [],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }


def admission_driver(*, exists=True):
    return SimpleNamespace(
        image_exists=AsyncMock(return_value=exists),
        resolve_image=AsyncMock(return_value=local_identity()),
        pull_image=AsyncMock(side_effect=AssertionError("must never pull a tag")),
        get_container_by_name=AsyncMock(return_value=None),
        get_container_info=AsyncMock(side_effect=AssertionError("no runtime")),
        delete_container=AsyncMock(side_effect=AssertionError("no runtime")),
    )


@pytest.fixture(autouse=True)
def billing_settings(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    monkeypatch.setattr(settings, "batch_jobs_allow_paid_plans", True)
    monkeypatch.setattr(settings, "batch_jobs_max_active_fleet", 10)
    monkeypatch.setattr(settings, "batch_jobs_max_active_per_owner", 10)
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", False)


async def make_resources(db, owner, *, cost_per_hour=10, max_runtime_seconds=1800):
    marker = uuid.uuid4().hex[:12]
    plan = ServerPlan(
        name=f"billing-plan-{marker}",
        slug=f"billing-plan-{marker}",
        cpu_limit=1.0,
        memory_limit="1g",
        disk_limit="2g",
        gpu_limit=0,
        cost_per_hour=cost_per_hour,
        max_servers_per_user=10,
        is_active=True,
        is_public=True,
        visible_to_roles=["user"],
    )
    template = EnvironmentTemplate(
        name=f"billing-env-{marker}",
        slug=f"billing-env-{marker}",
        image="approved:latest",
        is_active=True,
        is_public=True,
    )
    db.add_all([plan, template])
    await db.flush()
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint=uuid.uuid4().hex * 2,
        template_fingerprint=uuid.uuid4().hex * 2,
        configuration={
            "image": "approved:latest",
            "environment_variables": {"PRIVATE_VALUE": "must-not-leak"},
            "packages": [],
            "volumes": [],
            "ports": [],
        },
        runtime_identity=local_identity(),
    )
    volume = Volume(
        name=f"billing-volume-{marker}",
        display_name="Billing data",
        owner_id=owner.id,
        visibility="private",
        max_size_bytes=1024**3,
        status="active",
    )
    quota = ResourceQuota(
        user_id=owner.id,
        max_cpu_total=8,
        max_memory_total="16g",
        max_disk_total="100g",
        max_gpu_total=0,
        max_servers_total=10,
    )
    db.add_all([revision, volume, quota])
    await db.flush()
    return SimpleNamespace(
        plan=plan,
        template=template,
        revision=revision,
        volume=volume,
        quota=quota,
        max_runtime_seconds=max_runtime_seconds,
    )


def submit_request(resources, *, name="Paid job", max_runtime_seconds=None):
    return BatchJobSubmitRequest(
        name=name,
        revision_id=resources.revision.id,
        plan_id=resources.plan.id,
        volume_id=resources.volume.id,
        argv=["python", "-c", "print('ok')"],
        max_runtime_seconds=max_runtime_seconds or resources.max_runtime_seconds,
    )


async def submit_job(db, owner, resources, *, key=None, **overrides):
    return await BatchJobService(db).submit(
        owner,
        key or uuid.uuid4().hex,
        submit_request(resources, **overrides),
    )


async def admit(db, job_id, *, driver=None):
    return await BatchJobAdmissionService(db, driver or admission_driver()).admit(
        job_id, executor_id=uuid.uuid4()
    )


async def hold_for(db, job_id):
    return await db.scalar(
        select(CreditHold)
        .where(CreditHold.job_id == job_id)
        .execution_options(populate_existing=True)
    )


async def transaction_count(db, user_id):
    return int(
        await db.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.user_id == user_id)
        )
        or 0
    )


@pytest.mark.asyncio
async def test_paid_submit_creates_one_hold_and_reports_authorization(db_session, test_user):
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)

    assert detail.state == "queued"
    assert detail.billing.mode == "paid"
    assert detail.billing.authorized == 5
    assert detail.billing.rate_per_hour == 10
    assert detail.billing.state == HELD
    assert detail.billing.charged == 0

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.billing_mode == "paid"
    assert job.authorized_credits == 5
    assert job.billing_rate_per_hour == 10
    assert job.billing_state == HELD
    assert job.charged_credits == 0
    assert job.billing_transaction_id is None

    hold = await hold_for(db_session, detail.id)
    assert hold is not None
    assert hold.amount == 5
    assert hold.state == HELD
    assert hold.charged_credits == 0
    assert hold.settled_at is None
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 95


@pytest.mark.asyncio
async def test_paid_submit_with_insufficient_credits_returns_402_without_rows(
    db_session, test_user
):
    user_id = test_user.id
    test_user.nuke_balance = 50
    await db_session.commit()
    resources = await make_resources(
        db_session, test_user, cost_per_hour=60, max_runtime_seconds=3600
    )

    with pytest.raises(JobError) as exc:
        await submit_job(db_session, test_user, resources)
    assert exc.value.code == "insufficient_credits"
    assert exc.value.status_code == 402

    assert (
        await db_session.scalar(
            select(func.count()).select_from(BatchJob).where(BatchJob.user_id == user_id)
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(CreditHold).where(CreditHold.user_id == user_id)
        )
        == 0
    )
    assert await CreditHoldService.spendable_balance(db_session, user_id) == 50


@pytest.mark.asyncio
async def test_queue_cancel_releases_the_hold(db_session, test_user):
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)

    cancelled = await BatchJobService(db_session).cancel(test_user, detail.id)
    assert cancelled.state == "cancelled"
    assert cancelled.billing.state == RELEASED
    assert cancelled.billing.charged == 0

    hold = await hold_for(db_session, detail.id)
    assert hold.state == RELEASED
    assert hold.charged_credits == 0
    assert hold.settled_at is not None
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 100

    again = await BatchJobService(db_session).cancel(test_user, detail.id)
    assert again.state == "cancelled"
    assert again.billing.state == RELEASED


@pytest.mark.asyncio
async def test_queue_expiry_releases_the_hold(db_session, test_user):
    user_id = test_user.id
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)
    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    job.queue_expires_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()

    assert await admit(db_session, detail.id) is None

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.state == "expired"
    assert job.reason_code == "queue_expired"
    assert job.billing_state == RELEASED
    assert job.charged_credits == 0
    hold = await hold_for(db_session, detail.id)
    assert hold.state == RELEASED
    assert await CreditHoldService.spendable_balance(db_session, user_id) == 100
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(VolumeOperation)
            .where(VolumeOperation.operation_id == detail.id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_admission_fails_without_its_hold(db_session, test_user):
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)
    hold = await hold_for(db_session, detail.id)
    await db_session.delete(hold)
    await db_session.commit()

    assert await admit(db_session, detail.id) is None

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "billing_unavailable"
    assert job.billing_state == RELEASED
    assert job.reservation_active is False
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 100

    detail_body = await BatchJobService(db_session).get(test_user, detail.id)
    assert detail_body.reason_message == (
        "Job credit authorization is unavailable. Submit a new job."
    )


@pytest.mark.asyncio
async def test_admission_fails_when_hold_amount_does_not_match_authorization(db_session, test_user):
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)
    hold = await hold_for(db_session, detail.id)
    hold.amount = 99
    await db_session.commit()

    assert await admit(db_session, detail.id) is None

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "billing_unavailable"
    assert job.billing_state == RELEASED
    hold = await hold_for(db_session, detail.id)
    assert hold.state == RELEASED


@pytest.mark.asyncio
async def test_admission_fails_when_balance_no_longer_covers_the_hold(db_session, test_user):
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)
    test_user.nuke_balance = 4
    await db_session.commit()

    assert await admit(db_session, detail.id) is None

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "insufficient_credits"
    assert job.billing_state == RELEASED
    hold = await hold_for(db_session, detail.id)
    assert hold.state == RELEASED
    assert job.reservation_active is False


@pytest.mark.asyncio
async def test_admission_releases_when_paid_flag_turns_off(db_session, test_user, monkeypatch):
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)
    monkeypatch.setattr(settings, "batch_jobs_allow_paid_plans", False)

    assert await admit(db_session, detail.id) is None

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "paid_plan_unsupported"
    assert job.billing_state == RELEASED
    hold = await hold_for(db_session, detail.id)
    assert hold.state == RELEASED
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 100


@pytest.mark.asyncio
async def test_terminal_success_charges_observed_runtime_and_refunds(db_session, test_user):
    user_id = test_user.id
    resources = await make_resources(
        db_session, test_user, cost_per_hour=36, max_runtime_seconds=1800
    )
    detail = await submit_job(db_session, test_user, resources)
    admission = await admit(db_session, detail.id)
    assert isinstance(admission, JobAdmission)

    finished = utc_now()
    started = finished - timedelta(seconds=600)
    released = await BatchJobAdmissionService(db_session, admission_driver()).release_terminal(
        detail.id,
        fencing_token=admission.fencing_token,
        state="succeeded",
        outcome_code="succeeded",
        proof_class="observed",
        exit_code=0,
        started_at=started,
        finished_at=finished,
        executor_terminated=True,
    )
    assert released is not None
    assert released.state == "succeeded"

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.charged_credits == 6
    assert job.billing_state == SETTLED
    assert job.billing_transaction_id is not None
    assert job.reservation_active is False

    hold = await hold_for(db_session, detail.id)
    assert hold.state == SETTLED
    assert hold.charged_credits == 6
    assert hold.transaction_id == job.billing_transaction_id

    transaction_id = job.billing_transaction_id
    transaction = await db_session.scalar(
        select(CreditTransaction).where(CreditTransaction.id == transaction_id)
    )
    assert transaction.type == "batch_job_usage"
    assert transaction.amount == -6
    assert transaction.balance_after == 94
    assert transaction.meta["rate_per_hour"] == 36
    assert transaction.meta["authorized_credits"] == 18
    assert transaction.meta["observed_seconds"] == 600
    assert transaction.meta["refunded"] == 12
    assert transaction.meta["unpaid"] == 0
    assert test_user.nuke_balance == 94

    replay = await BatchJobAdmissionService(db_session, admission_driver()).release_terminal(
        detail.id,
        fencing_token=admission.fencing_token,
        state="failed",
        outcome_code="failed",
        executor_terminated=True,
    )
    assert replay is not None
    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.charged_credits == 6
    assert job.billing_state == SETTLED
    assert job.billing_transaction_id == transaction_id
    assert await transaction_count(db_session, user_id) == 1
    assert await CreditHoldService.spendable_balance(db_session, user_id) == 94


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "outcome"),
    [("failed", "failed"), ("timed_out", "timed_out")],
)
async def test_terminal_failure_and_timeout_charge_actual_runtime(
    db_session, test_user, state, outcome
):
    resources = await make_resources(
        db_session, test_user, cost_per_hour=36, max_runtime_seconds=1800
    )
    detail = await submit_job(db_session, test_user, resources)
    admission = await admit(db_session, detail.id)
    assert isinstance(admission, JobAdmission)

    finished = utc_now()
    # More than the maximum runtime is clamped to the authorized interval.
    started = finished - timedelta(seconds=7200)
    released = await BatchJobAdmissionService(db_session, admission_driver()).release_terminal(
        detail.id,
        fencing_token=admission.fencing_token,
        state=state,
        outcome_code=outcome,
        proof_class="observed",
        exit_code=1,
        started_at=started,
        finished_at=finished,
        executor_terminated=True,
    )
    assert released is not None
    assert released.charged_credits == 18
    assert released.billing_state == SETTLED
    hold = await hold_for(db_session, detail.id)
    assert hold.state == SETTLED
    assert hold.charged_credits == 18
    assert test_user.nuke_balance == 82


@pytest.mark.asyncio
async def test_partial_balance_settlement_reports_unpaid_on_job_detail(db_session, test_user):
    user_id = test_user.id
    resources = await make_resources(
        db_session, test_user, cost_per_hour=36, max_runtime_seconds=1800
    )
    detail = await submit_job(db_session, test_user, resources)
    admission = await admit(db_session, detail.id)
    assert isinstance(admission, JobAdmission)

    owner = await db_session.get(User, user_id, populate_existing=True)
    owner.nuke_balance = 6
    await db_session.commit()
    finished = utc_now()
    released = await BatchJobAdmissionService(db_session, admission_driver()).release_terminal(
        detail.id,
        fencing_token=admission.fencing_token,
        state="succeeded",
        outcome_code="succeeded",
        exit_code=0,
        started_at=finished - timedelta(seconds=3600),
        finished_at=finished,
        executor_terminated=True,
    )
    assert released is not None
    assert released.charged_credits == 6
    assert released.billing_state == SETTLED

    owner = await db_session.get(User, user_id, populate_existing=True)
    serialized = await BatchJobService(db_session).get(owner, detail.id)
    assert serialized.billing.authorized == 18
    assert serialized.billing.charged == 6
    assert serialized.billing.unpaid == 12


@pytest.mark.asyncio
async def test_prestart_failure_releases_the_full_hold(db_session, test_user):
    user_id = test_user.id
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)

    assert await admit(db_session, detail.id, driver=admission_driver(exists=False)) is None

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "artifact_missing"
    assert job.charged_credits == 0
    assert job.billing_state == RELEASED
    hold = await hold_for(db_session, detail.id)
    assert hold.state == RELEASED
    assert hold.charged_credits == 0
    assert await transaction_count(db_session, user_id) == 0
    assert await CreditHoldService.spendable_balance(db_session, user_id) == 100


@pytest.mark.asyncio
async def test_recovery_required_retains_the_hold(db_session, test_user):
    user_id = test_user.id
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)
    admission = await admit(db_session, detail.id)
    assert isinstance(admission, JobAdmission)

    driver = admission_driver()
    result = await BatchJobFinalizer(db_session, driver).finalize(
        detail.id,
        fencing_token=admission.fencing_token,
        state="succeeded",
        outcome_code="succeeded",
        executor_terminated=False,
    )
    assert result.executor_unconfirmed is True

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.state == "recovery_required"
    assert job.billing_state == HELD
    assert job.charged_credits == 0
    assert job.reservation_active is True
    hold = await hold_for(db_session, detail.id)
    assert hold.state == HELD
    assert await CreditHoldService.spendable_balance(db_session, user_id) == 95
    driver.delete_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_zero_cost_job_is_unaffected_by_holds(db_session, test_user):
    resources = await make_resources(db_session, test_user, cost_per_hour=0)
    detail = await submit_job(db_session, test_user, resources)
    assert detail.billing.mode == "zero_cost"
    assert detail.billing.authorized == 0
    assert detail.billing.rate_per_hour == 0
    assert detail.billing.state == "none"
    assert await hold_for(db_session, detail.id) is None

    admission = await admit(db_session, detail.id)
    assert isinstance(admission, JobAdmission)
    finished = utc_now()
    released = await BatchJobAdmissionService(db_session, admission_driver()).release_terminal(
        detail.id,
        fencing_token=admission.fencing_token,
        state="succeeded",
        outcome_code="succeeded",
        exit_code=0,
        started_at=finished - timedelta(seconds=600),
        finished_at=finished,
        executor_terminated=True,
    )
    assert released is not None
    assert released.charged_credits == 0
    assert released.billing_state == "none"
    assert released.billing_transaction_id is None
    assert await transaction_count(db_session, test_user.id) == 0


@pytest.mark.asyncio
async def test_paid_submit_replay_keeps_one_hold_and_one_transaction(db_session, test_user):
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    service = BatchJobService(db_session)
    request = submit_request(resources)

    first = await service.submit(test_user, "paid-stable-key", request)
    replay = await service.submit(test_user, "paid-stable-key", request)
    assert replay.replayed is True
    assert replay.id == first.id
    assert (
        await db_session.scalar(
            select(func.count()).select_from(CreditHold).where(CreditHold.job_id == first.id)
        )
        == 1
    )

    admission = await admit(db_session, first.id)
    assert isinstance(admission, JobAdmission)
    finished = utc_now()
    service = BatchJobAdmissionService(db_session, admission_driver())
    for _ in range(2):
        await service.release_terminal(
            first.id,
            fencing_token=admission.fencing_token,
            state="succeeded",
            outcome_code="succeeded",
            exit_code=0,
            started_at=finished - timedelta(seconds=360),
            finished_at=finished,
            executor_terminated=True,
        )
    assert await transaction_count(db_session, test_user.id) == 1


@pytest.mark.asyncio
async def test_interactive_debit_cannot_consume_held_credits(db_session, test_user):
    resources = await make_resources(
        db_session, test_user, cost_per_hour=10, max_runtime_seconds=1800
    )
    detail = await submit_job(db_session, test_user, resources)
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 95

    credit = CreditService(db_session)
    with pytest.raises(HTTPException) as denied:
        await credit.consume_credits(str(test_user.id), 96, "Interactive server usage")
    assert denied.value.status_code == 400
    assert test_user.nuke_balance == 100

    await credit.consume_credits(str(test_user.id), 95, "Interactive server usage")
    assert test_user.nuke_balance == 5
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 0

    cancelled = await BatchJobService(db_session).cancel(test_user, detail.id)
    assert cancelled.billing.state == RELEASED
    assert test_user.nuke_balance == 5
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 5


@pytest_asyncio.fixture
async def committed_paid_world():
    """A committed owner and unused resources for one paid submit/debit race."""
    marker = uuid.uuid4().hex
    owner_id = uuid.uuid4()
    async with AsyncSession(test_engine, expire_on_commit=False) as seed, seed.begin():
        owner = User(
            id=owner_id,
            username=f"paid_{marker}",
            email=f"{marker}@example.test",
            role="user",
            is_active=True,
            nuke_balance=100,
        )
        seed.add(owner)
        await seed.flush()
        resources = await make_resources(seed, owner, cost_per_hour=100)
        # One hour of maximum runtime authorizes the whole balance.
        request = BatchJobSubmitRequest(
            name=f"paid-race-{marker}",
            revision_id=resources.revision.id,
            plan_id=resources.plan.id,
            volume_id=resources.volume.id,
            argv=["true"],
            max_runtime_seconds=3600,
        )
    fixture = SimpleNamespace(
        owner_id=owner_id,
        request=request,
        plan_id=resources.plan.id,
        template_id=resources.template.id,
        volume_id=resources.volume.id,
    )
    try:
        yield fixture
    finally:
        async with AsyncSession(test_engine) as cleanup, cleanup.begin():
            await cleanup.execute(delete(CreditHold).where(CreditHold.user_id == owner_id))
            await cleanup.execute(delete(BatchJob).where(BatchJob.user_id == owner_id))
            await cleanup.execute(delete(Volume).where(Volume.owner_id == owner_id))
            await cleanup.execute(delete(ResourceQuota).where(ResourceQuota.user_id == owner_id))
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
async def test_concurrent_interactive_debit_and_paid_submit_cannot_double_spend(
    committed_paid_world,
):
    fixture = committed_paid_world
    barrier = asyncio.Barrier(2)

    async def submit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            owner = await db.get(User, fixture.owner_id)
            await asyncio.wait_for(barrier.wait(), timeout=5)
            try:
                return await BatchJobService(db).submit(owner, "paid-race-key", fixture.request)
            except JobError as exc:
                return exc

    async def debit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            try:
                await CreditService(db).consume_credits(
                    str(fixture.owner_id), 100, "Interactive server usage"
                )
                return "debited"
            except HTTPException as exc:
                return exc

    submitted, debited = await asyncio.wait_for(asyncio.gather(submit(), debit()), timeout=10)
    if isinstance(submitted, Exception):
        assert submitted.code == "insufficient_credits"
        assert debited == "debited"
    else:
        assert submitted.billing.state == HELD
        assert isinstance(debited, HTTPException)
        assert debited.status_code == 400

    async with AsyncSession(test_engine) as verify:
        balance = await verify.scalar(select(User.nuke_balance).where(User.id == fixture.owner_id))
        held = await CreditHoldService.held_total(verify, fixture.owner_id)
        jobs = int(
            await verify.scalar(
                select(func.count())
                .select_from(BatchJob)
                .where(BatchJob.user_id == fixture.owner_id)
            )
            or 0
        )
    assert int(balance) >= held
    if isinstance(submitted, Exception):
        assert held == 0
        assert jobs == 0
        assert int(balance) == 0
    else:
        assert held == 100
        assert jobs == 1
        assert int(balance) == 100
