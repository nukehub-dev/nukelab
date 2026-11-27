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

from app.api.auth import get_password_hash
from app.core.permissions import Permission
from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache
from app.core.time_utils import utc_now
from app.models.api_token import ApiToken
from app.models.batch_job import BatchJob, BatchJobLog
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume

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


def auth(token):
    return {"Authorization": f"Bearer {token}"}


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
    assert listing.status_code == 403
    assert detail.status_code == 403


@pytest.mark.parametrize("role_index", [0, 1, 2])
async def test_default_non_admin_roles_are_denied(
    client, user_token, moderator_token, support_token, role_index
):
    token = (user_token, moderator_token, support_token)[role_index]
    await _denied(client, auth(token))


async def test_missing_jwt_is_rejected(client):
    assert (await client.get("/api/admin/jobs")).status_code == 401
    assert (await client.get(f"/api/admin/jobs/{uuid.uuid4()}")).status_code == 401


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
        await client.post(f"/api/admin/jobs/{target}/reconcile", headers=headers, json={})
    ).status_code == 404
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
