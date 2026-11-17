# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Stale health probes cannot mutate or restart a newer server generation."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import func, select, update

from app.models.health_check import HealthCheck
from app.models.server import Server
from app.services.health_check_service import HealthCheckService
from app.services.server_launch_service import LaunchError
from app.services.server_operation_service import create_operation


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["replacement", "metadata", "active_operation"])
@pytest.mark.parametrize("failed_probe", [False, True])
async def test_inflight_probe_cannot_overwrite_or_restart_changed_authority(
    db_session, test_user, change, failed_probe
):
    server = Server(
        id=uuid.uuid4(),
        name="observed-" + uuid.uuid4().hex[:8],
        user_id=test_user.id,
        status="running",
        container_id="sampled-container",
        health_status="healthy",
    )
    db_session.add(server)
    await db_session.flush()
    server_id, owner_id = server.id, server.user_id
    db_session.add(
        HealthCheck(
            server_id=server_id,
            container_id="sampled-container",
            status="unhealthy",
            consecutive_failures=2,
        )
    )
    await db_session.commit()
    service = HealthCheckService(db_session)
    service._auto_restart = AsyncMock()

    async def probe(container_id):
        assert container_id == "sampled-container" and not db_session.in_transaction()
        async with db_session.begin():
            values = {"health_status": "healthy"}
            if change == "replacement":
                values["container_id"] = "new-container"
            elif change == "metadata":
                values["name"] = "new-name"
            else:
                await create_operation(
                    db_session,
                    server_id=server_id,
                    owner_id=owner_id,
                    action="restart",
                    username="owner",
                    resources={"cpu": 1.0, "memory": "2g", "disk": "10g", "gpu": 0},
                )
                values["status"] = "starting"
            await db_session.execute(
                update(Server)
                .where(Server.id == server_id)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        if failed_probe:
            raise RuntimeError("old runtime disappeared")
        return {"State": {"Running": True, "Health": {"Status": "unhealthy"}}}

    runtime = SimpleNamespace(get_container_info=AsyncMock(side_effect=probe), close=AsyncMock())
    with patch(
        "app.services.health_check_service.get_fresh_driver", AsyncMock(return_value=runtime)
    ):
        await service._check_container(server)
    current = await db_session.get(Server, server_id, populate_existing=True)
    assert current.health_status == "healthy"
    assert current.status == ("starting" if change == "active_operation" else "running")
    assert current.container_id == (
        "new-container" if change == "replacement" else "sampled-container"
    )
    assert (
        await db_session.scalar(
            select(func.count()).select_from(HealthCheck).where(HealthCheck.server_id == server_id)
        )
        == 1
    )
    service._auto_restart.assert_not_awaited()
    runtime.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_container_failures_do_not_increment_new_generation_failure_count(
    db_session, test_user
):
    server = Server(
        id=uuid.uuid4(),
        name="new-generation",
        user_id=test_user.id,
        status="running",
        container_id="new-container",
    )
    db_session.add(server)
    await db_session.flush()
    server_id = server.id
    db_session.add(
        HealthCheck(
            server_id=server_id,
            container_id="old-container",
            status="unhealthy",
            consecutive_failures=9,
        )
    )
    await db_session.commit()
    runtime = SimpleNamespace(
        get_container_info=AsyncMock(
            return_value={"State": {"Running": True, "Health": {"Status": "unhealthy"}}}
        ),
        close=AsyncMock(),
    )
    service = HealthCheckService(db_session)
    service._auto_restart = AsyncMock()
    with patch(
        "app.services.health_check_service.get_fresh_driver", AsyncMock(return_value=runtime)
    ):
        await service._check_container(server)
    check = await db_session.scalar(
        select(HealthCheck).where(
            HealthCheck.server_id == server_id, HealthCheck.container_id == "new-container"
        )
    )
    assert check.consecutive_failures == 1
    service._auto_restart.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_reservation_receives_sample_version_after_driver_connection_await(
    db_session, test_user, monkeypatch
):
    monkeypatch.setattr(
        "app.services.health_check_service.settings.server_auto_restart_enabled", True
    )
    server = Server(
        id=uuid.uuid4(),
        name="before-restart",
        user_id=test_user.id,
        status="running",
        container_id="sampled-container",
    )
    db_session.add(server)
    await db_session.commit()
    server_id, version = server.id, server.updated_at
    runtime = SimpleNamespace(close=AsyncMock())

    async def connect():
        assert not db_session.in_transaction()
        async with db_session.begin():
            await db_session.execute(
                update(Server)
                .where(Server.id == server_id)
                .values(container_id="replacement")
                .execution_options(synchronize_session=False)
            )
        return runtime

    lifecycle = Mock(restart=AsyncMock(side_effect=LaunchError("configuration_changed", 409)))
    with (
        patch("app.services.health_check_service.get_fresh_driver", AsyncMock(side_effect=connect)),
        patch("app.services.health_check_service.ServerLifecycleService", return_value=lifecycle),
    ):
        await HealthCheckService(db_session)._auto_restart(
            server, expected_version=version, expected_container_id="sampled-container"
        )
    assert lifecycle.restart.call_args.kwargs["expected_version"] == version
    assert (
        await db_session.scalar(
            select(func.count()).select_from(HealthCheck).where(HealthCheck.server_id == server_id)
        )
        == 0
    )
    assert (
        await db_session.get(Server, server_id, populate_existing=True)
    ).container_id == "replacement"
    runtime.close.assert_awaited_once()
