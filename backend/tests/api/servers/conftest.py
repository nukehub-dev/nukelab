# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""HTTP server tests use a runtime boundary that never contacts a real daemon."""

import hashlib
import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.container.driver import ContainerDriver, ContainerDriverError
from app.models.server import Server
from app.models.volume import Volume


@pytest.fixture(autouse=True)
def server_api_runtime(monkeypatch, db_session):
    containers, volumes = {}, {}
    absent = set()

    def identity(reference):
        local = (
            reference
            if isinstance(reference, str) and reference.startswith("sha256:")
            else "sha256:" + hashlib.sha256(str(reference).encode()).hexdigest()
        )
        return {
            "requested_reference": str(reference),
            "local_id": local,
            "repository_digests": [],
            "os": "linux",
            "architecture": "amd64",
            "registry_verified": False,
        }

    async def inspect(container_id):
        if container_id in absent or container_id not in containers:
            raise ContainerDriverError("Not found", status=404)
        return deepcopy(containers[container_id])

    async def create(**kwargs):
        container_id = uuid.uuid4().hex
        containers[container_id] = {
            "Id": container_id,
            "Name": kwargs["name"],
            "Image": kwargs["image"],
            "State": {"Running": False, "Status": "created"},
            "Config": {"Labels": kwargs.get("labels", {})},
        }
        return container_id

    async def start(container_id):
        item = await inspect(container_id)
        item["State"] = {"Running": True, "Status": "running"}
        containers[container_id] = item

    async def stop(container_id, **kwargs):
        item = await inspect(container_id)
        item["State"] = {"Running": False, "Status": "exited"}
        containers[container_id] = item

    async def delete(container_id, **kwargs):
        absent.add(container_id)

    async def ensure(name, **kwargs):
        volumes[name] = {"Name": name}

    driver = SimpleNamespace(
        resolve_image=AsyncMock(side_effect=identity),
        image_exists=AsyncMock(return_value=True),
        pull_image=AsyncMock(),
        get_container_info=AsyncMock(side_effect=inspect),
        create_container=AsyncMock(side_effect=create),
        start_container=AsyncMock(side_effect=start),
        stop_container=AsyncMock(side_effect=stop),
        delete_container=AsyncMock(side_effect=delete),
        ensure_volume=AsyncMock(side_effect=ensure),
        create_volume=AsyncMock(side_effect=ensure),
        get_volume=AsyncMock(side_effect=lambda name: volumes.get(name)),
        get_container_by_name=AsyncMock(
            side_effect=lambda name: next(
                (
                    key
                    for key, item in containers.items()
                    if key not in absent and item.get("Name") == name
                ),
                None,
            )
        ),
        wait_for_container_ready=AsyncMock(return_value=True),
        exec_in_container=AsyncMock(),
        get_image_env=AsyncMock(return_value={}),
        immutable_toolchain_cache_name=ContainerDriver.immutable_toolchain_cache_name,
        prepare_immutable_toolchain_volume=AsyncMock(
            side_effect=lambda image, cache, mounts: {
                "mounts": mounts,
                "env": {},
                "env_prepend": {},
            }
        ),
    )

    async def acquire():
        # Snapshot before lifecycle takes ownership of transaction boundaries.
        for row in (await db_session.scalars(select(Server))).all():
            if (
                row.container_id
                and row.container_id not in containers
                and row.container_id not in absent
            ):
                containers[row.container_id] = {
                    "Id": row.container_id,
                    "Name": "legacy-" + str(row.id),
                    "Image": identity(row.image or "legacy:latest")["local_id"],
                    "State": {
                        "Running": row.status == "running",
                        "Status": "running" if row.status == "running" else "exited",
                    },
                    "Config": {
                        "Labels": {
                            "nukelab.server.id": str(row.id),
                            "nukelab.user.id": str(row.user_id),
                        }
                    },
                }
        for row in (await db_session.scalars(select(Volume))).all():
            volumes.setdefault(row.name, {"Name": row.name})
        return driver

    async def runtime_status(container_id):
        await acquire()
        try:
            info = await inspect(container_id)
        except ContainerDriverError:
            return "unknown"
        return "running" if info["State"]["Running"] else "stopped"

    monkeypatch.setattr("app.api.servers.spawner.get_status", runtime_status)
    monkeypatch.setattr("app.api.servers.get_driver", acquire)
    yield driver
