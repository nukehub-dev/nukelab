# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Logout must not bypass an in-flight lifecycle claim or release its GPU."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server
from app.services.server_operation_service import create_operation


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_state", ["prepared", "executing", "uncertain"])
async def test_logout_keeps_active_operation_and_gpu_protected(
    client, user_token, test_user, db_session, monkeypatch, operation_state
):
    from app.services.server_operation_service import claim_operation, finish_operation

    test_user.preferences = {"stop_on_logout": True}
    server = Server(
        name="logout-protected",
        user_id=test_user.id,
        status="running",
        container_id="new-generation",
        allocated_gpu=1,
    )
    db_session.add(server)
    await db_session.flush()
    server_id = server.id
    db_session.add(GpuAllocation(server_id=server_id, device="nvidia.com/gpu=0"))
    operation = await create_operation(
        db_session,
        server_id=server_id,
        owner_id=test_user.id,
        action="restart",
        username=test_user.username,
        resources={"cpu": 1, "memory": "1g", "disk": "1g", "gpu": 1},
    )
    if operation_state != "prepared":
        claimed = await claim_operation(db_session, operation.id, operation.fencing_token)
        assert claimed is not None
    if operation_state == "uncertain":
        finished = await finish_operation(
            db_session, operation.id, operation.fencing_token, "uncertain"
        )
        assert finished is not None
    operation_id = operation.id
    await db_session.commit()
    driver = SimpleNamespace(
        stop_container=AsyncMock(), delete_container=AsyncMock(), get_container_info=AsyncMock()
    )
    monkeypatch.setattr("app.api.auth.get_driver", AsyncMock(return_value=driver))
    response = await client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 200
    await db_session.refresh(server)
    await db_session.refresh(operation)
    assert server.status == "running" and server.container_id == "new-generation"
    assert operation.id == operation_id and operation.state == operation_state
    assert (
        await db_session.scalar(select(GpuAllocation).where(GpuAllocation.server_id == server_id))
        is not None
    )
    driver.get_container_info.assert_not_awaited()
    driver.stop_container.assert_not_awaited()
    driver.delete_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token_before_server_stop(
    client, user_token, test_user, db_session
):
    from app.api.auth import create_refresh_token_for_user
    from app.models.refresh_token import RefreshToken

    refresh_token = await create_refresh_token_for_user(str(test_user.id), db_session)
    test_user.preferences = {"stop_on_logout": True}
    server = Server(
        name="logout-revocation-first",
        user_id=test_user.id,
        status="running",
        container_id="runtime",
    )
    db_session.add(server)
    await db_session.commit()
    observed: dict[str, object] = {}

    async def stop(server_id, owner_id=None):
        token = await db_session.scalar(
            select(RefreshToken)
            .where(RefreshToken.user_id == test_user.id)
            .execution_options(populate_existing=True)
        )
        observed["revoked_at"] = token.revoked_at if token else None
        row = await db_session.get(Server, server_id)
        assert row is not None
        row.status = "stopped"
        return row

    with patch("app.api.auth.ServerTerminationService") as service:
        service.return_value.stop = AsyncMock(side_effect=stop)
        response = await client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"refresh_token": refresh_token},
        )
    assert response.status_code == 200
    assert observed["revoked_at"] is not None
    service.return_value.stop.assert_awaited_once()
