# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Batch job runtime checkpoints: create, start, adoption and cancellation."""

import copy
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver, ContainerDriverError
from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.resource_quota import ResourceQuota
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.schemas.batch_job import BatchJobSubmitRequest
from app.services.batch_job_admission_service import BatchJobAdmissionService, JobAdmission
from app.services.batch_job_finalizer import BatchJobFinalizer
from app.services.batch_job_runtime import (
    BatchJobRuntimeService,
    capture_tail,
    container_status,
    sanitize_environment,
    validate_job_container,
)
from app.services.batch_job_service import BatchJobService
from tests.conftest import test_engine
from tests.services.test_batch_job_admission import (
    IMAGE_ID,
    TOOLCHAIN_ID,
    _make_resources,
)

JOB_IMAGE_ID = IMAGE_ID
TOOLCHAIN_IMAGE_ID = TOOLCHAIN_ID


def make_driver(*, toolchain=False, runtime_identity=None, toolchain_identity=None):
    return BatchJobDriver(
        toolchain=toolchain,
        runtime_identity=runtime_identity,
        toolchain_identity=toolchain_identity,
    )


def runtime_identity():
    return {
        "requested_reference": "approved:latest",
        "local_id": JOB_IMAGE_ID,
        "repository_digests": [],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }


def toolchain_identity():
    return {
        "requested_reference": "toolchain:latest",
        "local_id": TOOLCHAIN_IMAGE_ID,
        "repository_digests": [],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }


def iso(value):
    return None if value is None else value.replace(tzinfo=None).isoformat() + "Z"


def container_info(
    *,
    job_id,
    fencing_token,
    container_name=None,
    container_id="job-container",
    status="running",
    exit_code=None,
    oom_killed=False,
    started_at=None,
    finished_at=None,
    image=JOB_IMAGE_ID,
    labels=None,
):
    label_set = {
        "nukelab.managed": "true",
        "nukelab.workload": "job",
        "nukelab.job.id": str(job_id),
        "nukelab.job.fence": str(fencing_token),
    }
    if labels:
        label_set.update(labels)
    state = {
        "Status": status,
        "Running": status == "running",
        "StartedAt": iso(started_at) if started_at else "0001-01-01T00:00:00Z",
        "FinishedAt": iso(finished_at) if finished_at else "0001-01-01T00:00:00Z",
        "ExitCode": exit_code,
        "OOMKilled": oom_killed,
    }
    return {
        "Id": container_id,
        "Name": f"/{container_name or f'nukelab-job-{job_id}'}",
        "Image": image,
        "Config": {"Labels": label_set},
        "State": state,
    }


class BatchJobDriver:
    """Fake daemon implementing the admission and headless batch methods."""

    immutable_toolchain_cache_name = staticmethod(ContainerDriver.immutable_toolchain_cache_name)

    def __init__(
        self,
        *,
        toolchain=False,
        runtime_identity=None,
        toolchain_identity=None,
    ):
        self.toolchain = toolchain
        self.runtime_identity = runtime_identity or globals()["runtime_identity"]()
        self.toolchain_identity = toolchain_identity or globals()["toolchain_identity"]()
        self.containers: dict[str, dict] = {}
        self.names: dict[str, str] = {}
        self.created: list[dict] = []
        self.started: list[str] = []
        self.stopped: list[tuple[str, int]] = []
        self.deleted: list[tuple[str, bool]] = []
        self.prepared: list[dict] = []
        self.toolchain_calls: list[tuple[str, str, list[str]]] = []
        self.image_env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/root"}
        self.image_env_by_image: dict[str, dict[str, str]] = {}
        self.image_env_calls: list[str] = []
        self.logs = "job output"
        self.log_error: BaseException | None = None
        self.prepare_error: BaseException | None = None
        self.toolchain_error: BaseException | None = None
        self.volume_missing = False
        self.volume_error: BaseException | None = None
        self.create_side_effect = None
        self.start_side_effect = None
        self.stop_side_effect = None
        self.delete_side_effect = None
        self.on_create = None
        self.on_start = None
        self._counter = 0

    async def image_exists(self, image):
        return True

    async def resolve_image(self, image):
        if self.toolchain and image == self.toolchain_identity["local_id"]:
            return copy.deepcopy(self.toolchain_identity)
        if image == self.runtime_identity["local_id"]:
            return copy.deepcopy(self.runtime_identity)
        raise AssertionError(f"unexpected image resolution: {image}")

    async def pull_image(self, image):
        raise AssertionError("immutable admission must never pull a mutable tag")

    async def get_volume(self, name):
        if self.volume_error is not None:
            raise self.volume_error
        return None if self.volume_missing else {"Name": name}

    async def prepare_batch_volume(self, *, name, image, volume, labels, timeout_seconds=30):
        self.prepared.append(
            {
                "name": name,
                "image": image,
                "volume": volume,
                "labels": labels,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.prepare_error is not None:
            raise self.prepare_error

    async def prepare_immutable_toolchain_volume(self, image, cache_name, mount_paths):
        self.toolchain_calls.append((image, cache_name, list(mount_paths)))
        if self.toolchain_error is not None:
            raise self.toolchain_error
        return {
            "mounts": list(mount_paths),
            "env": {"TOOLCHAIN_ENV": "enabled", "PATH_EXTRA": "${PATH}"},
            "env_prepend": {"PATH": "/opt/nuke/bin"},
        }

    async def get_image_env(self, image):
        self.image_env_calls.append(image)
        return dict(self.image_env_by_image.get(image, self.image_env))

    async def create_batch_container(
        self,
        *,
        name,
        image,
        argv,
        mounts,
        labels,
        limits,
        env,
        workdir="/work",
        timeout_seconds=None,
    ):
        if self.on_create is not None:
            await self.on_create()
        if self.create_side_effect is not None:
            result = self.create_side_effect
            if callable(result):
                result = await result()
            if isinstance(result, BaseException):
                raise result
        self._counter += 1
        container_id = f"created-{self._counter}"
        self.created.append(
            {
                "name": name,
                "image": image,
                "argv": list(argv),
                "mounts": copy.deepcopy(mounts),
                "labels": dict(labels),
                "limits": copy.deepcopy(limits),
                "env": dict(env),
                "workdir": workdir,
                "timeout_seconds": timeout_seconds,
            }
        )
        self.names[name] = container_id
        self.containers[container_id] = container_info(
            job_id=labels["nukelab.job.id"],
            fencing_token=labels["nukelab.job.fence"],
            container_name=name,
            container_id=container_id,
            status="created",
            image=image,
        )
        return container_id

    async def get_container_by_name(self, name):
        return self.names.get(name)

    async def get_container_info(self, container_id):
        info = self.containers.get(container_id)
        if info is None:
            raise ContainerDriverError("not found", status=404)
        return copy.deepcopy(info)

    async def start_container(self, container_id):
        if self.on_start is not None:
            await self.on_start()
        if self.start_side_effect is not None:
            result = self.start_side_effect
            if callable(result):
                result = await result()
            if isinstance(result, BaseException):
                raise result
        self.started.append(container_id)
        info = self.containers[container_id]
        info["State"].update(
            {
                "Status": "running",
                "Running": True,
                "StartedAt": iso(utc_now()),
            }
        )

    async def stop_container(self, container_id, timeout=30):
        self.stopped.append((container_id, timeout))
        if self.stop_side_effect is not None:
            result = self.stop_side_effect
            if callable(result):
                result = await result()
            if isinstance(result, BaseException):
                raise result
        info = self.containers.get(container_id)
        if info is None:
            raise ContainerDriverError("not found", status=404)
        if not info["State"]["Running"]:
            raise ContainerDriverError("not modified", status=304)
        info["State"].update(
            {
                "Status": "exited",
                "Running": False,
                "ExitCode": 143,
                "FinishedAt": iso(utc_now()),
            }
        )

    async def delete_container(self, container_id, force=True):
        self.deleted.append((container_id, force))
        if self.delete_side_effect is not None:
            result = self.delete_side_effect
            if callable(result):
                result = await result()
            if isinstance(result, BaseException):
                raise result
        info = self.containers.pop(container_id, None)
        if info is None:
            raise ContainerDriverError("not found", status=404)
        name = info["Name"].lstrip("/")
        self.names.pop(name, None)

    async def get_container_logs(self, container_id, tail=100, **kwargs):
        if self.log_error is not None:
            raise self.log_error
        return self.logs

    def add_job_container(self, job, **changes):
        container_id = changes.pop("container_id", "job-container")
        info = container_info(
            job_id=job.id,
            fencing_token=job.fencing_token,
            container_name=job.container_name,
            container_id=container_id,
            **changes,
        )
        self.containers[container_id] = info
        if job.container_name:
            self.names[job.container_name] = container_id
        return container_id


@pytest.fixture(autouse=True)
def batch_settings(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    monkeypatch.setattr(settings, "batch_jobs_allow_paid_plans", False)
    monkeypatch.setattr(settings, "batch_jobs_max_active_fleet", 5)
    monkeypatch.setattr(settings, "batch_jobs_max_active_per_owner", 10)


async def cleanup_owner(owner_id):
    async with AsyncSession(test_engine) as cleanup, cleanup.begin():
        await cleanup.execute(delete(VolumeOperation).where(VolumeOperation.owner_id == owner_id))
        await cleanup.execute(delete(BatchJob).where(BatchJob.user_id == owner_id))
        await cleanup.execute(delete(Volume).where(Volume.owner_id == owner_id))
        await cleanup.execute(delete(ResourceQuota).where(ResourceQuota.user_id == owner_id))
        await cleanup.execute(
            delete(EnvironmentRevision).where(
                EnvironmentRevision.template_id.in_(
                    select(EnvironmentTemplate.id).where(
                        EnvironmentTemplate.slug.like("admission-env-%")
                    )
                )
            )
        )
        await cleanup.execute(
            delete(EnvironmentTemplate).where(EnvironmentTemplate.slug.like("admission-env-%"))
        )
        await cleanup.execute(delete(ServerPlan).where(ServerPlan.slug.like("admission-plan-%")))
        await cleanup.execute(delete(User).where(User.id == owner_id))


async def create_queued_job(*, toolchain=False, argv=None, max_runtime_seconds=600):
    marker = uuid.uuid4().hex
    owner_id = uuid.uuid4()
    async with AsyncSession(test_engine, expire_on_commit=False) as db, db.begin():
        owner = User(
            id=owner_id,
            username=f"runtime-{marker}",
            email=f"runtime-{marker}@example.test",
            role="user",
            is_active=True,
            is_verified=True,
            nuke_balance=100,
        )
        db.add(owner)
        await db.flush()
        resources = await _make_resources(db, owner, toolchain=toolchain)
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        owner = await db.get(User, owner_id)
        previous_submission = settings.batch_jobs_submission_enabled
        settings.batch_jobs_submission_enabled = True
        try:
            detail = await BatchJobService(db).submit(
                owner,
                uuid.uuid4().hex,
                BatchJobSubmitRequest(
                    name=f"runtime-{marker}",
                    revision_id=resources.revision.id,
                    plan_id=resources.plan.id,
                    volume_id=resources.volume.id,
                    argv=argv or ["python", "-c", "print('ok')"],
                    max_runtime_seconds=max_runtime_seconds,
                ),
            )
        finally:
            settings.batch_jobs_submission_enabled = previous_submission
    return SimpleNamespace(
        job_id=detail.id,
        owner_id=owner_id,
        plan_id=resources.plan.id,
        revision_id=resources.revision.id,
        template_id=resources.template.id,
        volume_id=resources.volume.id,
        volume_name=resources.volume.name,
        resources=resources,
    )


async def admit_job(fixture, driver):
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        admission = await BatchJobAdmissionService(db, driver).admit(
            fixture.job_id, executor_id=uuid.uuid4()
        )
    assert isinstance(admission, JobAdmission)
    return admission


async def load_job(job_id):
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        return await db.get(BatchJob, job_id, populate_existing=True)


async def set_job(job_id, **values):
    async with AsyncSession(test_engine, expire_on_commit=False) as db, db.begin():
        job = await db.scalar(
            select(BatchJob)
            .where(BatchJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        for key, value in values.items():
            setattr(job, key, value)
        return job


async def volume_operation(job_id):
    async with AsyncSession(test_engine) as db:
        return await db.scalar(
            select(VolumeOperation).where(VolumeOperation.operation_id == job_id)
        )


@pytest_asyncio.fixture
async def committed_queued_job():
    fixture = await create_queued_job()
    try:
        yield fixture
    finally:
        await cleanup_owner(fixture.owner_id)


@pytest_asyncio.fixture
async def committed_admitted_job():
    fixture = await create_queued_job()
    driver = make_driver()
    admission = await admit_job(fixture, driver)
    fixture.driver = driver
    fixture.admission = admission
    try:
        yield fixture
    finally:
        await cleanup_owner(fixture.owner_id)


@pytest_asyncio.fixture
async def committed_toolchain_job():
    fixture = await create_queued_job(toolchain=True)
    driver = make_driver(toolchain=True)
    admission = await admit_job(fixture, driver)
    fixture.driver = driver
    fixture.admission = admission
    try:
        yield fixture
    finally:
        await cleanup_owner(fixture.owner_id)


class RuntimeHarness:
    def __init__(self, db, driver):
        self.db = db
        self.driver = driver
        self.service = BatchJobRuntimeService(db, driver)


@pytest_asyncio.fixture
async def runtime_harness(committed_admitted_job):
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        yield RuntimeHarness(db, committed_admitted_job.driver), committed_admitted_job


@pytest.mark.asyncio
async def test_start_persists_both_checkpoints_before_runtime_calls(runtime_harness):
    harness, fixture = runtime_harness
    driver = harness.driver
    observed = {}

    async def on_create():
        job = await load_job(fixture.job_id)
        observed["create_requested_at"] = job.create_requested_at
        observed["start_before_create"] = job.start_requested_at

    async def on_start():
        job = await load_job(fixture.job_id)
        observed["start_requested_at"] = job.start_requested_at

    driver.on_create = on_create
    driver.on_start = on_start

    result = await harness.service.start(fixture.job_id)

    assert result.action == "running"
    assert observed["create_requested_at"] is not None
    assert observed["start_before_create"] is None
    assert observed["start_requested_at"] is not None
    assert len(driver.created) == 1
    assert driver.started == ["created-1"]
    assert driver.prepared[0]["name"] == f"nukelab-job-prep-{fixture.job_id}"
    assert driver.prepared[0]["volume"] == fixture.volume_name

    job = await load_job(fixture.job_id)
    assert job.state == "running"
    assert job.reservation_active is True
    assert job.container_id == "created-1"
    assert job.started_at is not None
    assert job.deadline_at is not None
    assert job.start_observed_at is not None
    assert job.heartbeat_at is not None

    created = driver.created[0]
    assert created["name"] == f"nukelab-job-{fixture.job_id}"
    assert created["image"] == JOB_IMAGE_ID
    assert created["argv"] == ["python", "-c", "print('ok')"]
    assert created["workdir"] == "/work"
    assert created["timeout_seconds"] == 600
    assert created["mounts"] == [
        {
            "Type": "volume",
            "Source": fixture.volume_name,
            "Target": "/work",
            "ReadOnly": False,
        }
    ]
    assert created["labels"] == {
        "nukelab.managed": "true",
        "nukelab.workload": "job",
        "nukelab.job.id": str(fixture.job_id),
        "nukelab.job.fence": str(fixture.admission.fencing_token),
    }
    assert created["limits"]["memory_bytes"] == 1024 * 1024**2
    assert created["env"]["NUKELAB_JOB_ID"] == str(fixture.job_id)
    assert created["env"]["NUKELAB_JOB_NAME"] == job.name
    assert created["env"]["NUKELAB_USER_ID"] == str(fixture.owner_id)
    assert created["env"]["NUKELAB_CPU_COUNT"] == "1"
    assert created["env"]["OMP_NUM_THREADS"] == "1"
    assert created["env"]["PRIVATE_VALUE"] == "must-not-leak"


@pytest.mark.asyncio
async def test_duplicate_start_never_creates_or_starts_twice(runtime_harness):
    harness, fixture = runtime_harness
    driver = harness.driver
    first = await harness.service.start(fixture.job_id)
    second = await harness.service.start(fixture.job_id)
    assert first.action == "running"
    assert second.action in ("running", "noop")
    assert len(driver.created) == 1
    assert driver.started == ["created-1"]


@pytest.mark.asyncio
async def test_duplicate_start_claims_preparation_before_runtime_io(
    committed_toolchain_job, monkeypatch
):
    import asyncio

    fixture = committed_toolchain_job
    driver = fixture.driver
    executor_id = uuid.uuid4()
    monkeypatch.setattr("app.services.batch_job_runtime.current_executor_id", lambda: executor_id)
    monkeypatch.setattr("app.services.batch_job_monitor.current_executor_id", lambda: executor_id)

    entered = asyncio.Event()
    release = asyncio.Event()
    original_prepare = driver.prepare_batch_volume

    async def gated_prepare(**kwargs):
        entered.set()
        await release.wait()
        return await original_prepare(**kwargs)

    driver.prepare_batch_volume = gated_prepare

    async with (
        AsyncSession(test_engine, expire_on_commit=False) as first_db,
        AsyncSession(test_engine, expire_on_commit=False) as second_db,
    ):
        first = asyncio.create_task(BatchJobRuntimeService(first_db, driver).start(fixture.job_id))
        await asyncio.wait_for(entered.wait(), timeout=5)
        second = await asyncio.wait_for(
            BatchJobRuntimeService(second_db, driver).start(fixture.job_id), timeout=5
        )
        release.set()
        first_result = await asyncio.wait_for(first, timeout=10)

    assert first_result.action == "running"
    assert second.action == "deferred"
    assert len(driver.toolchain_calls) == 1
    assert len(driver.prepared) == 1
    assert len(driver.created) == 1
    assert len(driver.started) == 1
    job = await load_job(fixture.job_id)
    assert job.state == "running"
    assert job.reservation_active is True


@pytest.mark.asyncio
async def test_cancel_before_start_releases_cancelled_without_create(
    runtime_harness,
):
    harness, fixture = runtime_harness
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        owner = await db.get(User, fixture.owner_id)
        cancelled = await BatchJobService(db).cancel(owner, fixture.job_id)
    assert cancelled.state == "cancelling"

    result = await harness.service.start(fixture.job_id)

    assert result.action == "cancelled"
    assert harness.driver.created == []
    assert harness.driver.started == []
    job = await load_job(fixture.job_id)
    assert job.state == "cancelled"
    assert job.outcome_code == "cancelled"
    assert job.reason_code == "request_cancelled"
    assert job.proof_class == "control_plane"
    assert job.reservation_active is False
    guard = await volume_operation(fixture.job_id)
    assert guard.state == "failed"


@pytest.mark.asyncio
async def test_create_409_adopts_matching_named_container(runtime_harness):
    harness, fixture = runtime_harness
    driver = harness.driver
    adopted_id = "adopted-container"
    driver.create_side_effect = ContainerDriverError("name exists", status=409)
    driver.add_job_container(
        SimpleNamespace(
            id=fixture.job_id,
            fencing_token=fixture.admission.fencing_token,
            container_name=f"nukelab-job-{fixture.job_id}",
        ),
        container_id=adopted_id,
        status="created",
    )

    result = await harness.service.start(fixture.job_id)

    assert result.action == "running"
    assert driver.started == [adopted_id]
    job = await load_job(fixture.job_id)
    assert job.container_id == adopted_id
    assert job.state == "running"


@pytest.mark.asyncio
async def test_lost_create_response_requires_recovery(runtime_harness):
    harness, fixture = runtime_harness
    harness.driver.create_side_effect = TimeoutError()

    result = await harness.service.start(fixture.job_id)

    assert result.action == "recovery_required"
    job = await load_job(fixture.job_id)
    assert job.state == "recovery_required"
    assert job.reservation_active is True
    assert job.create_requested_at is not None
    guard = await volume_operation(fixture.job_id)
    assert guard.state == "reserved"


@pytest.mark.asyncio
async def test_lost_start_response_adopts_running_container(runtime_harness):
    harness, fixture = runtime_harness
    driver = harness.driver

    async def start_then_fail():
        driver.containers["created-1"]["State"].update(
            {
                "Status": "running",
                "Running": True,
                "StartedAt": iso(utc_now()),
            }
        )
        return ContainerDriverError("gateway timeout", status=504)

    driver.start_side_effect = start_then_fail

    result = await harness.service.start(fixture.job_id)

    assert result.action == "running"
    job = await load_job(fixture.job_id)
    assert job.state == "running"
    assert job.container_id == "created-1"


@pytest.mark.asyncio
async def test_uncertain_start_without_running_container_retains_guard(runtime_harness):
    harness, fixture = runtime_harness
    driver = harness.driver
    driver.start_side_effect = ContainerDriverError("engine unavailable", status=503)

    result = await harness.service.start(fixture.job_id)

    assert result.action == "recovery_required"
    job = await load_job(fixture.job_id)
    assert job.state == "recovery_required"
    assert job.reservation_active is True
    guard = await volume_operation(fixture.job_id)
    assert guard.state == "reserved"


@pytest.mark.asyncio
async def test_volume_prepare_failure_is_terminal(runtime_harness):
    harness, fixture = runtime_harness
    harness.driver.prepare_error = ContainerDriverError("batch_volume_prepare_failed")

    result = await harness.service.start(fixture.job_id)

    assert result.action == "failed"
    job = await load_job(fixture.job_id)
    assert job.state == "failed"
    assert job.reason_code == "volume_unavailable"
    assert job.proof_class == "control_plane"
    assert job.reservation_active is False
    assert harness.driver.created == []


@pytest.mark.asyncio
async def test_volume_prepare_unknown_requires_recovery(runtime_harness):
    harness, fixture = runtime_harness
    harness.driver.prepare_error = ContainerDriverError("batch_volume_prepare_unknown")

    result = await harness.service.start(fixture.job_id)

    assert result.action == "recovery_required"
    job = await load_job(fixture.job_id)
    assert job.state == "recovery_required"
    assert job.reservation_active is True
    assert harness.driver.created == []


@pytest.mark.asyncio
async def test_missing_work_volume_fails_before_create(runtime_harness):
    harness, fixture = runtime_harness
    harness.driver.volume_missing = True

    result = await harness.service.start(fixture.job_id)

    assert result.action == "failed"
    job = await load_job(fixture.job_id)
    assert job.state == "failed"
    assert job.reason_code == "volume_unavailable"
    assert harness.driver.created == []


@pytest.mark.asyncio
async def test_toolchain_is_prepared_and_mounted_read_only(committed_toolchain_job):
    driver = committed_toolchain_job.driver
    driver.image_env_by_image = {
        JOB_IMAGE_ID: {"PATH": "/runtime/bin", "RUNTIME_ONLY": "runtime"},
        TOOLCHAIN_IMAGE_ID: {"PATH": "/toolchain/bin", "TOOLCHAIN_ONLY": "toolchain"},
    }
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        service = BatchJobRuntimeService(db, driver)
        result = await service.start(committed_toolchain_job.job_id)

    assert result.action == "running"
    assert len(driver.toolchain_calls) == 1
    image, cache_name, mounts = driver.toolchain_calls[0]
    assert image == TOOLCHAIN_IMAGE_ID
    assert mounts == ["/opt/nuke"]
    created = driver.created[0]
    assert created["mounts"][1] == {
        "Type": "volume",
        "Source": cache_name,
        "Target": "/opt/nuke",
        "ReadOnly": True,
    }
    assert created["env"]["TOOLCHAIN_ENV"] == "enabled"
    # Manifest defaults expand against the toolchain image, not the runtime.
    assert created["env"]["PATH"] == "/opt/nuke/bin:/toolchain/bin"
    assert created["env"]["PATH_EXTRA"] == "/opt/nuke/bin:/toolchain/bin"
    assert driver.image_env_calls == [TOOLCHAIN_IMAGE_ID]


@pytest.mark.asyncio
async def test_persisted_start_request_prevents_restart(runtime_harness):
    harness, fixture = runtime_harness
    driver = harness.driver
    await set_job(
        fixture.job_id,
        state="starting",
        create_requested_at=utc_now(),
        start_requested_at=utc_now(),
        heartbeat_at=utc_now() - timedelta(seconds=settings.batch_jobs_heartbeat_stale_seconds + 5),
    )
    driver.add_job_container(
        SimpleNamespace(
            id=fixture.job_id,
            fencing_token=fixture.admission.fencing_token,
            container_name=f"nukelab-job-{fixture.job_id}",
        ),
        container_id="existing-container",
        status="created",
    )

    result = await harness.service.start(fixture.job_id)

    assert result.action == "recovery_required"
    assert driver.started == []
    job = await load_job(fixture.job_id)
    assert job.state == "recovery_required"


@pytest.mark.asyncio
async def test_executor_unconfirmed_retains_reservation_and_guard(committed_admitted_job):
    fixture = committed_admitted_job
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        finalizer = BatchJobFinalizer(db, fixture.driver)
        result = await finalizer.finalize(
            fixture.job_id,
            fencing_token=fixture.admission.fencing_token,
            state="succeeded",
            outcome_code="succeeded",
            proof_class="runtime",
            exit_code=0,
            executor_terminated=False,
        )
    assert result.executor_unconfirmed is True
    job = await load_job(fixture.job_id)
    assert job.state == "recovery_required"
    assert job.reservation_active is True
    assert (await volume_operation(fixture.job_id)).state == "reserved"


@pytest.mark.asyncio
async def test_repeated_terminal_release_is_idempotent(committed_admitted_job):
    fixture = committed_admitted_job
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        finalizer = BatchJobFinalizer(db, fixture.driver)
        first = await finalizer.finalize(
            fixture.job_id,
            fencing_token=fixture.admission.fencing_token,
            state="succeeded",
            outcome_code="succeeded",
            proof_class="runtime",
            exit_code=0,
            executor_terminated=True,
            log_state="available",
            log_text="first result",
        )
        second = await finalizer.finalize(
            fixture.job_id,
            fencing_token=fixture.admission.fencing_token,
            state="succeeded",
            outcome_code="succeeded",
            proof_class="runtime",
            exit_code=0,
            executor_terminated=True,
            log_state="available",
            log_text="second result",
        )
    assert first.applied is True
    assert second.already_terminal is True
    job = await load_job(fixture.job_id)
    assert job.state == "succeeded"
    assert job.exit_code == 0
    assert job.reservation_active is False
    assert (await volume_operation(fixture.job_id)).state == "succeeded"
    from app.models.batch_job import BatchJobLog

    async with AsyncSession(test_engine) as db:
        payload = await db.get(BatchJobLog, fixture.job_id)
    assert payload.text == "first result"


def test_sanitize_environment_drops_platform_and_fixed_keys():
    environment = sanitize_environment(
        {
            "environment_variables": {
                "SAFE": "value",
                "HOME": "/root",
                "NUKELAB_AUTH_ENABLED": "true",
                "JWT_SECRET": "secret",
                "DATABASE_URL": "postgres://secret",
                "invalid-key": "value",
                "NOT_A_STRING": 3,
            }
        }
    )
    assert environment == {"SAFE": "value"}


def test_capture_tail_counts_bytes_and_truncates_safely(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_log_tail_bytes", 8)
    capture = capture_tail("abcdefghij")
    assert capture.state == "truncated"
    assert capture.truncated is True
    assert capture.size_bytes == 10
    assert capture.text == "cdefghij"

    malformed = capture_tail("\udcffabcdefghij")
    assert malformed.state == "truncated"
    assert malformed.size_bytes > 8


def test_container_status_and_identity_validation():
    job = SimpleNamespace(
        job_id=uuid.uuid4(),
        fencing_token=uuid.uuid4(),
        container_name="nukelab-job-example",
        runtime_identity={"local_id": JOB_IMAGE_ID},
    )
    info = container_info(
        job_id=job.job_id,
        fencing_token=job.fencing_token,
        container_name=job.container_name,
        status="created",
    )
    assert container_status(info) == "created"
    assert validate_job_container(job, info) is None
    assert (
        validate_job_container(job, container_info(job_id=job.job_id, fencing_token=uuid.uuid4()))
        == "identity_mismatch"
    )
