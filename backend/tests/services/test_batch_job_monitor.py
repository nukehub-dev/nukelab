# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Batch job monitoring: observe identity, stop safely and finalize once."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.batch_job import BatchJobLog
from app.models.user import User
from app.services.batch_job_monitor import BatchJobMonitorService
from app.services.batch_job_service import BatchJobService
from tests.conftest import test_engine
from tests.services.test_batch_job_runtime import (
    committed_admitted_job as committed_admitted_job,
)
from tests.services.test_batch_job_runtime import (
    load_job,
    set_job,
    volume_operation,
)


async def promote(driver, fixture, *, state="running", **info):
    container_id = info.pop("container_id", "job-container")
    editor = await set_job(
        fixture.job_id,
        state=state,
        container_id=container_id,
    )
    info.setdefault("started_at", utc_now() - timedelta(minutes=1))
    driver.add_job_container(editor, container_id=container_id, **info)
    return editor


@pytest.mark.asyncio
async def test_running_job_refreshes_heartbeat_and_deadline(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    job = await promote(driver, fixture, status="running")
    old_heartbeat = job.heartbeat_at

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "running"
    updated = await load_job(fixture.job_id)
    assert updated.state == "running"
    assert updated.heartbeat_at is not None and updated.heartbeat_at >= old_heartbeat
    assert updated.started_at is not None
    assert updated.deadline_at == updated.started_at + timedelta(seconds=600)
    assert updated.start_observed_at is not None


@pytest.mark.asyncio
async def test_natural_zero_exit_succeeds_with_bounded_logs(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    driver.logs = "hello from the job"
    finished = utc_now() - timedelta(seconds=2)
    await promote(
        driver,
        fixture,
        status="exited",
        exit_code=0,
        started_at=utc_now() - timedelta(minutes=1),
        finished_at=finished,
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "succeeded"
    job = await load_job(fixture.job_id)
    assert job.state == "succeeded"
    assert job.outcome_code == "succeeded"
    assert job.exit_code == 0
    assert job.proof_class == "runtime"
    assert job.reservation_active is False
    assert job.cleanup_state == "complete"
    assert job.cleanup_attempts == 1
    assert job.log_state == "available"
    assert job.log_size_bytes == len("hello from the job")
    async with AsyncSession(test_engine) as db:
        payload = await db.get(BatchJobLog, fixture.job_id)
    assert payload is not None
    assert payload.text == "hello from the job"
    assert driver.deleted == [(job.container_id, False)]
    guard = await volume_operation(fixture.job_id)
    assert guard.state == "succeeded"


@pytest.mark.asyncio
async def test_nonzero_exit_fails_and_releases_guard(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    await promote(
        driver,
        fixture,
        status="exited",
        exit_code=7,
        started_at=utc_now() - timedelta(minutes=1),
        finished_at=utc_now() - timedelta(seconds=1),
    )
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)
    assert observation.action == "failed"
    job = await load_job(fixture.job_id)
    assert job.state == "failed"
    assert job.reason_code == "nonzero_exit"
    assert job.exit_code == 7
    assert job.reservation_active is False
    assert (await volume_operation(fixture.job_id)).state == "failed"


@pytest.mark.asyncio
async def test_oom_kill_is_reported_as_failed(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    await promote(
        driver,
        fixture,
        status="exited",
        exit_code=137,
        oom_killed=True,
        started_at=utc_now() - timedelta(minutes=1),
        finished_at=utc_now() - timedelta(seconds=1),
    )
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)
    assert observation.action == "failed"
    job = await load_job(fixture.job_id)
    assert job.state == "failed"
    assert job.reason_code == "oom_killed"
    assert job.exit_code == 137


@pytest.mark.asyncio
async def test_deadline_stops_the_verified_runtime_and_times_out(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    job = await promote(driver, fixture, status="running")
    await set_job(
        fixture.job_id,
        started_at=utc_now() - timedelta(minutes=20),
        deadline_at=utc_now() - timedelta(seconds=1),
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "timed_out"
    assert driver.stopped and driver.stopped[0][0] == job.container_id
    updated = await load_job(fixture.job_id)
    assert updated.state == "timed_out"
    assert updated.reason_code == "job_deadline_exceeded"
    assert updated.reservation_active is False
    assert updated.cleanup_state == "complete"


@pytest.mark.asyncio
async def test_cancelling_running_job_stops_and_finishes_cancelled(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    job = await promote(driver, fixture, status="running")
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        owner = await db.get(User, fixture.owner_id)
        cancelled = await BatchJobService(db).cancel(owner, fixture.job_id)
    assert cancelled.state == "cancelling"

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "cancelled"
    assert driver.stopped and driver.stopped[0][0] == job.container_id
    updated = await load_job(fixture.job_id)
    assert updated.state == "cancelled"
    assert updated.reason_code == "request_cancelled"
    assert updated.reservation_active is False


@pytest.mark.asyncio
async def test_natural_exit_before_stop_request_wins_over_cancellation(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    stop_at = utc_now()
    finished = stop_at - timedelta(seconds=30)
    editor = await set_job(
        fixture.job_id,
        state="cancelling",
        container_id="job-container",
        stop_requested_at=stop_at,
    )
    driver.add_job_container(
        editor,
        status="exited",
        exit_code=0,
        started_at=stop_at - timedelta(minutes=1),
        finished_at=finished,
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "succeeded"
    job = await load_job(fixture.job_id)
    assert job.state == "succeeded"
    assert job.exit_code == 0
    assert driver.stopped == []


@pytest.mark.asyncio
async def test_log_tail_is_truncated_to_the_configured_budget(committed_admitted_job, monkeypatch):
    fixture = committed_admitted_job
    driver = fixture.driver
    monkeypatch.setattr(settings, "batch_jobs_log_tail_bytes", 10)
    driver.logs = "0123456789abcdef"
    await promote(
        driver,
        fixture,
        status="exited",
        exit_code=0,
        started_at=utc_now() - timedelta(minutes=1),
        finished_at=utc_now() - timedelta(seconds=1),
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    job = await load_job(fixture.job_id)
    assert job.state == "succeeded"
    assert job.log_state == "truncated"
    assert job.log_truncated is True
    assert job.log_size_bytes == 16
    async with AsyncSession(test_engine) as db:
        payload = await db.get(BatchJobLog, fixture.job_id)
    assert payload.text == "6789abcdef"
    assert payload.truncated is True


@pytest.mark.asyncio
async def test_log_capture_failure_keeps_the_exit_result(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    driver.log_error = RuntimeError("log driver unavailable")
    await promote(
        driver,
        fixture,
        status="exited",
        exit_code=0,
        started_at=utc_now() - timedelta(minutes=1),
        finished_at=utc_now() - timedelta(seconds=1),
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    job = await load_job(fixture.job_id)
    assert job.state == "succeeded"
    assert job.log_state == "unavailable"
    async with AsyncSession(test_engine) as db:
        assert await db.get(BatchJobLog, fixture.job_id) is None


@pytest.mark.asyncio
async def test_container_identity_mismatch_requires_recovery(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    job = await promote(driver, fixture, status="running")
    driver.containers[job.container_id]["Config"]["Labels"]["nukelab.job.fence"] = str(uuid.uuid4())

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "recovery_required"
    updated = await load_job(fixture.job_id)
    assert updated.state == "recovery_required"
    assert updated.reservation_active is True
    assert (await volume_operation(fixture.job_id)).state == "reserved"
    assert driver.stopped == []


@pytest.mark.asyncio
async def test_missing_runtime_for_starting_job_starts_exactly_once(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "running"
    assert len(driver.created) == 1
    assert driver.started == ["created-1"]
    job = await load_job(fixture.job_id)
    assert job.state == "running"


@pytest.mark.asyncio
async def test_missing_runtime_for_running_job_requires_recovery(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    await set_job(
        fixture.job_id,
        state="running",
        container_id="missing-container",
        container_name=f"nukelab-job-{fixture.job_id}",
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "recovery_required"
    job = await load_job(fixture.job_id)
    assert job.state == "recovery_required"
    assert driver.created == []


@pytest.mark.asyncio
async def test_created_container_is_started_when_no_start_was_issued(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    editor = await set_job(
        fixture.job_id,
        state="starting",
        create_requested_at=utc_now() - timedelta(seconds=5),
        container_id="created-only",
    )
    driver.add_job_container(editor, container_id="created-only", status="created")

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "running"
    assert driver.started == ["created-only"]
    job = await load_job(fixture.job_id)
    assert job.state == "running"
    assert job.start_requested_at is not None


@pytest.mark.asyncio
async def test_created_container_after_start_checkpoint_requires_recovery(
    committed_admitted_job,
):
    fixture = committed_admitted_job
    driver = fixture.driver
    started = utc_now()
    editor = await set_job(
        fixture.job_id,
        state="starting",
        create_requested_at=started - timedelta(seconds=10),
        start_requested_at=started,
        heartbeat_at=started - timedelta(seconds=settings.batch_jobs_heartbeat_stale_seconds + 5),
        container_id="created-only",
    )
    driver.add_job_container(editor, container_id="created-only", status="created")

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "recovery_required"
    assert driver.started == []
    job = await load_job(fixture.job_id)
    assert job.state == "recovery_required"


@pytest.mark.asyncio
async def test_cancelled_created_container_requires_recovery(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    stop_at = utc_now()
    editor = await set_job(
        fixture.job_id,
        state="cancelling",
        stop_requested_at=stop_at,
        create_requested_at=stop_at - timedelta(seconds=10),
        container_id="created-only",
    )
    driver.add_job_container(editor, container_id="created-only", status="created")

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        observation = await BatchJobMonitorService(db, driver).observe_job(fixture.job_id)

    assert observation.action == "recovery_required"
    assert driver.started == []
    assert driver.stopped == []


@pytest.mark.asyncio
async def test_monitor_bound_and_scan_are_bounded(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    await promote(driver, fixture, status="running")
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        service = BatchJobMonitorService(db, driver)
        with pytest.raises(ValueError, match="between 1 and 500"):
            await service.monitor(limit=0)
        report = await service.monitor(limit=1)
    assert report.scanned >= 1
