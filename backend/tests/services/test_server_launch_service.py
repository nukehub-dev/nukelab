# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Exercise persisted launch admission with real policy/accounting and a fake runtime."""

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob
from app.models.credit_transaction import CreditTransaction
from app.models.gpu_allocation import GpuAllocation
from app.models.resource_quota import ResourceQuota
from app.models.server import Server
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.server_volume import ServerVolume
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.schemas.server_queue import QueuedServerResponse
from app.services.credit_hold_service import CreditHoldService
from app.services.server_launch_service import LaunchError, LaunchReservation, ServerLaunchService
from app.services.server_launch_validation import normalize_launch_request

IMAGE_ID = "sha256:" + "a" * 64
OTHER_IMAGE_ID = "sha256:" + "b" * 64


@dataclass(frozen=True)
class LaunchFixture:
    owner_id: uuid.UUID
    plan_id: uuid.UUID
    environment_id: uuid.UUID
    username: str

    def request(self, name="launch-test"):
        return normalize_launch_request(
            {
                "name": name,
                "plan_id": str(self.plan_id),
                "environment_id": str(self.environment_id),
                "volume_mounts": [
                    {
                        "volume_id": "",
                        "mount_path": f"/home/{self.username}",
                        "mode": "read_write",
                        "max_size_bytes": 1024**3,
                    }
                ],
            },
            username=self.username,
        )


def runtime_driver(*, observed_image=IMAGE_ID):
    def resolve(reference):
        return {
            "requested_reference": reference,
            "local_id": OTHER_IMAGE_ID if reference == OTHER_IMAGE_ID else IMAGE_ID,
            "repository_digests": [],
            "os": "linux",
            "architecture": "amd64",
            "registry_verified": False,
        }

    return SimpleNamespace(
        ensure_volume=AsyncMock(),
        image_exists=AsyncMock(return_value=True),
        pull_image=AsyncMock(),
        resolve_image=AsyncMock(side_effect=resolve),
        get_container_info=AsyncMock(return_value={"Image": observed_image}),
    )


@pytest_asyncio.fixture
async def launch_fixture(db_session, test_user, monkeypatch):
    from app.models.environment_template import EnvironmentTemplate

    monkeypatch.setattr(settings, "credits_enabled", True)
    monkeypatch.setattr(settings, "gpu_devices", "")
    monkeypatch.setattr(settings, "resource_pool_cpu", 34.0)
    plan = ServerPlan(
        name="Launch plan",
        slug="launch-plan",
        cpu_limit=1.0,
        memory_limit="1g",
        disk_limit="2g",
        gpu_limit=0,
        cost_per_hour=3,
        is_active=True,
        is_public=True,
    )
    environment = EnvironmentTemplate(
        name="Launch env",
        slug="launch-env",
        image="approved:latest",
        environment_variables={"SECRET_NAME": "private-value"},
        is_active=True,
        is_public=True,
    )
    quota = ResourceQuota(
        user_id=test_user.id,
        max_cpu_total=8,
        max_memory_total="16g",
        max_disk_total="100g",
        max_gpu_total=4,
        max_servers_total=5,
    )
    db_session.add_all([plan, environment, quota])
    await db_session.flush()
    fixture = LaunchFixture(test_user.id, plan.id, environment.id, test_user.username)
    await db_session.commit()
    return fixture


async def resolve_and_reserve(db, fixture, driver=None, name="launch-test"):
    service = ServerLaunchService(db, driver or runtime_driver())
    request = fixture.request(name)
    revision_id = await service.resolve_revision(fixture.owner_id, request)
    outcome = await service.reserve(fixture.owner_id, request, revision_id)
    return service, outcome, revision_id


@pytest.mark.asyncio
async def test_scarcity_enqueues_full_blank_volume_intent_without_allocating(
    db_session, launch_fixture, monkeypatch
):
    monkeypatch.setattr(settings, "resource_pool_cpu", 0.5)
    driver = runtime_driver()
    service = ServerLaunchService(db_session, driver)
    service.spawner.spawn = AsyncMock(side_effect=AssertionError("No runtime while waiting"))
    request = launch_fixture.request()
    revision_id = await service.resolve_revision(launch_fixture.owner_id, request)
    outcome = await service.reserve(launch_fixture.owner_id, request, revision_id)
    assert isinstance(outcome, QueuedServerResponse)
    assert outcome.queue_position == 1
    stored = await db_session.get(ServerQueue, outcome.queue_id)
    expected = request.model_dump(mode="json")
    assert stored.request_payload == expected
    assert stored.request_payload["volume_mounts"][0]["volume_id"] == ""
    assert stored.revision_id == revision_id
    assert stored.plan_snapshot["cost_per_hour"] == 3
    assert stored.reason_code == "capacity_wait"
    for model in (Server, Volume, ServerVolume, VolumeOperation, GpuAllocation, CreditTransaction):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    assert (await db_session.get(User, launch_fixture.owner_id)).nuke_balance == 100
    service.spawner.spawn.assert_not_awaited()
    driver.get_container_info.assert_not_awaited()


@pytest.mark.asyncio
async def test_reservation_persists_server_mounts_and_guard_before_runtime(
    db_session, launch_fixture
):
    service, outcome, _ = await resolve_and_reserve(db_session, launch_fixture)
    assert isinstance(outcome, LaunchReservation)
    server = await db_session.get(Server, outcome.server_id)
    assert server.status == "starting"
    assert server.started_at is None
    assert server.last_billed_at is None
    assert server.container_id is None
    mounts = (
        await db_session.scalars(
            select(ServerVolume).where(
                ServerVolume.server_id == server.id,
            )
        )
    ).all()
    assert len(mounts) == 1
    assert mounts[0].volume_id == server.volume_id
    assert mounts[0].mount_path == f"/home/{launch_fixture.username}"
    guard = await db_session.scalar(
        select(VolumeOperation).where(
            VolumeOperation.operation_id == server.id,
        )
    )
    assert guard.kind == "mount" and guard.state == "reserved"
    assert outcome.mounts[0]["volume_id"] == str(server.volume_id)
    assert outcome.request.volume_mounts[0].volume_id == ""
    assert await db_session.scalar(select(func.count()).select_from(CreditTransaction)) == 0
    service.driver.get_container_info.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_empty_selected_volume_is_marked_for_one_time_initialization(
    db_session, launch_fixture
):
    volume = Volume(
        id=uuid.uuid4(),
        name="existing-empty-volume",
        display_name="Existing empty volume",
        owner_id=launch_fixture.owner_id,
        visibility="private",
        max_size_bytes=1024**3,
        size_bytes=0,
        status="active",
    )
    db_session.add(volume)
    await db_session.flush()
    await db_session.commit()

    request = normalize_launch_request(
        {
            "name": "existing-volume-launch",
            "plan_id": str(launch_fixture.plan_id),
            "environment_id": str(launch_fixture.environment_id),
            "volume_id": str(volume.id),
            "volume_mode": "read_write",
        },
        username=launch_fixture.username,
    )
    service = ServerLaunchService(db_session, runtime_driver())
    revision_id = await service.resolve_revision(launch_fixture.owner_id, request)
    outcome = await service.reserve(launch_fixture.owner_id, request, revision_id)

    assert isinstance(outcome, LaunchReservation)
    assert outcome.mounts[0]["auto_created"] is True
    refreshed = await db_session.get(Volume, volume.id, populate_existing=True)
    assert refreshed.labels["initialize_for_server"] == str(outcome.server_id)


@pytest.mark.asyncio
async def test_exhausted_exclusive_gpu_pool_waits_with_gpu_reason(
    db_session, launch_fixture, monkeypatch
):
    monkeypatch.setattr(settings, "gpu_enabled", True)
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0")
    plan = await db_session.get(ServerPlan, launch_fixture.plan_id)
    plan.gpu_limit = 1
    db_session.add(GpuAllocation(server_id=uuid.uuid4(), device="nvidia.com/gpu=0"))
    await db_session.commit()
    _, outcome, _ = await resolve_and_reserve(db_session, launch_fixture)
    assert isinstance(outcome, QueuedServerResponse)
    entry = await db_session.get(ServerQueue, outcome.queue_id)
    assert entry.reason_code == "gpu_wait"
    assert entry.requested_gpu == 1
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Volume)) == 0


@pytest.mark.asyncio
async def test_changed_plan_cannot_claim_waiting_request(db_session, launch_fixture, monkeypatch):
    monkeypatch.setattr(settings, "resource_pool_cpu", 0.5)
    service, outcome, revision_id = await resolve_and_reserve(db_session, launch_fixture)
    assert isinstance(outcome, QueuedServerResponse)
    queue_id = outcome.queue_id
    plan = await db_session.get(ServerPlan, launch_fixture.plan_id)
    plan.cost_per_hour = 7
    await db_session.commit()
    monkeypatch.setattr(settings, "resource_pool_cpu", 34.0)
    with pytest.raises(LaunchError, match="configuration_changed"):
        await service.reserve(
            launch_fixture.owner_id, launch_fixture.request(), revision_id, queue_id=queue_id
        )
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Volume)) == 0


@pytest.mark.asyncio
async def test_provision_updates_reserved_orm_identity_and_records_actual_image(
    db_session, launch_fixture
):
    service, reservation, _ = await resolve_and_reserve(db_session, launch_fixture)
    assert isinstance(reservation, LaunchReservation)
    reserved = await db_session.get(Server, reservation.server_id)
    await db_session.commit()  # End verification read before service-owned transaction.

    async def spawn(**kwargs):
        assert kwargs["server_id"] == str(reservation.server_id)
        assert kwargs["image"] == IMAGE_ID
        assert kwargs["resolved_images"]["runtime"]["local_id"] == IMAGE_ID
        assert kwargs["volume_mounts"] == reservation.mounts
        assert not db_session.in_transaction()  # No admission lock spans runtime work.
        return Server(
            id=reservation.server_id,
            container_id="runtime-container",
            image=IMAGE_ID,
            external_url="https://server.example.test",
            health_status="healthy",
        )

    service.spawner.spawn = AsyncMock(side_effect=spawn)
    launched = await service.provision(reservation)
    assert launched is reserved
    assert launched.status == "running"
    assert launched.started_at is not None
    assert launched.last_billed_at == launched.started_at
    assert launched.last_activity == launched.started_at
    assert launched.container_id == "runtime-container"
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 1
    record = await db_session.scalar(
        select(ServerLaunchRecord).where(
            ServerLaunchRecord.server_id == reservation.server_id,
        )
    )
    assert record.actual_runtime_identity["local_id"] == IMAGE_ID
    assert record.manifest["environment_variable_names"] == ["SECRET_NAME"]
    assert "private-value" not in str(record.manifest)
    assert (await db_session.get(User, launch_fixture.owner_id)).nuke_balance == 100
    assert await db_session.scalar(select(func.count()).select_from(CreditTransaction)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown_spawn", "wrong_runtime_image"])
async def test_unknown_runtime_failure_keeps_starting_reservation_and_guard(
    db_session, launch_fixture, failure
):
    driver = runtime_driver(
        observed_image=OTHER_IMAGE_ID if failure == "wrong_runtime_image" else IMAGE_ID
    )
    service, reservation, _ = await resolve_and_reserve(db_session, launch_fixture, driver)
    if failure == "unknown_spawn":
        service.spawner.spawn = AsyncMock(side_effect=RuntimeError("runtime outcome unknown"))
    else:
        service.spawner.spawn = AsyncMock(
            return_value=Server(
                id=reservation.server_id,
                container_id="uncertain-container",
                image=IMAGE_ID,
                health_status="healthy",
            )
        )
    with pytest.raises(LaunchError, match="recovery_required"):
        await service.provision(reservation)
    server = await db_session.get(Server, reservation.server_id)
    assert server.status == "starting"
    assert server.status_reason == "recovery_required"
    assert server.last_billed_at is None
    assert server.started_at is None
    guard = await db_session.scalar(
        select(VolumeOperation).where(
            VolumeOperation.operation_id == reservation.server_id,
        )
    )
    assert guard.state == "reserved"
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 0
    assert await db_session.get(Volume, server.volume_id) is not None


@pytest_asyncio.fixture
async def committed_launch_fixture():
    """Commit uniquely owned inputs so independent admission sessions share visibility."""
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.environment_revision import EnvironmentRevision
    from app.models.environment_template import EnvironmentTemplate
    from tests.conftest import test_engine

    marker = uuid.uuid4().hex
    owner_id, plan_id, environment_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fixture = LaunchFixture(owner_id, plan_id, environment_id, f"launch_{marker}")
    async with AsyncSession(test_engine) as db, db.begin():
        db.add(
            User(
                id=owner_id,
                username=fixture.username,
                email=f"{marker}@example.test",
                role="user",
                is_active=True,
                nuke_balance=100,
            )
        )
        db.add(
            ServerPlan(
                id=plan_id,
                name=f"launch-{marker}",
                slug=f"launch-{marker}",
                cpu_limit=1.0,
                memory_limit="1g",
                disk_limit="2g",
                gpu_limit=0,
                is_active=True,
                is_public=True,
                max_servers_per_user=5,
            )
        )
        db.add(
            EnvironmentTemplate(
                id=environment_id,
                name=f"launch-{marker}",
                slug=f"launch-{marker}",
                image="approved:latest",
                is_active=True,
                is_public=True,
            )
        )
        await db.flush()
        db.add(
            ResourceQuota(
                user_id=owner_id,
                max_cpu_total=8,
                max_memory_total="16g",
                max_disk_total="100g",
                max_servers_total=5,
                max_gpu_total=0,
            )
        )
    try:
        yield fixture
    finally:
        async with AsyncSession(test_engine) as cleanup, cleanup.begin():
            await cleanup.execute(delete(ServerQueue).where(ServerQueue.user_id == owner_id))
            await cleanup.execute(
                delete(VolumeOperation).where(VolumeOperation.owner_id == owner_id)
            )
            await cleanup.execute(delete(Server).where(Server.user_id == owner_id))
            await cleanup.execute(delete(Volume).where(Volume.owner_id == owner_id))
            await cleanup.execute(delete(ResourceQuota).where(ResourceQuota.user_id == owner_id))
            await cleanup.execute(
                delete(EnvironmentRevision).where(
                    EnvironmentRevision.template_id == environment_id,
                )
            )
            await cleanup.execute(
                delete(EnvironmentTemplate).where(EnvironmentTemplate.id == environment_id)
            )
            await cleanup.execute(delete(ServerPlan).where(ServerPlan.id == plan_id))
            await cleanup.execute(delete(User).where(User.id == owner_id))


@pytest.mark.asyncio
@pytest.mark.parametrize("same_name", [True, False])
async def test_independent_admission_sessions_serialize_names_and_capacity(
    committed_launch_fixture, monkeypatch, same_name
):
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.conftest import test_engine

    fixture = committed_launch_fixture
    monkeypatch.setattr(settings, "resource_pool_cpu", 1.0)
    monkeypatch.setattr(settings, "gpu_devices", "")
    async with AsyncSession(test_engine) as prepare:
        revision_id = await ServerLaunchService(prepare, runtime_driver()).resolve_revision(
            fixture.owner_id,
            fixture.request(),
        )
    barrier = asyncio.Barrier(2)

    async def reserve(name):
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            try:
                return await ServerLaunchService(db, runtime_driver()).reserve(
                    fixture.owner_id,
                    fixture.request(name),
                    revision_id,
                )
            except LaunchError as exc:
                return exc.code

    results = await asyncio.wait_for(
        asyncio.gather(
            reserve("same-server" if same_name else "first-server"),
            reserve("same-server" if same_name else "second-server"),
        ),
        timeout=10,
    )
    assert sum(isinstance(result, LaunchReservation) for result in results) == 1
    if same_name:
        assert "request_already_exists" in results
    else:
        assert sum(isinstance(result, QueuedServerResponse) for result in results) == 1
    async with AsyncSession(test_engine) as verify:
        servers = (
            await verify.scalars(select(Server).where(Server.user_id == fixture.owner_id))
        ).all()
        assert len(servers) == 1
        assert sum(server.allocated_cpu for server in servers) == 1.0
        assert servers[0].status == "starting"
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(Volume)
                .where(
                    Volume.owner_id == fixture.owner_id,
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_queued_claim_provisions_preserved_request_and_links_real_server(
    db_session, launch_fixture, monkeypatch
):
    monkeypatch.setattr(settings, "resource_pool_cpu", 0.5)
    service, queued, revision_id = await resolve_and_reserve(db_session, launch_fixture)
    assert isinstance(queued, QueuedServerResponse)
    monkeypatch.setattr(settings, "resource_pool_cpu", 34.0)
    reservation = await service.reserve(
        launch_fixture.owner_id,
        launch_fixture.request(),
        revision_id,
        queue_id=queued.queue_id,
    )
    assert isinstance(reservation, LaunchReservation)
    assert reservation.queue_id == queued.queue_id
    assert reservation.claim_token is not None
    entry = await db_session.get(ServerQueue, queued.queue_id)
    assert entry.status == "starting"
    assert entry.server_id == reservation.server_id
    assert entry.claim_token == reservation.claim_token
    assert entry.request_payload["volume_mounts"][0]["volume_id"] == ""
    await db_session.commit()
    service.spawner.spawn = AsyncMock(
        return_value=Server(
            id=reservation.server_id,
            container_id="queued-runtime",
            image=IMAGE_ID,
            external_url="https://queued.example.test",
            health_status="healthy",
        )
    )
    server = await service.provision(reservation)
    linked = await db_session.get(ServerQueue, queued.queue_id)
    assert linked.status == "started"
    assert linked.server_id == server.id
    assert linked.started_at == server.started_at
    assert linked.reason_code is None
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Volume)) == 1
    assert await db_session.scalar(select(func.count()).select_from(CreditTransaction)) == 0


@pytest.mark.asyncio
async def test_successful_provision_redelivery_returns_same_server_without_runtime_or_debit(
    db_session, launch_fixture
):
    service, reservation, _ = await resolve_and_reserve(db_session, launch_fixture)
    service.spawner.spawn = AsyncMock(
        return_value=Server(
            id=reservation.server_id,
            container_id="once-only",
            image=IMAGE_ID,
            external_url="https://once.example.test",
            health_status="healthy",
        )
    )
    first = await service.provision(reservation)
    billed_at = first.last_billed_at
    redelivered = await service.provision(reservation)
    assert redelivered is first
    assert redelivered.last_billed_at == billed_at
    service.spawner.spawn.assert_awaited_once()
    assert service.driver.get_container_info.await_count == 1
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Volume)) == 1
    assert await db_session.scalar(select(func.count()).select_from(CreditTransaction)) == 0
    assert (await db_session.get(User, launch_fixture.owner_id)).nuke_balance == 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,expected",
    [
        ("missing_owner", "permission_revoked"),
        ("disabled_owner", "permission_revoked"),
        ("read_only_role", "permission_revoked"),
        ("missing_plan", "configuration_changed"),
        ("inactive_plan", "configuration_changed"),
        ("private_plan", "permission_revoked"),
        ("missing_environment", "permission_revoked"),
        ("inactive_environment", "permission_revoked"),
        ("private_environment", "permission_revoked"),
        ("disabled_gpu", "gpu_unavailable"),
    ],
)
async def test_current_policy_rejections_precede_image_resolution(
    db_session, launch_fixture, monkeypatch, change, expected
):
    from app.models.environment_template import EnvironmentTemplate

    fixture = launch_fixture
    request = fixture.request()
    owner_id = fixture.owner_id
    if change == "missing_owner":
        owner_id = uuid.uuid4()
    elif change == "missing_plan":
        request = request.model_copy(update={"plan_id": uuid.uuid4()})
    elif change == "missing_environment":
        request = request.model_copy(update={"environment_id": uuid.uuid4()})
    elif change in {"disabled_owner", "read_only_role"}:
        user = await db_session.get(User, owner_id)
        if change == "disabled_owner":
            user.is_active = False
        else:
            user.role = "guest"
    elif change in {"inactive_plan", "private_plan", "disabled_gpu"}:
        plan = await db_session.get(ServerPlan, fixture.plan_id)
        if change == "inactive_plan":
            plan.is_active = False
        elif change == "private_plan":
            plan.is_public = False
            plan.visible_to_roles = []
        else:
            plan.gpu_limit = 1
            monkeypatch.setattr(settings, "gpu_enabled", False)
    else:
        environment = await db_session.get(EnvironmentTemplate, fixture.environment_id)
        if change == "inactive_environment":
            environment.is_active = False
        else:
            environment.is_public = False
    await db_session.commit()
    driver = runtime_driver()
    with pytest.raises(LaunchError, match=expected):
        await ServerLaunchService(db_session, driver).resolve_revision(owner_id, request)
    driver.image_exists.assert_not_awaited()
    driver.resolve_image.assert_not_awaited()
    driver.pull_image.assert_not_awaited()
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Volume)) == 0


@pytest.mark.asyncio
async def test_credit_denial_creates_no_waiting_or_storage_reservation(db_session, launch_fixture):
    service = ServerLaunchService(db_session, runtime_driver())
    request = launch_fixture.request()
    revision_id = await service.resolve_revision(launch_fixture.owner_id, request)
    user = await db_session.get(User, launch_fixture.owner_id)
    user.nuke_balance = 2  # Selected plan costs three per hour.
    await db_session.commit()
    with pytest.raises(LaunchError, match="insufficient_credits") as denial:
        await service.reserve(launch_fixture.owner_id, request, revision_id)
    assert denial.value.status_code == 402
    for model in (Server, Volume, ServerQueue, VolumeOperation, CreditTransaction):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    assert (await db_session.get(User, launch_fixture.owner_id)).nuke_balance == 2


@pytest.mark.asyncio
async def test_held_batch_credits_block_an_interactive_launch(db_session, launch_fixture):
    service = ServerLaunchService(db_session, runtime_driver())
    request = launch_fixture.request()
    revision_id = await service.resolve_revision(launch_fixture.owner_id, request)
    owner = await db_session.get(User, launch_fixture.owner_id)
    owner.nuke_balance = 3  # Exactly the selected plan's hourly cost.
    now = utc_now()
    job = BatchJob(
        user_id=owner.id,
        name="held-batch-job",
        idempotency_key_hash=uuid.uuid4().hex * 2,
        request_fingerprint=uuid.uuid4().hex * 2,
        revision_id=revision_id,
        plan_id=launch_fixture.plan_id,
        argv=["true"],
        max_runtime_seconds=600,
        state="queued",
        state_changed_at=now,
        revision_snapshot={},
        plan_snapshot={},
        volume_snapshot={},
        fencing_token=uuid.uuid4(),
        billing_mode="paid",
        authorized_credits=3,
        billing_rate_per_hour=3,
        billing_state="held",
        created_at=now,
        updated_at=now,
    )
    db_session.add(job)
    await db_session.flush()
    await CreditHoldService.create_hold(db_session, user_id=owner.id, job_id=job.id, amount=3)
    await db_session.commit()

    with pytest.raises(LaunchError, match="insufficient_credits") as denial:
        await service.reserve(launch_fixture.owner_id, request, revision_id)
    assert denial.value.status_code == 402
    for model in (Server, Volume, ServerQueue, VolumeOperation, CreditTransaction):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    assert (await db_session.get(User, launch_fixture.owner_id)).nuke_balance == 3


@pytest.mark.asyncio
async def test_existing_volume_under_backup_cannot_be_reserved_for_launch(
    db_session, launch_fixture
):
    from app.services.volume_operation_service import (
        VolumeOperationError,
        acquire_volume_operations,
    )

    volume = Volume(
        name="protected-launch-data",
        display_name="Data",
        owner_id=launch_fixture.owner_id,
        visibility="private",
        max_size_bytes=1024**3,
        status="active",
    )
    db_session.add(volume)
    await db_session.flush()
    volume_id = volume.id
    await acquire_volume_operations(
        db_session,
        volume_ids=[volume_id],
        owner_id=launch_fixture.owner_id,
        operation_id=uuid.uuid4(),
        kind="backup",
    )
    await db_session.commit()
    request = normalize_launch_request(
        {
            "name": "protected-launch",
            "plan_id": str(launch_fixture.plan_id),
            "environment_id": str(launch_fixture.environment_id),
            "volume_id": str(volume_id),
        },
        username=launch_fixture.username,
    )
    service = ServerLaunchService(db_session, runtime_driver())
    revision_id = await service.resolve_revision(launch_fixture.owner_id, request)
    with pytest.raises(VolumeOperationError, match="volume_busy"):
        await service.reserve(launch_fixture.owner_id, request, revision_id)
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 0
    assert await db_session.scalar(select(func.count()).select_from(ServerVolume)) == 0
    assert await db_session.scalar(select(func.count()).select_from(VolumeOperation)) == 1
    assert (await db_session.get(Volume, volume_id)).last_mounted_at is None


@pytest.mark.asyncio
async def test_workspace_read_only_ceiling_blocks_owner_write_mount(db_session, launch_fixture):
    from app.models.shared_workspace import SharedWorkspace
    from app.models.workspace_volume import WorkspaceVolume
    from app.services.server_launch_validation import LaunchValidationError

    volume = Volume(
        name="read-only-launch-data",
        display_name="Data",
        owner_id=launch_fixture.owner_id,
        max_size_bytes=1024**3,
        status="active",
    )
    workspace = SharedWorkspace(name="Read-only sharing", owner_id=launch_fixture.owner_id)
    db_session.add_all([volume, workspace])
    await db_session.flush()
    volume_id = volume.id
    db_session.add(
        WorkspaceVolume(volume_id=volume_id, workspace_id=workspace.id, role="read_only")
    )
    await db_session.commit()
    request = normalize_launch_request(
        {
            "name": "write-ceiling",
            "plan_id": str(launch_fixture.plan_id),
            "environment_id": str(launch_fixture.environment_id),
            "volume_id": str(volume_id),
            "volume_mode": "read_write",
        },
        username=launch_fixture.username,
    )
    service = ServerLaunchService(db_session, runtime_driver())
    revision_id = await service.resolve_revision(launch_fixture.owner_id, request)
    with pytest.raises(LaunchValidationError, match="volume_unavailable") as denial:
        await service.reserve(launch_fixture.owner_id, request, revision_id)
    assert denial.value.status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 0
    assert await db_session.scalar(select(func.count()).select_from(VolumeOperation)) == 0


@pytest.mark.asyncio
async def test_missing_approved_local_image_is_not_replaced_by_tag_pull(db_session, launch_fixture):
    from app.models.environment_template import EnvironmentTemplate

    environment = await db_session.get(EnvironmentTemplate, launch_fixture.environment_id)
    environment.image = IMAGE_ID
    await db_session.commit()
    driver = runtime_driver()
    driver.image_exists.return_value = False
    service = ServerLaunchService(db_session, driver)
    with pytest.raises(LaunchError, match="artifact_missing"):
        await service.resolve_revision(launch_fixture.owner_id, launch_fixture.request())
    driver.image_exists.assert_awaited_once_with(IMAGE_ID)
    driver.pull_image.assert_not_awaited()
    driver.resolve_image.assert_not_awaited()
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 0


@pytest.mark.asyncio
async def test_resolve_revision_reuses_active_revision_without_re_resolving(
    db_session, launch_fixture
):
    driver = runtime_driver()
    service = ServerLaunchService(db_session, driver)
    request = launch_fixture.request()

    first = await service.resolve_revision(launch_fixture.owner_id, request)
    assert driver.resolve_image.await_count == 1
    assert driver.image_exists.await_count == 1

    second = await service.resolve_revision(launch_fixture.owner_id, request)

    assert second == first
    assert driver.resolve_image.await_count == 2
    assert driver.image_exists.await_count == 2
    driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_reused_revision_missing_local_artifact_never_pulls_mutable_tag(
    db_session, launch_fixture
):
    driver = runtime_driver()
    service = ServerLaunchService(db_session, driver)
    request = launch_fixture.request()
    await service.resolve_revision(launch_fixture.owner_id, request)

    driver.image_exists.return_value = False
    with pytest.raises(LaunchError, match="artifact_missing"):
        await service.resolve_revision(launch_fixture.owner_id, request)

    assert driver.resolve_image.await_count == 1
    driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_active_revision_is_not_silently_replaced_on_resolve(
    db_session, launch_fixture
):
    from app.models.environment_revision import EnvironmentRevision
    from app.services.environment_revision_service import RevisionUnavailable

    driver = runtime_driver()
    service = ServerLaunchService(db_session, driver)
    request = launch_fixture.request()
    revision_id = await service.resolve_revision(launch_fixture.owner_id, request)

    revision = await db_session.get(EnvironmentRevision, revision_id)
    revision.revoked = True
    await db_session.commit()

    with pytest.raises(RevisionUnavailable):
        await service.resolve_revision(launch_fixture.owner_id, request)

    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(EnvironmentRevision)
            .where(EnvironmentRevision.template_id == launch_fixture.environment_id)
        )
        == 1
    )
    driver.pull_image.assert_not_awaited()


def registry_fakes(*, local_id=IMAGE_ID):
    from app.schemas.environment_manifest import ImageIdentity
    from app.services.registry_client import VerifiedImage
    from app.services.registry_image_service import RegistryResolution

    manifest_digest = "sha256:" + "c" * 64
    verified_reference = f"registry.example/approved@{manifest_digest}"
    verified = VerifiedImage(
        requested_reference="approved:latest",
        verified_reference=verified_reference,
        manifest_digest=manifest_digest,
        index_digest="sha256:" + "d" * 64,
        descriptor_media_type="application/vnd.oci.image.manifest.v1+json",
        os="linux",
        architecture="amd64",
        variant=None,
    )
    identity = ImageIdentity(
        requested_reference="approved:latest",
        local_id=local_id,
        repository_digests=[verified_reference],
        os="linux",
        architecture="amd64",
        registry_verified=True,
        verified_reference=verified_reference,
        manifest_digest=manifest_digest,
        index_digest=verified.index_digest,
        descriptor_media_type=verified.descriptor_media_type,
    )
    registry = SimpleNamespace(
        resolve=AsyncMock(
            return_value=RegistryResolution(
                policy="require",
                state="verified",
                verified=verified,
                fallback_reason=None,
                pull_requested=False,
            )
        )
    )
    artifacts = SimpleNamespace(ensure_local=AsyncMock(return_value=identity))
    return registry, artifacts, identity


@pytest.mark.asyncio
async def test_registry_verified_reference_captures_portable_revision(db_session, launch_fixture):
    from app.models.environment_revision import EnvironmentRevision

    driver = runtime_driver()
    registry, artifacts, _ = registry_fakes()
    service = ServerLaunchService(db_session, driver, registry=registry, artifacts=artifacts)
    request = launch_fixture.request()

    revision_id = await service.resolve_revision(launch_fixture.owner_id, request)
    revision = await db_session.get(EnvironmentRevision, revision_id)

    assert revision is not None
    assert revision.runtime_identity["registry_verified"] is True
    assert revision.portable_fingerprint is not None
    registry.resolve.assert_awaited_once_with("approved:latest")
    artifacts.ensure_local.assert_awaited_once()
    driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_reused_verified_revision_requires_exact_local_proof(db_session, launch_fixture):
    driver = runtime_driver()
    registry, artifacts, _ = registry_fakes()
    service = ServerLaunchService(db_session, driver, registry=registry, artifacts=artifacts)
    request = launch_fixture.request()

    first = await service.resolve_revision(launch_fixture.owner_id, request)
    second = await service.resolve_revision(launch_fixture.owner_id, request)

    assert second == first
    registry.resolve.assert_awaited_once()
    assert artifacts.ensure_local.await_count == 2
    driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_registry_require_failure_maps_to_launch_error(db_session, launch_fixture):
    from app.services.registry_client import RegistryError

    driver = runtime_driver()
    registry = SimpleNamespace(
        resolve=AsyncMock(side_effect=RegistryError("registry_unreachable", "offline"))
    )
    service = ServerLaunchService(
        db_session, driver, registry=registry, artifacts=SimpleNamespace()
    )

    with pytest.raises(LaunchError) as failure:
        await service.resolve_revision(launch_fixture.owner_id, launch_fixture.request())

    assert failure.value.code == "registry_unreachable"
    assert failure.value.status_code == 503
    driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_template_change_during_image_resolution_cannot_approve_stale_configuration(
    db_session, launch_fixture
):
    from app.models.environment_template import EnvironmentTemplate
    from app.services.environment_revision_service import ConfigurationChanged

    driver = runtime_driver()
    original_resolve = driver.resolve_image.side_effect

    async def resolve_while_template_changes(reference):
        # Image I/O is outside SQL locks; simulate an admin committing a template edit.
        assert not db_session.in_transaction()
        async with db_session.begin():
            environment = await db_session.get(EnvironmentTemplate, launch_fixture.environment_id)
            environment.image = "approved:new"
        return original_resolve(reference)

    driver.resolve_image.side_effect = resolve_while_template_changes
    with pytest.raises(ConfigurationChanged):
        await ServerLaunchService(db_session, driver).resolve_revision(
            launch_fixture.owner_id,
            launch_fixture.request(),
        )
    from app.models.environment_revision import EnvironmentRevision

    assert await db_session.scalar(select(func.count()).select_from(EnvironmentRevision)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["revoked", "missing", "different_template"])
async def test_unavailable_or_mismatched_revision_cannot_reserve(
    db_session, launch_fixture, unavailable
):
    from app.models.environment_revision import EnvironmentRevision
    from app.models.environment_template import EnvironmentTemplate
    from app.services.environment_revision_service import RevisionUnavailable

    fixture = launch_fixture
    service = ServerLaunchService(db_session, runtime_driver())
    request = fixture.request()
    revision_id = await service.resolve_revision(fixture.owner_id, request)
    if unavailable == "revoked":
        revision = await db_session.get(EnvironmentRevision, revision_id)
        revision.revoked = True
        await db_session.commit()
    elif unavailable == "missing":
        revision_id = uuid.uuid4()
    else:
        environment = EnvironmentTemplate(
            name="Other approval",
            slug="other-approval",
            image="approved:other",
            is_public=True,
            is_active=True,
        )
        db_session.add(environment)
        await db_session.flush()
        other_id = environment.id
        await db_session.commit()
        revision_id = await service.resolve_revision(
            fixture.owner_id, request.model_copy(update={"environment_id": other_id})
        )
    expected_exception = LaunchError if unavailable == "different_template" else RevisionUnavailable
    with pytest.raises(
        expected_exception,
        match="revision_unavailable" if unavailable == "different_template" else "unavailable",
    ):
        await service.reserve(fixture.owner_id, request, revision_id)
    assert await db_session.scalar(select(func.count()).select_from(Server)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Volume)) == 0
    assert await db_session.scalar(select(func.count()).select_from(ServerQueue)) == 0


@pytest.mark.asyncio
async def test_captured_local_image_disappearing_before_provision_never_pulls_mutable_tag(
    db_session, launch_fixture
):
    from app.container.driver import ContainerDriverError

    driver = runtime_driver()
    service, reservation, _ = await resolve_and_reserve(db_session, launch_fixture, driver)
    original_resolve = driver.resolve_image.side_effect

    def artifact_disappeared(reference):
        if reference == IMAGE_ID:
            raise ContainerDriverError("Recorded local artifact no longer exists")
        return original_resolve(reference)

    driver.resolve_image.side_effect = artifact_disappeared
    # Exercise the real spawner's pinned-artifact branch, before any runtime creation.
    with pytest.raises(LaunchError, match="recovery_required"):
        await service.provision(reservation)
    driver.pull_image.assert_not_awaited()
    driver.get_container_info.assert_not_awaited()
    assert driver.resolve_image.await_args.args == (IMAGE_ID,)
    server = await db_session.get(Server, reservation.server_id)
    assert server.status == "starting"
    assert server.status_reason == "recovery_required"
    assert server.container_id is None
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 0
