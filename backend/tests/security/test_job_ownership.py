# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Foreign job and resource ids must be indistinguishable from missing ids."""

import uuid

import pytest

from app.config import settings
from app.core.time_utils import utc_now
from app.models.user import User
from tests.services.test_batch_job_service import (
    make_environment,
    make_plan,
    make_resources,
    make_volume,
    stored_job,
    submit_request,
)


def headers(token, key=None):
    values = {"Authorization": f"Bearer {token}"}
    if key is not None:
        values["Idempotency-Key"] = key
    return values


@pytest.fixture
def enabled_jobs(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    return settings


async def make_foreign_user(db_session):
    foreign = User(
        username=f"foreign-{uuid.uuid4().hex[:8]}",
        email=f"foreign-{uuid.uuid4().hex[:8]}@example.test",
        role="user",
        is_active=True,
        is_verified=True,
    )
    db_session.add(foreign)
    await db_session.flush()
    return foreign


@pytest.mark.asyncio
async def test_foreign_job_ids_match_missing_for_detail_cancel_and_logs(
    client, db_session, test_user, user_token
):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    foreign = await make_foreign_user(db_session)
    foreign_volume = await make_volume(db_session, foreign)
    foreign_job = stored_job(
        foreign,
        revision,
        plan,
        foreign_volume,
        created_at=utc_now(),
        name="Foreign job",
    )
    db_session.add(foreign_job)
    await db_session.commit()

    missing_id = uuid.uuid4()
    for method, suffix in (
        ("GET", ""),
        ("POST", "/cancel"),
        ("GET", "/logs"),
    ):
        foreign_response = await client.request(
            method,
            f"/api/jobs/{foreign_job.id}{suffix}",
            headers=headers(user_token),
        )
        missing_response = await client.request(
            method,
            f"/api/jobs/{missing_id}{suffix}",
            headers=headers(user_token),
        )
        assert foreign_response.status_code == 404
        assert missing_response.status_code == 404
        assert foreign_response.json() == missing_response.json()
        assert foreign_response.json() == {"detail": {"code": "job_not_found"}}

    listed = await client.get("/api/jobs?state=all", headers=headers(user_token))
    assert listed.status_code == 200
    assert foreign_job.id not in {uuid.UUID(item["id"]) for item in listed.json()["items"]}


@pytest.mark.asyncio
async def test_foreign_submission_resources_match_missing_resources(
    client, db_session, test_user, user_token, enabled_jobs
):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    foreign = await make_foreign_user(db_session)
    foreign_volume = await make_volume(db_session, foreign)
    _, foreign_revision = await make_environment(db_session, is_public=False)
    foreign_plan = await make_plan(db_session, is_public=False, visible_to_roles=[])
    await db_session.commit()

    cases = (
        ("volume_id", foreign_volume.id, "volume_unavailable"),
        ("revision_id", foreign_revision.id, "revision_unavailable"),
        ("plan_id", foreign_plan.id, "plan_unavailable"),
    )
    for field, foreign_id, code in cases:
        foreign_body = submit_request(revision, plan, volume).model_dump(mode="json")
        foreign_body[field] = str(foreign_id)
        missing_body = submit_request(revision, plan, volume).model_dump(mode="json")
        missing_body[field] = str(uuid.uuid4())

        foreign_response = await client.post(
            "/api/jobs",
            headers=headers(user_token, f"foreign-{field}"),
            json=foreign_body,
        )
        missing_response = await client.post(
            "/api/jobs",
            headers=headers(user_token, f"missing-{field}"),
            json=missing_body,
        )
        assert foreign_response.status_code == missing_response.status_code == 422
        assert foreign_response.json() == missing_response.json()
        assert foreign_response.json()["detail"]["code"] == code
