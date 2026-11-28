# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin job visibility requires admin access, operations read, and JWT auth.

The same file carries the privacy regression: cross-owner rows expose bounded
labels and reason codes only. Command arguments, retained logs, environment
values, image/runtime references, volume ids, and fencing tokens never appear.
"""

import json
import secrets
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.api import admin_jobs
from app.api.auth import get_password_hash
from app.config import settings
from app.core.permissions import Permission
from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache
from app.core.time_utils import utc_now
from app.models.activity_log import ActivityLog
from app.models.api_token import ApiToken
from app.models.batch_job import BatchJob, BatchJobLog
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from tests.services.test_batch_job_runtime import BatchJobDriver

pytestmark = pytest.mark.asyncio

IMAGE_REFERENCE = "registry.example.test/pilot@sha256:" + "c" * 64

FORBIDDEN_VALUES = (
    "argv",
    "secret.py",
    "argv-secret",
    "log-secret output",
    "env-secret",
    "API_KEY",
    "Private job name",
    "/var/lib/private/runtime",
    "container-private-id",
    "nukelab-job-private-name",
    "plan-snapshot-secret",
    IMAGE_REFERENCE,
    "registry.example.test",
)

AUDIT_KEYS = {
    "reason",
    "outcome",
    "applied",
    "previous_state",
    "new_state",
    "terminal_state",
    "proof_source",
    "runtime_state",
    "liveness",
    "reason_code",
}
CANCEL_AUDIT_KEYS = {"reason", "outcome", "applied", "previous_state", "new_state"}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_runtime(monkeypatch):
    driver = BatchJobDriver()

    async def _get_driver():
        return driver

    monkeypatch.setattr(admin_jobs, "get_driver", _get_driver)
    return driver


async def _private_job(db):
    marker = uuid.uuid4().hex[:8]
    owner = User(
        username=f"foreign-job-owner-{marker}",
        email=f"foreign-job-owner-{marker}@example.test",
        password_hash=get_password_hash("otherpass123"),
        first_name="Foreign",
        last_name="Owner",
        role="user",
        is_active=True,
        is_verified=True,
    )
    template = EnvironmentTemplate(
        name=f"Private environment {marker}",
        slug=f"private-job-env-{marker}",
        image="registry.example.test/pilot:1",
    )
    db.add_all([owner, template])
    await db.flush()
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint=uuid.uuid4().hex * 2,
        template_fingerprint=uuid.uuid4().hex * 2,
        configuration={"environment_variables": {"API_KEY": "env-secret"}},
        runtime_identity={
            "requested_reference": template.image,
            "registry_verified": True,
            "verified_reference": IMAGE_REFERENCE,
        },
        revoked=False,
    )
    plan = ServerPlan(
        name=f"Private plan {marker}",
        slug=f"private-job-plan-{marker}",
        cpu_limit=2,
        memory_limit="4g",
        disk_limit="20g",
    )
    db.add_all([revision, plan])
    await db.flush()
    volume = Volume(
        name=f"private-volume-{marker}",
        display_name="pilot-data",
        owner_id=owner.id,
        visibility="private",
        status="active",
    )
    db.add(volume)
    await db.flush()
    now = utc_now()
    job = BatchJob(
        id=uuid.uuid4(),
        user_id=owner.id,
        name="Private job name",
        idempotency_key_hash=uuid.uuid4().hex * 2,
        request_fingerprint=uuid.uuid4().hex * 2,
        revision_id=revision.id,
        plan_id=plan.id,
        volume_id=volume.id,
        argv=["python", "/work/secret.py", "--token=argv-secret"],
        max_runtime_seconds=1800,
        state="running",
        reason_code="waiting_capacity",
        state_changed_at=now,
        queue_expires_at=now + timedelta(days=1),
        revision_snapshot={
            "environment_name": "Private environment",
            "display_label": "Private environment — approved 2026-11-20",
            "fingerprint": revision.fingerprint,
            "image_reference": IMAGE_REFERENCE,
            "configuration": {"environment_variables": {"API_KEY": "env-secret"}},
            "runtime_identity": {"path": "/var/lib/private/runtime"},
        },
        plan_snapshot={
            "name": plan.name,
            "secret": "plan-snapshot-secret",
        },
        volume_snapshot={
            "id": str(volume.id),
            "display_name": volume.display_name,
            "visibility": "private",
        },
        reservation_active=True,
        volume_operation_id=None,
        volume_fencing_token=uuid.uuid4(),
        runtime_identity={"path": "/var/lib/private/runtime"},
        container_id="container-private-id",
        container_name="nukelab-job-private-name",
        executor_id=uuid.uuid4(),
        heartbeat_at=now,
        fencing_token=uuid.uuid4(),
        cleanup_state="pending",
        cleanup_attempts=0,
        billing_mode="zero_cost",
        charged_credits=0,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.add(
        BatchJobLog(
            job_id=job.id,
            text="log-secret output",
            encoding="utf-8",
            truncated=False,
            size_bytes=17,
            captured_at=now,
        )
    )
    await db.commit()
    return job, owner, volume, revision, plan


async def _denied(client, headers):
    listing = await client.get("/api/admin/jobs", headers=headers)
    detail = await client.get(f"/api/admin/jobs/{uuid.uuid4()}", headers=headers)
    reconcile = await client.post(
        f"/api/admin/jobs/{uuid.uuid4()}/reconcile",
        headers=headers,
        json={"reason": "negative authorization check"},
    )
    cancel = await client.post(
        f"/api/admin/jobs/{uuid.uuid4()}/cancel",
        headers=headers,
        json={"reason": "negative authorization check"},
    )
    assert listing.status_code == 403
    assert detail.status_code == 403
    assert reconcile.status_code == 403
    assert cancel.status_code == 403


@pytest.mark.parametrize("role_index", [0, 1, 2])
async def test_default_non_admin_roles_are_denied(
    client, user_token, moderator_token, support_token, role_index
):
    token = (user_token, moderator_token, support_token)[role_index]
    await _denied(client, auth(token))


async def test_missing_jwt_is_rejected(client):
    assert (await client.get("/api/admin/jobs")).status_code == 401
    assert (await client.get(f"/api/admin/jobs/{uuid.uuid4()}")).status_code == 401
    assert (
        await client.post(
            f"/api/admin/jobs/{uuid.uuid4()}/reconcile",
            json={"reason": "missing token"},
        )
    ).status_code == 401


async def test_admin_and_super_admin_can_read(client, admin_token, superadmin_token):
    for token in (admin_token, superadmin_token):
        headers = auth(token)
        listing = await client.get("/api/admin/jobs", headers=headers)
        assert listing.status_code == 200
        assert listing.json()["pagination"] == {
            "limit": 50,
            "offset": 0,
            "total": 0,
            "has_more": False,
        }
        assert listing.json()["items"] == []
        assert "no-store" in listing.headers["cache-control"]


async def test_admin_access_alone_is_insufficient(client, support_token):
    ROLE_PERMISSIONS["support"] = [Permission.ADMIN_ACCESS]
    _rebuild_expansion_cache()
    await _denied(client, auth(support_token))


async def test_operations_read_alone_is_insufficient(client, moderator_token):
    ROLE_PERMISSIONS["moderator"] = [Permission.OPERATIONS_READ_ALL]
    _rebuild_expansion_cache()
    await _denied(client, auth(moderator_token))


async def test_read_only_operations_role_can_read_but_cannot_mutate(
    client, support_token, db_session
):
    ROLE_PERMISSIONS["support"] = [
        Permission.ADMIN_ACCESS,
        Permission.OPERATIONS_READ_ALL,
    ]
    _rebuild_expansion_cache()
    job, _, _, _, _ = await _private_job(db_session)
    headers = auth(support_token)

    listing = await client.get("/api/admin/jobs", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["pagination"]["total"] == 1
    detail = await client.get(f"/api/admin/jobs/{job.id}", headers=headers)
    assert detail.status_code == 200

    target = uuid.uuid4()
    assert (await client.post("/api/admin/jobs", headers=headers, json={})).status_code == 405
    assert (
        await client.post(
            f"/api/admin/jobs/{target}/reconcile",
            headers=headers,
            json={"reason": "read-only role must not reconcile"},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/admin/jobs/{target}/cancel",
            headers=headers,
            json={"reason": "read-only role must not cancel"},
        )
    ).status_code == 403
    assert (await client.delete(f"/api/admin/jobs/{target}", headers=headers)).status_code == 405


async def test_admin_api_token_cannot_use_job_view(client, admin_user, db_session):
    raw_token = "nukelab_" + secrets.token_urlsafe(32)
    db_session.add(
        ApiToken(
            user_id=admin_user.id,
            name="Admin jobs token",
            token_hash=get_password_hash(raw_token),
            token_prefix=raw_token[:16],
            scopes=["*"],
            is_active=True,
        )
    )
    await db_session.commit()

    listing = await client.get("/api/admin/jobs", headers=auth(raw_token))
    assert listing.status_code == 403
    assert "JWT" in listing.json()["detail"]
    detail = await client.get(f"/api/admin/jobs/{uuid.uuid4()}", headers=auth(raw_token))
    assert detail.status_code == 403
    reconcile = await client.post(
        f"/api/admin/jobs/{uuid.uuid4()}/reconcile",
        headers=auth(raw_token),
        json={"reason": "api token must not reconcile"},
    )
    assert reconcile.status_code == 403
    assert "JWT" in reconcile.json()["detail"]
    cancel = await client.post(
        f"/api/admin/jobs/{uuid.uuid4()}/cancel",
        headers=auth(raw_token),
        json={"reason": "api token must not cancel"},
    )
    assert cancel.status_code == 403
    assert "JWT" in cancel.json()["detail"]


async def test_cross_owner_rows_never_disclose_payloads_or_runtime_identity(
    client, admin_token, db_session
):
    job, owner, volume, revision, plan = await _private_job(db_session)
    headers = auth(admin_token)

    listing = await client.get("/api/admin/jobs", headers=headers)
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["owner_username"] == owner.username
    assert item["owner_display_name"] == "Foreign Owner"
    assert item["environment_name"] == "Private environment"
    assert item["environment_display_label"] == "Private environment — approved 2026-11-20"
    assert item["plan_name"] == plan.name
    assert item["volume_display_name"] == "pilot-data"
    assert item["reason_code"] == "waiting_capacity"
    assert item["log_state"] == "pending"
    assert item["reservation_active"] is True
    assert item["can_reconcile"] is False

    forbidden = [
        *FORBIDDEN_VALUES,
        str(volume.id),
        str(revision.id),
        str(revision.fingerprint),
        str(job.fencing_token),
        str(job.volume_fencing_token),
        str(job.executor_id),
    ]
    text = json.dumps(listing.json())
    detail_text = json.dumps(
        (await client.get(f"/api/admin/jobs/{job.id}", headers=headers)).json()
    )
    for value in forbidden:
        assert value not in text
        assert value not in detail_text
    for key in ("argv", "logs", "log_text", "environment_values", "name"):
        assert f'"{key}"' not in text


async def test_reconcile_response_and_audit_never_disclose_payloads(
    client, admin_token, admin_user, db_session, fake_runtime
):
    job, owner, volume, revision, _plan = await _private_job(db_session)
    now = utc_now()
    job.state = "recovery_required"
    job.reason_code = "runtime_unverifiable"
    job.reservation_active = True
    job.heartbeat_at = now - timedelta(seconds=settings.batch_jobs_heartbeat_stale_seconds + 5)
    job.create_requested_at = now - timedelta(minutes=5)
    job.volume_operation_id = job.id
    guard = VolumeOperation(
        operation_id=job.id,
        volume_id=volume.id,
        owner_id=owner.id,
        kind="job_writer",
        state="reserved",
        fencing_token=uuid.uuid4(),
    )
    job.volume_fencing_token = guard.fencing_token
    db_session.add(guard)
    job_id = job.id
    volume_id = volume.id
    revision_id = revision.id
    revision_fingerprint = str(revision.fingerprint)
    job_fence = str(job.fencing_token)
    volume_fence = str(job.volume_fencing_token)
    executor_id = str(job.executor_id)
    admin_id = admin_user.id
    await db_session.commit()

    response = await client.post(
        f"/api/admin/jobs/{job_id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "operator verified the absent recorded runtime"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["applied"] is True
    assert data["outcome"] == "applied"
    assert data["terminal_state"] == "failed"
    assert data["proof_source"] == "runtime_inspection"
    assert data["reason_code"] == "runtime_absent"
    assert data["job"]["state"] == "failed"
    assert data["job"]["reservation_active"] is False
    assert data["job"]["guard_active"] is False

    forbidden = [
        *FORBIDDEN_VALUES,
        str(volume_id),
        str(revision_id),
        revision_fingerprint,
        job_fence,
        volume_fence,
        executor_id,
    ]
    text = json.dumps(data)
    for value in forbidden:
        assert value not in text
    for key in ("argv", "logs", "log_text", "environment_values", "name"):
        assert f'"{key}"' not in text

    logs = (
        await db_session.scalars(
            select(ActivityLog)
            .where(ActivityLog.target_id == job_id)
            .order_by(ActivityLog.created_at, ActivityLog.id)
        )
    ).all()
    assert len(logs) == 1
    entry = logs[0]
    assert entry.action == "jobs.reconcile_applied"
    assert entry.target_type == "batch_job"
    assert entry.target_id == job_id
    assert entry.actor_id == admin_id
    assert set(entry.details) <= AUDIT_KEYS
    audit_text = json.dumps(entry.details)
    for value in forbidden:
        assert value not in audit_text


async def test_cancel_response_and_audit_never_disclose_payloads(
    client, admin_token, admin_user, db_session
):
    job, owner, volume, revision, _plan = await _private_job(db_session)
    job.volume_operation_id = job.id
    guard = VolumeOperation(
        operation_id=job.id,
        volume_id=volume.id,
        owner_id=owner.id,
        kind="job_writer",
        state="reserved",
        fencing_token=uuid.uuid4(),
    )
    job.volume_fencing_token = guard.fencing_token
    db_session.add(guard)
    job_id = job.id
    volume_id = volume.id
    revision_id = revision.id
    revision_fingerprint = str(revision.fingerprint)
    job_fence = str(job.fencing_token)
    volume_fence = str(job.volume_fencing_token)
    executor_id = str(job.executor_id)
    admin_id = admin_user.id
    await db_session.commit()

    response = await client.post(
        f"/api/admin/jobs/{job_id}/cancel",
        headers=auth(admin_token),
        json={"reason": "operator requests a safe stop"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["applied"] is True
    assert data["outcome"] == "cancellation_requested"
    assert data["job"]["state"] == "cancelling"
    assert data["job"]["reservation_active"] is True
    assert data["job"]["guard_active"] is True

    forbidden = [
        *FORBIDDEN_VALUES,
        str(volume_id),
        str(revision_id),
        revision_fingerprint,
        job_fence,
        volume_fence,
        executor_id,
    ]
    text = json.dumps(data)
    for value in forbidden:
        assert value not in text
    for key in ("argv", "logs", "log_text", "environment_values", "name"):
        assert f'"{key}"' not in text

    logs = (
        await db_session.scalars(
            select(ActivityLog)
            .where(ActivityLog.target_id == job_id)
            .order_by(ActivityLog.created_at, ActivityLog.id)
        )
    ).all()
    assert len(logs) == 1
    entry = logs[0]
    assert entry.action == "jobs.cancel_applied"
    assert entry.target_type == "batch_job"
    assert entry.target_id == job_id
    assert entry.actor_id == admin_id
    assert set(entry.details) == CANCEL_AUDIT_KEYS
    audit_text = json.dumps(entry.details)
    for value in forbidden:
        assert value not in audit_text
