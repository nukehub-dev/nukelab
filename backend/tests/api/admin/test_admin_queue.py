# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Read-only admin queue listing, sanitization, and owner recovery messaging."""

import json
import uuid
from datetime import timedelta

import pytest

from app.api.auth import get_password_hash
from app.core.time_utils import utc_now
from app.main import app
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.user import User

pytestmark = pytest.mark.asyncio


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _targets(db):
    marker = uuid.uuid4().hex[:8]
    plan = ServerPlan(
        name=f"Admin queue plan {marker}",
        slug=f"admin-queue-plan-{marker}",
        cpu_limit=2,
    )
    environment = EnvironmentTemplate(
        name=f"Admin queue environment {marker}",
        slug=f"admin-queue-env-{marker}",
        image="approved",
    )
    db.add_all([plan, environment])
    await db.flush()
    return plan, environment


async def _queue_row(
    db,
    owner,
    plan,
    environment,
    *,
    name,
    status="pending",
    reason_code=None,
    requested_at=None,
    priority=0,
    **values,
):
    requested_at = requested_at or utc_now()
    row = ServerQueue(
        user_id=owner.id,
        environment_id=environment.id,
        plan_id=plan.id,
        status=status,
        priority=priority,
        server_name=name,
        request_payload={
            "launch_token": "payload-token",
            "volume_mounts": [{"mount_path": "/home/private", "volume_id": str(uuid.uuid4())}],
            "environment_values": {"API_KEY": "env-secret"},
        },
        request_version=7,
        plan_snapshot={
            "secret": "plan-snapshot-secret",
            "volume_id": str(uuid.uuid4()),
            "mount_path": "/home/private",
        },
        revision_id=uuid.uuid4(),
        claim_token=uuid.uuid4(),
        requested_at=requested_at,
        expires_at=requested_at + timedelta(hours=1),
        reason_code=reason_code,
        **values,
    )
    db.add(row)
    await db.flush()
    return row


async def _other_user(db):
    marker = uuid.uuid4().hex[:8]
    user = User(
        username=f"queue-owner-{marker}",
        email=f"queue-owner-{marker}@example.test",
        password_hash=get_password_hash("otherpass123"),
        role="user",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


async def test_admin_queue_filters_order_and_bounded_pagination(
    client, admin_token, db_session, test_user
):
    plan, environment = await _targets(db_session)
    foreign = await _other_user(db_session)
    now = utc_now()
    old = await _queue_row(
        db_session,
        test_user,
        plan,
        environment,
        name="old-pending",
        requested_at=now - timedelta(days=5),
    )
    starting = await _queue_row(
        db_session,
        test_user,
        plan,
        environment,
        name="orphan-starting",
        status="starting",
        reason_code="recovery_required",
        requested_at=now - timedelta(days=2),
    )
    failed = await _queue_row(
        db_session,
        test_user,
        plan,
        environment,
        name="recent-failed",
        status="failed",
        reason_code="runtime_absent",
        requested_at=now - timedelta(days=1),
        failed_at=now - timedelta(days=1),
    )
    foreign_row = await _queue_row(
        db_session,
        foreign,
        plan,
        environment,
        name="foreign-pending",
        requested_at=now - timedelta(hours=1),
    )
    headers = auth(admin_token)

    listed = await client.get("/api/admin/server-queue", headers=headers)
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["pagination"] == {
        "limit": 50,
        "offset": 0,
        "total": 4,
        "has_more": False,
    }
    assert [item["id"] for item in payload["items"]] == [
        str(old.id),
        str(starting.id),
        str(failed.id),
        str(foreign_row.id),
    ]
    first = payload["items"][0]
    assert set(first) == {
        "id",
        "owner_id",
        "server_id",
        "server_name",
        "environment_id",
        "plan_id",
        "status",
        "reason_code",
        "position",
        "priority",
        "requested_at",
        "started_at",
        "failed_at",
        "expires_at",
    }
    assert first["owner_id"] == str(test_user.id)
    assert first["status"] == "pending"
    assert first["position"] == 1
    assert first["priority"] == 0
    assert payload["items"][3]["position"] == 2
    assert payload["items"][1]["position"] is None
    assert payload["items"][2]["position"] is None

    # A starting row without any linked operation is still visible.
    assert starting.id == uuid.UUID(payload["items"][1]["id"])
    assert payload["items"][1]["status"] == "starting"
    assert payload["items"][1]["reason_code"] == "recovery_required"
    assert payload["items"][1]["server_id"] is None

    by_status = await client.get("/api/admin/server-queue?status=starting", headers=headers)
    assert [item["id"] for item in by_status.json()["items"]] == [str(starting.id)]
    by_statuses = await client.get(
        "/api/admin/server-queue?status=starting&status=failed", headers=headers
    )
    assert {item["id"] for item in by_statuses.json()["items"]} == {
        str(starting.id),
        str(failed.id),
    }

    by_owner = await client.get(f"/api/admin/server-queue?owner_id={test_user.id}", headers=headers)
    assert by_owner.json()["pagination"]["total"] == 3
    by_foreign = await client.get(f"/api/admin/server-queue?owner_id={foreign.id}", headers=headers)
    assert [item["id"] for item in by_foreign.json()["items"]] == [str(foreign_row.id)]

    aged = await client.get("/api/admin/server-queue?age_days=3", headers=headers)
    assert [item["id"] for item in aged.json()["items"]] == [str(old.id)]
    older = await client.get(
        "/api/admin/server-queue",
        params={"older_than": (now - timedelta(days=3)).isoformat()},
        headers=headers,
    )
    assert [item["id"] for item in older.json()["items"]] == [str(old.id)]

    recovery = await client.get("/api/admin/server-queue?recovery_required=true", headers=headers)
    assert [item["id"] for item in recovery.json()["items"]] == [str(starting.id)]
    healthy = await client.get("/api/admin/server-queue?recovery_required=false", headers=headers)
    assert {item["id"] for item in healthy.json()["items"]} == {
        str(old.id),
        str(failed.id),
        str(foreign_row.id),
    }

    first_page = await client.get("/api/admin/server-queue?limit=2&offset=0", headers=headers)
    second_page = await client.get("/api/admin/server-queue?limit=2&offset=2", headers=headers)
    repeated = await client.get("/api/admin/server-queue?limit=2&offset=0", headers=headers)
    assert [item["id"] for item in first_page.json()["items"]] == [
        str(old.id),
        str(starting.id),
    ]
    assert first_page.json()["pagination"]["has_more"] is True
    assert [item["id"] for item in second_page.json()["items"]] == [
        str(failed.id),
        str(foreign_row.id),
    ]
    assert second_page.json()["pagination"]["has_more"] is False
    assert first_page.json()["items"] == repeated.json()["items"]

    assert (await client.get("/api/admin/server-queue?limit=0", headers=headers)).status_code == 422
    assert (
        await client.get("/api/admin/server-queue?limit=101", headers=headers)
    ).status_code == 422
    assert (
        await client.get("/api/admin/server-queue?offset=1001", headers=headers)
    ).status_code == 422
    assert (
        await client.get("/api/admin/server-queue?status=unknown", headers=headers)
    ).status_code == 422


async def test_admin_queue_ties_use_deterministic_id_order(
    client, admin_token, db_session, test_user
):
    plan, environment = await _targets(db_session)
    requested_at = utc_now() - timedelta(minutes=5)
    rows = [
        await _queue_row(
            db_session,
            test_user,
            plan,
            environment,
            name=f"tie-{index}",
            status="pending",
            requested_at=requested_at,
        )
        for index in range(3)
    ]
    response = await client.get(
        f"/api/admin/server-queue?owner_id={test_user.id}&limit=3",
        headers=auth(admin_token),
    )
    assert [item["id"] for item in response.json()["items"]] == [
        str(row.id) for row in sorted(rows, key=lambda row: str(row.id))
    ]


async def test_admin_queue_sanitizes_payloads_tokens_and_raw_text(
    client, admin_token, db_session, test_user
):
    plan, environment = await _targets(db_session)
    row = await _queue_row(
        db_session,
        test_user,
        plan,
        environment,
        name="sanitized-starting",
        status="starting",
        reason_code="recovery_required",
        error_message="/private/host/path: password=secret",
        started_at=utc_now(),
    )
    bad_reason = await _queue_row(
        db_session,
        test_user,
        plan,
        environment,
        name="raw-reason",
        status="starting",
        reason_code="/private/host/path: password=secret",
    )
    response = await client.get(
        f"/api/admin/server-queue?owner_id={test_user.id}",
        headers=auth(admin_token),
    )
    assert response.status_code == 200
    payload = response.json()
    text = json.dumps(payload)
    for forbidden in (
        "request_payload",
        "claim_token",
        "request_version",
        "plan_snapshot",
        "revision_id",
        "error_message",
        "volume_mounts",
        "environment_values",
        "mount_path",
        "volume_id",
        "/home/private",
        "/private/host/path",
        "password=secret",
        "payload-token",
        "env-secret",
        "plan-snapshot-secret",
        plan.name,
        environment.name,
        str(row.claim_token),
        str(row.revision_id),
        str(row.request_payload["volume_mounts"][0]["volume_id"]),
    ):
        assert forbidden not in text

    items = {item["id"]: item for item in payload["items"]}
    sanitized = items[str(row.id)]
    assert sanitized["status"] == "starting"
    assert sanitized["reason_code"] == "recovery_required"
    assert sanitized["environment_id"] == str(environment.id)
    assert sanitized["plan_id"] == str(plan.id)
    assert items[str(bad_reason.id)]["reason_code"] is None


async def test_admin_queue_exposes_no_mutation_route(client, admin_token):
    headers = auth(admin_token)
    target = uuid.uuid4()
    assert (
        await client.post("/api/admin/server-queue", headers=headers, json={})
    ).status_code == 405
    assert (
        await client.post(f"/api/admin/server-queue/{target}/cancel", headers=headers)
    ).status_code == 404
    assert (
        await client.delete(f"/api/admin/server-queue/{target}", headers=headers)
    ).status_code == 404
    assert (
        await client.patch(f"/api/admin/server-queue/{target}", headers=headers, json={})
    ).status_code == 404

    queue_routes = [route for route in app.routes if route.path.startswith("/admin/server-queue")]
    assert {route.path for route in queue_routes} == {"/admin/server-queue"}
    methods = {method for route in queue_routes for method in route.methods}
    assert methods <= {"GET", "HEAD"}
    assert methods & {"POST", "PUT", "PATCH", "DELETE"} == set()


async def test_owner_queue_explains_recovery_and_keeps_pending_cancellation(
    client, user_token, db_session, test_user
):
    plan, environment = await _targets(db_session)
    foreign = await _other_user(db_session)
    pending = await _queue_row(
        db_session,
        test_user,
        plan,
        environment,
        name="owner-pending",
        requested_at=utc_now() - timedelta(minutes=1),
    )
    recovery = await _queue_row(
        db_session,
        test_user,
        plan,
        environment,
        name="owner-recovery",
        status="starting",
        reason_code="recovery_required",
        requested_at=utc_now() - timedelta(minutes=2),
        error_message="/private/host/path: password=secret",
    )
    await _queue_row(
        db_session,
        foreign,
        plan,
        environment,
        name="foreign-recovery",
        status="starting",
        reason_code="recovery_required",
        requested_at=utc_now(),
    )
    raw_reason = await _queue_row(
        db_session,
        test_user,
        plan,
        environment,
        name="owner-raw-reason",
        status="failed",
        reason_code="/private/host/path: password=secret",
        requested_at=utc_now() - timedelta(minutes=3),
        failed_at=utc_now(),
    )
    headers = auth(user_token)

    listed = await client.get("/api/server-queue", headers=headers)
    assert listed.status_code == 200
    items = {item["id"]: item for item in listed.json()["items"]}
    assert set(items) == {str(pending.id), str(recovery.id), str(raw_reason.id)}
    assert items[str(raw_reason.id)]["reason_code"] is None
    assert items[str(raw_reason.id)]["message"] == (
        "Launch failed. Submit a new request to try again."
    )

    owner_pending = items[str(pending.id)]
    assert owner_pending["status"] == "pending"
    assert owner_pending["can_cancel"] is True
    assert owner_pending["position"] == 1
    assert owner_pending["message"] == "Waiting for available capacity."

    owner_recovery = items[str(recovery.id)]
    assert owner_recovery["status"] == "starting"
    assert owner_recovery["reason_code"] == "recovery_required"
    assert owner_recovery["position"] is None
    assert owner_recovery["can_cancel"] is False
    assert "support" in owner_recovery["message"].lower()
    assert "submit" in owner_recovery["message"].lower()

    text = listed.text
    for forbidden in (
        "foreign-recovery",
        "/private/host/path",
        "password=secret",
        "request_version",
        "claim_token",
        "request_payload",
        str(recovery.claim_token),
    ):
        assert forbidden not in text

    cancelled = await client.post(f"/api/server-queue/{pending.id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["can_cancel"] is False

    refused = await client.post(f"/api/server-queue/{recovery.id}/cancel", headers=headers)
    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "launch_in_progress"}
