# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Foreign owners cannot release holds and paid jobs cannot start unsecured."""

import uuid

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models.batch_job import BatchJob
from app.models.credit_hold import CreditHold
from app.models.user import User
from app.models.volume_operation import VolumeOperation
from app.services.batch_job_admission_service import BatchJobAdmissionService
from app.services.batch_job_service import BatchJobService, JobError
from app.services.credit_hold_service import HELD, RELEASED, CreditHoldService
from tests.services.test_batch_job_billing import (
    admission_driver,
    make_resources,
    submit_job,
)


@pytest.fixture(autouse=True)
def paid_jobs(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    monkeypatch.setattr(settings, "batch_jobs_allow_paid_plans", True)
    monkeypatch.setattr(settings, "batch_jobs_max_active_fleet", 10)
    monkeypatch.setattr(settings, "batch_jobs_max_active_per_owner", 10)


async def foreign_user(db):
    user = User(
        username=f"foreign-paid-{uuid.uuid4().hex[:8]}",
        email=f"foreign-paid-{uuid.uuid4().hex[:8]}@example.test",
        role="user",
        is_active=True,
        nuke_balance=100,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_foreign_owner_cannot_release_or_read_another_owners_hold(db_session, test_user):
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)
    foreign = await foreign_user(db_session)

    service = BatchJobService(db_session)
    with pytest.raises(JobError) as cancel_error:
        await service.cancel(foreign, detail.id)
    assert cancel_error.value.code == "job_not_found"
    assert cancel_error.value.status_code == 404

    with pytest.raises(JobError) as detail_error:
        await service.get(foreign, detail.id)
    assert detail_error.value.code == "job_not_found"

    hold = await db_session.scalar(select(CreditHold).where(CreditHold.job_id == detail.id))
    assert hold.state == HELD
    assert hold.charged_credits == 0
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 95

    serialized = (await service.get(test_user, detail.id)).model_dump_json()
    assert "hold_id" not in serialized
    assert "transaction_id" not in serialized
    assert str(hold.id) not in serialized


@pytest.mark.asyncio
async def test_cancelling_an_owned_job_never_releases_a_foreign_hold(db_session, test_user):
    first_resources = await make_resources(db_session, test_user, cost_per_hour=10)
    first = await submit_job(db_session, test_user, first_resources)

    second_user = await foreign_user(db_session)
    second_resources = await make_resources(db_session, second_user, cost_per_hour=10)
    second = await submit_job(db_session, second_user, second_resources)

    cancelled = await BatchJobService(db_session).cancel(second_user, second.id)
    assert cancelled.billing.state == RELEASED

    first_hold = await db_session.scalar(
        select(CreditHold)
        .where(CreditHold.job_id == first.id)
        .execution_options(populate_existing=True)
    )
    second_hold = await db_session.scalar(
        select(CreditHold)
        .where(CreditHold.job_id == second.id)
        .execution_options(populate_existing=True)
    )
    assert first_hold.state == HELD
    assert second_hold.state == RELEASED
    assert await CreditHoldService.spendable_balance(db_session, test_user.id) == 95


@pytest.mark.asyncio
async def test_paid_job_cannot_start_without_its_hold(db_session, test_user):
    resources = await make_resources(db_session, test_user, cost_per_hour=10)
    detail = await submit_job(db_session, test_user, resources)
    hold = await db_session.scalar(select(CreditHold).where(CreditHold.job_id == detail.id))
    await db_session.delete(hold)
    await db_session.commit()

    admission = await BatchJobAdmissionService(db_session, admission_driver()).admit(
        detail.id, executor_id=uuid.uuid4()
    )
    assert admission is None

    job = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "billing_unavailable"
    assert job.billing_state == RELEASED
    assert job.reservation_active is False
    assert job.volume_operation_id is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(VolumeOperation)
            .where(VolumeOperation.operation_id == detail.id)
        )
        == 0
    )
