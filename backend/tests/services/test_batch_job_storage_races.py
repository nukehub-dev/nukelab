# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Deterministic storage race gates for batch admission and volume exclusion.

Every competing writer uses its own committed PostgreSQL session so the only
serialization is the platform admission lock. No test relies on sleeps or task
start order for correctness.
"""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.batch_job import BatchJob
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.resource_quota import ResourceQuota
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.schemas.batch_job import BatchJobSubmitRequest
from app.schemas.server_queue import QueuedServerResponse
from app.services.batch_job_admission_service import (
    BatchJobAdmissionService,
    JobAdmission,
    JobAdmissionError,
)
from app.services.batch_job_finalizer import BatchJobFinalizer
from app.services.batch_job_service import BatchJobService, JobError
from app.services.resource_pool_service import ResourcePoolService
from app.services.server_launch_service import LaunchReservation, ServerLaunchService
from app.services.server_launch_validation import normalize_launch_request
from app.services.user_service import UserService
from app.services.volume_mutation_service import volume_writer
from app.services.volume_operation_service import (
    ACTIVE_STATES,
    VolumeOperationError,
    acquire_volume_operations,
)
from app.services.volume_recovery_runtime import VolumeRecoveryRuntime
from app.services.volume_service import VolumeService
from tests.conftest import test_engine

JOB_IMAGE_ID = "sha256:" + "a" * 64


def local_identity():
    return {
        "requested_reference": "approved:latest",
        "local_id": JOB_IMAGE_ID,
        "repository_digests": [],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }


def admission_driver():
    return SimpleNamespace(
        image_exists=AsyncMock(return_value=True),
        resolve_image=AsyncMock(return_value=local_identity()),
        pull_image=AsyncMock(side_effect=AssertionError("must never pull a tag")),
    )


def launch_driver():
    return SimpleNamespace(
        ensure_volume=AsyncMock(),
        image_exists=AsyncMock(return_value=True),
        pull_image=AsyncMock(),
        resolve_image=AsyncMock(return_value=local_identity()),
        get_container_info=AsyncMock(return_value={"Image": JOB_IMAGE_ID}),
    )


def launch_request(fixture, owner_index):
    owner_id = fixture.owner_ids[owner_index]
    username = fixture.usernames[owner_index]
    return normalize_launch_request(
        {
            "name": f"race-launch-{owner_id}",
            "plan_id": str(fixture.plan_id),
            "environment_id": str(fixture.template_id),
            "volume_mounts": [
                {
                    "volume_id": "",
                    "mount_path": f"/home/{username}",
                    "mode": "read_write",
                    "max_size_bytes": 1024**3,
                }
            ],
        },
        username=username,
    )


@pytest.fixture(autouse=True)
def race_settings(monkeypatch):
    monkeypatch.setattr(settings, "batch_jobs_submission_enabled", True)
    monkeypatch.setattr(settings, "batch_jobs_require_storage_enforcement", False)
    monkeypatch.setattr(settings, "batch_jobs_allowed_user_ids", "")
    monkeypatch.setattr(settings, "batch_jobs_max_active_per_owner", 1)
    monkeypatch.setattr(settings, "batch_jobs_max_active_fleet", 10)
    monkeypatch.setattr(settings, "resource_pool_cpu", 1000.0)
    monkeypatch.setattr(settings, "resource_pool_memory_mib", 1_000_000)
    monkeypatch.setattr(settings, "resource_pool_disk_mib", 1_000_000)
    monkeypatch.setattr(settings, "registry_verification_policy", "off")
    monkeypatch.setattr(settings, "gpu_devices", "")
    monkeypatch.setattr(settings, "credits_enabled", False)


@pytest_asyncio.fixture
async def committed_race_world(race_settings):
    """Three owners: two queued batch jobs and one interactive launch candidate."""
    marker = uuid.uuid4().hex
    owner_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    usernames = [f"race_{marker}_{index}" for index in range(3)]
    plan_id = uuid.uuid4()
    template_id = uuid.uuid4()
    volume_ids = [uuid.uuid4(), uuid.uuid4()]
    revision_id = None
    job_ids = []
    async with AsyncSession(test_engine, expire_on_commit=False) as seed, seed.begin():
        seed.add_all(
            [
                User(
                    id=owner_id,
                    username=username,
                    email=f"{username}@example.test",
                    role="user",
                    is_active=True,
                    nuke_balance=100,
                )
                for owner_id, username in zip(owner_ids, usernames, strict=True)
            ]
        )
        seed.add(
            ServerPlan(
                id=plan_id,
                name=f"race-plan-{marker}",
                slug=f"race-plan-{marker}",
                cpu_limit=1.0,
                memory_limit="1g",
                disk_limit="2g",
                gpu_limit=0,
                cost_per_hour=0,
                allow_batch_jobs=True,
                is_active=True,
                is_public=True,
                visible_to_roles=["user"],
                max_servers_per_user=10,
            )
        )
        seed.add(
            EnvironmentTemplate(
                id=template_id,
                name=f"race-env-{marker}",
                slug=f"race-env-{marker}",
                image="approved:latest",
                is_active=True,
                is_public=True,
            )
        )
        await seed.flush()
        seed.add_all(
            [
                ResourceQuota(
                    user_id=owner_id,
                    max_cpu_total=8,
                    max_memory_total="16g",
                    max_disk_total="100g",
                    max_gpu_total=0,
                    max_servers_total=10,
                )
                for owner_id in owner_ids
            ]
        )
        seed.add_all(
            [
                Volume(
                    id=volume_id,
                    name=f"race-volume-{volume_id}",
                    display_name="Race data",
                    owner_id=owner_ids[index],
                    visibility="private",
                    max_size_bytes=1024**3,
                    status="active",
                )
                for index, volume_id in enumerate(volume_ids)
            ]
        )

    async with AsyncSession(test_engine, expire_on_commit=False) as launch_seed:
        revision_id = await ServerLaunchService(launch_seed, launch_driver()).resolve_revision(
            owner_ids[2],
            launch_request(
                SimpleNamespace(
                    owner_ids=owner_ids,
                    usernames=usernames,
                    plan_id=plan_id,
                    template_id=template_id,
                ),
                2,
            ),
        )
    for index, owner_id in enumerate(owner_ids[:2]):
        async with AsyncSession(test_engine, expire_on_commit=False) as submit:
            owner = await submit.get(User, owner_id)
            detail = await BatchJobService(submit).submit(
                owner,
                uuid.uuid4().hex,
                BatchJobSubmitRequest(
                    name=f"race-job-{marker}-{index}",
                    revision_id=revision_id,
                    plan_id=plan_id,
                    volume_id=volume_ids[index],
                    argv=["true"],
                    max_runtime_seconds=300,
                ),
            )
            job_ids.append(detail.id)

    fixture = SimpleNamespace(
        owner_ids=owner_ids,
        usernames=usernames,
        plan_id=plan_id,
        template_id=template_id,
        revision_id=revision_id,
        volume_ids=volume_ids,
        job_ids=job_ids,
    )
    try:
        yield fixture
    finally:
        async with AsyncSession(test_engine) as cleanup, cleanup.begin():
            await cleanup.execute(delete(ServerQueue).where(ServerQueue.user_id.in_(owner_ids)))
            await cleanup.execute(delete(BatchJob).where(BatchJob.user_id.in_(owner_ids)))
            await cleanup.execute(
                delete(VolumeOperation).where(VolumeOperation.owner_id.in_(owner_ids))
            )
            await cleanup.execute(delete(Server).where(Server.user_id.in_(owner_ids)))
            await cleanup.execute(delete(Volume).where(Volume.owner_id.in_(owner_ids)))
            await cleanup.execute(delete(ResourceQuota).where(ResourceQuota.user_id.in_(owner_ids)))
            await cleanup.execute(
                delete(EnvironmentRevision).where(EnvironmentRevision.template_id == template_id)
            )
            await cleanup.execute(
                delete(EnvironmentTemplate).where(EnvironmentTemplate.id == template_id)
            )
            await cleanup.execute(delete(ServerPlan).where(ServerPlan.id == plan_id))
            await cleanup.execute(delete(User).where(User.id.in_(owner_ids)))


async def _admit(job_id):
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        return await BatchJobAdmissionService(db, admission_driver()).admit(
            job_id, executor_id=uuid.uuid4()
        )


async def _job_snapshot(job_id):
    async with AsyncSession(test_engine) as db:
        return await db.get(BatchJob, job_id, populate_existing=True)


async def _active_guards(volume_ids):
    async with AsyncSession(test_engine) as db:
        return (
            await db.scalars(
                select(VolumeOperation).where(
                    VolumeOperation.volume_id.in_(volume_ids),
                    VolumeOperation.state.in_(ACTIVE_STATES),
                )
            )
        ).all()


@pytest.mark.asyncio
@pytest.mark.parametrize("round_index", range(3))
@pytest.mark.parametrize("dimension", ["cpu", "memory", "disk"])
async def test_last_cpu_memory_or_disk_slot_has_exactly_one_batch_winner(
    committed_race_world, monkeypatch, dimension, round_index
):
    fixture = committed_race_world
    limits = {"cpu": 1000.0, "memory": 1_000_000, "disk": 1_000_000}
    limits[dimension] = {"cpu": 1.0, "memory": 1024, "disk": 2048}[dimension]
    monkeypatch.setattr(settings, "resource_pool_cpu", limits["cpu"])
    monkeypatch.setattr(settings, "resource_pool_memory_mib", limits["memory"])
    monkeypatch.setattr(settings, "resource_pool_disk_mib", limits["disk"])
    barrier = asyncio.Barrier(2)

    async def admit(job_id):
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return await BatchJobAdmissionService(db, admission_driver()).admit(
                job_id, executor_id=uuid.uuid4()
            )

    results = await asyncio.wait_for(
        asyncio.gather(admit(fixture.job_ids[0]), admit(fixture.job_ids[1])),
        timeout=10,
    )

    assert sum(isinstance(result, JobAdmission) for result in results) == 1
    winner_index = next(
        index for index, result in enumerate(results) if isinstance(result, JobAdmission)
    )
    loser_index = 1 - winner_index
    winner = await _job_snapshot(fixture.job_ids[winner_index])
    loser = await _job_snapshot(fixture.job_ids[loser_index])
    assert winner.state == "starting"
    assert winner.reservation_active is True
    assert loser.state == "queued"
    assert loser.reason_code == "waiting_capacity"
    assert loser.reservation_active is False

    guards = await _active_guards([fixture.volume_ids[winner_index]])
    assert len(guards) == 1
    assert guards[0].kind == "job_writer"
    assert len(await _active_guards([fixture.volume_ids[loser_index]])) == 0
    async with AsyncSession(test_engine) as verify:
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(BatchJob)
                .where(
                    BatchJob.id.in_(fixture.job_ids),
                    BatchJob.reservation_active.is_(True),
                )
            )
            == 1
        )
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(VolumeOperation)
                .where(
                    VolumeOperation.operation_id.in_(fixture.job_ids),
                    VolumeOperation.state.in_(ACTIVE_STATES),
                )
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("round_index", range(3))
async def test_interactive_launch_and_batch_job_share_one_last_slot(
    committed_race_world, monkeypatch, round_index
):
    fixture = committed_race_world
    monkeypatch.setattr(settings, "resource_pool_cpu", 1.0)
    request = launch_request(fixture, 2)
    barrier = asyncio.Barrier(2)

    async def admit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return await BatchJobAdmissionService(db, admission_driver()).admit(
                fixture.job_ids[0], executor_id=uuid.uuid4()
            )

    async def launch():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return await ServerLaunchService(db, launch_driver()).reserve(
                fixture.owner_ids[2], request, fixture.revision_id
            )

    job_result, launch_result = await asyncio.wait_for(
        asyncio.gather(admit(), launch()),
        timeout=10,
    )
    job_won = isinstance(job_result, JobAdmission)
    launch_won = isinstance(launch_result, LaunchReservation)
    assert job_won != launch_won
    if job_won:
        assert isinstance(launch_result, QueuedServerResponse)
        assert launch_result.message
        assert launch_result.queue_position == 1
    else:
        assert job_result is None
        job = await _job_snapshot(fixture.job_ids[0])
        assert job.state == "queued"
        assert job.reason_code == "waiting_capacity"
        assert job.reservation_active is False

    async with AsyncSession(test_engine) as verify:
        allocated = await ResourcePoolService(verify)._get_allocated_resources()
        assert allocated["cpu"] == 1.0
        if launch_won:
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(Server)
                    .where(Server.user_id == fixture.owner_ids[2])
                )
                == 1
            )
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(BatchJob)
                    .where(BatchJob.reservation_active.is_(True))
                )
                == 0
            )
        else:
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(Server)
                    .where(Server.user_id == fixture.owner_ids[2])
                )
                == 0
            )
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(BatchJob)
                    .where(BatchJob.id == fixture.job_ids[0], BatchJob.reservation_active.is_(True))
                )
                == 1
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("round_index", range(2))
@pytest.mark.parametrize("kind", ["writer", "mount", "backup", "restore"])
async def test_job_admission_and_exclusive_volume_intent_have_one_winner(
    committed_race_world, kind, round_index
):
    fixture = committed_race_world
    volume_id = fixture.volume_ids[0]
    owner_id = fixture.owner_ids[0]
    job_id = fixture.job_ids[0]
    barrier = asyncio.Barrier(2)

    async def compete():
        try:
            async with AsyncSession(test_engine) as db, db.begin():
                await asyncio.wait_for(barrier.wait(), timeout=5)
                rows = await acquire_volume_operations(
                    db,
                    volume_ids=[volume_id],
                    owner_id=owner_id,
                    operation_id=uuid.uuid4(),
                    kind=kind,
                )
                return rows[0].kind
        except VolumeOperationError as exc:
            return exc.code

    async def admit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return await BatchJobAdmissionService(db, admission_driver()).admit(
                job_id, executor_id=uuid.uuid4()
            )

    competitor_result, admission = await asyncio.wait_for(
        asyncio.gather(compete(), admit()),
        timeout=10,
    )
    guards = await _active_guards([volume_id])
    assert len(guards) == 1
    job = await _job_snapshot(job_id)
    if isinstance(admission, JobAdmission):
        assert competitor_result == "volume_busy"
        assert guards[0].kind == "job_writer"
        assert guards[0].operation_id == job_id
        assert job.state == "starting"
    else:
        assert competitor_result == kind
        assert guards[0].kind == kind
        assert job.state == "queued"
        assert job.reason_code == "volume_busy"
        assert job.reservation_active is False
        async with AsyncSession(test_engine) as verify:
            assert (
                await verify.scalar(
                    select(func.count())
                    .select_from(VolumeOperation)
                    .where(
                        VolumeOperation.operation_id == job_id,
                        VolumeOperation.state.in_(ACTIVE_STATES),
                    )
                )
                == 0
            )


@pytest.mark.asyncio
async def test_batch_admission_and_share_mutation_never_overlap(committed_race_world):
    fixture = committed_race_world
    volume_id = fixture.volume_ids[0]
    job_id = fixture.job_ids[0]
    barrier = asyncio.Barrier(2)
    share_entered = asyncio.Event()
    release_share = asyncio.Event()

    async def share():
        async with AsyncSession(test_engine) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            try:
                async with volume_writer(db, volume_id):
                    share_entered.set()
                    await release_share.wait()
                return "shared"
            except HTTPException as exc:
                return exc.detail

    async def admit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return await BatchJobAdmissionService(db, admission_driver()).admit(
                job_id, executor_id=uuid.uuid4()
            )

    share_task = asyncio.create_task(share())
    admit_task = asyncio.create_task(admit())
    entered_task = asyncio.create_task(share_entered.wait())
    done, _pending = await asyncio.wait(
        {admit_task, entered_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if admit_task not in done:
        await asyncio.wait_for(admit_task, timeout=10)
    release_share.set()
    share_result = await asyncio.wait_for(share_task, timeout=10)
    admission = await asyncio.wait_for(admit_task, timeout=10)
    if not entered_task.done():
        entered_task.cancel()
        await asyncio.gather(entered_task, return_exceptions=True)

    assert len(await _active_guards([volume_id])) <= 1
    job = await _job_snapshot(job_id)
    if isinstance(admission, JobAdmission):
        assert share_result["code"] == "volume_busy"
        assert job.state == "starting"
        guards = await _active_guards([volume_id])
        assert len(guards) == 1
        assert guards[0].kind == "job_writer"
    else:
        assert share_result == "shared"
        assert job.state == "queued"
        assert job.reason_code == "volume_busy"
        assert len(await _active_guards([volume_id])) == 0
        # The completed share released its writer; the queued job may now admit.
        second = await _admit(job_id)
        assert isinstance(second, JobAdmission)
        guards = await _active_guards([volume_id])
        assert len(guards) == 1
        assert guards[0].kind == "job_writer"


@pytest.mark.asyncio
async def test_batch_admission_and_volume_delete_have_one_verified_winner(
    committed_race_world, monkeypatch
):
    fixture = committed_race_world
    volume_id = fixture.volume_ids[0]
    job_id = fixture.job_ids[0]
    barrier = asyncio.Barrier(2)
    delete_entered = asyncio.Event()
    release_delete = asyncio.Event()

    class DeleteDriver:
        async def delete_volume(self, _name):
            return None

        async def get_volume(self, _name):
            return None

    async def gated_assert_detached(self, _name):
        delete_entered.set()
        await release_delete.wait()

    monkeypatch.setattr(VolumeRecoveryRuntime, "assert_detached", gated_assert_detached)
    monkeypatch.setattr(
        "app.services.volume_service.get_container_client",
        AsyncMock(return_value=DeleteDriver()),
    )

    async def delete_volume():
        async with AsyncSession(test_engine) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            try:
                return await VolumeService(db).delete_volume(str(volume_id))
            except HTTPException as exc:
                return exc.detail

    async def admit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return await BatchJobAdmissionService(db, admission_driver()).admit(
                job_id, executor_id=uuid.uuid4()
            )

    delete_task = asyncio.create_task(delete_volume())
    admit_task = asyncio.create_task(admit())
    entered_task = asyncio.create_task(delete_entered.wait())
    done, _pending = await asyncio.wait(
        {admit_task, entered_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if admit_task not in done:
        await asyncio.wait_for(admit_task, timeout=10)
    release_delete.set()
    delete_result = await asyncio.wait_for(delete_task, timeout=10)
    admission = await asyncio.wait_for(admit_task, timeout=10)
    if not entered_task.done():
        entered_task.cancel()
        await asyncio.gather(entered_task, return_exceptions=True)

    job = await _job_snapshot(job_id)
    if delete_entered.is_set():
        assert delete_result is True
        assert admission is None
        assert job.state == "queued"
        assert job.reason_code == "volume_busy"
        assert len(await _active_guards([volume_id])) == 0
        async with AsyncSession(test_engine) as verify:
            assert await verify.get(Volume, volume_id) is None
    else:
        assert delete_result["code"] == "volume_busy"
        assert isinstance(admission, JobAdmission)
        assert job.state == "starting"
        guards = await _active_guards([volume_id])
        assert len(guards) == 1
        assert guards[0].kind == "job_writer"


@pytest.mark.asyncio
async def test_account_deletion_cannot_remove_an_active_job_guard(committed_race_world):
    fixture = committed_race_world
    owner_id = fixture.owner_ids[0]
    job_id = fixture.job_ids[0]
    barrier = asyncio.Barrier(2)

    async def delete_account():
        async with AsyncSession(test_engine) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            try:
                await UserService(db).delete_user(str(owner_id))
                return "deleted"
            except HTTPException as exc:
                return exc.detail

    async def admit():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return await BatchJobAdmissionService(db, admission_driver()).admit(
                job_id, executor_id=uuid.uuid4()
            )

    deletion, admission = await asyncio.wait_for(
        asyncio.gather(delete_account(), admit()),
        timeout=10,
    )

    assert deletion == {"code": "user_resources_require_cleanup"}
    assert isinstance(admission, JobAdmission)
    async with AsyncSession(test_engine) as verify:
        assert await verify.get(User, owner_id) is not None
        job = await verify.get(BatchJob, job_id, populate_existing=True)
        assert job.state == "starting"
        assert job.reservation_active is True
    guards = await _active_guards([fixture.volume_ids[0]])
    assert len(guards) == 1
    assert guards[0].kind == "job_writer"


@pytest.mark.asyncio
async def test_recovery_required_reservation_and_guard_cannot_be_stolen_or_cleaned(
    committed_race_world, monkeypatch
):
    fixture = committed_race_world
    owner_id = fixture.owner_ids[0]
    job_id = fixture.job_ids[0]
    volume_id = fixture.volume_ids[0]
    monkeypatch.setattr(settings, "batch_jobs_max_active_per_owner", 2)
    monkeypatch.setattr(settings, "resource_pool_cpu", 4.0)

    initial = await _admit(job_id)
    assert isinstance(initial, JobAdmission)
    async with AsyncSession(test_engine) as db:
        service = BatchJobAdmissionService(db, admission_driver())
        assert await service.mark_recovery_required(
            job_id,
            fencing_token=initial.fencing_token,
            executor_id=uuid.uuid4(),
            reason_code="runtime_unverifiable",
        )

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        owner = await db.get(User, owner_id)
        extra = await BatchJobService(db).submit(
            owner,
            uuid.uuid4().hex,
            BatchJobSubmitRequest(
                name="competing-recovery-job",
                revision_id=fixture.revision_id,
                plan_id=fixture.plan_id,
                volume_id=volume_id,
                argv=["true"],
                max_runtime_seconds=300,
            ),
        )
    assert await _admit(extra.id) is None
    competitor = await _job_snapshot(extra.id)
    assert competitor.state == "queued"
    assert competitor.reason_code == "volume_busy"
    guards = await _active_guards([volume_id])
    assert len(guards) == 1
    assert guards[0].operation_id == job_id
    assert guards[0].state == "reserved"

    async with AsyncSession(test_engine) as db:
        cleanup = await BatchJobFinalizer(db, admission_driver()).cleanup(job_id)
    assert cleanup.state == "pending"
    assert cleanup.attempts == 0

    async with AsyncSession(test_engine) as db:
        owner = await db.get(User, owner_id)
        with pytest.raises(JobError) as cancel_error:
            await BatchJobService(db).cancel(owner, job_id)
    assert cancel_error.value.code == "job_not_cancellable"

    async with AsyncSession(test_engine) as db:
        service = BatchJobAdmissionService(db, admission_driver())
        with pytest.raises(JobAdmissionError, match="executor_unconfirmed"):
            await service.release_terminal(
                job_id,
                fencing_token=initial.fencing_token,
                state="succeeded",
                outcome_code="succeeded",
                proof_class="observed",
                exit_code=0,
                executor_terminated=False,
            )

    retained = await _job_snapshot(job_id)
    assert retained.state == "recovery_required"
    assert retained.reservation_active is True
    guards = await _active_guards([volume_id])
    assert len(guards) == 1
    assert guards[0].state == "reserved"
    async with AsyncSession(test_engine) as verify:
        allocated = await ResourcePoolService(verify)._get_allocated_resources()
        assert allocated["cpu"] == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize("state,outcome", [("succeeded", "succeeded"), ("failed", "failed")])
async def test_terminal_release_is_idempotent_and_drops_the_guard_once(
    committed_race_world, state, outcome
):
    fixture = committed_race_world
    job_id = fixture.job_ids[0]
    volume_id = fixture.volume_ids[0]
    admission = await _admit(job_id)
    assert isinstance(admission, JobAdmission)

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        service = BatchJobAdmissionService(db, admission_driver())
        first = await service.release_terminal(
            job_id,
            fencing_token=admission.fencing_token,
            state=state,
            outcome_code=outcome,
            proof_class="observed",
            exit_code=0 if state == "succeeded" else 1,
            executor_terminated=True,
        )
        assert first is not None
        assert first.state == state
        assert first.reservation_active is False
        guard = await db.scalar(
            select(VolumeOperation).where(VolumeOperation.operation_id == job_id)
        )
        assert guard.state == ("succeeded" if state == "succeeded" else "failed")
        completed_at = guard.completed_at
        assert completed_at is not None

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        service = BatchJobAdmissionService(db, admission_driver())
        replay = await service.release_terminal(
            job_id,
            fencing_token=admission.fencing_token,
            state="failed" if state == "succeeded" else "succeeded",
            outcome_code="failed" if state == "succeeded" else "succeeded",
            proof_class="observed",
            exit_code=99,
            executor_terminated=True,
        )
        assert replay is not None
        assert replay.state == state
        assert replay.charged_credits == 0
        guard = await db.scalar(
            select(VolumeOperation).where(VolumeOperation.operation_id == job_id)
        )
        assert guard.completed_at == completed_at
        assert (
            await db.scalar(
                select(func.count())
                .select_from(VolumeOperation)
                .where(VolumeOperation.operation_id == job_id)
            )
            == 1
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(VolumeOperation)
                .where(
                    VolumeOperation.volume_id == volume_id,
                    VolumeOperation.state.in_(ACTIVE_STATES),
                )
            )
            == 0
        )
        # A later writer can take the released volume.
        rows = await acquire_volume_operations(
            db,
            volume_ids=[volume_id],
            owner_id=fixture.owner_ids[0],
            operation_id=uuid.uuid4(),
            kind="writer",
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_running_cancel_releases_guard_once(
    committed_race_world,
):
    fixture = committed_race_world
    queued_job_id = fixture.job_ids[1]
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        owner = await db.get(User, fixture.owner_ids[1])
        service = BatchJobService(db)
        first = await service.cancel(owner, queued_job_id)
        second = await service.cancel(owner, queued_job_id)
    assert first.state == "cancelled"
    assert second.state == "cancelled"
    assert second.billing.charged == 0
    assert await _active_guards([fixture.volume_ids[1]]) == []

    running_job_id = fixture.job_ids[0]
    admission = await _admit(running_job_id)
    assert isinstance(admission, JobAdmission)
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        owner = await db.get(User, fixture.owner_ids[0])
        service = BatchJobService(db)
        first = await service.cancel(owner, running_job_id)
        second = await service.cancel(owner, running_job_id)
    assert first.state == "cancelling"
    assert second.state == "cancelling"
    assert second.billing.charged == 0
    guards = await _active_guards([fixture.volume_ids[0]])
    assert len(guards) == 1
    assert guards[0].kind == "job_writer"

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        released = await BatchJobAdmissionService(db, admission_driver()).release_terminal(
            running_job_id,
            fencing_token=admission.fencing_token,
            state="cancelled",
            outcome_code="cancelled",
            reason_code="request_cancelled",
            proof_class="control_plane",
            executor_terminated=True,
        )
        assert released is not None
        assert released.state == "cancelled"
        assert released.reservation_active is False
        guard = await db.scalar(
            select(VolumeOperation).where(VolumeOperation.operation_id == running_job_id)
        )
        assert guard.state == "failed"
        completed_at = guard.completed_at
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        replay = await BatchJobAdmissionService(db, admission_driver()).release_terminal(
            running_job_id,
            fencing_token=admission.fencing_token,
            state="cancelled",
            outcome_code="cancelled",
            executor_terminated=True,
        )
        assert replay is not None
        guard = await db.scalar(
            select(VolumeOperation).where(VolumeOperation.operation_id == running_job_id)
        )
        assert guard.completed_at == completed_at
        assert (
            await db.scalar(
                select(func.count())
                .select_from(VolumeOperation)
                .where(
                    VolumeOperation.volume_id == fixture.volume_ids[0],
                    VolumeOperation.state.in_(ACTIVE_STATES),
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_finalize_replay_does_not_release_or_cleanup_twice(committed_race_world):
    fixture = committed_race_world
    job_id = fixture.job_ids[0]

    class CleanupDriver:
        def __init__(self):
            self.deleted = []

        async def delete_container(self, identifier, force=False):
            self.deleted.append((identifier, force))

    driver = CleanupDriver()
    admission = await _admit(job_id)
    assert isinstance(admission, JobAdmission)
    async with AsyncSession(test_engine) as db, db.begin():
        job = await db.get(BatchJob, job_id, with_for_update=True)
        job.container_id = "race-container"

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        first = await BatchJobFinalizer(db, driver).finalize(
            job_id,
            fencing_token=admission.fencing_token,
            state="succeeded",
            outcome_code="succeeded",
            proof_class="observed",
            exit_code=0,
            executor_terminated=True,
        )
    assert first.applied is True
    assert first.already_terminal is False
    assert first.cleanup is not None
    assert first.cleanup.state == "complete"
    assert driver.deleted == [("race-container", False)]

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        second = await BatchJobFinalizer(db, driver).finalize(
            job_id,
            fencing_token=admission.fencing_token,
            state="failed",
            outcome_code="failed",
            proof_class="observed",
            exit_code=1,
            executor_terminated=True,
        )
        assert second.applied is False
        assert second.already_terminal is True
        job = await db.get(BatchJob, job_id, populate_existing=True)
        assert job.state == "succeeded"
        assert job.charged_credits == 0
        assert job.cleanup_attempts == 1
        assert driver.deleted == [("race-container", False)]
        guards = (
            await db.scalars(
                select(VolumeOperation).where(VolumeOperation.volume_id == fixture.volume_ids[0])
            )
        ).all()
        assert len(guards) == 1
        assert guards[0].state == "succeeded"
