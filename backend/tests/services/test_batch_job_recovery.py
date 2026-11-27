# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Batch job recovery: stale inspections, retained guards and cleanup retry."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.system_setting import SystemSetting
from app.services.batch_job_reconciliation import (
    SCAN_STATE_KEY,
    BatchJobReconciliationService,
)
from tests.conftest import test_engine
from tests.services.test_batch_job_runtime import (
    committed_admitted_job as committed_admitted_job,
)
from tests.services.test_batch_job_runtime import (
    load_job,
    set_job,
    volume_operation,
)


async def stale_running(driver, fixture, **info):
    editor = await set_job(
        fixture.job_id,
        state="running",
        container_id="job-container",
        started_at=utc_now() - timedelta(minutes=1),
        deadline_at=utc_now() + timedelta(minutes=9),
        heartbeat_at=utc_now() - timedelta(seconds=settings.batch_jobs_heartbeat_stale_seconds + 5),
    )
    info.setdefault("status", "running")
    info.setdefault("started_at", utc_now() - timedelta(minutes=1))
    driver.add_job_container(editor, container_id="job-container", **info)
    return editor


@pytest.mark.asyncio
async def test_stale_heartbeat_triggers_inspection_not_takeover(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    old = await stale_running(driver, fixture)

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        report = await BatchJobReconciliationService(db, driver).scan(limit=5)

    assert report.scanned >= 1
    assert report.started >= 1
    assert driver.created == []
    assert driver.started == []
    job = await load_job(fixture.job_id)
    assert job.state == "running"
    assert job.heartbeat_at > old.heartbeat_at
    assert job.reservation_active is True


@pytest.mark.asyncio
async def test_fresh_heartbeat_is_not_selected_for_inspection(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    await set_job(
        fixture.job_id,
        state="running",
        container_id="job-container",
        heartbeat_at=utc_now(),
    )
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        service = BatchJobReconciliationService(db, driver)
        async with db.begin():
            candidates = await service._stale_candidates(10)
    assert fixture.job_id not in candidates
    assert driver.created == []


@pytest.mark.asyncio
async def test_started_job_is_never_started_again_after_stale_inspection(
    committed_admitted_job,
):
    fixture = committed_admitted_job
    driver = fixture.driver
    now = utc_now()
    await set_job(
        fixture.job_id,
        state="starting",
        create_requested_at=now - timedelta(minutes=10),
        start_requested_at=now - timedelta(minutes=9),
        heartbeat_at=now - timedelta(minutes=10),
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        report = await BatchJobReconciliationService(db, driver).scan(limit=5)

    assert report.recovery_required >= 1
    assert driver.created == []
    assert driver.started == []
    job = await load_job(fixture.job_id)
    assert job.state == "recovery_required"
    assert job.reservation_active is True
    assert (await volume_operation(fixture.job_id)).state == "reserved"


@pytest.mark.asyncio
async def test_recovery_required_row_retains_reservation_and_guard(
    committed_admitted_job,
):
    fixture = committed_admitted_job
    driver = fixture.driver
    await set_job(
        fixture.job_id,
        state="recovery_required",
        heartbeat_at=utc_now()
        - timedelta(seconds=settings.batch_jobs_heartbeat_stale_seconds + 60),
    )
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        report = await BatchJobReconciliationService(db, driver).scan(limit=5)
    assert report.retained >= 1
    job = await load_job(fixture.job_id)
    assert job.state == "recovery_required"
    assert job.reservation_active is True
    assert (await volume_operation(fixture.job_id)).state == "reserved"
    assert driver.deleted == []


@pytest.mark.asyncio
async def test_recovery_required_exited_runtime_is_finalized(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    editor = await set_job(
        fixture.job_id,
        state="recovery_required",
        container_id="job-container",
        heartbeat_at=utc_now()
        - timedelta(seconds=settings.batch_jobs_heartbeat_stale_seconds + 60),
        started_at=utc_now() - timedelta(minutes=10),
        deadline_at=utc_now() + timedelta(minutes=10),
    )
    driver.add_job_container(
        editor,
        container_id="job-container",
        status="exited",
        exit_code=0,
        started_at=utc_now() - timedelta(minutes=2),
        finished_at=utc_now() - timedelta(minutes=1),
    )

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        report = await BatchJobReconciliationService(db, driver).scan(limit=5)

    assert report.finalized >= 1
    job = await load_job(fixture.job_id)
    assert job.state == "succeeded"
    assert job.reservation_active is False
    assert (await volume_operation(fixture.job_id)).state == "succeeded"


@pytest.mark.asyncio
async def test_cleanup_failure_is_recorded_and_retried(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    editor = await set_job(
        fixture.job_id,
        state="failed",
        outcome_code="failed",
        reason_code="nonzero_exit",
        finished_at=utc_now(),
        container_id="job-container",
        cleanup_state="pending",
        cleanup_attempts=0,
        reservation_active=False,
    )
    driver.add_job_container(editor, container_id="job-container", status="exited", exit_code=1)
    driver.delete_side_effect = RuntimeError("daemon busy")

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        report = await BatchJobReconciliationService(db, driver).scan(limit=10)
    assert report.cleanup_pending >= 1
    job = await load_job(fixture.job_id)
    assert job.state == "failed"
    assert job.cleanup_state == "pending"
    assert job.cleanup_attempts == 1

    driver.delete_side_effect = None
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        report = await BatchJobReconciliationService(db, driver).scan(limit=10)
    assert report.cleanup_completed >= 1
    job = await load_job(fixture.job_id)
    assert job.state == "failed"
    assert job.cleanup_state == "complete"
    assert job.cleanup_attempts == 2


@pytest.mark.asyncio
async def test_scan_state_is_persisted_without_identifiers(committed_admitted_job):
    fixture = committed_admitted_job
    driver = fixture.driver
    await stale_running(driver, fixture)
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        await BatchJobReconciliationService(db, driver).scan(limit=5)
    async with AsyncSession(test_engine) as db:
        state = await db.get(SystemSetting, SCAN_STATE_KEY)
    assert state is not None
    assert '"report"' in state.value
    assert str(fixture.job_id) not in state.value
    assert str(fixture.owner_id) not in state.value


@pytest.mark.asyncio
async def test_recovery_scan_bound_is_validated(committed_admitted_job):
    driver = committed_admitted_job.driver
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        service = BatchJobReconciliationService(db, driver)
        for value in (0, 501, True, "5"):
            with pytest.raises(ValueError, match="between 1 and 500"):
                await service.scan(limit=value)
