# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""GPU servers must recreate (never plain-start) containers in exclusive mode.

A stopped container keeps its original GPU DeviceRequests baked in. When the
exclusive allocator is enabled, start-class paths must route GPU servers
through spawner.spawn (recreate with the devices they currently own) instead
of container.start on the stale container. Non-GPU servers and
allocator-disabled mode keep the cheap plain-start behavior.
"""

import uuid as uuid_mod
from unittest import mock

import pytest_asyncio

from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_plan import ServerPlan

POOL = "nvidia.com/gpu=0,nvidia.com/gpu=1"


def _mock_spawn_server():
    new = mock.AsyncMock()
    new.container_id = "new-cid"
    new.image = "test:latest"
    new.volume_id = None
    new.external_url = "http://test"
    new.allocated_cpu = 1.0
    new.allocated_memory = "1g"
    return new


@pytest_asyncio.fixture
async def gpu_plan_env(db_session):
    plan = ServerPlan(
        name=f"gpu-plan-{uuid_mod.uuid4().hex[:8]}",
        slug=f"gpu-plan-{uuid_mod.uuid4().hex[:8]}",
        cpu_limit=1,
        memory_limit="1g",
        disk_limit="10g",
        gpu_limit=1,
        is_public=True,
        is_active=True,
        cost_per_hour=0,
        visible_to_roles=["user"],
    )
    env = EnvironmentTemplate(
        name=f"gpu-env-{uuid_mod.uuid4().hex[:8]}",
        slug=f"gpu-env-{uuid_mod.uuid4().hex[:8]}",
        image="test:latest",
    )
    db_session.add_all([plan, env])
    await db_session.commit()
    await db_session.refresh(plan)
    await db_session.refresh(env)
    return plan, env


@pytest_asyncio.fixture
async def gpu_server(db_session, test_user, gpu_plan_env):
    plan, env = gpu_plan_env
    server = Server(
        name="gpu-srv",
        user_id=test_user.id,
        status="stopped",
        container_id="old-cid",
        plan_id=plan.id,
        environment_id=env.id,
        allocated_gpu=1,
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server


@pytest_asyncio.fixture
async def plain_server(db_session, test_user, gpu_plan_env):
    """Non-GPU server on a GPU-less plan."""
    plan, env = gpu_plan_env
    plan.gpu_limit = 0
    await db_session.commit()
    server = Server(
        name="plain-srv",
        user_id=test_user.id,
        status="stopped",
        container_id="old-cid",
        plan_id=plan.id,
        environment_id=env.id,
        allocated_gpu=0,
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server
