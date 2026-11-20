# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause
"""Recovery executors use a constrained driver boundary."""

import uuid
from unittest.mock import AsyncMock, Mock

import aiodocker
import pytest

from app.container.docker_driver import DockerDriver
from app.container.driver import ContainerDriverError


def invocation():
    operation = str(uuid.uuid4())
    return {
        "name": "nukelab-recovery-" + operation,
        "image": "sha256:" + "a" * 64,
        "command": ["capture"],
        "labels": {
            "nukelab.recovery.operation": operation,
            "nukelab.recovery.fence": str(uuid.uuid4()),
        },
        "limits": {},
        "mounts": [
            {"Type": "volume", "Source": "private-data", "Target": "/source", "ReadOnly": True},
            {
                "Type": "bind",
                "Source": "/private/artifact",
                "Target": "/artifact",
                "ReadOnly": False,
            },
        ],
    }


def driver():
    value = DockerDriver()
    value.client = Mock()
    value.client.containers = AsyncMock()
    value.client.containers.create.return_value = Mock(id="helper-id")
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("restore", [False, True])
async def test_executor_is_unstarted_non_root_and_has_bounded_isolation(restore):
    runtime, args = driver(), invocation()
    if restore:
        args["mounts"][0].update(Target="/target", ReadOnly=False)
    assert await runtime.create_recovery_helper(**args) == "helper-id"
    config = runtime.client.containers.create.call_args.kwargs["config"]
    assert config["User"] == "65532:65532"
    host = config["HostConfig"]
    assert host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"]
    assert host["NetworkMode"] == "none" and host["SecurityOpt"] == ["no-new-privileges:true"]
    assert host["Memory"] == 1024**3 and host["PidsLimit"] == 64
    assert host["NanoCpus"] == 10**9 and host["RestartPolicy"] == {"Name": "no"}
    assert host["Mounts"][0]["VolumeOptions"]["NoCopy"] is not restore
    runtime.client.containers.create.return_value.start.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "name",
        "image",
        "fence",
        "command",
        "writable_source",
        "traversal",
        "duplicate",
        "missing_artifact",
        "memory",
    ],
)
async def test_invalid_execution_contract_never_contacts_runtime(bad):
    runtime, args = driver(), invocation()
    if bad == "name":
        args["name"] = "foreign"
    elif bad == "image":
        args["image"] = "mutable:latest"
    elif bad == "fence":
        args["labels"]["nukelab.recovery.fence"] = "bad"
    elif bad == "command":
        args["command"] = ["capture\x00bad"]
    elif bad == "writable_source":
        args["mounts"][0]["ReadOnly"] = False
    elif bad == "traversal":
        args["mounts"][1]["Source"] = "/safe/../escape"
    elif bad == "duplicate":
        args["mounts"].append(args["mounts"][0])
    elif bad == "missing_artifact":
        args["mounts"].pop()
    else:
        args["limits"]["memory_bytes"] = True
    with pytest.raises(ContainerDriverError):
        await runtime.create_recovery_helper(**args)
    runtime.client.containers.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_stopped_containers_are_included_when_requested():
    runtime = driver()
    runtime.client.containers.list.return_value = []
    assert await runtime.list_containers(all=True) == []
    runtime.client.containers.list.assert_awaited_once_with(filters=None, all=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [0, 17, None, True, "0", "error"])
async def test_wait_requires_integer_exit_proof_and_maps_daemon_failure(outcome):
    runtime = driver()
    helper = AsyncMock()
    runtime.client.containers.get.return_value = helper
    helper.wait.return_value = {"StatusCode": outcome}
    if outcome == "error":
        helper.wait.side_effect = aiodocker.DockerError(500, {"message": "failed"})
    if type(outcome) is int:
        assert await runtime.wait_recovery_helper("helper-id", 1) == outcome
    else:
        with pytest.raises(ContainerDriverError):
            await runtime.wait_recovery_helper("helper-id", 1)
