# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Independent launch persistence, runtime naming and finalization race regressions."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver
from app.container.spawner import ServerSpawner
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_launch_intent import ServerLaunchIntent
from app.models.server_launch_record import ServerLaunchRecord
from app.services.server_launch_service import LaunchError, LaunchReservation, ServerLaunchService
from tests.conftest import test_engine
from tests.container.test_reserved_spawner import arguments
from tests.container.test_reserved_spawner import reserved_driver as reserved_driver
from tests.services.test_server_launch_service import (
    IMAGE_ID,
    runtime_driver,
)
from tests.services.test_server_launch_service import (
    committed_launch_fixture as committed_launch_fixture,
)

OLD_TOOLCHAIN_ID = "sha256:" + "c" * 64
NEW_TOOLCHAIN_ID = "sha256:" + "d" * 64


def identity(reference, local_id):
    return {
        "requested_reference": reference,
        "local_id": local_id,
        "repository_digests": [],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }


def configure_policy(monkeypatch):
    monkeypatch.setattr(settings, "resource_pool_cpu", 34.0)
    monkeypatch.setattr(settings, "gpu_devices", "")
    monkeypatch.setattr(settings, "credits_enabled", True)


@pytest.mark.asyncio
async def test_fresh_session_recovers_original_revision_and_mounts_after_template_changes(
    committed_launch_fixture, monkeypatch
):
    configure_policy(monkeypatch)
    fixture = committed_launch_fixture
    async with AsyncSession(test_engine) as setup, setup.begin():
        template = await setup.get(EnvironmentTemplate, fixture.environment_id)
        template.tool_image = "toolchain:old"
        template.tool_mounts = ["/opt/nuke"]
        template.environment_variables = {"APPROVED_SETTING": "original"}
    driver = runtime_driver()
    driver.immutable_toolchain_cache_name = ContainerDriver.immutable_toolchain_cache_name
    driver.resolve_image.side_effect = lambda reference: identity(
        reference, OLD_TOOLCHAIN_ID if reference == "toolchain:old" else IMAGE_ID
    )
    async with AsyncSession(test_engine, expire_on_commit=False) as original:
        service = ServerLaunchService(original, driver)
        request = fixture.request("recover-original")
        revision_id = await service.resolve_revision(fixture.owner_id, request)
        reservation = await service.reserve(fixture.owner_id, request, revision_id)
        assert isinstance(reservation, LaunchReservation)
        server_id = reservation.server_id
        expected_mounts = deepcopy(reservation.mounts)
        expected_request = reservation.request.model_dump(mode="json")
        saved = await original.get(ServerLaunchIntent, server_id)
        assert saved.revision_id == revision_id
        assert saved.owner_id == fixture.owner_id
        assert saved.mounts == expected_mounts
        assert saved.request_payload == expected_request
    # The service, transaction and launch return value are discarded before recovery.
    del service, reservation
    async with AsyncSession(test_engine) as edit, edit.begin():
        template = await edit.get(EnvironmentTemplate, fixture.environment_id)
        template.tool_image = "toolchain:new"
        template.environment_variables = {"APPROVED_SETTING": "replacement"}
    recovered_driver = runtime_driver()
    recovered_driver.resolve_image.side_effect = lambda reference: identity(
        reference, NEW_TOOLCHAIN_ID if reference == "toolchain:new" else IMAGE_ID
    )
    async with AsyncSession(test_engine, expire_on_commit=False) as recovered_db:
        recovered_service = ServerLaunchService(recovered_db, recovered_driver)
        recovered = await recovered_service.load_reservation(server_id, fixture.owner_id)
        assert recovered.server_id == server_id
        assert recovered.revision_id == revision_id
        assert recovered.request.model_dump(mode="json") == expected_request
        assert recovered.mounts == expected_mounts
        assert recovered.gpu_devices == []
        assert not recovered_db.in_transaction()

        async def spawn(**kwargs):
            assert not recovered_db.in_transaction()
            assert kwargs["tool_image"] == OLD_TOOLCHAIN_ID
            assert kwargs["resolved_images"]["toolchain"]["local_id"] == OLD_TOOLCHAIN_ID
            assert kwargs["env_vars"] == {"APPROVED_SETTING": "original"}
            assert kwargs["volume_mounts"] == expected_mounts
            return SimpleNamespace(
                container_id="recovered-runtime",
                image=IMAGE_ID,
                external_url="https://test.invalid/recovered",
                health_status="healthy",
                _observed_toolchain_identity=identity(OLD_TOOLCHAIN_ID, OLD_TOOLCHAIN_ID),
            )

        recovered_service.spawner.spawn = AsyncMock(side_effect=spawn)
        # Only the durable intent may supply runtime mounts; serialized return
        # values from a previous process are not authoritative provisioning data.
        stale_delivery = replace(
            recovered,
            mounts=[{**expected_mounts[0], "volume_name": "wrong-volume-from-stale-delivery"}],
        )
        server = await recovered_service.provision(stale_delivery)
        assert server.id == server_id
        assert server.status == "running"
        assert (
            await recovered_db.scalar(
                select(func.count())
                .select_from(ServerLaunchRecord)
                .where(
                    ServerLaunchRecord.server_id == server_id,
                    ServerLaunchRecord.revision_id == revision_id,
                )
            )
            == 1
        )
    recovered_driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_cannot_load_another_owners_reserved_launch(
    committed_launch_fixture, monkeypatch
):
    configure_policy(monkeypatch)
    fixture = committed_launch_fixture
    async with AsyncSession(test_engine, expire_on_commit=False) as original:
        service = ServerLaunchService(original, runtime_driver())
        request = fixture.request("owner-private")
        revision = await service.resolve_revision(fixture.owner_id, request)
        reservation = await service.reserve(fixture.owner_id, request, revision)
        server_id = reservation.server_id
    async with AsyncSession(test_engine, expire_on_commit=False) as unauthorized:
        service = ServerLaunchService(unauthorized, runtime_driver())
        with pytest.raises(LaunchError):
            await service.load_reservation(server_id, uuid4())


@pytest.mark.asyncio
async def test_finalization_does_not_overwrite_concurrent_reconciliation_state(
    committed_launch_fixture, monkeypatch
):
    configure_policy(monkeypatch)
    fixture = committed_launch_fixture
    driver = runtime_driver()
    async with AsyncSession(test_engine, expire_on_commit=False) as launching:
        service = ServerLaunchService(launching, driver)
        request = fixture.request("state-race")
        revision = await service.resolve_revision(fixture.owner_id, request)
        reservation = await service.reserve(fixture.owner_id, request, revision)
        server_id = reservation.server_id

        async def spawn_while_reconciliation_commits(**kwargs):
            assert not launching.in_transaction()
            # Another operation commits while provisioning has released its SQL locks.
            async with AsyncSession(test_engine) as reconciler, reconciler.begin():
                await reconciler.execute(
                    update(Server)
                    .where(Server.id == server_id)
                    .values(
                        status="stopped",
                        container_id="authoritative-reconciled-runtime",
                        status_reason="operator_reconciled",
                    )
                )
            return SimpleNamespace(
                container_id="late-runtime",
                image=IMAGE_ID,
                external_url="https://test.invalid/late",
                health_status="healthy",
            )

        service.spawner.spawn = AsyncMock(side_effect=spawn_while_reconciliation_commits)
        with pytest.raises(LaunchError, match="recovery_required"):
            await service.provision(reservation)
    async with AsyncSession(test_engine) as verify:
        stored = await verify.get(Server, server_id)
        assert stored.status == "stopped"
        assert stored.container_id == "authoritative-reconciled-runtime"
        assert stored.status_reason == "operator_reconciled"
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(ServerLaunchRecord)
                .where(
                    ServerLaunchRecord.server_id == server_id,
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_case_variant_names_get_distinct_stable_pinned_runtime_names(reserved_driver):
    first = arguments()
    second = arguments()
    first["server_name"] = "Experiment"
    second["server_name"] = "experiment"
    second["user_id"] = first["user_id"]
    spawner = ServerSpawner(driver=reserved_driver)
    await spawner.spawn(**first)
    await spawner.spawn(**second)
    first_name, second_name = [
        call.kwargs["name"] for call in reserved_driver.create_container.await_args_list
    ]
    assert first_name != second_name
    assert first["server_id"].replace("-", "") in first_name.replace("-", "")
    assert second["server_id"].replace("-", "") in second_name.replace("-", "")
    # Runtime identity remains deterministic when the same reservation is delivered again.
    reserved_driver.create_container.reset_mock()
    await spawner.spawn(**first)
    assert reserved_driver.create_container.await_args.kwargs["name"] == first_name
