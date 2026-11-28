# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Physical purge of expired batch-job log payloads without result loss."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob, BatchJobLog
from app.services.batch_job_retention import LogPurgeReport, purge_expired_logs
from tests.conftest import test_engine
from tests.services.test_batch_job_runtime import cleanup_owner, create_queued_job


async def _terminal_job_with_log(
    *,
    state: str = "succeeded",
    expires_at,
    log_state: str = "available",
    log_text: str = "hidden job output",
):
    fixture = await create_queued_job()
    now = utc_now()
    async with AsyncSession(test_engine, expire_on_commit=False) as db, db.begin():
        job = await db.get(BatchJob, fixture.job_id)
        job.state = state
        job.outcome_code = state
        job.proof_class = "runtime"
        job.exit_code = 0 if state == "succeeded" else 1
        job.result_recorded_at = now
        job.state_changed_at = now
        job.finished_at = now
        job.reservation_active = False
        job.cleanup_state = "complete"
        job.cleanup_attempts = 2
        job.log_state = log_state
        job.log_size_bytes = len(log_text.encode())
        job.log_expires_at = expires_at
        db.add(
            BatchJobLog(
                job_id=fixture.job_id,
                text=log_text,
                encoding="utf-8",
                truncated=False,
                size_bytes=len(log_text.encode()),
                captured_at=now,
                expires_at=expires_at,
            )
        )
    return fixture


@pytest.mark.asyncio
async def test_expired_payload_is_deleted_and_terminal_result_preserved():
    now = utc_now()
    fixture = await _terminal_job_with_log(expires_at=now - timedelta(seconds=1))
    try:
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            report = await purge_expired_logs(db, now=now)
        assert report == LogPurgeReport(scanned=1, deleted=1, errors=0)

        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            assert await db.get(BatchJobLog, fixture.job_id) is None
            job = await db.get(BatchJob, fixture.job_id, populate_existing=True)
        assert job.state == "succeeded"
        assert job.outcome_code == "succeeded"
        assert job.exit_code == 0
        assert job.proof_class == "runtime"
        assert job.result_recorded_at is not None
        assert job.finished_at is not None
        assert job.billing_mode == "zero_cost"
        assert job.charged_credits == 0
        assert job.cleanup_state == "complete"
        assert job.cleanup_attempts == 2
        assert job.reservation_active is False
        assert job.log_state == "expired"
        assert job.log_size_bytes == len(b"hidden job output")
        assert job.log_expires_at == now - timedelta(seconds=1)
    finally:
        await cleanup_owner(fixture.owner_id)


@pytest.mark.asyncio
async def test_unexpired_payload_is_retained():
    now = utc_now()
    fixture = await _terminal_job_with_log(expires_at=now + timedelta(minutes=5))
    try:
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            report = await purge_expired_logs(db, now=now)
        assert report == LogPurgeReport(scanned=0, deleted=0, errors=0)

        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            payload = await db.get(BatchJobLog, fixture.job_id)
            job = await db.get(BatchJob, fixture.job_id, populate_existing=True)
        assert payload is not None
        assert payload.text == "hidden job output"
        assert job.log_state == "available"
    finally:
        await cleanup_owner(fixture.owner_id)


@pytest.mark.asyncio
async def test_active_job_payload_is_never_purged():
    now = utc_now()
    fixture = await _terminal_job_with_log(
        state="running",
        expires_at=now - timedelta(minutes=1),
    )
    try:
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            report = await purge_expired_logs(db, now=now)
        assert report == LogPurgeReport(scanned=0, deleted=0, errors=0)

        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            assert await db.get(BatchJobLog, fixture.job_id) is not None
            job = await db.get(BatchJob, fixture.job_id, populate_existing=True)
        assert job.state == "running"
        assert job.log_state == "available"
    finally:
        await cleanup_owner(fixture.owner_id)


@pytest.mark.asyncio
async def test_expiry_cutoff_is_inclusive():
    now = utc_now()
    fixture = await _terminal_job_with_log(expires_at=now)
    try:
        async with AsyncSession(test_engine) as db:
            report = await purge_expired_logs(db, now=now)
        assert report == LogPurgeReport(scanned=1, deleted=1, errors=0)
    finally:
        await cleanup_owner(fixture.owner_id)


@pytest.mark.asyncio
async def test_repeated_purge_is_idempotent():
    now = utc_now()
    fixture = await _terminal_job_with_log(expires_at=now - timedelta(hours=1))
    try:
        async with AsyncSession(test_engine) as db:
            first = await purge_expired_logs(db, now=now)
            second = await purge_expired_logs(db, now=now)
        assert first == LogPurgeReport(scanned=1, deleted=1, errors=0)
        assert second == LogPurgeReport(scanned=0, deleted=0, errors=0)

        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            job = await db.get(BatchJob, fixture.job_id, populate_existing=True)
        assert job.state == "succeeded"
        assert job.log_state == "expired"
    finally:
        await cleanup_owner(fixture.owner_id)


@pytest.mark.asyncio
async def test_purge_is_bounded_by_the_requested_batch_size():
    now = utc_now()
    fixtures = [
        await _terminal_job_with_log(expires_at=now - timedelta(minutes=index + 1))
        for index in range(3)
    ]
    try:
        async with AsyncSession(test_engine) as db:
            first = await purge_expired_logs(db, now=now, limit=2)
            second = await purge_expired_logs(db, now=now, limit=2)
        assert first == LogPurgeReport(scanned=2, deleted=2, errors=0)
        assert second == LogPurgeReport(scanned=1, deleted=1, errors=0)

        async with AsyncSession(test_engine) as db:
            remaining = [await db.get(BatchJobLog, fixture.job_id) for fixture in fixtures]
        assert remaining == [None, None, None]
    finally:
        for fixture in fixtures:
            await cleanup_owner(fixture.owner_id)


@pytest.mark.asyncio
async def test_missing_job_without_payload_is_handled_gracefully():
    now = utc_now()
    fixture = await _terminal_job_with_log(expires_at=now - timedelta(minutes=1))
    async with AsyncSession(test_engine) as db, db.begin():
        job = await db.get(BatchJob, fixture.job_id)
        await db.delete(job)

    async with AsyncSession(test_engine) as db:
        report = await purge_expired_logs(db, now=now)
    assert report == LogPurgeReport(scanned=0, deleted=0, errors=0)
    await cleanup_owner(fixture.owner_id)
