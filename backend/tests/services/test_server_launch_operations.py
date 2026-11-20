# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Successive launch generations and duplicate delivery executor exclusion."""

import uuid
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.container.driver import ContainerDriverError
from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_volume import ServerVolume
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.services.server_launch_service import LaunchError
from app.services.server_operation_service import claim_operation, create_operation
from app.services.volume_operation_service import acquire_volume_operations
from tests.services.test_server_launch_service import IMAGE_ID, resolve_and_reserve
from tests.services.test_server_launch_service import launch_fixture as launch_fixture


def spawned(server_id, container_id="old-runtime"):
    return Server(
        id=server_id,
        container_id=container_id,
        image=IMAGE_ID,
        health_status="healthy",
        external_url="https://runtime.example.test",
    )


@pytest.mark.asyncio
async def test_initial_intent_has_journal_and_duplicate_claim_never_changes_executor_state(
    db_session, launch_fixture
):
    service, reservation, _ = await resolve_and_reserve(db_session, launch_fixture)
    assert reservation.operation_id == reservation.server_id
    row = await db_session.get(ServerLaunchOperation, reservation.operation_id)
    assert row.action == "create" and row.state == "prepared" and row.generation == 1
    assert row.mounts == reservation.mounts
    assert row.resources == {"cpu": 1.0, "memory": "1g", "disk": "2g", "gpu": 0}
    await claim_operation(db_session, row.id, row.fencing_token)
    await db_session.commit()
    service.spawner.spawn = AsyncMock()
    with pytest.raises(LaunchError, match="launch_in_progress"):
        await service.provision(reservation)
    row = await db_session.get(ServerLaunchOperation, reservation.operation_id)
    server = await db_session.get(Server, reservation.server_id)
    assert row.state == "executing" and row.reason_code is None
    assert server.status_reason is None
    service.spawner.spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_claiming_executor_can_mark_uncertain_and_replay_never_respawns(
    db_session, launch_fixture
):
    service, reservation, _ = await resolve_and_reserve(db_session, launch_fixture)
    service.spawner.spawn = AsyncMock(side_effect=RuntimeError("late runtime outcome"))
    with pytest.raises(LaunchError, match="recovery_required"):
        await service.provision(reservation)
    row = await db_session.get(ServerLaunchOperation, reservation.operation_id)
    assert row.state == "uncertain" and row.reason_code == "recovery_required"
    original_update = row.updated_at
    await db_session.commit()
    with pytest.raises(LaunchError, match="launch_in_progress"):
        await service.provision(reservation)
    row = await db_session.get(ServerLaunchOperation, reservation.operation_id)
    assert row.state == "uncertain" and row.updated_at == original_update
    assert service.spawner.spawn.await_count == 1


async def successor(db, fixture):
    service, first, _ = await resolve_and_reserve(db, fixture)
    service.spawner.spawn = AsyncMock(return_value=spawned(first.server_id))
    await service.provision(first)
    operation_id = uuid.uuid4()
    desired_volume = Volume(
        id=uuid.uuid4(),
        name="new-" + uuid.uuid4().hex,
        display_name="Replacement data",
        owner_id=fixture.owner_id,
        visibility="private",
        status="active",
        max_size_bytes=1024**3,
    )
    db.add(desired_volume)
    await db.flush()
    server = await db.get(Server, first.server_id)
    server.status = "starting"
    # The larger old allocation must stay reserved until termination is proven.
    server.allocated_cpu = 4.0
    desired_mount = deepcopy(first.mounts[0]) | {
        "volume_id": str(desired_volume.id),
        "volume_name": desired_volume.name,
        "auto_created": True,
    }
    db.add_all(
        [
            GpuAllocation(server_id=server.id, device="old-only"),
            GpuAllocation(server_id=server.id, device="selected"),
        ]
    )
    await acquire_volume_operations(
        db,
        volume_ids=[uuid.UUID(first.mounts[0]["volume_id"]), desired_volume.id],
        owner_id=fixture.owner_id,
        operation_id=operation_id,
        kind="mount",
    )
    await create_operation(
        db,
        server_id=server.id,
        owner_id=fixture.owner_id,
        action="update",
        operation_id=operation_id,
        revision_id=first.revision_id,
        request_payload=first.request.model_dump(mode="json"),
        mounts=[desired_mount],
        previous_mounts=first.mounts,
        gpu_devices=["selected"],
        username=fixture.username,
        environment_slug=first.environment_slug,
        resources={"cpu": 2.0, "memory": "1g", "disk": "2g", "gpu": 1},
        generation=2,
        previous_container_id="old-runtime",
        previous_status="running",
    )
    await db.commit()
    reservation = await service.load_operation_reservation(operation_id, fixture.owner_id)
    service.spawner.spawn = AsyncMock(return_value=spawned(first.server_id, "new-runtime"))
    service.driver.stop_container = AsyncMock()
    service.driver.delete_container = AsyncMock()
    return service, first, reservation


def previous_info(reservation, *, running=False, foreign=False):
    return {
        "Image": IMAGE_ID,
        "State": {"Running": running},
        "Config": {
            "Labels": {
                "nukelab.server.id": str(uuid.uuid4()) if foreign else str(reservation.server_id),
                "nukelab.user.id": str(reservation.owner_id),
            }
        },
    }


@pytest.mark.asyncio
async def test_successive_generation_swaps_membership_and_releases_only_obsolete_reservations(
    db_session, launch_fixture
):
    service, first, reservation = await successor(db_session, launch_fixture)
    service.driver.get_container_info.side_effect = [
        previous_info(reservation, running=True),
        previous_info(reservation),
        {"Image": IMAGE_ID},
    ]
    server = await service.provision(reservation)
    assert server.id == first.server_id and server.container_id == "new-runtime"
    assert server.allocated_cpu == 2.0 and server.allocated_gpu == 1
    service.driver.stop_container.assert_awaited_once_with("old-runtime")
    service.driver.delete_container.assert_awaited_once_with("old-runtime", force=False)
    assert service.spawner.spawn.call_args.kwargs["launch_operation_id"] == str(
        reservation.operation_id
    )
    assert (
        await db_session.get(ServerLaunchOperation, reservation.operation_id)
    ).state == "succeeded"
    records = (
        await db_session.scalars(
            select(ServerLaunchRecord)
            .where(ServerLaunchRecord.server_id == server.id)
            .order_by(ServerLaunchRecord.generation)
        )
    ).all()
    assert [record.generation for record in records] == [1, 2]
    assert records[1].id == reservation.operation_id
    memberships = (
        await db_session.scalars(select(ServerVolume).where(ServerVolume.server_id == server.id))
    ).all()
    assert [str(mount.volume_id) for mount in memberships] == [reservation.mounts[0]["volume_id"]]
    guards = (
        await db_session.scalars(
            select(VolumeOperation).where(
                VolumeOperation.operation_id.in_([first.operation_id, reservation.operation_id])
            )
        )
    ).all()
    assert all(
        guard.state
        == (
            "reserved"
            if guard.operation_id == reservation.operation_id
            and str(guard.volume_id) == reservation.mounts[0]["volume_id"]
            else "succeeded"
        )
        for guard in guards
    )
    assert list(
        await db_session.scalars(
            select(GpuAllocation.device).where(GpuAllocation.server_id == server.id)
        )
    ) == ["selected"]
    await db_session.commit()
    replayed = await service.provision(reservation)
    assert replayed.id == server.id
    assert service.spawner.spawn.await_count == 1


@pytest.mark.parametrize(
    "failure", ["foreign_labels", "inspection_unavailable", "still_running", "delete_failed"]
)
@pytest.mark.asyncio
async def test_unknown_predecessor_never_releases_guards_or_rewrites_membership(
    db_session, launch_fixture, failure
):
    service, first, reservation = await successor(db_session, launch_fixture)
    if failure == "inspection_unavailable":
        service.driver.get_container_info.side_effect = ContainerDriverError("unavailable", 503)
    elif failure == "foreign_labels":
        service.driver.get_container_info.return_value = previous_info(reservation, foreign=True)
    elif failure == "still_running":
        service.driver.get_container_info.return_value = previous_info(reservation, running=True)
    else:
        service.driver.get_container_info.return_value = previous_info(reservation)
        service.driver.delete_container.side_effect = ContainerDriverError("delete failed", 503)
    with pytest.raises(LaunchError, match="recovery_required"):
        await service.provision(reservation)
    service.spawner.spawn.assert_not_awaited()
    if failure != "delete_failed":
        service.driver.delete_container.assert_not_awaited()
    server = await db_session.get(Server, first.server_id)
    assert server.container_id == "old-runtime" and server.allocated_cpu == 4.0
    assert server.volume_id == uuid.UUID(first.mounts[0]["volume_id"])
    guards = (
        await db_session.scalars(
            select(VolumeOperation).where(
                VolumeOperation.operation_id.in_([first.operation_id, reservation.operation_id])
            )
        )
    ).all()
    assert all(guard.state == "reserved" for guard in guards)
    assert (
        await db_session.get(ServerLaunchOperation, reservation.operation_id)
    ).state == "uncertain"
