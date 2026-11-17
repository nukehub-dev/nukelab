# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Termination only releases persistent allocations after verified runtime absence."""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container.driver import ContainerDriverError
from app.models.credit_transaction import CreditTransaction
from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_volume import ServerVolume
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.services.server_launch_service import LaunchError
from app.services.server_termination_service import ServerTerminationService
from tests.conftest import test_engine
from tests.services.test_server_launch_service import (
    committed_launch_fixture as committed_launch_fixture,
)


@dataclass(frozen=True)
class TerminationFixture:
    owner_id: UUID
    server_id: UUID
    volume_ids: list[UUID]
    previous_operation_id: UUID

    def inspect(self, *, running=True):
        return {
            "Id": "owned-runtime",
            "Config": {
                "Labels": {
                    "nukelab.server.id": str(self.server_id),
                    "nukelab.user.id": str(self.owner_id),
                }
            },
            "State": {"Running": running},
        }


@pytest_asyncio.fixture
async def termination_fixture(db_session, test_user):
    owner_id = test_user.id
    first, second = uuid4(), uuid4()
    server_id, previous_operation_id = uuid4(), uuid4()
    for volume_id in (first, second):
        db_session.add(
            Volume(
                id=volume_id,
                name=f"terminate-{volume_id}",
                display_name="Data",
                owner_id=owner_id,
                size_bytes=0,
                max_size_bytes=1024**3,
                status="active",
            )
        )
    await db_session.flush()
    db_session.add(
        Server(
            id=server_id,
            name="terminate",
            user_id=owner_id,
            status="running",
            container_id="owned-runtime",
            volume_id=first,
            allocated_cpu=2.0,
            allocated_memory="2g",
            allocated_disk="2g",
            allocated_gpu=1,
        )
    )
    await db_session.flush()
    # Deliberately cover both legacy primary volume and additional association.
    db_session.add(
        ServerVolume(
            server_id=server_id,
            volume_id=second,
            mount_path="/other",
            mode="read_write",
            is_primary=False,
        )
    )
    db_session.add(
        ServerLaunchOperation(
            id=previous_operation_id,
            server_id=server_id,
            owner_id=owner_id,
            action="restart",
            state="succeeded",
            fencing_token=uuid4(),
            username="testuser",
            resources={"cpu": 2, "memory": "2g", "disk": "2g", "gpu": 1},
            mounts=[],
            gpu_devices=[],
        )
    )
    db_session.add_all(
        [
            VolumeOperation(
                operation_id=server_id,
                volume_id=first,
                owner_id=owner_id,
                kind="mount",
                state="running",
                fencing_token=uuid4(),
            ),
            VolumeOperation(
                operation_id=previous_operation_id,
                volume_id=second,
                owner_id=owner_id,
                kind="mount",
                state="reserved",
                fencing_token=uuid4(),
            ),
            GpuAllocation(server_id=server_id, device=f"nvidia.com/gpu={uuid4()}"),
        ]
    )
    await db_session.commit()
    return TerminationFixture(owner_id, server_id, [first, second], previous_operation_id)


def driver(fixture, *, running=True):
    return SimpleNamespace(
        get_container_info=AsyncMock(
            side_effect=[fixture.inspect(running=running), ContainerDriverError("missing", 404)]
        ),
        stop_container=AsyncMock(),
        delete_container=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_stop_confirms_owned_runtime_absence_then_releases_all_mount_generations(
    db_session, termination_fixture
):
    fixture = termination_fixture
    runtime = driver(fixture)

    async def stop(container_id):
        assert not db_session.in_transaction()
        assert container_id == "owned-runtime"
        # Transaction-closed cached state proves resources were retained during I/O.

    runtime.stop_container.side_effect = stop
    server = await ServerTerminationService(db_session, runtime).stop(
        fixture.server_id, fixture.owner_id
    )
    assert server.status == "stopped" and server.container_id is None
    assert server.stopped_at is not None and server.expires_at is None
    runtime.delete_container.assert_awaited_once_with("owned-runtime", force=False)
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == fixture.server_id)
        )
        == 0
    )
    guards = (
        await db_session.scalars(
            select(VolumeOperation).where(VolumeOperation.volume_id.in_(fixture.volume_ids))
        )
    ).all()
    assert len(guards) == 2 and all(guard.state == "succeeded" for guard in guards)
    operation = await db_session.scalar(
        select(ServerLaunchOperation).where(
            ServerLaunchOperation.server_id == fixture.server_id,
            ServerLaunchOperation.action == "stop",
        )
    )
    assert operation.state == "succeeded"
    assert {mount["volume_id"] for mount in operation.mounts} == {
        str(id_) for id_ in fixture.volume_ids
    }
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Volume).where(Volume.id.in_(fixture.volume_ids))
        )
        == 2
    )


@pytest.mark.asyncio
async def test_delete_cleans_metadata_and_credit_rows_only_after_runtime_absent(
    db_session, termination_fixture
):
    fixture = termination_fixture
    db_session.add(
        CreditTransaction(
            user_id=fixture.owner_id,
            server_id=fixture.server_id,
            amount=-1,
            balance_after=99,
            type="usage",
        )
    )
    await db_session.commit()
    runtime = driver(fixture)
    await ServerTerminationService(db_session, runtime).delete(fixture.server_id, fixture.owner_id)
    assert await db_session.get(Server, fixture.server_id) is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CreditTransaction)
            .where(CreditTransaction.user_id == fixture.owner_id)
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == fixture.server_id)
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Volume).where(Volume.id.in_(fixture.volume_ids))
        )
        == 2
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["starting", "stopping"])
@pytest.mark.parametrize("action", ["stop", "delete"])
async def test_unfinished_server_without_container_cannot_release_resources(
    db_session, termination_fixture, status, action
):
    fixture = termination_fixture
    server = await db_session.get(Server, fixture.server_id)
    server.status, server.container_id = status, None
    await db_session.commit()
    runtime = driver(fixture)
    with pytest.raises(LaunchError, match="launch_in_progress") as error:
        await getattr(ServerTerminationService(db_session, runtime), action)(fixture.server_id)
    assert error.value.status_code == 409
    runtime.get_container_info.assert_not_awaited()
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == fixture.server_id)
        )
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["prepared", "executing", "uncertain"])
async def test_active_executor_blocks_termination_even_if_server_status_is_not_starting(
    db_session, termination_fixture, state
):
    fixture = termination_fixture
    db_session.add(
        ServerLaunchOperation(
            server_id=fixture.server_id,
            owner_id=fixture.owner_id,
            action="start",
            state=state,
            fencing_token=uuid4(),
            username="testuser",
            resources={},
            mounts=[],
            gpu_devices=[],
        )
    )
    await db_session.commit()
    runtime = driver(fixture)
    with pytest.raises(LaunchError, match="launch_in_progress"):
        await ServerTerminationService(db_session, runtime).stop(fixture.server_id)
    runtime.get_container_info.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_server_id_is_not_found_without_runtime_access(
    db_session, termination_fixture
):
    runtime = driver(termination_fixture)
    with pytest.raises(LaunchError, match="server_not_found") as error:
        await ServerTerminationService(db_session, runtime).delete(
            termination_fixture.server_id, uuid4()
        )
    assert error.value.status_code == 404
    runtime.get_container_info.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_missing_runtime_is_safe_without_stop_or_delete(
    db_session, termination_fixture
):
    runtime = driver(termination_fixture)
    runtime.get_container_info.side_effect = ContainerDriverError("not found", 404)
    server = await ServerTerminationService(db_session, runtime).stop(termination_fixture.server_id)
    assert server.status == "stopped"
    runtime.stop_container.assert_not_awaited()
    runtime.delete_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_stopped_runtime_is_removed_before_resource_release(
    db_session, termination_fixture
):
    runtime = driver(termination_fixture, running=False)
    await ServerTerminationService(db_session, runtime).stop(termination_fixture.server_id)
    runtime.stop_container.assert_not_awaited()
    runtime.delete_container.assert_awaited_once_with("owned-runtime", force=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["inspect", "stop", "delete", "postinspect"])
@pytest.mark.parametrize("action", ["stop", "delete"])
async def test_runtime_failure_retains_stopping_quota_gpu_guards_and_uncertain_journal(
    db_session, termination_fixture, failure_stage, action
):
    fixture = termination_fixture
    runtime = driver(fixture)
    error = ContainerDriverError("private runtime exception details", 503)
    if failure_stage == "inspect":
        runtime.get_container_info.side_effect = error
    elif failure_stage == "postinspect":
        runtime.get_container_info.side_effect = [fixture.inspect(), error]
    else:
        getattr(runtime, f"{failure_stage}_container").side_effect = error
    with pytest.raises(LaunchError, match="^recovery_required$"):
        await getattr(ServerTerminationService(db_session, runtime), action)(fixture.server_id)
    server = await db_session.get(Server, fixture.server_id)
    assert server.status == "stopping" and server.container_id == "owned-runtime"
    assert server.status_reason == "recovery_required"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == fixture.server_id)
        )
        == 1
    )
    guards = (
        await db_session.scalars(
            select(VolumeOperation).where(VolumeOperation.volume_id.in_(fixture.volume_ids))
        )
    ).all()
    assert {guard.state for guard in guards} == {"running", "reserved"}
    operation = await db_session.scalar(
        select(ServerLaunchOperation).where(
            ServerLaunchOperation.server_id == fixture.server_id,
            ServerLaunchOperation.action == action,
        )
    )
    assert operation.state == "uncertain"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch", ["container_id", "server_id", "owner_id", "missing_labels", "malformed_state"]
)
async def test_runtime_identity_mismatch_cannot_stop_or_delete_another_container(
    db_session, termination_fixture, mismatch
):
    fixture = termination_fixture
    info = fixture.inspect()
    if mismatch == "container_id":
        info["Id"] = "different-runtime"
    elif mismatch == "server_id":
        info["Config"]["Labels"]["nukelab.server.id"] = str(uuid4())
    elif mismatch == "owner_id":
        info["Config"]["Labels"]["nukelab.user.id"] = str(uuid4())
    elif mismatch == "missing_labels":
        info["Config"] = {}
    else:
        info["State"] = {"Running": "false"}
    runtime = driver(fixture)
    runtime.get_container_info.side_effect = None
    runtime.get_container_info.return_value = info
    with pytest.raises(LaunchError, match="recovery_required"):
        await ServerTerminationService(db_session, runtime).delete(fixture.server_id)
    runtime.stop_container.assert_not_awaited()
    runtime.delete_container.assert_not_awaited()
    assert await db_session.get(Server, fixture.server_id) is not None


@pytest.mark.asyncio
async def test_delete_returning_without_absence_proof_never_releases_guards(
    db_session, termination_fixture
):
    fixture = termination_fixture
    runtime = driver(fixture)
    runtime.get_container_info.side_effect = [fixture.inspect(), fixture.inspect(running=False)]
    with pytest.raises(LaunchError, match="recovery_required"):
        await ServerTerminationService(db_session, runtime).stop(fixture.server_id)
    server = await db_session.get(Server, fixture.server_id)
    assert server.status == "stopping"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == fixture.server_id)
        )
        == 1
    )


@pytest.mark.asyncio
async def test_cancellation_keeps_stopping_resources_and_journal(db_session, termination_fixture):
    fixture = termination_fixture
    runtime = driver(fixture)
    runtime.stop_container.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await ServerTerminationService(db_session, runtime).stop(fixture.server_id)
    server = await db_session.get(Server, fixture.server_id)
    assert server.status == "stopping"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == fixture.server_id)
        )
        == 1
    )
    operation = await db_session.scalar(
        select(ServerLaunchOperation).where(
            ServerLaunchOperation.server_id == fixture.server_id,
            ServerLaunchOperation.action == "stop",
        )
    )
    assert operation.state == "uncertain"


@pytest.mark.asyncio
@pytest.mark.parametrize("first_action,second_action", [("stop", "delete"), ("delete", "stop")])
async def test_independent_sessions_cannot_overtake_inflight_termination(
    committed_launch_fixture, first_action, second_action
):
    fixture = committed_launch_fixture
    server_id = uuid4()
    async with AsyncSession(test_engine) as setup, setup.begin():
        setup.add(
            Server(
                id=server_id,
                name="termination-race",
                user_id=fixture.owner_id,
                status="running",
                container_id="owned-runtime",
                allocated_cpu=1,
                allocated_memory="1g",
                allocated_disk="1g",
                allocated_gpu=0,
            )
        )
    inputs = TerminationFixture(fixture.owner_id, server_id, [], uuid4())
    entered, release = asyncio.Event(), asyncio.Event()
    runtime = driver(inputs)
    intruder_runtime = driver(inputs)

    async def slow_stop(container_id):
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=10)

    runtime.stop_container.side_effect = slow_stop

    async def first():
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            await getattr(ServerTerminationService(db, runtime), first_action)(server_id)

    task = asyncio.create_task(first())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        async with AsyncSession(test_engine, expire_on_commit=False) as competitor:
            with pytest.raises(LaunchError, match="launch_in_progress"):
                await getattr(
                    ServerTerminationService(competitor, intruder_runtime), second_action
                )(server_id)
        intruder_runtime.get_container_info.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=10)
    async with AsyncSession(test_engine) as verify:
        stored = await verify.get(Server, server_id)
        if first_action == "delete":
            assert stored is None
        else:
            assert stored.status == "stopped"


@pytest.mark.asyncio
async def test_stale_enforcement_decision_cannot_stop_a_newer_server(
    db_session, termination_fixture
):
    from datetime import timedelta

    fixture = termination_fixture
    row = await db_session.get(Server, fixture.server_id)
    observed = row.updated_at
    row.updated_at = observed + timedelta(seconds=1)
    await db_session.commit()
    driver = SimpleNamespace(
        get_container_info=AsyncMock(), stop_container=AsyncMock(), delete_container=AsyncMock()
    )
    with pytest.raises(LaunchError, match="configuration_changed"):
        await ServerTerminationService(db_session, driver).stop(
            fixture.server_id, expected_version=observed
        )
    await db_session.refresh(row)
    assert row.status == "running"
    assert (
        await db_session.scalar(select(GpuAllocation).where(GpuAllocation.server_id == row.id))
        is not None
    )
    driver.get_container_info.assert_not_awaited()
    driver.stop_container.assert_not_awaited()
    driver.delete_container.assert_not_awaited()
