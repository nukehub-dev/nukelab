# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Read-only admin batch-job listing, filtering, detail, and sanitization."""

import json
import uuid
from datetime import timedelta

import pytest

from app.api.auth import get_password_hash
from app.core.time_utils import utc_now
from app.main import app
from app.models.batch_job import BatchJob
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation

pytestmark = pytest.mark.asyncio

IMAGE_REFERENCE = "registry.example.test/pilot@sha256:" + "b" * 64


def auth(token):
    return {"Authorization": f"Bearer {token}"}


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
    assert item["can_reconcile"] is False
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


async def test_admin_jobs_exposes_no_mutation_route(client, admin_token):
    headers = auth(admin_token)
    target = uuid.uuid4()
    assert (await client.post("/api/admin/jobs", headers=headers, json={})).status_code == 405
    assert (
        await client.put(f"/api/admin/jobs/{target}", headers=headers, json={})
    ).status_code == 405
    assert (await client.delete(f"/api/admin/jobs/{target}", headers=headers)).status_code == 405
    assert (
        await client.post(f"/api/admin/jobs/{target}/reconcile", headers=headers, json={})
    ).status_code == 404

    job_routes = [route for route in app.routes if route.path.startswith("/admin/jobs")]
    assert {route.path for route in job_routes} == {"/admin/jobs", "/admin/jobs/{job_id}"}
    methods = {method for route in job_routes for method in route.methods}
    assert methods <= {"GET", "HEAD"}
    assert methods & {"POST", "PUT", "PATCH", "DELETE"} == set()
