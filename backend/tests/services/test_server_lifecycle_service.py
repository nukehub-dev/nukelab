# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Lifecycle admission policy, capacity handover and legacy resume regressions."""

import uuid
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.container.driver import ContainerDriverError
from app.models.environment_template import EnvironmentTemplate
from app.models.gpu_allocation import GpuAllocation
from app.models.resource_quota import ResourceQuota
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_plan import ServerPlan
from app.models.server_volume import ServerVolume
from app.models.shared_workspace import SharedWorkspace
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.models.workspace_volume import WorkspaceVolume
from app.services.server_launch_service import LaunchError
from app.services.server_launch_validation import LaunchValidationError
from app.services.server_lifecycle_service import ServerLifecycleService
from tests.services.test_server_launch_service import IMAGE_ID, resolve_and_reserve, runtime_driver
from tests.services.test_server_launch_service import launch_fixture as launch_fixture


def spawn_result(server_id, container="old-runtime"):
    return Server(
        id=server_id,
        container_id=container,
        image=IMAGE_ID,
        health_status="healthy",
        external_url="https://runtime.example.test",
    )


async def captured(db, fixture):
    driver = runtime_driver()
    launch, initial, _ = await resolve_and_reserve(db, fixture, driver)
    launch.spawner.spawn = AsyncMock(return_value=spawn_result(initial.server_id))
    await launch.provision(initial)
    return ServerLifecycleService(db, driver), initial


async def workspace_ceiling(db, fixture, volume_id):
    workspace = SharedWorkspace(id=uuid.uuid4(), name="Readonly ceiling", owner_id=fixture.owner_id)
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceVolume(workspace_id=workspace.id, volume_id=volume_id, role="read_only"))
    await db.commit()


@pytest.mark.parametrize("action", ["start", "restart", "update"])
@pytest.mark.asyncio
async def test_shrink_holds_old_allocations_and_counts_own_server_once(
    db_session, launch_fixture, monkeypatch, action
):
    lifecycle, initial = await captured(db_session, launch_fixture)
    monkeypatch.setattr(settings, "gpu_enabled", True)
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0,nvidia.com/gpu=1")
    server = await db_session.get(Server, initial.server_id)
    server.allocated_cpu, server.allocated_memory, server.allocated_disk, server.allocated_gpu = (
        4.0,
        "4g",
        "8g",
        2,
    )
    plan = await db_session.get(ServerPlan, launch_fixture.plan_id)
    plan.cpu_limit, plan.memory_limit, plan.disk_limit, plan.gpu_limit = 2.0, "2g", "4g", 1
    quota = await db_session.scalar(
        select(ResourceQuota).where(ResourceQuota.user_id == launch_fixture.owner_id)
    )
    quota.max_cpu_total, quota.max_memory_total, quota.max_gpu_total, quota.max_servers_total = (
        2.0,
        "2g",
        1,
        1,
    )
    db_session.add_all(
        [
            GpuAllocation(server_id=server.id, device="nvidia.com/gpu=0"),
            GpuAllocation(server_id=server.id, device="nvidia.com/gpu=1"),
        ]
    )
    await db_session.commit()
    reservation = await lifecycle.reserve_existing(
        server.id, owner_id=launch_fixture.owner_id, action=action
    )
    server = await db_session.get(Server, server.id)
    if action == "start":
        assert reservation is server and server.status == "running"
        return
    assert server.status == "starting" and server.container_id == "old-runtime"
    assert (
        server.allocated_cpu,
        server.allocated_memory,
        server.allocated_disk,
        server.allocated_gpu,
    ) == (4.0, "4096m", "8192m", 2)
    operation = await db_session.get(ServerLaunchOperation, reservation.operation_id)
    assert operation.action == action and operation.generation == 2
    assert operation.resources == {"cpu": 2.0, "memory": "2g", "disk": "4g", "gpu": 1}
    assert len(operation.gpu_devices) == 1
    assert (
        len(
            list(
                await db_session.scalars(
                    select(GpuAllocation).where(GpuAllocation.server_id == server.id)
                )
            )
        )
        == 2
    )
    quota = await db_session.scalar(
        select(ResourceQuota).where(ResourceQuota.user_id == launch_fixture.owner_id)
    )
    assert quota.usage_servers == 1 and quota.usage_cpu == 4.0 and quota.usage_gpu == 2


@pytest.mark.asyncio
async def test_replacement_cannot_admit_into_an_already_overcommitted_pool(
    db_session, launch_fixture, monkeypatch
):
    lifecycle, initial = await captured(db_session, launch_fixture)
    monkeypatch.setattr(settings, "resource_pool_cpu", 3.0)
    server = await db_session.get(Server, initial.server_id)
    server.allocated_cpu = 2.0
    plan = await db_session.get(ServerPlan, launch_fixture.plan_id)
    plan.cpu_limit = 2.0
    db_session.add(
        Server(
            id=uuid.uuid4(),
            user_id=launch_fixture.owner_id,
            name="other-allocation",
            status="running",
            allocated_cpu=2.0,
            allocated_memory="1g",
            allocated_disk="2g",
            allocated_gpu=0,
        )
    )
    await db_session.commit()
    with pytest.raises(LaunchError, match="capacity_wait"):
        await lifecycle.reserve_existing(
            initial.server_id, owner_id=launch_fixture.owner_id, action="restart"
        )


@pytest.mark.asyncio
async def test_active_journal_blocks_overlapping_lifecycle_actions(db_session, launch_fixture):
    lifecycle, initial = await captured(db_session, launch_fixture)
    first = await lifecycle.reserve_existing(
        initial.server_id, owner_id=launch_fixture.owner_id, action="restart"
    )
    with pytest.raises(LaunchError, match="launch_in_progress"):
        await lifecycle.reserve_existing(
            initial.server_id, owner_id=launch_fixture.owner_id, action="update"
        )
    active = await db_session.scalar(
        select(ServerLaunchOperation).where(
            ServerLaunchOperation.server_id == initial.server_id,
            ServerLaunchOperation.state == "prepared",
        )
    )
    assert active.id == first.operation_id


@pytest.mark.asyncio
async def test_changed_mutable_template_does_not_replace_captured_revision(
    db_session, launch_fixture
):
    lifecycle, initial = await captured(db_session, launch_fixture)
    template = await db_session.get(EnvironmentTemplate, launch_fixture.environment_id)
    template.image = "changed:latest"
    template.environment_variables = {"OTHER": "new-value"}
    await db_session.commit()
    lifecycle.driver.resolve_image.reset_mock()
    result = await lifecycle.reserve_existing(
        initial.server_id, owner_id=launch_fixture.owner_id, action="restart"
    )
    assert result.revision_id == initial.revision_id and result.generation == 2
    lifecycle.driver.resolve_image.assert_not_awaited()
    lifecycle.driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_journals_union_of_old_and_desired_mounts_before_runtime(
    db_session, launch_fixture
):
    lifecycle, initial = await captured(db_session, launch_fixture)
    request = launch_fixture.request("launch-test")
    reserved = await lifecycle.reserve_existing(
        initial.server_id, owner_id=launch_fixture.owner_id, request=request, action="update"
    )
    assert reserved.mounts[0]["volume_id"] != initial.mounts[0]["volume_id"]
    operation = await db_session.get(ServerLaunchOperation, reserved.operation_id)
    assert operation.previous_mounts[0]["volume_id"] == initial.mounts[0]["volume_id"]
    guards = list(
        await db_session.scalars(
            select(VolumeOperation).where(VolumeOperation.operation_id == operation.id)
        )
    )
    assert {str(guard.volume_id) for guard in guards} == {
        initial.mounts[0]["volume_id"],
        reserved.mounts[0]["volume_id"],
    }
    assert all(guard.state == "reserved" for guard in guards)
    memberships = list(
        await db_session.scalars(
            select(ServerVolume).where(ServerVolume.server_id == initial.server_id)
        )
    )
    assert [str(mount.volume_id) for mount in memberships] == [initial.mounts[0]["volume_id"]]


@pytest.mark.parametrize(
    "change,code",
    [
        ("role", "permission_revoked"),
        ("inactive", "permission_revoked"),
        ("credits", "insufficient_credits"),
        ("volume", "volume_unavailable"),
    ],
)
@pytest.mark.asyncio
async def test_current_owner_policy_and_volume_access_are_rechecked(
    db_session, launch_fixture, change, code
):
    lifecycle, initial = await captured(db_session, launch_fixture)
    owner = await db_session.get(User, launch_fixture.owner_id)
    if change == "role":
        owner.role = "guest"
    elif change == "inactive":
        owner.is_active = False
    elif change == "credits":
        owner.nuke_balance = 0
    else:
        await workspace_ceiling(
            db_session, launch_fixture, uuid.UUID(initial.mounts[0]["volume_id"])
        )
    await db_session.commit()
    with pytest.raises((LaunchError, LaunchValidationError), match=code):
        await lifecycle.reserve_existing(
            initial.server_id, owner_id=launch_fixture.owner_id, action="restart"
        )


@pytest.mark.asyncio
async def test_gpu_shrink_releases_extra_old_devices_only_after_verified_runtime_termination(
    db_session, launch_fixture, monkeypatch
):
    lifecycle, initial = await captured(db_session, launch_fixture)
    monkeypatch.setattr(settings, "gpu_enabled", True)
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0,nvidia.com/gpu=1")
    server = await db_session.get(Server, initial.server_id)
    server.allocated_gpu = 2
    plan = await db_session.get(ServerPlan, launch_fixture.plan_id)
    plan.gpu_limit = 1
    db_session.add_all(
        [
            GpuAllocation(server_id=server.id, device="nvidia.com/gpu=0"),
            GpuAllocation(server_id=server.id, device="nvidia.com/gpu=1"),
        ]
    )
    await db_session.commit()
    reservation = await lifecycle.reserve_existing(
        initial.server_id, owner_id=launch_fixture.owner_id, action="restart"
    )
    lifecycle.driver.stop_container, lifecycle.driver.delete_container = AsyncMock(), AsyncMock()
    labels = {"nukelab.server.id": str(initial.server_id), "nukelab.user.id": str(initial.owner_id)}
    lifecycle.driver.get_container_info.side_effect = [
        {"Id": "old-runtime", "Config": {"Labels": labels}, "State": {"Running": True}},
        {"Id": "old-runtime", "Config": {"Labels": labels}, "State": {"Running": False}},
        {"Image": IMAGE_ID},
    ]
    lifecycle.spawner.spawn = AsyncMock(return_value=spawn_result(initial.server_id, "new-runtime"))
    result = await lifecycle.provision(reservation)
    assert result.allocated_gpu == 1
    remaining = list(
        await db_session.scalars(
            select(GpuAllocation.device).where(GpuAllocation.server_id == result.id)
        )
    )
    assert remaining == reservation.gpu_devices
    lifecycle.driver.delete_container.assert_awaited_once_with("old-runtime", force=False)


@pytest.mark.asyncio
async def test_retired_gpu_device_is_not_selected_for_replacement(
    db_session, launch_fixture, monkeypatch
):
    lifecycle, initial = await captured(db_session, launch_fixture)
    monkeypatch.setattr(settings, "gpu_enabled", True)
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=1")
    server = await db_session.get(Server, initial.server_id)
    server.allocated_gpu = 1
    plan = await db_session.get(ServerPlan, launch_fixture.plan_id)
    plan.gpu_limit = 1
    db_session.add(GpuAllocation(server_id=server.id, device="nvidia.com/gpu=0"))
    await db_session.commit()
    reservation = await lifecycle.reserve_existing(
        server.id, owner_id=launch_fixture.owner_id, action="restart"
    )
    assert reservation.gpu_devices == ["nvidia.com/gpu=1"]
    # The removed device may still be mounted by the old runtime; keep its row.
    assert set(
        await db_session.scalars(
            select(GpuAllocation.device).where(GpuAllocation.server_id == server.id)
        )
    ) == {"nvidia.com/gpu=0", "nvidia.com/gpu=1"}


async def legacy(db, fixture, *, container_id="legacy-runtime", gpu=0):
    volume = Volume(
        id=uuid.uuid4(),
        name="legacy-" + uuid.uuid4().hex,
        display_name="Legacy data",
        owner_id=fixture.owner_id,
        visibility="private",
        status="active",
        max_size_bytes=1024**3,
    )
    db.add(volume)
    await db.flush()
    server = Server(
        id=uuid.uuid4(),
        name="legacy-" + uuid.uuid4().hex[:8],
        user_id=fixture.owner_id,
        status="stopped",
        container_id=container_id,
        volume_id=volume.id,
        volume_mode="read_write",
        allocated_cpu=1.0,
        allocated_memory="1g",
        allocated_disk="2g",
        allocated_gpu=gpu,
    )
    db.add(server)
    await db.flush()
    await db.commit()
    return server


@pytest.mark.asyncio
@pytest.mark.parametrize("already_running", [False, True])
async def test_legacy_container_resumes_without_fabricating_provenance(
    db_session, launch_fixture, already_running
):
    server = await legacy(db_session, launch_fixture)
    driver = runtime_driver()
    driver.start_container = AsyncMock()
    if already_running:
        driver.start_container.side_effect = ContainerDriverError("already started", 304)
    labels = {"nukelab.server.id": str(server.id), "nukelab.user.id": str(launch_fixture.owner_id)}
    before = {
        "Id": "legacy-runtime",
        "Image": IMAGE_ID,
        "Config": {"Labels": labels},
        "State": {"Running": already_running},
    }
    after = deepcopy(before)
    after["State"]["Running"] = True
    driver.get_container_info.side_effect = [before, after]
    service = ServerLifecycleService(db_session, driver)
    service.spawner.spawn = AsyncMock()
    result = await service.start(server.id, owner_id=launch_fixture.owner_id)
    assert result.status == "running" and result.container_id == "legacy-runtime"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ServerLaunchRecord)
            .where(ServerLaunchRecord.server_id == result.id)
        )
        == 0
    )
    driver.start_container.assert_awaited_once_with("legacy-runtime")
    driver.pull_image.assert_not_awaited()
    service.spawner.spawn.assert_not_awaited()


@pytest.mark.parametrize(
    "mode", ["exclusive_gpu", "missing_identity", "missing_runtime", "restart"]
)
@pytest.mark.asyncio
async def test_legacy_missing_configuration_never_authorizes_recreation(
    db_session, launch_fixture, monkeypatch, mode
):
    if mode == "exclusive_gpu":
        monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0")
    server = await legacy(
        db_session,
        launch_fixture,
        container_id=None if mode == "missing_identity" else "legacy-runtime",
        gpu=1 if mode == "exclusive_gpu" else 0,
    )
    driver = runtime_driver()
    driver.start_container = AsyncMock()
    driver.get_container_info.side_effect = ContainerDriverError("missing", 404)
    service = ServerLifecycleService(db_session, driver)
    service.spawner.spawn = AsyncMock()
    with pytest.raises(
        LaunchError,
        match="recovery_required" if mode == "missing_runtime" else "revision_unavailable",
    ):
        await service.start(
            server.id,
            owner_id=launch_fixture.owner_id,
            action="restart" if mode == "restart" else "start",
        )
    driver.pull_image.assert_not_awaited()
    service.spawner.spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_resume_respects_current_workspace_volume_ceiling(db_session, launch_fixture):
    server = await legacy(db_session, launch_fixture)
    await workspace_ceiling(db_session, launch_fixture, server.volume_id)
    service = ServerLifecycleService(db_session, runtime_driver())
    with pytest.raises((LaunchError, LaunchValidationError), match="volume_unavailable"):
        await service.reserve_existing(server.id, owner_id=launch_fixture.owner_id)


@pytest.mark.asyncio
async def test_revision_resolution_cannot_overwrite_a_completed_intervening_edit(
    db_session, launch_fixture, monkeypatch
):
    lifecycle, initial = await captured(db_session, launch_fixture)
    environment = EnvironmentTemplate(
        name="New selection",
        slug="new-selection",
        image="approved:new",
        is_active=True,
        is_public=True,
    )
    db_session.add(environment)
    await db_session.commit()
    request = launch_fixture.request().model_copy(update={"environment_id": environment.id})

    async def resolve(*_):
        server = await db_session.get(Server, initial.server_id)
        server.name = "newer-name"
        await db_session.commit()
        return initial.revision_id

    monkeypatch.setattr(lifecycle, "resolve_revision", resolve)
    with pytest.raises(LaunchError, match="configuration_changed"):
        await lifecycle.reserve_existing(initial.server_id, request=request, action="update")
    server = await db_session.get(Server, initial.server_id)
    assert server.name == "newer-name" and server.status == "running"
    active = await db_session.scalar(
        select(ServerLaunchOperation).where(
            ServerLaunchOperation.server_id == initial.server_id,
            ServerLaunchOperation.state.in_(["prepared", "executing", "uncertain"]),
        )
    )
    assert active is None


@pytest.mark.asyncio
async def test_running_edit_rejects_a_stale_selection_before_admission(
    db_session, launch_fixture, monkeypatch
):
    lifecycle, initial = await captured(db_session, launch_fixture)
    start = lifecycle.start

    async def interleave(*args, **kwargs):
        server = await db_session.get(Server, initial.server_id)
        server.name = "newer-name"
        await db_session.commit()
        return await start(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "start", interleave)
    with pytest.raises(LaunchError, match="configuration_changed"):
        await lifecycle.update(initial.server_id, {"name": "stale-name"})
    server = await db_session.get(Server, initial.server_id)
    assert server.name == "newer-name"
