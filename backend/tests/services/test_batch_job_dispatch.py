# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded dispatch claims each queued job once and survives broker failure."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.batch_job import BatchJobSubmitRequest
from app.services.batch_job_dispatch_service import BatchJobDispatchService
from app.services.batch_job_monitor import BatchJobMonitorService
from app.services.batch_job_service import BatchJobService
from tests.conftest import test_engine
from tests.services.test_batch_job_runtime import (
    committed_queued_job as committed_queued_job,
)
from tests.services.test_batch_job_runtime import (
    load_job,
    make_driver,
    set_job,
    volume_operation,
)


@pytest_asyncio.fixture(autouse=True)
async def reset_dispatch_cursor():
    async with AsyncSession(test_engine) as db, db.begin():
        await db.execute(
            delete(SystemSetting).where(SystemSetting.key == "batch_jobs_dispatch_cursor")
        )
    yield


@pytest.mark.asyncio
async def test_dispatch_selects_queued_job_and_enqueues_only_its_id(committed_queued_job):
    fixture = committed_queued_job
    await set_job(fixture.job_id, created_at=utc_now().replace(year=2020))
    driver = make_driver()
    sent = []

    async with AsyncSession(test_engine) as db:
        report = await BatchJobDispatchService(db, driver, enqueue=sent.append).dispatch(limit=1)

    assert report.selected == 1
    assert report.admitted == 1
    assert report.enqueued == 1
    assert sent == [str(fixture.job_id)]
    job = await load_job(fixture.job_id)
    assert job.state == "starting"
    assert job.reservation_active is True
    assert job.create_requested_at is None
    assert job.start_requested_at is None
    guard = await volume_operation(fixture.job_id)
    assert guard.state == "reserved"
    assert driver.created == []

    async with AsyncSession(test_engine) as db:
        duplicate = await BatchJobDispatchService(db, driver, enqueue=sent.append).dispatch(limit=1)
    assert duplicate.admitted == 0
    assert sent == [str(fixture.job_id)]


@pytest.mark.asyncio
async def test_broker_failure_leaves_a_monitor_recoverable_starting_job(
    committed_queued_job,
):
    fixture = committed_queued_job
    await set_job(fixture.job_id, created_at=utc_now().replace(year=2020))
    driver = make_driver()

    def enqueue(_job_id):
        raise RuntimeError("broker down")

    async with AsyncSession(test_engine) as db:
        report = await BatchJobDispatchService(db, driver, enqueue=enqueue).dispatch(limit=1)

    assert report.admitted == 1
    assert report.enqueued == 0
    assert report.errors == 1
    job = await load_job(fixture.job_id)
    assert job.state == "starting"
    assert job.reservation_active is True

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)
    assert observation.action == "running"
    job = await load_job(fixture.job_id)
    assert job.state == "running"
    assert job.container_id is not None
    assert driver.started == [job.container_id]


@pytest.mark.asyncio
async def test_owner_capacity_waits_without_creating_a_runtime(committed_queued_job, monkeypatch):
    fixture = committed_queued_job
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    monkeypatch.setattr(settings, "batch_jobs_max_active_per_owner", 1)
    await set_job(fixture.job_id, created_at=utc_now().replace(year=2019))

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        owner = await db.get(User, fixture.owner_id)
        second = await BatchJobService(db).submit(
            owner,
            uuid.uuid4().hex,
            BatchJobSubmitRequest(
                name="second job",
                revision_id=fixture.resources.revision.id,
                plan_id=fixture.resources.plan.id,
                volume_id=fixture.resources.volume.id,
                argv=["true"],
                max_runtime_seconds=300,
            ),
        )
    await set_job(second.id, created_at=utc_now().replace(year=2020))

    driver = make_driver()
    sent = []
    async with AsyncSession(test_engine) as db:
        report = await BatchJobDispatchService(db, driver, enqueue=sent.append).dispatch(limit=2)

    assert report.admitted == 1
    assert report.waiting >= 1
    assert len(sent) == 1
    first = await load_job(fixture.job_id)
    waiting = await load_job(second.id)
    assert first.state == "starting"
    assert waiting.state == "queued"
    assert waiting.reason_code == "waiting_capacity"
    assert driver.created == []


@pytest.mark.asyncio
async def test_expired_queued_job_finishes_without_a_runtime(committed_queued_job):
    fixture = committed_queued_job
    await set_job(
        fixture.job_id,
        created_at=utc_now().replace(year=2019),
        queue_expires_at=utc_now().replace(year=2019),
    )
    driver = make_driver()
    sent = []

    async with AsyncSession(test_engine) as db:
        report = await BatchJobDispatchService(db, driver, enqueue=sent.append).dispatch(limit=1)

    assert report.admitted == 0
    assert report.failed == 1
    assert sent == []
    job = await load_job(fixture.job_id)
    assert job.state == "expired"
    assert job.reason_code == "queue_expired"
    assert driver.created == []


@pytest.mark.asyncio
async def test_admission_is_not_selected_twice_after_terminal(committed_queued_job):
    fixture = committed_queued_job
    await set_job(fixture.job_id, created_at=utc_now().replace(year=2018))
    driver = make_driver()
    sent = []
    async with AsyncSession(test_engine) as db:
        first = await BatchJobDispatchService(db, driver, enqueue=sent.append).dispatch(limit=1)
    assert first.admitted == 1
    await set_job(fixture.job_id, state="succeeded", outcome_code="succeeded")
    async with AsyncSession(test_engine) as db:
        second = await BatchJobDispatchService(db, driver, enqueue=sent.append).dispatch(limit=1)
    assert second.admitted == 0
    assert len(sent) == 1
    assert (await load_job(fixture.job_id)).state == "succeeded"


@pytest.mark.asyncio
async def test_dispatch_bound_rejects_invalid_values(committed_queued_job):
    async with AsyncSession(test_engine) as db:
        service = BatchJobDispatchService(db, make_driver())
        for value in (0, -1, 101, True, "10"):
            with pytest.raises(ValueError, match="between 1 and 100"):
                await service.dispatch(limit=value)


@pytest.mark.asyncio
async def test_dispatch_scan_orders_by_created_at_and_id(committed_queued_job):
    fixture = committed_queued_job
    await set_job(fixture.job_id, created_at=utc_now().replace(year=2017))
    async with AsyncSession(test_engine) as db:
        service = BatchJobDispatchService(db, make_driver(), enqueue=lambda _job: None)
        async with db.begin():
            ids = await service._scan_batch(5)
    assert ids
    assert ids[0] == fixture.job_id
