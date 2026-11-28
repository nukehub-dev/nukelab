# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Batch job API authentication, response contract and owner operations."""

import uuid

import pytest

from app.api.auth import create_access_token
from app.config import settings
from app.models.user import User
from tests.services.test_batch_job_service import (
    make_environment,
    make_resources,
    submit_request,
)


def auth_headers(token, idempotency_key=None):
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


@pytest.fixture
def enabled_jobs(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    return settings


@pytest.mark.asyncio
async def test_job_routes_require_jwt(client, api_token):
    unauthenticated = await client.get("/api/jobs/capabilities")
    assert unauthenticated.status_code == 401

    api_token_response = await client.get(
        "/api/jobs/capabilities",
        headers=auth_headers(api_token.raw_token),
    )
    assert api_token_response.status_code == 403
    assert "JWT" in api_token_response.json()["detail"]


@pytest.mark.asyncio
async def test_guest_is_denied_job_permissions(client, db_session):
    guest = User(
        username=f"guest-{uuid.uuid4().hex[:8]}",
        email=f"guest-{uuid.uuid4().hex[:8]}@example.test",
        role="guest",
        is_active=True,
        is_verified=True,
    )
    db_session.add(guest)
    await db_session.commit()
    token = create_access_token(data={"sub": guest.username, "role": guest.role})

    response = await client.get("/api/jobs/capabilities", headers=auth_headers(token))
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "permission_denied"}}


@pytest.mark.asyncio
async def test_capabilities_contract(client, user_token, monkeypatch):
    monkeypatch.setattr(settings, "xfs_quota_enabled", False)
    response = await client.get("/api/jobs/capabilities", headers=auth_headers(user_token))
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "enabled": True,
        "can_submit": False,
        "billing_mode": "zero_cost",
        "secrets_enabled": False,
        "storage_limits_enforced": False,
        "storage_enforcement_required": False,
        "reason_code": "feature_disabled",
        "limits": {
            "max_active_jobs": 1,
            "max_queued_jobs": 3,
            "default_runtime_seconds": 1800,
            "max_runtime_seconds": 7200,
            "queue_ttl_seconds": 86400,
            "max_argv_items": 64,
            "max_input_bytes": 16384,
            "log_tail_bytes": 262144,
            "log_retention_seconds": 604800,
        },
    }


@pytest.mark.asyncio
async def test_eligible_revisions_endpoint_is_sanitized(client, db_session, test_user, user_token):
    template, revision = await make_environment(db_session)
    await db_session.commit()

    response = await client.get("/api/jobs/eligible-revisions", headers=auth_headers(user_token))
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["revision_id"] == str(revision.id)
    assert item["environment_id"] == str(template.id)
    assert item["environment_name"] == template.name
    assert item["supports_jobs"] is True
    assert "configuration" not in item
    assert "environment_variables" not in item
    assert "PILOT_TOKEN" not in response.text


@pytest.mark.asyncio
async def test_submit_requires_idempotency_key(
    client, db_session, test_user, user_token, enabled_jobs
):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    await db_session.commit()
    body = submit_request(revision, plan, volume).model_dump(mode="json")

    missing = await client.post(
        "/api/jobs",
        headers=auth_headers(user_token),
        json=body,
    )
    assert missing.status_code == 422
    assert missing.json() == {"detail": {"code": "invalid_request", "field": "Idempotency-Key"}}


@pytest.mark.asyncio
async def test_submit_replay_detail_list_cancel_and_logs(
    client, db_session, test_user, user_token, enabled_jobs
):
    template, revision, plan, volume = await make_resources(db_session, test_user)
    await db_session.commit()
    body = submit_request(revision, plan, volume).model_dump(mode="json")
    headers = auth_headers(user_token, "api-idempotency-key")

    created = await client.post("/api/jobs", headers=headers, json=body)
    assert created.status_code == 202
    detail = created.json()
    assert detail["replayed"] is False
    assert detail["state"] == "queued"
    assert detail["reason_code"] == "waiting_capacity"
    assert detail["reason_message"] == "Waiting for capacity."
    assert detail["can_cancel"] is True
    assert detail["environment"]["revision_id"] == str(revision.id)
    assert detail["environment"]["environment_id"] == str(template.id)
    assert detail["environment"]["image_reference"].startswith("registry.example.test/")
    assert detail["plan"]["id"] == str(plan.id)
    assert detail["volume"] == {
        "id": str(volume.id),
        "display_name": "pilot-data",
        "available": True,
    }
    assert detail["argv"] == ["python", "/work/input.py"]
    assert detail["limits"] == {"max_runtime_seconds": 600}
    assert detail["result"] is None
    assert detail["logs"]["state"] == "pending"
    assert detail["billing"] == {"mode": "zero_cost", "charged": 0}
    job_id = detail["id"]

    replay = await client.post("/api/jobs", headers=headers, json=body)
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["id"] == job_id

    listed = await client.get("/api/jobs", headers=auth_headers(user_token))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [job_id]
    assert listed.json()["next_cursor"] is None
    summary = listed.json()["items"][0]
    assert summary["environment_name"] == template.name
    assert summary["can_cancel"] is True

    detail_response = await client.get(f"/api/jobs/{job_id}", headers=auth_headers(user_token))
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == job_id

    logs_response = await client.get(f"/api/jobs/{job_id}/logs", headers=auth_headers(user_token))
    assert logs_response.status_code == 200
    assert logs_response.json()["state"] == "pending"
    assert logs_response.json()["text"] is None

    cancelled = await client.post(f"/api/jobs/{job_id}/cancel", headers=auth_headers(user_token))
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["result"]["outcome_code"] == "cancelled"
    assert cancelled.json()["can_cancel"] is False

    after_cancel = await client.get("/api/jobs?state=active", headers=auth_headers(user_token))
    assert after_cancel.json()["items"] == []
    history = await client.get("/api/jobs?state=history", headers=auth_headers(user_token))
    assert [item["id"] for item in history.json()["items"]] == [job_id]


@pytest.mark.asyncio
async def test_list_rejects_unknown_state(client, user_token):
    response = await client.get("/api/jobs?state=bogus", headers=auth_headers(user_token))
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_request", "field": "state"}}


@pytest.mark.asyncio
async def test_volume_availability_is_owner_scoped(
    client, db_session, test_user, user_token, enabled_jobs
):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    await db_session.commit()
    body = submit_request(revision, plan, volume).model_dump(mode="json")

    created = await client.post(
        "/api/jobs",
        headers=auth_headers(user_token, "availability-key"),
        json=body,
    )
    assert created.status_code == 202
    job_id = created.json()["id"]

    await db_session.delete(volume)
    await db_session.commit()

    detail = await client.get(f"/api/jobs/{job_id}", headers=auth_headers(user_token))
    assert detail.status_code == 200
    assert detail.json()["volume"] == {
        "id": str(volume.id),
        "display_name": "pilot-data",
        "available": False,
    }
