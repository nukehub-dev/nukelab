# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Batch job admission: artifact proof, policy rechecks, reservation and guard."""

import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob, BatchJobLog
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.resource_quota import ResourceQuota
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.schemas.batch_job import BatchJobSubmitRequest
from app.schemas.environment_manifest import ImageIdentity
from app.services.batch_job_admission_service import (
    BatchJobAdmissionService,
    JobAdmission,
    JobAdmissionError,
)
from app.services.batch_job_service import BatchJobService, JobError
from app.services.operation_heartbeat import _TARGETS, operation_heartbeat
from app.services.quota_service import QuotaService
from app.services.resource_pool_service import ResourcePoolService
from tests.conftest import test_engine

IMAGE_ID = "sha256:" + "a" * 64
TOOLCHAIN_ID = "sha256:" + "b" * 64
OTHER_IMAGE_ID = "sha256:" + "d" * 64
VERIFIED_DIGEST = "sha256:" + "c" * 64
VERIFIED_REFERENCE = "registry.example.test/nukelab/runtime@" + VERIFIED_DIGEST


def local_identity(local_id=IMAGE_ID, requested="approved:latest"):
    return {
        "requested_reference": requested,
        "local_id": local_id,
        "repository_digests": [],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }


def verified_identity():
    return {
        **local_identity(),
        "repository_digests": [VERIFIED_REFERENCE],
        "registry_verified": True,
        "verified_reference": VERIFIED_REFERENCE,
        "manifest_digest": VERIFIED_DIGEST,
        "index_digest": None,
        "descriptor_media_type": "application/vnd.oci.image.manifest.v1+json",
    }


def configuration(*, toolchain=False):
    return {
        "image": "approved:latest",
        "tool_image": "toolchain:latest" if toolchain else None,
        "tool_mounts": ["/opt/nuke"] if toolchain else [],
        "environment_variables": {"PRIVATE_VALUE": "must-not-leak"},
        "packages": [],
        "volumes": [],
        "ports": [],
    }


def admission_driver(
    *,
    exists=True,
    resolved_runtime=None,
    resolved_toolchain=None,
    runtime_identity=None,
):
    runtime_identity = runtime_identity or local_identity()
    toolchain_identity = local_identity(TOOLCHAIN_ID, "toolchain:latest")
    resolved_runtime = resolved_runtime or runtime_identity
    resolved_toolchain = resolved_toolchain or toolchain_identity

    async def resolve(reference):
        if reference == TOOLCHAIN_ID:
            return resolved_toolchain
        if reference == IMAGE_ID:
            return resolved_runtime
        raise AssertionError(f"Unexpected image lookup: {reference}")

    return SimpleNamespace(
        image_exists=AsyncMock(return_value=exists),
        resolve_image=AsyncMock(side_effect=resolve),
        pull_image=AsyncMock(side_effect=AssertionError("must never pull a tag")),
    )


@pytest.fixture(autouse=True)
def admission_settings(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    monkeypatch.setattr(settings, "batch_jobs_allow_paid_plans", False)
    monkeypatch.setattr(settings, "batch_jobs_max_active_fleet", 5)
    monkeypatch.setattr(settings, "batch_jobs_max_active_per_owner", 1)


async def _make_resources(
    db,
    user,
    *,
    registry_verified=False,
    toolchain=False,
):
    marker = uuid.uuid4().hex[:12]
    plan = ServerPlan(
        name=f"admission-plan-{marker}",
        slug=f"admission-plan-{marker}",
        cpu_limit=1.0,
        memory_limit="1g",
        disk_limit="2g",
        gpu_limit=0,
        cost_per_hour=0,
        max_servers_per_user=10,
        is_active=True,
        is_public=True,
    )
    template = EnvironmentTemplate(
        name=f"admission-env-{marker}",
        slug=f"admission-env-{marker}",
        image="approved:latest",
        tool_image="toolchain:latest" if toolchain else None,
        tool_mounts=["/opt/nuke"] if toolchain else [],
        is_active=True,
        is_public=True,
    )
    db.add_all([plan, template])
    await db.flush()
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint=uuid.uuid4().hex * 2,
        template_fingerprint=uuid.uuid4().hex * 2,
        configuration=configuration(toolchain=toolchain),
        runtime_identity=verified_identity() if registry_verified else local_identity(),
        toolchain_identity=local_identity(TOOLCHAIN_ID, "toolchain:latest") if toolchain else None,
    )
    volume = Volume(
        name=f"admission-volume-{marker}",
        display_name="Admission data",
        owner_id=user.id,
        visibility="private",
        max_size_bytes=1024**3,
        status="active",
    )
    quota = ResourceQuota(
        user_id=user.id,
        max_cpu_total=8,
        max_memory_total="16g",
        max_disk_total="100g",
        max_gpu_total=0,
        max_servers_total=10,
    )
    db.add_all([revision, volume, quota])
    await db.flush()
    return SimpleNamespace(
        plan=plan,
        template=template,
        revision=revision,
        volume=volume,
        quota=quota,
    )


async def _make_job(
    db,
    user,
    *,
    registry_verified=False,
    toolchain=False,
    name="Admission job",
):
    resources = await _make_resources(
        db, user, registry_verified=registry_verified, toolchain=toolchain
    )
    request = BatchJobSubmitRequest(
        name=name,
        revision_id=resources.revision.id,
        plan_id=resources.plan.id,
        volume_id=resources.volume.id,
        argv=["python", "-c", "print('ok')"],
        max_runtime_seconds=600,
    )
    detail = await BatchJobService(db).submit(user, uuid.uuid4().hex, request)
    await db.commit()
    return SimpleNamespace(
        job_id=detail.id,
        owner_id=user.id,
        plan_id=resources.plan.id,
        revision_id=resources.revision.id,
        volume_id=resources.volume.id,
        template_id=resources.template.id,
        resources=resources,
    )


def _active_job(user_id, revision_id, *, plan_id=None, volume_id=None, cpu=1.0):
    now = utc_now()
    return BatchJob(
        user_id=user_id,
        name=f"active-{uuid.uuid4().hex[:8]}",
        idempotency_key_hash=uuid.uuid4().hex * 2,
        request_fingerprint=uuid.uuid4().hex * 2,
        revision_id=revision_id,
        plan_id=plan_id,
        volume_id=volume_id,
        argv=["true"],
        max_runtime_seconds=60,
        state="starting",
        state_changed_at=now,
        revision_snapshot={},
        plan_snapshot={},
        volume_snapshot={},
        reservation_active=True,
        reserved_cpu=cpu,
        reserved_memory_mib=1024,
        reserved_disk_mib=2048,
        fencing_token=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )


async def _load_job(job_id):
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        return await db.get(BatchJob, job_id)


async def _wait_job(job_id, predicate, *, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        job = await _load_job(job_id)
        if job is not None and predicate(job):
            return job
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Job heartbeat condition was not reached")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_admits_once_with_reservation_guard_and_proved_identity(db_session, test_user):
    fixture = await _make_job(db_session, test_user, toolchain=True)
    executor_id = uuid.uuid4()
    service = BatchJobAdmissionService(db_session, admission_driver())

    admission = await service.admit(fixture.job_id, executor_id=executor_id)

    assert isinstance(admission, JobAdmission)
    assert admission.job_id == fixture.job_id
    assert admission.owner_id == fixture.owner_id
    assert admission.revision_id == fixture.revision_id
    assert admission.plan_id == fixture.plan_id
    assert admission.volume_id == fixture.volume_id
    assert admission.container_name == f"nukelab-job-{fixture.job_id}"
    assert admission.image == IMAGE_ID
    assert admission.runtime_identity["local_id"] == IMAGE_ID
    assert admission.runtime_identity["image"] == IMAGE_ID
    assert admission.runtime_identity["spawn_reference"] == IMAGE_ID
    assert admission.runtime_identity["platform"]["os"] == "linux"
    assert admission.toolchain_identity["local_id"] == TOOLCHAIN_ID
    assert admission.toolchain_mounts == ["/opt/nuke"]
    assert admission.configuration["environment_variables"] == {"PRIVATE_VALUE": "must-not-leak"}
    assert admission.cpu == 1.0
    assert admission.memory_mib == 1024
    assert admission.disk_mib == 2048
    assert admission.max_runtime_seconds == 600

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "starting"
    assert job.reason_code is None
    assert job.reservation_active is True
    assert job.reserved_at is not None
    assert job.reserved_cpu == 1.0
    assert job.reserved_memory_mib == 1024
    assert job.reserved_disk_mib == 2048
    assert job.volume_operation_id == fixture.job_id
    assert job.volume_fencing_token == admission.volume_fencing_token
    assert job.fencing_token == admission.fencing_token
    assert job.runtime_identity["local_id"] == IMAGE_ID
    assert job.container_name == admission.container_name
    assert job.executor_id == executor_id
    assert job.heartbeat_at is not None
    assert job.state_changed_at is not None

    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == fixture.job_id)
    )
    assert guard.kind == "job_writer"
    assert guard.state == "reserved"
    assert guard.owner_id == fixture.owner_id
    assert guard.volume_id == fixture.volume_id
    assert guard.fencing_token == admission.volume_fencing_token

    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(VolumeOperation)
            .where(VolumeOperation.operation_id == fixture.job_id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_artifact_missing_fails_queued_without_guard(db_session, test_user):
    fixture = await _make_job(db_session, test_user)
    service = BatchJobAdmissionService(db_session, admission_driver(exists=False))

    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "failed"
    assert job.outcome_code == "failed"
    assert job.reason_code == "artifact_missing"
    assert job.proof_class == "artifact"
    assert job.finished_at is not None
    assert job.reservation_active is False
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(VolumeOperation)
            .where(VolumeOperation.operation_id == fixture.job_id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_local_identity_mismatch_fails_queued(db_session, test_user):
    fixture = await _make_job(db_session, test_user)
    driver = admission_driver(resolved_runtime=local_identity(OTHER_IMAGE_ID))
    service = BatchJobAdmissionService(db_session, driver)

    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "revision_unavailable"
    assert job.proof_class == "control_plane"
    assert job.reservation_active is False


@pytest.mark.asyncio
async def test_registry_verified_identity_is_proved_from_the_snapshot(db_session, test_user):
    fixture = await _make_job(db_session, test_user, registry_verified=True)
    identity = ImageIdentity.model_validate(verified_identity())
    artifacts = SimpleNamespace(ensure_local=AsyncMock(return_value=identity))
    driver = admission_driver()
    service = BatchJobAdmissionService(db_session, driver, artifacts=artifacts)

    admission = await service.admit(fixture.job_id, executor_id=uuid.uuid4())

    assert isinstance(admission, JobAdmission)
    artifacts.ensure_local.assert_awaited_once()
    verified = artifacts.ensure_local.await_args.args[0]
    assert verified.verified_reference == VERIFIED_REFERENCE
    assert verified.manifest_digest == VERIFIED_DIGEST
    assert admission.image == VERIFIED_REFERENCE
    assert admission.runtime_identity["registry_verified"] is True
    assert admission.runtime_identity["verified_reference"] == VERIFIED_REFERENCE
    driver.image_exists.assert_not_awaited()
    driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_expiry_terminalizes_without_reservation(db_session, test_user):
    fixture = await _make_job(db_session, test_user)
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    job.queue_expires_at = utc_now()
    await db_session.commit()

    service = BatchJobAdmissionService(db_session, admission_driver())
    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "expired"
    assert job.outcome_code == "expired"
    assert job.reason_code == "queue_expired"
    assert job.proof_class == "control_plane"
    assert job.finished_at is not None
    assert job.reservation_active is False
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(VolumeOperation)
            .where(VolumeOperation.operation_id == fixture.job_id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_revoked_revision_fails_queued(db_session, test_user):
    fixture = await _make_job(db_session, test_user)
    revision = await db_session.get(
        EnvironmentRevision, fixture.revision_id, populate_existing=True
    )
    revision.revoked = True
    await db_session.commit()

    service = BatchJobAdmissionService(db_session, admission_driver())
    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "revision_unavailable"
    assert job.proof_class == "control_plane"
    assert job.reservation_active is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("cpu_limit", 2.0),
        ("memory_limit", "2g"),
        ("disk_limit", "4g"),
        ("cost_per_hour", 1),
    ],
)
async def test_material_plan_edit_fails_queued(db_session, test_user, field, value):
    fixture = await _make_job(db_session, test_user)
    plan = await db_session.get(ServerPlan, fixture.plan_id, populate_existing=True)
    setattr(plan, field, value)
    await db_session.commit()

    service = BatchJobAdmissionService(db_session, admission_driver())
    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "plan_changed"
    assert job.proof_class == "control_plane"
    assert job.reservation_active is False


@pytest.mark.asyncio
async def test_nonzero_snapshot_cost_never_reserves(db_session, test_user):
    fixture = await _make_job(db_session, test_user)
    plan = await db_session.get(ServerPlan, fixture.plan_id, populate_existing=True)
    plan.cost_per_hour = 1
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    job.plan_snapshot = {**job.plan_snapshot, "cost_per_hour": 1}
    await db_session.commit()

    service = BatchJobAdmissionService(db_session, admission_driver())
    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "paid_plan_unsupported"
    assert job.proof_class == "control_plane"
    assert job.reservation_active is False
    assert job.charged_credits == 0
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(VolumeOperation)
            .where(VolumeOperation.operation_id == fixture.job_id)
        )
        == 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("toolchain", [False, True])
async def test_admission_persists_rehydration_snapshot_without_owner_exposure(
    db_session, test_user, toolchain
):
    fixture = await _make_job(db_session, test_user, toolchain=toolchain)
    service = BatchJobAdmissionService(db_session, admission_driver())
    admission = await service.admit(fixture.job_id, executor_id=uuid.uuid4())
    assert isinstance(admission, JobAdmission)

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    snapshot = job.revision_snapshot
    assert snapshot["revision_id"] == str(fixture.revision_id)
    assert snapshot["environment_id"] == str(fixture.template_id)
    assert snapshot["configuration"]["image"] == "approved:latest"
    assert snapshot["runtime_identity"]["local_id"] == IMAGE_ID
    assert snapshot["toolchain_mounts"] == (["/opt/nuke"] if toolchain else [])
    if toolchain:
        assert snapshot["toolchain_identity"]["local_id"] == TOOLCHAIN_ID
        assert snapshot["toolchain_identity"]["spawn_reference"] == TOOLCHAIN_ID
    else:
        assert snapshot["toolchain_identity"] is None
    assert snapshot["admitted_at"] is not None
    assert "T" in snapshot["admitted_at"]

    detail = await BatchJobService(db_session).get(test_user, fixture.job_id)
    serialized = detail.model_dump_json()
    assert "toolchain_identity" not in serialized
    assert "toolchain_mounts" not in serialized
    assert "admitted_at" not in serialized


@pytest.mark.asyncio
async def test_release_terminal_commits_result_log_and_guard_atomically(db_session, test_user):
    fixture = await _make_job(db_session, test_user)
    service = BatchJobAdmissionService(db_session, admission_driver())
    admission = await service.admit(fixture.job_id, executor_id=uuid.uuid4())
    assert isinstance(admission, JobAdmission)

    started = utc_now() - timedelta(seconds=30)
    finished = utc_now()
    expires = finished + timedelta(days=2)
    observed = {**admission.runtime_identity, "container_id": "container-1"}
    released = await service.release_terminal(
        fixture.job_id,
        fencing_token=admission.fencing_token,
        state="succeeded",
        outcome_code="succeeded",
        proof_class="observed",
        exit_code=0,
        started_at=started,
        finished_at=finished,
        log_state="available",
        log_text="hello\nworld",
        log_truncated=False,
        log_size_bytes=11,
        log_expires_at=expires,
        observed_runtime_identity=observed,
        executor_terminated=True,
    )

    assert released is not None
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "succeeded"
    assert job.outcome_code == "succeeded"
    assert job.proof_class == "observed"
    assert job.exit_code == 0
    assert job.started_at == started
    assert job.finished_at == finished
    assert job.runtime_identity == observed
    assert job.reservation_active is False
    assert job.log_state == "available"
    assert job.log_truncated is False
    assert job.log_size_bytes == 11
    assert job.log_expires_at == expires

    payload = await db_session.get(BatchJobLog, fixture.job_id, populate_existing=True)
    assert payload is not None
    assert payload.text == "hello\nworld"
    assert payload.encoding == "utf-8"
    assert payload.truncated is False
    assert payload.size_bytes == 11
    assert payload.expires_at == expires
    assert payload.captured_at is not None

    guard = await db_session.scalar(
        select(VolumeOperation)
        .where(VolumeOperation.operation_id == fixture.job_id)
        .execution_options(populate_existing=True)
    )
    assert guard.state == "succeeded"
    assert guard.completed_at is not None


@pytest.mark.asyncio
async def test_release_terminal_replay_preserves_recorded_result_and_log(db_session, test_user):
    fixture = await _make_job(db_session, test_user)
    service = BatchJobAdmissionService(db_session, admission_driver())
    admission = await service.admit(fixture.job_id, executor_id=uuid.uuid4())
    assert isinstance(admission, JobAdmission)

    first = await service.release_terminal(
        fixture.job_id,
        fencing_token=admission.fencing_token,
        state="succeeded",
        outcome_code="succeeded",
        proof_class="observed",
        exit_code=0,
        log_state="available",
        log_text="first log",
        executor_terminated=True,
    )
    assert first is not None
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    recorded_finished = job.finished_at
    payload = await db_session.get(BatchJobLog, fixture.job_id, populate_existing=True)
    recorded_text = payload.text
    recorded_captured = payload.captured_at

    replay = await service.release_terminal(
        fixture.job_id,
        fencing_token=admission.fencing_token,
        state="failed",
        outcome_code="failed",
        reason_code="must_not_replace",
        proof_class="observed",
        exit_code=99,
        log_state="available",
        log_text="second log",
        executor_terminated=True,
    )

    assert replay is not None
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "succeeded"
    assert job.outcome_code == "succeeded"
    assert job.reason_code is None
    assert job.exit_code == 0
    assert job.finished_at == recorded_finished
    payload = await db_session.get(BatchJobLog, fixture.job_id, populate_existing=True)
    assert payload.text == recorded_text == "first log"
    assert payload.captured_at == recorded_captured
    guard = await db_session.scalar(
        select(VolumeOperation)
        .where(VolumeOperation.operation_id == fixture.job_id)
        .execution_options(populate_existing=True)
    )
    assert guard.state == "succeeded"


@pytest.mark.asyncio
async def test_release_terminal_bounds_log_payload(db_session, test_user, monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_log_tail_bytes", 8)
    fixture = await _make_job(db_session, test_user)
    service = BatchJobAdmissionService(db_session, admission_driver())
    admission = await service.admit(fixture.job_id, executor_id=uuid.uuid4())
    assert isinstance(admission, JobAdmission)

    await service.release_terminal(
        fixture.job_id,
        fencing_token=admission.fencing_token,
        state="failed",
        outcome_code="failed",
        proof_class="observed",
        exit_code=1,
        log_state="available",
        log_text="0123456789",
        executor_terminated=True,
    )

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    payload = await db_session.get(BatchJobLog, fixture.job_id, populate_existing=True)
    assert payload.text == "23456789"
    assert payload.truncated is True
    assert payload.size_bytes == 10
    assert job.log_truncated is True
    assert job.log_size_bytes == 10


@pytest.mark.asyncio
async def test_busy_volume_waits_then_admits_after_release(db_session, test_user):
    fixture = await _make_job(db_session, test_user)
    blocker = VolumeOperation(
        operation_id=uuid.uuid4(),
        volume_id=fixture.volume_id,
        owner_id=fixture.owner_id,
        kind="mount",
        state="reserved",
        fencing_token=uuid.uuid4(),
    )
    db_session.add(blocker)
    await db_session.commit()

    service = BatchJobAdmissionService(db_session, admission_driver())
    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "queued"
    assert job.reason_code == "volume_busy"
    assert job.reservation_active is False
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(VolumeOperation)
            .where(
                VolumeOperation.operation_id == fixture.job_id,
                VolumeOperation.kind == "job_writer",
            )
        )
        == 0
    )

    await db_session.delete(blocker)
    await db_session.commit()
    admission = await service.admit(fixture.job_id, executor_id=uuid.uuid4())
    assert isinstance(admission, JobAdmission)


@pytest.mark.asyncio
async def test_capacity_wait_keeps_job_queued(db_session, test_user, monkeypatch):
    fixture = await _make_job(db_session, test_user)
    monkeypatch.setattr(settings, "resource_pool_cpu", 0.5)
    service = BatchJobAdmissionService(db_session, admission_driver())

    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "queued"
    assert job.reason_code == "waiting_capacity"
    assert job.reservation_active is False

    monkeypatch.setattr(settings, "resource_pool_cpu", 34.0)
    assert isinstance(await service.admit(fixture.job_id, executor_id=uuid.uuid4()), JobAdmission)


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", ["owner", "fleet"])
async def test_owner_and_fleet_active_caps_wait(db_session, test_user, monkeypatch, cap):
    fixture = await _make_job(db_session, test_user)
    if cap == "owner":
        monkeypatch.setattr(settings, "batch_jobs_max_active_per_owner", 1)
        owner_id = test_user.id
    else:
        monkeypatch.setattr(settings, "batch_jobs_max_active_fleet", 1)
        owner_id = uuid.uuid4()
        db_session.add(
            User(
                id=owner_id,
                username=f"fleet-{uuid.uuid4().hex[:12]}",
                email=f"fleet-{uuid.uuid4().hex[:12]}@example.test",
                role="user",
                is_active=True,
            )
        )
        await db_session.flush()
    db_session.add(_active_job(owner_id, fixture.revision_id))
    await db_session.commit()

    service = BatchJobAdmissionService(db_session, admission_driver())
    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "queued"
    assert job.reason_code == "waiting_capacity"
    assert job.reservation_active is False


@pytest.mark.asyncio
async def test_quota_denial_fails_queued(db_session, test_user):
    fixture = await _make_job(db_session, test_user)
    quota = await db_session.get(ResourceQuota, fixture.resources.quota.id, populate_existing=True)
    quota.max_cpu_total = 0.5
    await db_session.commit()

    service = BatchJobAdmissionService(db_session, admission_driver())
    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "quota_exceeded"
    assert job.proof_class == "control_plane"
    assert job.reservation_active is False
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(VolumeOperation)
            .where(VolumeOperation.operation_id == fixture.job_id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_recovery_required_retains_counts_until_proven_release(db_session, test_user):
    user_id = test_user.id
    fixture = await _make_job(db_session, test_user)
    service = BatchJobAdmissionService(db_session, admission_driver())
    admission = await service.admit(fixture.job_id, executor_id=uuid.uuid4())
    assert isinstance(admission, JobAdmission)

    assert await service.mark_recovery_required(
        fixture.job_id,
        fencing_token=admission.fencing_token,
        executor_id=uuid.uuid4(),
        reason_code="runtime_unverifiable",
    )
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "recovery_required"
    assert job.reservation_active is True
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == fixture.job_id)
    )
    assert guard.state == "reserved"

    pool = ResourcePoolService(db_session)
    allocated = await pool._get_allocated_resources()
    assert allocated["cpu"] == 1.0
    assert allocated["memory_mb"] == 1024
    assert allocated["disk_mb"] == 2048
    quota = await QuotaService(db_session).recalculate_usage(str(user_id), commit=False)
    assert quota.usage_cpu == 1.0
    assert quota.usage_memory_mb == 1024
    assert quota.usage_servers == 1
    await db_session.commit()

    with pytest.raises(JobAdmissionError, match="executor_unconfirmed"):
        await service.release_terminal(
            fixture.job_id,
            fencing_token=admission.fencing_token,
            state="succeeded",
            outcome_code="succeeded",
            proof_class="observed",
            exit_code=0,
            log_state="available",
            log_text="must-not-persist",
            executor_terminated=False,
        )
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "recovery_required"
    assert job.reservation_active is True
    assert job.log_state == "pending"
    assert await db_session.get(BatchJobLog, fixture.job_id) is None
    guard = await db_session.scalar(
        select(VolumeOperation)
        .where(VolumeOperation.operation_id == fixture.job_id)
        .execution_options(populate_existing=True)
    )
    assert guard.state == "reserved"

    released = await service.release_terminal(
        fixture.job_id,
        fencing_token=admission.fencing_token,
        state="succeeded",
        outcome_code="succeeded",
        proof_class="observed",
        exit_code=0,
        executor_terminated=True,
    )
    assert released is not None
    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "succeeded"
    assert job.outcome_code == "succeeded"
    assert job.reservation_active is False
    assert job.finished_at is not None
    guard = await db_session.scalar(
        select(VolumeOperation)
        .where(VolumeOperation.operation_id == fixture.job_id)
        .execution_options(populate_existing=True)
    )
    assert guard.state == "succeeded"
    assert guard.completed_at is not None
    allocated = await ResourcePoolService(db_session)._get_allocated_resources()
    assert allocated["cpu"] == 0
    assert allocated["memory_mb"] == 0
    assert allocated["disk_mb"] == 0
    quota = await QuotaService(db_session).recalculate_usage(str(user_id), commit=False)
    assert quota.usage_cpu == 0
    assert quota.usage_memory_mb == 0
    assert quota.usage_servers == 0


def test_heartbeat_targets_cover_existing_states_and_job_active_states():
    assert _TARGETS["launch"].active_states == ("executing",)
    assert _TARGETS["backup"].active_states == ("in_progress",)
    assert _TARGETS["restore"].active_states == ("in_progress",)
    assert set(_TARGETS["job"].active_states) == {"starting", "running", "cancelling"}
    assert "queued" not in _TARGETS["job"].active_states
    assert "recovery_required" not in _TARGETS["job"].active_states


@pytest.mark.asyncio
async def test_capabilities_and_cohort_parsing(db_session, test_user, monkeypatch):
    service = BatchJobService(db_session)
    other_id = uuid.uuid4()
    monkeypatch.setattr(
        settings,
        "batch_jobs_allowed_user_ids",
        f" {other_id}, not-a-uuid, {test_user.id} , {test_user.id} ",
    )
    assert settings.batch_jobs_allowed_user_id_set == {other_id, test_user.id}
    allowed = await service.capabilities(test_user)
    assert allowed.can_submit is True
    assert allowed.reason_code is None

    monkeypatch.setattr(settings, "batch_jobs_allowed_user_ids", str(uuid.uuid4()))
    denied = await service.capabilities(test_user)
    assert denied.enabled is True
    assert denied.can_submit is False
    assert denied.reason_code == "cohort_not_allowed"

    monkeypatch.setattr(settings, "batch_jobs_allowed_user_ids", "")
    permissive = await service.capabilities(test_user)
    assert permissive.can_submit is True
    assert permissive.reason_code is None


@pytest.mark.asyncio
async def test_submit_rejects_user_outside_cohort_without_creating_a_job(
    db_session, test_user, monkeypatch
):
    resources = await _make_resources(db_session, test_user)
    request = BatchJobSubmitRequest(
        name="cohort job",
        revision_id=resources.revision.id,
        plan_id=resources.plan.id,
        volume_id=resources.volume.id,
        argv=["true"],
        max_runtime_seconds=300,
    )
    monkeypatch.setattr(settings, "batch_jobs_allowed_user_ids", str(uuid.uuid4()))

    with pytest.raises(JobError) as failure:
        await BatchJobService(db_session).submit(test_user, uuid.uuid4().hex, request)

    assert failure.value.code == "cohort_not_allowed"
    assert failure.value.status_code == 403
    assert (
        await db_session.scalar(
            select(func.count()).select_from(BatchJob).where(BatchJob.user_id == test_user.id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_admission_fails_queued_owner_removed_from_cohort(db_session, test_user, monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_allowed_user_ids", str(test_user.id))
    fixture = await _make_job(db_session, test_user)
    monkeypatch.setattr(settings, "batch_jobs_allowed_user_ids", str(uuid.uuid4()))

    service = BatchJobAdmissionService(db_session, admission_driver())
    assert await service.admit(fixture.job_id, executor_id=uuid.uuid4()) is None

    job = await db_session.get(BatchJob, fixture.job_id, populate_existing=True)
    assert job.state == "failed"
    assert job.reason_code == "cohort_not_allowed"
    assert job.proof_class == "control_plane"
    assert job.reservation_active is False
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(VolumeOperation)
            .where(VolumeOperation.operation_id == fixture.job_id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_owner_outside_cohort_can_still_read_and_cancel_existing_job(
    db_session, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "batch_jobs_allowed_user_ids", str(test_user.id))
    fixture = await _make_job(db_session, test_user)
    monkeypatch.setattr(settings, "batch_jobs_allowed_user_ids", str(uuid.uuid4()))

    service = BatchJobService(db_session)
    detail = await service.get(test_user, fixture.job_id)
    assert detail.id == fixture.job_id
    cancelled = await service.cancel(test_user, fixture.job_id)
    assert cancelled.state == "cancelled"
    assert cancelled.reason_code == "request_cancelled"


@pytest_asyncio.fixture
async def committed_job_fixture():
    """Commit unique resources so independent admission sessions can race."""
    marker = uuid.uuid4().hex
    owner_id = uuid.uuid4()
    async with AsyncSession(test_engine, expire_on_commit=False) as db, db.begin():
        owner = User(
            id=owner_id,
            username=f"job_{marker}",
            email=f"{marker}@example.test",
            role="user",
            is_active=True,
            nuke_balance=100,
        )
        db.add(owner)
        await db.flush()
        resources = await _make_resources(db, owner)
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        detail = await BatchJobService(db).submit(
            await db.get(User, owner_id),
            uuid.uuid4().hex,
            BatchJobSubmitRequest(
                name=f"race-{marker}",
                revision_id=resources.revision.id,
                plan_id=resources.plan.id,
                volume_id=resources.volume.id,
                argv=["true"],
                max_runtime_seconds=300,
            ),
        )
    try:
        yield SimpleNamespace(
            job_id=detail.id,
            owner_id=owner_id,
            plan_id=resources.plan.id,
            revision_id=resources.revision.id,
            volume_id=resources.volume.id,
            template_id=resources.template.id,
        )
    finally:
        async with AsyncSession(test_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                delete(VolumeOperation).where(VolumeOperation.owner_id == owner_id)
            )
            await cleanup.execute(delete(BatchJob).where(BatchJob.user_id == owner_id))
            await cleanup.execute(delete(Volume).where(Volume.owner_id == owner_id))
            await cleanup.execute(delete(ResourceQuota).where(ResourceQuota.user_id == owner_id))
            await cleanup.execute(
                delete(EnvironmentRevision).where(
                    EnvironmentRevision.template_id == resources.template.id
                )
            )
            await cleanup.execute(
                delete(EnvironmentTemplate).where(EnvironmentTemplate.id == resources.template.id)
            )
            await cleanup.execute(delete(ServerPlan).where(ServerPlan.id == resources.plan.id))
            await cleanup.execute(delete(User).where(User.id == owner_id))


@pytest.mark.asyncio
async def test_independent_admission_sessions_grant_one_reservation(committed_job_fixture):
    fixture = committed_job_fixture
    barrier = asyncio.Barrier(2)

    async def admit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return await BatchJobAdmissionService(db, admission_driver()).admit(
                fixture.job_id, executor_id=uuid.uuid4()
            )

    results = await asyncio.wait_for(
        asyncio.gather(admit(), admit()),
        timeout=10,
    )
    assert sum(isinstance(result, JobAdmission) for result in results) == 1
    assert sum(result is None for result in results) == 1
    async with AsyncSession(test_engine) as verify:
        job = await verify.get(BatchJob, fixture.job_id, populate_existing=True)
        assert job.state == "starting"
        assert job.reservation_active is True
        guards = (
            await verify.scalars(
                select(VolumeOperation).where(VolumeOperation.operation_id == fixture.job_id)
            )
        ).all()
        assert len(guards) == 1
        assert guards[0].kind == "job_writer"
        assert guards[0].state == "reserved"


@pytest.mark.asyncio
async def test_admission_commits_once_after_the_critical_section(committed_job_fixture):
    fixture = committed_job_fixture
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        original_commit = db.commit
        commits = []

        async def counted_commit():
            commits.append(True)
            await original_commit()

        with patch.object(db, "commit", counted_commit):
            admission = await BatchJobAdmissionService(db, admission_driver()).admit(
                fixture.job_id, executor_id=uuid.uuid4()
            )
        assert isinstance(admission, JobAdmission)
        assert len(commits) == 1


@pytest.mark.asyncio
async def test_queued_cancel_before_admission_prevents_start(committed_job_fixture):
    fixture = committed_job_fixture
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        user = await db.get(User, fixture.owner_id)
        cancelled = await BatchJobService(db).cancel(user, fixture.job_id)
    assert cancelled.state == "cancelled"

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        admission = await BatchJobAdmissionService(db, admission_driver()).admit(
            fixture.job_id, executor_id=uuid.uuid4()
        )
    assert admission is None
    async with AsyncSession(test_engine) as verify:
        job = await verify.get(BatchJob, fixture.job_id, populate_existing=True)
        assert job.state == "cancelled"
        assert job.reservation_active is False
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(VolumeOperation)
                .where(VolumeOperation.operation_id == fixture.job_id)
            )
            == 0
        )


@pytest.mark.asyncio
async def test_admission_starting_then_cancel_sets_cancelling_and_keeps_guard(
    committed_job_fixture, monkeypatch
):
    fixture = committed_job_fixture
    entered = asyncio.Event()
    release = asyncio.Event()
    original_can_fit = ResourcePoolService.can_fit_resources

    async def gated_can_fit(self, *args, **kwargs):
        entered.set()
        await release.wait()
        return await original_can_fit(self, *args, **kwargs)

    monkeypatch.setattr(ResourcePoolService, "can_fit_resources", gated_can_fit)

    async def admit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            return await BatchJobAdmissionService(db, admission_driver()).admit(
                fixture.job_id, executor_id=uuid.uuid4()
            )

    async def cancel():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            user = await db.get(User, fixture.owner_id)
            await asyncio.sleep(0.05)
            return await BatchJobService(db).cancel(user, fixture.job_id)

    admit_task = asyncio.create_task(admit())
    await asyncio.wait_for(entered.wait(), timeout=5)
    cancel_task = asyncio.create_task(cancel())
    await asyncio.sleep(0.05)
    release.set()
    admission, cancelled = await asyncio.wait_for(
        asyncio.gather(admit_task, cancel_task), timeout=10
    )

    assert isinstance(admission, JobAdmission)
    assert cancelled.state == "cancelling"
    async with AsyncSession(test_engine) as verify:
        job = await verify.get(BatchJob, fixture.job_id, populate_existing=True)
        assert job.state == "cancelling"
        assert job.reservation_active is True
        assert job.stop_requested_at is not None
        guards = (
            await verify.scalars(
                select(VolumeOperation).where(VolumeOperation.operation_id == fixture.job_id)
            )
        ).all()
        assert len(guards) == 1
        assert guards[0].kind == "job_writer"
        assert guards[0].state == "reserved"


@pytest.mark.asyncio
async def test_job_heartbeat_refreshes_starting_and_stops_on_recovery(committed_job_fixture):
    fixture = committed_job_fixture
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with AsyncSession(test_engine) as db:
        admission = await BatchJobAdmissionService(db, admission_driver()).admit(
            fixture.job_id, executor_id=uuid.uuid4()
        )
    assert isinstance(admission, JobAdmission)
    executor_id = uuid.uuid4()

    async with operation_heartbeat(
        session_factory,
        kind="job",
        operation_id=fixture.job_id,
        fencing_token=admission.fencing_token,
        executor_id=executor_id,
        interval=0.05,
    ):
        first = await _wait_job(
            fixture.job_id,
            lambda row: row.executor_id == executor_id and row.heartbeat_at is not None,
        )
        await _wait_job(fixture.job_id, lambda row: row.heartbeat_at > first.heartbeat_at)
        async with AsyncSession(test_engine) as db, db.begin():
            job = await db.get(
                BatchJob,
                fixture.job_id,
                populate_existing=True,
                with_for_update=True,
            )
            job.state = "recovery_required"
        await asyncio.sleep(0.2)
        stopped = await _load_job(fixture.job_id)

    assert stopped.state == "recovery_required"
    assert stopped.executor_id == executor_id
    heartbeat_at = stopped.heartbeat_at
    await asyncio.sleep(0.15)
    assert (await _load_job(fixture.job_id)).heartbeat_at == heartbeat_at
