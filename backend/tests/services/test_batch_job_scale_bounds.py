# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded batch-job scale, cursor, cleanup and retention contracts.

These tests assert bounded shapes and explicit limits, not wall-clock latency.
The only physical-schema assertion is an EXPLAIN check that the owner-history
and queued-dispatch scans use their intended indexes.
"""

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.config import settings
from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob, BatchJobLog
from app.models.system_setting import SystemSetting
from app.services.batch_job_dispatch_service import BatchJobDispatchService
from app.services.batch_job_reconciliation import BatchJobReconciliationService
from app.services.batch_job_service import BatchJobService
from tests.services.test_batch_job_admission import _make_resources

BASE_TIME = utc_now().replace(microsecond=0) - timedelta(days=1)


def _seed_job(
    user,
    resources,
    *,
    created_at,
    state="queued",
    name="Scale job",
    argv=None,
    cleanup_state="pending",
    last_cleanup_at=None,
    heartbeat_at=None,
    log_state="pending",
    log_expires_at=None,
    reservation_active=False,
):
    return BatchJob(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name,
        idempotency_key_hash=uuid.uuid4().hex * 2,
        request_fingerprint=uuid.uuid4().hex * 2,
        revision_id=resources.revision.id,
        plan_id=resources.plan.id,
        volume_id=resources.volume.id,
        argv=argv or ["true"],
        max_runtime_seconds=300,
        state=state,
        state_changed_at=created_at,
        queue_expires_at=created_at + timedelta(days=1),
        revision_snapshot={
            "revision_id": str(resources.revision.id),
            "environment_id": str(resources.template.id),
            "environment_name": "Scale environment",
            "display_label": "Scale environment — approved 2026-01-01",
            "fingerprint": resources.revision.fingerprint,
            "configuration": {"environment_variables": {"SCALE_SECRET": "must-not-leak"}},
            "runtime_identity": {"local_id": "sha256:" + "a" * 64},
        },
        plan_snapshot={
            "id": str(resources.plan.id),
            "name": resources.plan.name,
            "cpu": 1.0,
            "memory_mib": 1024,
            "disk_mib": 2048,
            "gpu_count": 0,
            "cost_per_hour": 0,
        },
        volume_snapshot={"id": str(resources.volume.id), "display_name": "Scale data"},
        reservation_active=reservation_active,
        fencing_token=uuid.uuid4(),
        cleanup_state=cleanup_state,
        last_cleanup_at=last_cleanup_at,
        heartbeat_at=heartbeat_at,
        log_state=log_state,
        log_expires_at=log_expires_at,
        log_truncated=False,
        log_size_bytes=0,
        created_at=created_at,
        updated_at=created_at,
    )


def _plan_indexes(payload):
    names = set()

    def walk(node):
        if isinstance(node, dict):
            name = node.get("Index Name")
            if isinstance(name, str):
                names.add(name)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return names


@pytest.mark.asyncio
async def test_list_cursor_is_fair_ordered_and_payload_bounded(db_session, test_user):
    resources = await _make_resources(db_session, test_user)
    jobs = [
        _seed_job(
            test_user,
            resources,
            created_at=BASE_TIME + timedelta(seconds=index),
            name=f"scale-job-{index:03d}",
        )
        for index in range(120)
    ]
    db_session.add_all(jobs)
    await db_session.flush()

    expected = [
        job.id for job in sorted(jobs, key=lambda job: (job.created_at, job.id), reverse=True)
    ]
    seen = []
    pages = []
    cursor = None
    while True:
        page = await BatchJobService(db_session).list(
            test_user, state_filter="all", limit=25, cursor=cursor
        )
        pages.append(len(page.items))
        seen.extend(item.id for item in page.items)
        for item in page.items:
            assert set(item.model_dump()) == {
                "id",
                "name",
                "state",
                "reason_code",
                "environment_name",
                "created_at",
                "started_at",
                "finished_at",
                "can_cancel",
            }
            assert len(item.name) <= 120
            assert len(item.environment_name) <= 120
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
        assert len(pages) <= 10

    assert pages == [25, 25, 25, 25, 20]
    assert seen == expected
    assert len(set(seen)) == 120


@pytest.mark.asyncio
async def test_detail_excludes_snapshots_and_stays_within_validated_argv_bounds(
    db_session, test_user
):
    resources = await _make_resources(db_session, test_user)
    argv = [f"arg-{index:03d}-" + ("x" * 200) for index in range(64)]
    assert sum(len(item.encode()) for item in argv) <= settings.batch_jobs_max_input_bytes
    job = _seed_job(
        test_user,
        resources,
        created_at=BASE_TIME,
        state="succeeded",
        argv=argv,
        cleanup_state="complete",
        log_state="available",
    )
    db_session.add(job)
    await db_session.flush()

    detail = await BatchJobService(db_session).get(test_user, job.id)
    serialized = detail.model_dump_json()

    assert detail.argv == argv
    assert len(detail.argv) == settings.batch_jobs_max_argv_items
    assert "SCALE_SECRET" not in serialized
    assert "configuration" not in serialized
    assert "runtime_identity" not in serialized
    assert "revision_snapshot" not in serialized
    assert len(serialized.encode("utf-8")) <= 64 * 1024


@pytest.mark.asyncio
async def test_log_reads_are_tail_bounded_and_retention_cutoff_hides_text(
    db_session, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "batch_jobs_log_tail_bytes", 64)
    resources = await _make_resources(db_session, test_user)
    now = utc_now()
    live = _seed_job(
        test_user,
        resources,
        created_at=BASE_TIME,
        state="failed",
        log_state="available",
        log_expires_at=now + timedelta(hours=1),
    )
    expired = _seed_job(
        test_user,
        resources,
        created_at=BASE_TIME + timedelta(seconds=1),
        state="failed",
        log_state="available",
        log_expires_at=now - timedelta(seconds=1),
    )
    db_session.add_all([live, expired])
    await db_session.flush()
    db_session.add_all(
        [
            BatchJobLog(
                job_id=live.id,
                text="L" * 100,
                encoding="utf-8",
                truncated=False,
                size_bytes=100,
                captured_at=now,
                expires_at=now + timedelta(hours=1),
            ),
            BatchJobLog(
                job_id=expired.id,
                text="E" * 100,
                encoding="utf-8",
                truncated=False,
                size_bytes=100,
                captured_at=now,
                expires_at=now - timedelta(seconds=1),
            ),
        ]
    )
    await db_session.flush()

    service = BatchJobService(db_session)
    live_logs = await service.logs(test_user, live.id)
    assert live_logs.state == "truncated"
    assert live_logs.text == "L" * 64
    assert live_logs.truncated is True
    assert live_logs.size_bytes == 100
    assert len(live_logs.text.encode()) <= settings.batch_jobs_log_tail_bytes

    expired_logs = await service.logs(test_user, expired.id)
    assert expired_logs.state == "expired"
    assert expired_logs.text is None
    assert expired_logs.size_bytes == 100
    assert (
        await db_session.scalar(select(BatchJobLog).where(BatchJobLog.job_id == live.id))
        is not None
    )
    assert (
        await db_session.scalar(select(BatchJobLog).where(BatchJobLog.job_id == expired.id))
        is not None
    )


@pytest.mark.asyncio
async def test_cleanup_and_stale_scans_apply_hard_limits_and_stable_order(db_session, test_user):
    resources = await _make_resources(db_session, test_user)
    terminal = [
        _seed_job(
            test_user,
            resources,
            created_at=BASE_TIME + timedelta(seconds=index),
            state="failed",
            cleanup_state="pending",
            last_cleanup_at=None if index % 2 == 0 else BASE_TIME + timedelta(minutes=index),
        )
        for index in range(25)
    ]
    stale = [
        _seed_job(
            test_user,
            resources,
            created_at=BASE_TIME + timedelta(minutes=index),
            state="starting",
            heartbeat_at=None,
            reservation_active=True,
        )
        for index in range(12)
    ]
    db_session.add_all([*terminal, *stale])
    await db_session.flush()

    service = BatchJobReconciliationService(db_session, SimpleNamespace())
    cleanup = await service._cleanup_candidates(500)
    assert len(cleanup) == 10
    expected_cleanup = [
        job.id
        for job in sorted(
            terminal,
            key=lambda job: (
                job.last_cleanup_at is not None,
                job.last_cleanup_at or BASE_TIME,
                job.id,
            ),
        )
    ][:10]
    assert cleanup == expected_cleanup

    stale_rows = await service._stale_candidates(7)
    assert len(stale_rows) == 7
    expected_stale = [job.id for job in sorted(stale, key=lambda job: (job.created_at, job.id))][:7]
    assert stale_rows == expected_stale


@pytest.mark.asyncio
async def test_dispatch_cursor_rotates_without_starvation_or_duplicates(db_session, test_user):
    resources = await _make_resources(db_session, test_user)
    queued = [
        _seed_job(
            test_user,
            resources,
            created_at=BASE_TIME + timedelta(seconds=index),
            state="queued",
        )
        for index in range(12)
    ]
    db_session.add_all(queued)
    await db_session.flush()

    service = BatchJobDispatchService(db_session, SimpleNamespace())
    expected = [job.id for job in sorted(queued, key=lambda job: (job.created_at, job.id))]
    first = await service._scan_batch(5)
    second = await service._scan_batch(5)
    third = await service._scan_batch(5)
    wrapped = await service._scan_batch(5)

    assert first == expected[:5]
    assert second == expected[5:10]
    assert third == expected[10:]
    assert wrapped == expected[:5]
    assert len(set(first + second + third)) == 12
    setting = await db_session.get(SystemSetting, "batch_jobs_dispatch_cursor")
    assert setting is not None
    assert len(setting.value) <= 512


@pytest.mark.asyncio
async def test_owner_history_and_queued_dispatch_plans_use_intended_indexes(db_session, test_user):
    resources = await _make_resources(db_session, test_user)
    jobs = [
        _seed_job(
            test_user,
            resources,
            created_at=BASE_TIME + timedelta(seconds=index),
            state="queued" if index % 3 == 0 else "failed",
            cleanup_state="complete",
        )
        for index in range(120)
    ]
    db_session.add_all(jobs)
    await db_session.flush()

    await db_session.execute(text("SET LOCAL enable_seqscan = off"))
    await db_session.execute(text("SET LOCAL enable_bitmapscan = off"))

    history_plan = (
        await db_session.execute(
            text(
                "EXPLAIN (FORMAT JSON) SELECT * FROM batch_jobs "
                "WHERE user_id = :user_id ORDER BY created_at DESC, id DESC LIMIT 26"
            ),
            {"user_id": test_user.id},
        )
    ).scalar()
    history = json.loads(history_plan) if isinstance(history_plan, str) else history_plan
    assert "ix_batch_jobs_owner_history" in _plan_indexes(history)

    dispatch_plan = (
        await db_session.execute(
            text(
                "EXPLAIN (FORMAT JSON) SELECT id FROM batch_jobs "
                "WHERE state = 'queued' ORDER BY created_at ASC, id ASC LIMIT 10"
            )
        )
    ).scalar()
    dispatch = json.loads(dispatch_plan) if isinstance(dispatch_plan, str) else dispatch_plan
    assert "ix_batch_jobs_pending_dispatch" in _plan_indexes(dispatch)
