# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Batch job submission, idempotency, limits, listing and log contracts."""

import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app.config import settings
from app.core.time_utils import utc_now
from app.db.base import Base
from app.models.batch_job import BatchJob, BatchJobLog
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.schemas.batch_job import BatchJobSubmitRequest
from app.services.batch_job_service import BatchJobService, JobError

IMAGE_REFERENCE = "registry.example.test/pilot@sha256:" + "b" * 64


async def make_environment(
    db,
    *,
    name="Batch env",
    is_public=True,
    is_active=True,
    revoked=False,
    with_environment_variables=True,
):
    template = EnvironmentTemplate(
        name=f"{name} {uuid.uuid4().hex[:8]}",
        slug=f"batch-env-{uuid.uuid4().hex[:8]}",
        image="registry.example.test/pilot:1",
        is_public=is_public,
        is_active=is_active,
    )
    db.add(template)
    await db.flush()
    configuration = {"image": template.image}
    if with_environment_variables:
        configuration["environment_variables"] = {"PILOT_TOKEN": "must-not-leak"}
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint=uuid.uuid4().hex * 2,
        template_fingerprint=uuid.uuid4().hex * 2,
        portable_fingerprint=None,
        configuration=configuration,
        runtime_identity={
            "requested_reference": template.image,
            "local_id": "sha256:" + "a" * 64,
            "repository_digests": [],
            "os": "linux",
            "architecture": "amd64",
            "registry_verified": True,
            "verified_reference": IMAGE_REFERENCE,
        },
        revoked=revoked,
    )
    db.add(revision)
    await db.flush()
    return template, revision


async def make_plan(db, *, cost_per_hour=0, gpu_limit=0, is_public=True, visible_to_roles=None):
    plan = ServerPlan(
        name=f"Batch plan {uuid.uuid4().hex[:8]}",
        slug=f"batch-plan-{uuid.uuid4().hex[:8]}",
        cpu_limit=1.5,
        memory_limit="2g",
        disk_limit="10g",
        gpu_limit=gpu_limit,
        cost_per_hour=cost_per_hour,
        allow_batch_jobs=True,
        is_active=True,
        is_public=is_public,
        visible_to_roles=["user"] if visible_to_roles is None else visible_to_roles,
    )
    db.add(plan)
    await db.flush()
    return plan


async def make_volume(db, owner, *, status="active", visibility="private"):
    volume = Volume(
        name=f"batch-vol-{uuid.uuid4().hex[:8]}",
        display_name="pilot-data",
        owner_id=owner.id,
        visibility=visibility,
        status=status,
    )
    db.add(volume)
    await db.flush()
    return volume


async def make_resources(db, user, **plan_kwargs):
    template, revision = await make_environment(db)
    plan = await make_plan(db, **plan_kwargs)
    volume = await make_volume(db, user)
    return template, revision, plan, volume


def submit_request(revision, plan, volume, **overrides):
    payload = {
        "name": "Checksum run",
        "revision_id": revision.id,
        "plan_id": plan.id,
        "volume_id": volume.id,
        "argv": ["python", "/work/input.py"],
        "max_runtime_seconds": 600,
    }
    payload.update(overrides)
    return BatchJobSubmitRequest(**payload)


def stored_job(
    owner,
    revision,
    plan,
    volume,
    *,
    created_at,
    state="queued",
    name="Stored job",
    reason_code="waiting_capacity",
    outcome_code=None,
    **overrides,
):
    revision_snapshot = {
        "revision_id": str(revision.id),
        "environment_id": str(revision.template_id),
        "environment_name": "Stored environment",
        "display_label": "Stored environment — approved 2026-11-20",
        "fingerprint": revision.fingerprint,
        "portable_fingerprint": None,
        "image_reference": IMAGE_REFERENCE,
        "configuration": {},
        "runtime_identity": {},
    }
    plan_snapshot = {
        "id": str(plan.id),
        "name": plan.name,
        "cpu": plan.cpu_limit,
        "memory_mib": 2048,
        "disk_mib": 10240,
        "gpu_count": plan.gpu_limit or 0,
        "cost_per_hour": plan.cost_per_hour or 0,
    }
    volume_snapshot = {
        "id": str(volume.id),
        "display_name": volume.display_name,
        "visibility": volume.visibility,
    }
    job = BatchJob(
        user_id=owner.id,
        name=name,
        idempotency_key_hash=uuid.uuid4().hex * 2,
        request_fingerprint=uuid.uuid4().hex * 2,
        revision_id=revision.id,
        plan_id=plan.id,
        volume_id=volume.id,
        argv=["echo", "stored"],
        max_runtime_seconds=1800,
        state=state,
        reason_code=reason_code,
        state_changed_at=created_at,
        queue_expires_at=created_at + timedelta(days=1),
        revision_snapshot=revision_snapshot,
        plan_snapshot=plan_snapshot,
        volume_snapshot=volume_snapshot,
        billing_mode="zero_cost",
        charged_credits=0,
        outcome_code=outcome_code,
        fencing_token=uuid.uuid4(),
        created_at=created_at,
        updated_at=created_at,
        **overrides,
    )
    return job


@pytest.fixture
def enabled_jobs(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    return settings


@pytest.mark.asyncio
async def test_capabilities_reflect_flag_permission_and_limits(db_session, test_user, monkeypatch):
    service = BatchJobService(db_session)
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", False)
    disabled = await service.capabilities(test_user)
    assert disabled.enabled is True
    assert disabled.can_submit is False
    assert disabled.reason_code == "feature_disabled"
    assert disabled.billing_mode == "zero_cost"
    assert disabled.limits.max_active_jobs == 1
    assert disabled.limits.max_queued_jobs == 3
    assert disabled.limits.max_runtime_seconds == 7200

    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    monkeypatch.setattr(settings, "batch_jobs_allow_paid_plans", True)
    enabled = await service.capabilities(test_user)
    assert enabled.enabled is True
    assert enabled.can_submit is True
    assert enabled.reason_code is None
    assert enabled.billing_mode == "paid"

    test_user.is_active = False
    inactive = await service.capabilities(test_user)
    assert inactive.enabled is False
    assert inactive.can_submit is False
    assert inactive.reason_code == "permission_denied"


@pytest.mark.asyncio
async def test_feature_disabled_keeps_owner_history_readable(db_session, test_user, monkeypatch):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    job = stored_job(
        test_user,
        revision,
        plan,
        volume,
        created_at=utc_now(),
        state="succeeded",
        reason_code=None,
        outcome_code="succeeded",
        name="Readable history",
    )
    db_session.add(job)
    await db_session.commit()
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", False)
    service = BatchJobService(db_session)

    listed = await service.list(test_user)
    assert [item.id for item in listed.items] == [job.id]
    detail = await service.get(test_user, job.id)
    assert detail.id == job.id
    assert detail.state == "succeeded"


@pytest.mark.asyncio
async def test_capabilities_deny_missing_write_permission(db_session, test_user, monkeypatch):
    from app.core.permissions import Permission
    from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache

    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    ROLE_PERMISSIONS["user"] = [
        permission
        for permission in ROLE_PERMISSIONS["user"]
        if permission != Permission.JOBS_WRITE_OWN
    ]
    _rebuild_expansion_cache()
    capabilities = await BatchJobService(db_session).capabilities(test_user)
    assert capabilities.enabled is True
    assert capabilities.can_submit is False
    assert capabilities.reason_code == "permission_denied"


@pytest.mark.asyncio
async def test_eligible_revisions_filters_private_inactive_and_revoked(db_session, test_user):
    public_template, public_revision = await make_environment(db_session)
    await make_environment(db_session, name="Private env", is_public=False)
    await make_environment(db_session, name="Inactive env", is_active=False)
    await make_environment(db_session, name="Revoked env", revoked=True)

    result = await BatchJobService(db_session).eligible_revisions(test_user)
    assert [item.revision_id for item in result.items] == [public_revision.id]
    item = result.items[0]
    assert item.environment_id == public_template.id
    assert item.environment_name == public_template.name
    assert item.fingerprint == public_revision.fingerprint
    assert item.portable_fingerprint is None
    assert item.image_reference == IMAGE_REFERENCE
    assert item.supports_jobs is True
    assert item.reason_code is None
    serialized = json.dumps(item.model_dump(mode="json"))
    assert "PILOT_TOKEN" not in serialized
    assert "environment_variables" not in serialized


@pytest.mark.asyncio
async def test_eligible_revisions_opens_private_templates_for_admins(db_session, admin_user):
    private_template, private_revision = await make_environment(
        db_session, name="Admin-only env", is_public=False
    )
    result = await BatchJobService(db_session).eligible_revisions(admin_user)
    assert private_revision.id in {item.revision_id for item in result.items}
    assert private_template.id in {item.environment_id for item in result.items}


@pytest.mark.asyncio
async def test_submit_persists_intent_snapshots_and_sanitized_detail(
    db_session, test_user, enabled_jobs
):
    template, revision, plan, volume = await make_resources(db_session, test_user)
    service = BatchJobService(db_session)
    detail = await service.submit(
        test_user,
        "submit-key-1",
        submit_request(revision, plan, volume),
    )

    assert detail.replayed is False
    assert detail.state == "queued"
    assert detail.reason_code == "waiting_capacity"
    assert detail.reason_message == "Waiting for capacity."
    assert detail.can_cancel is True
    assert detail.queue_expires_at is not None
    assert detail.environment.revision_id == revision.id
    assert detail.environment.environment_id == template.id
    assert detail.environment.image_reference == IMAGE_REFERENCE
    assert detail.plan.id == plan.id
    assert detail.plan.memory_mib == 2048
    assert detail.volume.id == volume.id
    assert detail.volume.available is True
    assert detail.argv == ["python", "/work/input.py"]
    assert detail.limits.max_runtime_seconds == 600
    assert detail.result is None
    assert detail.logs.state == "pending"
    assert detail.logs.size_bytes == 0
    assert detail.billing.mode == "zero_cost"
    assert detail.billing.charged == 0
    assert detail.billing.authorized == 0
    assert detail.billing.rate_per_hour == 0
    assert detail.billing.state == "none"
    serialized = json.dumps(detail.model_dump(mode="json"))
    assert "PILOT_TOKEN" not in serialized
    assert "must-not-leak" not in serialized

    stored = await db_session.get(BatchJob, detail.id, populate_existing=True)
    assert stored.user_id == test_user.id
    assert stored.state == "queued"
    assert stored.reservation_active is False
    assert stored.billing_mode == "zero_cost"
    assert stored.authorized_credits == 0
    assert stored.billing_rate_per_hour == 0
    assert stored.billing_state == "none"
    assert stored.revision_snapshot["configuration"]["environment_variables"] == {
        "PILOT_TOKEN": "must-not-leak"
    }
    assert stored.revision_snapshot["runtime_identity"]["verified_reference"] == IMAGE_REFERENCE
    assert stored.plan_snapshot["gpu_count"] == 0
    assert stored.fencing_token is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "code", "field"),
    [
        ({"name": "x" * 121}, "invalid_request", "name"),
        ({"name": "   "}, "invalid_request", "name"),
        ({"argv": []}, "invalid_request", "argv"),
        ({"argv": ["ok\x00bad"]}, "invalid_request", "argv"),
        ({"max_runtime_seconds": 59}, "runtime_too_long", "max_runtime_seconds"),
        ({"max_runtime_seconds": 7201}, "runtime_too_long", "max_runtime_seconds"),
    ],
)
async def test_submit_rejects_invalid_requests(
    db_session, test_user, enabled_jobs, overrides, code, field
):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    with pytest.raises(JobError) as exc:
        await BatchJobService(db_session).submit(
            test_user,
            "invalid-key",
            submit_request(revision, plan, volume, **overrides),
        )
    assert exc.value.code == code
    assert exc.value.field == field


@pytest.mark.asyncio
async def test_submit_rejects_oversized_argv(db_session, test_user, enabled_jobs):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    service = BatchJobService(db_session)

    with pytest.raises(JobError) as too_many:
        await service.submit(
            test_user,
            "argv-count",
            submit_request(
                revision,
                plan,
                volume,
                argv=["x"] * (settings.batch_jobs_max_argv_items + 1),
            ),
        )
    assert too_many.value.code == "argv_too_large"

    with pytest.raises(JobError) as too_large:
        await service.submit(
            test_user,
            "argv-bytes",
            submit_request(
                revision,
                plan,
                volume,
                argv=["x" * (settings.batch_jobs_max_input_bytes + 1)],
            ),
        )
    assert too_large.value.code == "argv_too_large"


@pytest.mark.asyncio
async def test_submit_rejects_invalid_idempotency_key(db_session, test_user, enabled_jobs):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    with pytest.raises(JobError) as exc:
        await BatchJobService(db_session).submit(
            test_user,
            "not visible\nascii",
            submit_request(revision, plan, volume),
        )
    assert exc.value.code == "invalid_request"
    assert exc.value.field == "Idempotency-Key"


@pytest.mark.asyncio
async def test_idempotent_replay_and_conflict(db_session, test_user, enabled_jobs):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    service = BatchJobService(db_session)
    request = submit_request(revision, plan, volume)

    first = await service.submit(test_user, "stable-key", request)
    replay = await service.submit(test_user, "stable-key", request)
    assert replay.replayed is True
    assert replay.id == first.id

    with pytest.raises(JobError) as conflict:
        await service.submit(
            test_user,
            "stable-key",
            submit_request(revision, plan, volume, name="Different request"),
        )
    assert conflict.value.code == "idempotency_conflict"
    assert conflict.value.status_code == 409
    assert (
        await db_session.scalar(select(BatchJob.id).where(BatchJob.user_id == test_user.id))
        == first.id
    )


@pytest.mark.asyncio
async def test_submit_enforces_queued_and_active_owner_limits(db_session, test_user, enabled_jobs):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    service = BatchJobService(db_session)
    submitted = [
        await service.submit(
            test_user,
            f"limit-key-{index}",
            submit_request(revision, plan, volume, name=f"Queued {index}"),
        )
        for index in range(settings.batch_jobs_max_queued_per_owner)
    ]

    with pytest.raises(JobError) as queued_limit:
        await service.submit(
            test_user,
            "limit-key-overflow",
            submit_request(revision, plan, volume, name="Overflow"),
        )
    assert queued_limit.value.code == "job_limit_reached"
    assert queued_limit.value.status_code == 429

    stored = await db_session.get(BatchJob, submitted[0].id, populate_existing=True)
    stored.state = "running"
    stored.started_at = utc_now()
    await db_session.commit()

    with pytest.raises(JobError) as active_limit:
        await service.submit(
            test_user,
            "limit-key-active",
            submit_request(revision, plan, volume, name="Blocked by active"),
        )
    assert active_limit.value.code == "job_limit_reached"


@pytest.mark.asyncio
async def test_nonzero_cost_plan_requires_paid_flag_and_creates_a_hold(
    db_session, test_user, enabled_jobs, monkeypatch
):
    _, revision, plan, volume = await make_resources(db_session, test_user, cost_per_hour=5)
    service = BatchJobService(db_session)

    monkeypatch.setattr(settings, "batch_jobs_allow_paid_plans", False)
    with pytest.raises(JobError) as exc:
        await service.submit(test_user, "paid-key-off", submit_request(revision, plan, volume))
    assert exc.value.code == "paid_plan_unsupported"
    assert exc.value.status_code == 422
    assert await db_session.scalar(select(BatchJob).where(BatchJob.user_id == test_user.id)) is None

    monkeypatch.setattr(settings, "batch_jobs_allow_paid_plans", True)
    detail = await service.submit(test_user, "paid-key-on", submit_request(revision, plan, volume))
    assert detail.billing.mode == "paid"
    assert detail.billing.authorized == 1
    assert detail.billing.rate_per_hour == 5
    assert detail.billing.state == "held"
    assert detail.billing.charged == 0


@pytest.mark.asyncio
async def test_submit_rejects_non_cpu_plan(db_session, test_user, enabled_jobs):
    _, revision, plan, volume = await make_resources(db_session, test_user, gpu_limit=1)
    with pytest.raises(JobError) as exc:
        await BatchJobService(db_session).submit(
            test_user,
            "gpu-plan",
            submit_request(revision, plan, volume),
        )
    assert exc.value.code == "plan_unavailable"


@pytest.mark.asyncio
async def test_submit_rejects_plan_not_marked_for_jobs(db_session, test_user, enabled_jobs):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    plan.allow_batch_jobs = False
    await db_session.flush()
    with pytest.raises(JobError) as exc:
        await BatchJobService(db_session).submit(
            test_user,
            "server-only-plan",
            submit_request(revision, plan, volume),
        )
    assert exc.value.code == "plan_unavailable"


@pytest.mark.asyncio
async def test_submit_rejects_foreign_and_missing_resources_identically(
    db_session, test_user, enabled_jobs
):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    foreign = User(
        username=f"foreign-{uuid.uuid4().hex[:8]}",
        email=f"foreign-{uuid.uuid4().hex[:8]}@example.test",
        role="user",
        is_active=True,
    )
    db_session.add(foreign)
    await db_session.flush()
    foreign_volume = await make_volume(db_session, foreign)
    _, foreign_revision = await make_environment(db_session, is_public=False)
    foreign_plan = await make_plan(db_session, is_public=False, visible_to_roles=[])
    service = BatchJobService(db_session)

    cases = [
        ({"volume_id": foreign_volume.id}, {"volume_id": uuid.uuid4()}, "volume_unavailable"),
        (
            {"revision_id": foreign_revision.id},
            {"revision_id": uuid.uuid4()},
            "revision_unavailable",
        ),
        ({"plan_id": foreign_plan.id}, {"plan_id": uuid.uuid4()}, "plan_unavailable"),
    ]
    for foreign_override, missing_override, code in cases:
        with pytest.raises(JobError) as foreign_error:
            await service.submit(
                test_user,
                f"foreign-{code}",
                submit_request(revision, plan, volume, **foreign_override),
            )
        with pytest.raises(JobError) as missing_error:
            await service.submit(
                test_user,
                f"missing-{code}",
                submit_request(revision, plan, volume, **missing_override),
            )
        assert foreign_error.value.code == code
        assert missing_error.value.code == code
        assert foreign_error.value.status_code == missing_error.value.status_code


@pytest.mark.asyncio
async def test_list_active_history_cursor_and_owner_scope(db_session, test_user, enabled_jobs):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    foreign = User(
        username=f"other-{uuid.uuid4().hex[:8]}",
        email=f"other-{uuid.uuid4().hex[:8]}@example.test",
        role="user",
        is_active=True,
    )
    db_session.add(foreign)
    await db_session.flush()
    foreign_volume = await make_volume(db_session, foreign)
    base = utc_now() - timedelta(minutes=10)
    owned = []
    for index in range(5):
        state = "queued" if index < 3 else "succeeded"
        job = stored_job(
            test_user,
            revision,
            plan,
            volume,
            created_at=base + timedelta(seconds=index),
            state=state,
            name=f"Owned {index}",
            outcome_code="succeeded" if state == "succeeded" else None,
        )
        db_session.add(job)
        owned.append(job)
    foreign_job = stored_job(
        foreign,
        revision,
        plan,
        foreign_volume,
        created_at=base + timedelta(minutes=1),
        name="Foreign",
    )
    db_session.add(foreign_job)
    await db_session.flush()

    service = BatchJobService(db_session)
    first_page = await service.list(test_user, limit=2)
    assert [item.name for item in first_page.items] == ["Owned 4", "Owned 3"]
    assert first_page.next_cursor is not None

    second_page = await service.list(test_user, limit=2, cursor=first_page.next_cursor)
    assert [item.name for item in second_page.items] == ["Owned 2", "Owned 1"]
    assert second_page.next_cursor is not None

    third_page = await service.list(test_user, limit=2, cursor=second_page.next_cursor)
    assert [item.name for item in third_page.items] == ["Owned 0"]
    assert third_page.next_cursor is None

    seen = [item.id for page in (first_page, second_page, third_page) for item in page.items]
    assert len(seen) == len(set(seen)) == 5
    assert foreign_job.id not in seen

    active = await service.list(test_user, state_filter="active", limit=100)
    assert {item.id for item in active.items} == {job.id for job in owned[:3]}
    history = await service.list(test_user, state_filter="history", limit=100)
    assert {item.id for item in history.items} == {job.id for job in owned[3:]}

    with pytest.raises(JobError) as invalid_state:
        await service.list(test_user, state_filter="bogus")
    assert invalid_state.value.code == "invalid_request"
    with pytest.raises(JobError) as invalid_cursor:
        await service.list(test_user, cursor="not-a-cursor")
    assert invalid_cursor.value.code == "invalid_request"


@pytest.mark.asyncio
async def test_get_and_cancel_are_owner_scoped(db_session, test_user, enabled_jobs):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    foreign = User(
        username=f"other-{uuid.uuid4().hex[:8]}",
        email=f"other-{uuid.uuid4().hex[:8]}@example.test",
        role="user",
        is_active=True,
    )
    db_session.add(foreign)
    await db_session.flush()
    foreign_volume = await make_volume(db_session, foreign)
    foreign_job = stored_job(
        foreign,
        revision,
        plan,
        foreign_volume,
        created_at=utc_now(),
        name="Foreign owned",
    )
    db_session.add(foreign_job)
    await db_session.flush()
    service = BatchJobService(db_session)

    with pytest.raises(JobError) as foreign_detail:
        await service.get(test_user, foreign_job.id)
    with pytest.raises(JobError) as missing_detail:
        await service.get(test_user, uuid.uuid4())
    assert foreign_detail.value.code == missing_detail.value.code == "job_not_found"
    assert foreign_detail.value.status_code == missing_detail.value.status_code == 404

    with pytest.raises(JobError) as foreign_cancel:
        await service.cancel(test_user, foreign_job.id)
    with pytest.raises(JobError) as missing_cancel:
        await service.cancel(test_user, uuid.uuid4())
    assert foreign_cancel.value.code == missing_cancel.value.code == "job_not_found"


@pytest.mark.asyncio
async def test_cancel_queued_running_recovery_and_terminal_states(
    db_session, test_user, enabled_jobs
):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    base = utc_now()
    queued = stored_job(test_user, revision, plan, volume, created_at=base, name="Queued to cancel")
    running = stored_job(
        test_user,
        revision,
        plan,
        volume,
        created_at=base + timedelta(seconds=1),
        state="running",
        name="Running to cancel",
        reason_code=None,
        started_at=base,
    )
    recovery = stored_job(
        test_user,
        revision,
        plan,
        volume,
        created_at=base + timedelta(seconds=2),
        state="recovery_required",
        name="Recovery job",
        reason_code="recovery_required",
    )
    succeeded = stored_job(
        test_user,
        revision,
        plan,
        volume,
        created_at=base + timedelta(seconds=3),
        state="succeeded",
        name="Terminal job",
        reason_code=None,
        outcome_code="succeeded",
        finished_at=base + timedelta(seconds=30),
    )
    db_session.add_all([queued, running, recovery, succeeded])
    await db_session.flush()
    service = BatchJobService(db_session)

    cancelled = await service.cancel(test_user, queued.id)
    assert cancelled.state == "cancelled"
    assert cancelled.result is not None
    assert cancelled.result.outcome_code == "cancelled"
    assert cancelled.result.exit_code is None
    assert cancelled.finished_at is not None
    assert cancelled.can_cancel is False
    first_finished = cancelled.finished_at
    again = await service.cancel(test_user, queued.id)
    assert again.state == "cancelled"
    assert again.finished_at == first_finished

    stopping = await service.cancel(test_user, running.id)
    assert stopping.state == "cancelling"
    assert stopping.can_cancel is False
    stored_running = await db_session.get(BatchJob, running.id, populate_existing=True)
    assert stored_running.stop_requested_at is not None
    again_running = await service.cancel(test_user, running.id)
    assert again_running.state == "cancelling"

    with pytest.raises(JobError) as not_cancellable:
        await service.cancel(test_user, recovery.id)
    assert not_cancellable.value.code == "job_not_cancellable"
    assert not_cancellable.value.status_code == 409

    terminal = await service.cancel(test_user, succeeded.id)
    assert terminal.state == "succeeded"
    assert terminal.result is not None
    assert terminal.result.outcome_code == "succeeded"


@pytest.mark.asyncio
async def test_log_states_pending_available_truncated_expired_and_unavailable(
    db_session, test_user, enabled_jobs, monkeypatch
):
    _, revision, plan, volume = await make_resources(db_session, test_user)
    base = utc_now()
    service = BatchJobService(db_session)

    pending = stored_job(test_user, revision, plan, volume, created_at=base, name="No payload yet")
    available = stored_job(
        test_user,
        revision,
        plan,
        volume,
        created_at=base + timedelta(seconds=1),
        name="Available log",
        log_state="available",
        log_size_bytes=5,
        log_expires_at=base + timedelta(days=7),
    )
    capped = stored_job(
        test_user,
        revision,
        plan,
        volume,
        created_at=base + timedelta(seconds=2),
        name="Capped log",
        log_state="truncated",
        log_truncated=True,
        log_size_bytes=8,
        log_expires_at=base + timedelta(days=7),
    )
    expired = stored_job(
        test_user,
        revision,
        plan,
        volume,
        created_at=base + timedelta(seconds=3),
        name="Expired log",
        log_state="available",
        log_size_bytes=5,
        log_expires_at=base - timedelta(seconds=1),
    )
    terminal = stored_job(
        test_user,
        revision,
        plan,
        volume,
        created_at=base + timedelta(seconds=4),
        state="failed",
        name="No retained log",
        reason_code=None,
        outcome_code="failed",
    )
    db_session.add_all([pending, available, capped, expired, terminal])
    await db_session.flush()
    db_session.add_all(
        [
            BatchJobLog(
                job_id=available.id,
                text="hello",
                encoding="utf-8",
                truncated=False,
                size_bytes=5,
                captured_at=base,
                expires_at=base + timedelta(days=7),
            ),
            BatchJobLog(
                job_id=capped.id,
                text="abcdefgh",
                encoding="utf-8",
                truncated=False,
                size_bytes=8,
                captured_at=base,
                expires_at=base + timedelta(days=7),
            ),
            BatchJobLog(
                job_id=expired.id,
                text="gone",
                encoding="utf-8",
                truncated=False,
                size_bytes=4,
                captured_at=base,
                expires_at=base - timedelta(seconds=1),
            ),
        ]
    )
    await db_session.flush()

    assert (await service.logs(test_user, pending.id)).state == "pending"
    available_log = await service.logs(test_user, available.id)
    assert available_log.state == "available"
    assert available_log.text == "hello"
    assert available_log.encoding == "utf-8"
    assert available_log.size_bytes == 5

    monkeypatch.setattr(settings, "batch_jobs_log_tail_bytes", 4)
    capped_log = await service.logs(test_user, capped.id)
    assert capped_log.state == "truncated"
    assert capped_log.text == "efgh"
    assert capped_log.truncated is True
    assert capped_log.size_bytes == 8

    expired_log = await service.logs(test_user, expired.id)
    assert expired_log.state == "expired"
    assert expired_log.text is None

    unavailable = await service.logs(test_user, terminal.id)
    assert unavailable.state == "unavailable"
    assert unavailable.text is None


def test_model_registration_and_migration_head():
    from app.models.credit_hold import CreditHold

    assert BatchJob.__tablename__ == "batch_jobs"
    assert BatchJobLog.__tablename__ == "batch_job_logs"
    assert CreditHold.__tablename__ == "credit_holds"
    assert "batch_jobs" in Base.metadata.tables
    assert "batch_job_logs" in Base.metadata.tables
    assert "credit_holds" in Base.metadata.tables

    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["a3b8c1d4e5f6"]
    assert script.get_revision("a3b8c1d4e5f6").down_revision == "f1a2b3c4d5e6"
    assert script.get_revision("f1a2b3c4d5e6").down_revision == "e2c7a9f4d6b1"
