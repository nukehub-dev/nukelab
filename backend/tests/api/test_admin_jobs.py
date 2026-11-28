# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin batch-job listing, filtering, detail, and proof-only reconciliation."""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.api import admin_jobs
from app.api.auth import get_password_hash
from app.core.permissions import Permission
from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache
from app.core.time_utils import utc_now
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.batch_job import BatchJob
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.services.activity_service import ActivityService
from tests.services.test_batch_job_runtime import BatchJobDriver

pytestmark = pytest.mark.asyncio

IMAGE_REFERENCE = "registry.example.test/pilot@sha256:" + "b" * 64


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_runtime(monkeypatch):
    driver = BatchJobDriver()

    async def _get_driver():
        return driver

    monkeypatch.setattr(admin_jobs, "get_driver", _get_driver)
    return driver


async def _activity(db, job_id):
    return (
        await db.scalars(
            select(ActivityLog)
            .where(ActivityLog.target_id == job_id)
            .order_by(ActivityLog.created_at, ActivityLog.id)
        )
    ).all()


async def _targets(db):
    marker = uuid.uuid4().hex[:8]
    template = EnvironmentTemplate(
        name=f"Admin job environment {marker}",
        slug=f"admin-job-env-{marker}",
        image="registry.example.test/pilot:1",
    )
    db.add(template)
    await db.flush()
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint=uuid.uuid4().hex * 2,
        template_fingerprint=uuid.uuid4().hex * 2,
        configuration={
            "image": template.image,
            "environment_variables": {"API_KEY": "env-secret"},
        },
        runtime_identity={
            "requested_reference": template.image,
            "local_id": "sha256:" + "a" * 64,
            "registry_verified": True,
            "verified_reference": IMAGE_REFERENCE,
        },
        revoked=False,
    )
    plan = ServerPlan(
        name=f"Admin job plan {marker}",
        slug=f"admin-job-plan-{marker}",
        cpu_limit=2,
        memory_limit="4g",
        disk_limit="20g",
    )
    db.add_all([revision, plan])
    await db.flush()
    return template, revision, plan


async def _owner(db, username=None):
    marker = uuid.uuid4().hex[:8]
    user = User(
        username=username or f"job-owner-{marker}",
        email=f"job-owner-{marker}@example.test",
        password_hash=get_password_hash("otherpass123"),
        first_name="Job",
        last_name="Operator",
        role="user",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _volume(db, owner, display_name="pilot-data"):
    volume = Volume(
        name=f"admin-job-vol-{uuid.uuid4().hex[:8]}",
        display_name=display_name,
        owner_id=owner.id,
        visibility="private",
        status="active",
    )
    db.add(volume)
    await db.flush()
    return volume


def _job(
    owner,
    revision,
    plan,
    volume,
    *,
    state="queued",
    created_at=None,
    reason_code="waiting_capacity",
    reservation_active=False,
    heartbeat_at=None,
    **overrides,
):
    now = created_at or utc_now()
    job = BatchJob(
        id=uuid.uuid4(),
        user_id=owner.id,
        name="private job name",
        idempotency_key_hash=uuid.uuid4().hex * 2,
        request_fingerprint=uuid.uuid4().hex * 2,
        revision_id=revision.id,
        plan_id=plan.id,
        volume_id=volume.id,
        argv=["python", "/work/secret.py", "--token=argv-secret"],
        max_runtime_seconds=1800,
        state=state,
        reason_code=reason_code,
        state_changed_at=now,
        queue_expires_at=now + timedelta(days=1),
        revision_snapshot={
            "revision_id": str(revision.id),
            "environment_id": str(revision.template_id),
            "environment_name": "Stored environment",
            "display_label": "Stored environment — approved 2026-11-20",
            "fingerprint": revision.fingerprint,
            "image_reference": IMAGE_REFERENCE,
            "configuration": {"environment_variables": {"API_KEY": "env-secret"}},
            "runtime_identity": {"path": "/var/lib/private/runtime"},
        },
        plan_snapshot={
            "id": str(plan.id),
            "name": plan.name,
            "cpu": 2,
            "memory_mib": 4096,
            "disk_mib": 20480,
            "gpu_count": 0,
            "cost_per_hour": 0,
            "secret": "plan-snapshot-secret",
        },
        volume_snapshot={
            "id": str(volume.id),
            "display_name": volume.display_name,
            "visibility": "private",
        },
        reservation_active=reservation_active,
        volume_operation_id=overrides.pop("volume_operation_id", None),
        runtime_identity={"path": "/var/lib/private/runtime"},
        container_id="container-private-id",
        container_name="nukelab-job-private-name",
        executor_id=uuid.uuid4(),
        heartbeat_at=heartbeat_at,
        fencing_token=uuid.uuid4(),
        outcome_code="succeeded" if state == "succeeded" else None,
        proof_class="observed",
        exit_code=0 if state == "succeeded" else None,
        cleanup_state=overrides.pop("cleanup_state", "pending"),
        cleanup_attempts=overrides.pop("cleanup_attempts", 0),
        billing_mode="zero_cost",
        charged_credits=0,
        created_at=now,
        updated_at=now,
        **overrides,
    )
    return job


async def _guarded(db, job, volume, owner, *, state="reserved"):
    guard = VolumeOperation(
        operation_id=job.id,
        volume_id=volume.id,
        owner_id=owner.id,
        kind="job_writer",
        state=state,
        fencing_token=uuid.uuid4(),
    )
    db.add(guard)
    await db.flush()
    return guard


async def _recovery_guarded(
    db,
    owner,
    revision,
    plan,
    *,
    heartbeat_at,
    container_id="container-private-id",
    create_requested_at=None,
):
    volume = await _volume(db, owner)
    job = _job(
        owner,
        revision,
        plan,
        volume,
        state="recovery_required",
        reason_code="runtime_unverifiable",
        reservation_active=True,
        heartbeat_at=heartbeat_at,
        container_id=container_id,
        create_requested_at=create_requested_at,
    )
    job.volume_operation_id = job.id
    db.add(job)
    await db.flush()
    guard = await _guarded(db, job, volume, owner)
    job.volume_fencing_token = guard.fencing_token
    await db.commit()
    return job, volume, guard


async def _load_job(db, job_id):
    return await db.get(BatchJob, job_id, populate_existing=True)


async def _load_guard(db, job_id):
    return await db.scalar(select(VolumeOperation).where(VolumeOperation.operation_id == job_id))


async def test_admin_jobs_filters_order_and_bounded_pagination(
    client, admin_token, db_session, test_user
):
    _, revision, plan = await _targets(db_session)
    foreign = await _owner(db_session)
    now = utc_now()
    old = _job(
        test_user,
        revision,
        plan,
        await _volume(db_session, test_user),
        created_at=now - timedelta(days=5),
        state="queued",
    )
    running = _job(
        test_user,
        revision,
        plan,
        await _volume(db_session, test_user),
        created_at=now - timedelta(days=2),
        state="running",
        reason_code=None,
    )
    succeeded = _job(
        test_user,
        revision,
        plan,
        await _volume(db_session, test_user),
        created_at=now - timedelta(days=1),
        state="succeeded",
        reason_code=None,
        finished_at=now - timedelta(days=1),
    )
    foreign_job = _job(
        foreign,
        revision,
        plan,
        await _volume(db_session, foreign),
        created_at=now - timedelta(minutes=30),
        state="failed",
        reason_code="runtime_unverifiable",
    )
    db_session.add_all([old, running, succeeded, foreign_job])
    await db_session.commit()
    headers = auth(admin_token)

    listed = await client.get("/api/admin/jobs", headers=headers)
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["pagination"] == {
        "limit": 50,
        "offset": 0,
        "total": 4,
        "has_more": False,
    }
    assert [item["id"] for item in payload["items"]] == [
        str(foreign_job.id),
        str(succeeded.id),
        str(running.id),
        str(old.id),
    ]
    assert payload["summary"] == {
        "total": 4,
        "queued": 1,
        "starting": 0,
        "running": 1,
        "cancelling": 0,
        "recovery_required": 0,
        "succeeded": 1,
        "failed": 1,
        "cancelled": 0,
        "timed_out": 0,
        "expired": 0,
    }

    active = await client.get("/api/admin/jobs?state=active", headers=headers)
    assert [item["id"] for item in active.json()["items"]] == [str(running.id), str(old.id)]
    assert active.json()["summary"] == payload["summary"]

    history = await client.get("/api/admin/jobs?state=history", headers=headers)
    assert [item["id"] for item in history.json()["items"]] == [
        str(foreign_job.id),
        str(succeeded.id),
    ]

    aged = await client.get("/api/admin/jobs?age_min_seconds=259200", headers=headers)
    assert [item["id"] for item in aged.json()["items"]] == [str(old.id)]
    assert aged.json()["pagination"]["total"] == 1
    assert aged.json()["summary"] == {
        "total": 1,
        "queued": 1,
        "starting": 0,
        "running": 0,
        "cancelling": 0,
        "recovery_required": 0,
        "succeeded": 0,
        "failed": 0,
        "cancelled": 0,
        "timed_out": 0,
        "expired": 0,
    }

    first_page = await client.get("/api/admin/jobs?limit=2&offset=0", headers=headers)
    second_page = await client.get("/api/admin/jobs?limit=2&offset=2", headers=headers)
    repeated = await client.get("/api/admin/jobs?limit=2&offset=0", headers=headers)
    assert [item["id"] for item in first_page.json()["items"]] == [
        str(foreign_job.id),
        str(succeeded.id),
    ]
    assert first_page.json()["pagination"]["has_more"] is True
    assert [item["id"] for item in second_page.json()["items"]] == [
        str(running.id),
        str(old.id),
    ]
    assert second_page.json()["pagination"]["has_more"] is False
    assert first_page.json()["items"] == repeated.json()["items"]

    assert (await client.get("/api/admin/jobs?limit=0", headers=headers)).status_code == 422
    assert (await client.get("/api/admin/jobs?limit=101", headers=headers)).status_code == 422
    assert (await client.get("/api/admin/jobs?offset=1001", headers=headers)).status_code == 422
    assert (await client.get("/api/admin/jobs?state=unknown", headers=headers)).status_code == 422
    assert (
        await client.get("/api/admin/jobs?age_min_seconds=-1", headers=headers)
    ).status_code == 422
    assert (
        await client.get("/api/admin/jobs?age_min_seconds=31536001", headers=headers)
    ).status_code == 422


async def test_admin_jobs_ties_use_deterministic_id_order(
    client, admin_token, db_session, test_user
):
    _, revision, plan = await _targets(db_session)
    created_at = utc_now() - timedelta(minutes=5)
    jobs = [
        _job(
            test_user,
            revision,
            plan,
            await _volume(db_session, test_user),
            created_at=created_at,
        )
        for _ in range(3)
    ]
    db_session.add_all(jobs)
    await db_session.commit()

    response = await client.get("/api/admin/jobs?limit=3", headers=auth(admin_token))
    assert [item["id"] for item in response.json()["items"]] == [
        str(job.id) for job in sorted(jobs, key=lambda row: str(row.id), reverse=True)
    ]


async def test_admin_jobs_sanitizes_labels_reasons_and_display_names(
    client, admin_token, db_session, test_user
):
    _, revision, plan = await _targets(db_session)
    owner = await _owner(db_session, username=f"  job\x01owner-{uuid.uuid4().hex[:8]}\t  ")
    volume = await _volume(db_session, owner, display_name="  Data\x01 Volume  ")
    job = _job(
        owner,
        revision,
        plan,
        volume,
        state="running",
        reason_code="/private/host/path: password=secret",
    )
    job.revision_snapshot = {
        **job.revision_snapshot,
        "environment_name": "  Env\tname\x02  ",
        "display_label": "  Env name — approved 2026-11-20\n  ",
    }
    job.plan_snapshot = {**job.plan_snapshot, "name": "P" * 150}
    job.log_state = "../../bad"
    job.cleanup_state = "cleanup/path"
    job.cleanup_attempts = 3
    db_session.add(job)
    await db_session.commit()

    response = await client.get(f"/api/admin/jobs/{job.id}", headers=auth(admin_token))
    assert response.status_code == 200
    item = response.json()
    assert set(item) == {
        "id",
        "state",
        "reason_code",
        "owner_id",
        "owner_username",
        "owner_display_name",
        "environment_name",
        "environment_display_label",
        "plan_name",
        "volume_display_name",
        "created_at",
        "updated_at",
        "finished_at",
        "reservation_active",
        "guard_active",
        "heartbeat_age_seconds",
        "log_state",
        "cleanup_state",
        "cleanup_attempts",
        "can_reconcile",
    }
    assert item["owner_username"] == owner.username.replace(" ", "").replace("\x01", "").replace(
        "\t", ""
    )
    assert item["owner_display_name"] == "Job Operator"
    assert item["environment_name"] == "Envname"
    assert item["environment_display_label"] == "Env name — approved 2026-11-20"
    assert item["plan_name"] == "P" * 120
    assert item["volume_display_name"] == "Data Volume"
    assert item["reason_code"] is None
    assert item["state"] == "running"
    assert item["log_state"] == "unknown"
    assert item["cleanup_state"] == "unknown"
    assert item["cleanup_attempts"] == 3
    assert item["can_reconcile"] is False

    text = json.dumps(item)
    for forbidden in (
        "argv",
        "secret.py",
        "argv-secret",
        "env-secret",
        "API_KEY",
        "private job name",
        "/private/host/path",
        "password=secret",
        "/var/lib/private/runtime",
        "container-private-id",
        "nukelab-job-private-name",
        IMAGE_REFERENCE,
        "registry.example.test",
        "plan-snapshot-secret",
        str(volume.id),
        str(revision.fingerprint),
    ):
        assert forbidden not in text


async def test_admin_jobs_exposes_reservation_guard_heartbeat_and_cleanup(
    client, admin_token, db_session, test_user
):
    _, revision, plan = await _targets(db_session)
    volume = await _volume(db_session, test_user)
    heartbeat_at = utc_now() - timedelta(seconds=95)
    job = _job(
        test_user,
        revision,
        plan,
        volume,
        state="recovery_required",
        reason_code="recovery_required",
        reservation_active=True,
        heartbeat_at=heartbeat_at,
        cleanup_state="pending",
        cleanup_attempts=2,
    )
    job.volume_operation_id = job.id
    job.volume_fencing_token = uuid.uuid4()
    db_session.add(job)
    guard = await _guarded(db_session, job, volume, test_user)
    await db_session.commit()

    detail = await client.get(f"/api/admin/jobs/{job.id}", headers=auth(admin_token))
    assert detail.status_code == 200
    item = detail.json()
    assert item["state"] == "recovery_required"
    assert item["reservation_active"] is True
    assert item["guard_active"] is True
    assert item["cleanup_state"] == "pending"
    assert item["cleanup_attempts"] == 2
    assert item["can_reconcile"] is True
    assert item["heartbeat_age_seconds"] >= 94

    guard.state = "succeeded"
    guard.completed_at = utc_now()
    await db_session.commit()
    released = await client.get(f"/api/admin/jobs/{job.id}", headers=auth(admin_token))
    assert released.json()["guard_active"] is False


async def test_admin_jobs_detail_and_missing_rows(client, admin_token, db_session, test_user):
    _, revision, plan = await _targets(db_session)
    job = _job(
        test_user,
        revision,
        plan,
        await _volume(db_session, test_user),
        state="succeeded",
        reason_code=None,
        finished_at=utc_now(),
    )
    db_session.add(job)
    await db_session.commit()
    headers = auth(admin_token)

    detail = await client.get(f"/api/admin/jobs/{job.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == str(job.id)
    assert detail.json()["finished_at"] is not None

    missing = await client.get(f"/api/admin/jobs/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "job_not_found"}


async def test_admin_jobs_reconcile_requires_manage_permission(
    client, admin_token, support_token, user_token, db_session, test_user
):
    _, revision, plan = await _targets(db_session)
    job, _, _ = await _recovery_guarded(
        db_session,
        test_user,
        revision,
        plan,
        heartbeat_at=utc_now(),
    )
    body = {"reason": "operator permission probe"}

    regular = await client.post(
        f"/api/admin/jobs/{job.id}/reconcile", headers=auth(user_token), json=body
    )
    assert regular.status_code == 403

    ROLE_PERMISSIONS["support"] = [
        Permission.ADMIN_ACCESS,
        Permission.OPERATIONS_READ_ALL,
    ]
    _rebuild_expansion_cache()
    read_only = auth(support_token)
    detail = await client.get(f"/api/admin/jobs/{job.id}", headers=read_only)
    assert detail.status_code == 200
    assert detail.json()["can_reconcile"] is False
    denied = await client.post(f"/api/admin/jobs/{job.id}/reconcile", headers=read_only, json=body)
    assert denied.status_code == 403
    assert await _activity(db_session, job.id) == []

    admin_detail = await client.get(f"/api/admin/jobs/{job.id}", headers=auth(admin_token))
    assert admin_detail.status_code == 200
    assert admin_detail.json()["can_reconcile"] is True


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"reason": ""},
        {"reason": "short"},
        {"reason": "   short   "},
        {"reason": "x" * 501},
        {"reason": "valid reason", "force": True},
        {"reason": "valid reason", "unknown": "field"},
        {"reason": "valid\nreason"},
        {"reason": "\x7f" * 8},
    ],
)
async def test_admin_jobs_reconcile_rejects_invalid_bodies(client, admin_token, body):
    response = await client.post(
        f"/api/admin/jobs/{uuid.uuid4()}/reconcile",
        headers=auth(admin_token),
        json=body,
    )
    assert response.status_code == 422


async def test_admin_jobs_exposes_only_proof_reconcile_mutation(client, admin_token):
    headers = auth(admin_token)
    target = uuid.uuid4()
    assert (await client.post("/api/admin/jobs", headers=headers, json={})).status_code == 405
    assert (
        await client.put(f"/api/admin/jobs/{target}", headers=headers, json={})
    ).status_code == 405
    assert (await client.delete(f"/api/admin/jobs/{target}", headers=headers)).status_code == 405
    assert (
        await client.post(f"/api/admin/jobs/{target}/cancel", headers=headers, json={})
    ).status_code == 404
    assert (
        await client.post(f"/api/admin/jobs/{target}/reconcile", headers=headers, json={})
    ).status_code == 422

    job_routes = {route.path: route for route in app.routes if route.path.startswith("/admin/jobs")}
    assert set(job_routes) == {
        "/admin/jobs",
        "/admin/jobs/{job_id}",
        "/admin/jobs/{job_id}/reconcile",
    }
    assert job_routes["/admin/jobs/{job_id}/reconcile"].methods == {"POST"}
    assert job_routes["/admin/jobs/{job_id}"].methods <= {"GET", "HEAD"}


async def test_proof_backed_reconcile_releases_reservation_and_guard_once(
    client, admin_token, admin_user, db_session, test_user, fake_runtime
):
    _, revision, plan = await _targets(db_session)
    now = utc_now()
    job, _, guard = await _recovery_guarded(
        db_session,
        test_user,
        revision,
        plan,
        heartbeat_at=now - timedelta(minutes=10),
        container_id="container-private-id",
        create_requested_at=now - timedelta(minutes=10),
    )
    fake_runtime.add_job_container(
        job,
        container_id="container-private-id",
        status="exited",
        exit_code=0,
        started_at=now - timedelta(minutes=2),
        finished_at=now - timedelta(minutes=1),
    )
    headers = auth(admin_token)

    response = await client.post(
        f"/api/admin/jobs/{job.id}/reconcile",
        headers=headers,
        json={"reason": "operator verified the recorded container exit"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["applied"] is True
    assert data["already_terminal"] is False
    assert data["outcome"] == "applied"
    assert data["terminal_state"] == "succeeded"
    assert data["proof_source"] == "runtime_inspection"
    assert data["reason_code"] == "exit_zero"
    assert data["job"]["id"] == str(job.id)
    assert data["job"]["state"] == "succeeded"
    assert data["job"]["reservation_active"] is False
    assert data["job"]["guard_active"] is False
    assert data["job"]["can_reconcile"] is False

    row = await _load_job(db_session, job.id)
    assert row.state == "succeeded"
    assert row.reservation_active is False
    assert row.exit_code == 0
    assert row.proof_class == "runtime"
    assert (await _load_guard(db_session, job.id)).state == "succeeded"
    assert len(fake_runtime.deleted) == 1

    logs = await _activity(db_session, job.id)
    assert [log.action for log in logs] == ["jobs.reconcile_applied"]
    assert logs[0].actor_id == admin_user.id
    details = logs[0].details
    assert details["reason"] == "operator verified the recorded container exit"
    assert details["outcome"] == "applied"
    assert details["applied"] is True
    assert details["previous_state"] == "recovery_required"
    assert details["new_state"] == "succeeded"
    assert details["terminal_state"] == "succeeded"
    assert details["proof_source"] == "runtime_inspection"
    assert details["runtime_state"] == "present"
    assert details["liveness"] == "stopped"
    assert details["reason_code"] == "exit_zero"

    repeated = await client.post(
        f"/api/admin/jobs/{job.id}/reconcile",
        headers=headers,
        json={"reason": "confirm the terminal result is not replayed"},
    )
    assert repeated.status_code == 200
    repeated_data = repeated.json()
    assert repeated_data["applied"] is False
    assert repeated_data["already_terminal"] is True
    assert repeated_data["outcome"] == "already_terminal"
    assert repeated_data["terminal_state"] is None
    assert repeated_data["proof_source"] is None
    assert repeated_data["reason_code"] is None
    assert repeated_data["job"]["state"] == "succeeded"

    assert (await _load_job(db_session, job.id)).state == "succeeded"
    assert (await _load_guard(db_session, job.id)).state == "succeeded"
    assert len(fake_runtime.deleted) == 1
    logs = await _activity(db_session, job.id)
    assert [log.action for log in logs] == ["jobs.reconcile_applied", "jobs.reconcile"]


async def test_ambiguous_proof_conflicts_without_releasing_reservation_or_guard(
    client, admin_token, db_session, test_user, fake_runtime
):
    _, revision, plan = await _targets(db_session)
    now = utc_now()
    job, _, guard = await _recovery_guarded(
        db_session,
        test_user,
        revision,
        plan,
        heartbeat_at=now,
        container_id="container-private-id",
        create_requested_at=now - timedelta(minutes=10),
    )

    response = await client.post(
        f"/api/admin/jobs/{job.id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "operator observed an absent runtime"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "proof_insufficient"}

    row = await _load_job(db_session, job.id)
    assert row.state == "recovery_required"
    assert row.reservation_active is True
    assert row.reason_code == "runtime_unverifiable"
    assert (await _load_guard(db_session, job.id)).state == "reserved"
    assert fake_runtime.deleted == []

    logs = await _activity(db_session, job.id)
    assert [log.action for log in logs] == ["jobs.reconcile"]
    details = logs[0].details
    assert details["outcome"] == "proof_insufficient"
    assert details["applied"] is False
    assert details["previous_state"] == "recovery_required"
    assert details["new_state"] == "recovery_required"
    assert details["terminal_state"] is None
    assert details["proof_source"] == "none"
    assert details["reason_code"] == "executor_live"
    assert details["runtime_state"] == "absent"
    assert details["liveness"] == "alive"


async def test_reconcile_rejects_non_recovery_required_active_rows(
    client, admin_token, db_session, test_user
):
    _, revision, plan = await _targets(db_session)
    job = _job(
        test_user,
        revision,
        plan,
        await _volume(db_session, test_user),
        state="running",
        reason_code=None,
        reservation_active=True,
        heartbeat_at=utc_now(),
    )
    db_session.add(job)
    await db_session.commit()

    response = await client.post(
        f"/api/admin/jobs/{job.id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "attempt to reconcile a running job"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "job_not_reconcilable"}
    assert (await _load_job(db_session, job.id)).state == "running"
    logs = await _activity(db_session, job.id)
    assert [log.action for log in logs] == ["jobs.reconcile"]
    assert logs[0].details["outcome"] == "job_not_reconcilable"


async def test_reconcile_already_terminal_is_idempotent(client, admin_token, db_session, test_user):
    _, revision, plan = await _targets(db_session)
    job = _job(
        test_user,
        revision,
        plan,
        await _volume(db_session, test_user),
        state="failed",
        reason_code="nonzero_exit",
        finished_at=utc_now(),
    )
    db_session.add(job)
    await db_session.commit()
    headers = auth(admin_token)

    for _ in range(2):
        response = await client.post(
            f"/api/admin/jobs/{job.id}/reconcile",
            headers=headers,
            json={"reason": "confirm the terminal row stays closed"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["applied"] is False
        assert data["already_terminal"] is True
        assert data["outcome"] == "already_terminal"
        assert data["terminal_state"] is None
        assert data["proof_source"] is None
        assert data["reason_code"] is None
        assert data["job"]["state"] == "failed"
        assert data["job"]["can_reconcile"] is False

    assert (await _load_job(db_session, job.id)).state == "failed"
    logs = await _activity(db_session, job.id)
    assert [log.action for log in logs] == ["jobs.reconcile", "jobs.reconcile"]
    assert all(log.details["outcome"] == "already_terminal" for log in logs)


async def test_reconcile_unknown_job_returns_not_found_and_audits(client, admin_token, db_session):
    target = uuid.uuid4()
    response = await client.post(
        f"/api/admin/jobs/{target}/reconcile",
        headers=auth(admin_token),
        json={"reason": "operator probe for an unknown job"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "job_not_found"}
    logs = await _activity(db_session, target)
    assert [log.action for log in logs] == ["jobs.reconcile"]
    assert logs[0].details["outcome"] == "job_not_found"
    assert logs[0].details["applied"] is False


async def test_reconcile_audit_failure_returns_500_without_mutation(
    client, admin_token, db_session, test_user, fake_runtime, monkeypatch
):
    _, revision, plan = await _targets(db_session)
    now = utc_now()
    job, _, guard = await _recovery_guarded(
        db_session,
        test_user,
        revision,
        plan,
        heartbeat_at=now - timedelta(minutes=10),
        container_id="container-private-id",
        create_requested_at=now - timedelta(minutes=10),
    )
    fake_runtime.add_job_container(
        job,
        container_id="container-private-id",
        status="exited",
        exit_code=1,
        started_at=now - timedelta(minutes=2),
        finished_at=now - timedelta(minutes=1),
    )

    async def _unavailable(*args, **kwargs):
        raise RuntimeError("activity store unavailable")

    monkeypatch.setattr(ActivityService, "log", _unavailable)

    response = await client.post(
        f"/api/admin/jobs/{job.id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "operator tries to reconcile during an audit outage"},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == {"code": "audit_unavailable"}

    row = await _load_job(db_session, job.id)
    assert row.state == "recovery_required"
    assert row.reservation_active is True
    assert (await _load_guard(db_session, job.id)).state == "reserved"
    assert fake_runtime.deleted == []
