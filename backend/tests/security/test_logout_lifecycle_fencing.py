# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Logout must not bypass an in-flight lifecycle claim or release its GPU."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server
from app.services.server_operation_service import create_operation


@pytest.mark.asyncio
async def test_logout_keeps_active_operation_and_gpu_protected(
    client, user_token, test_user, db_session, monkeypatch
):
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
    assert operation.id == operation_id and operation.state == "prepared"
    assert (
        await db_session.scalar(select(GpuAllocation).where(GpuAllocation.server_id == server_id))
        is not None
    )
    driver.get_container_info.assert_not_awaited()
    driver.stop_container.assert_not_awaited()
    driver.delete_container.assert_not_awaited()
