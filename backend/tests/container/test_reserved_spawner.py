# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Independent reserved-launch regressions; failures retain runtime protection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.config import settings
from app.container import spawner as spawner_module
from app.container.docker_driver import DockerDriver
from app.container.driver import (
    ContainerDriverError,
    ImageResolutionError,
    ImmutableToolchainCacheError,
)
from app.container.spawner import ServerSpawner

RUNTIME_ID = "sha256:" + "a" * 64
TOOLCHAIN_ID = "sha256:" + "b" * 64


def identity(image_id=RUNTIME_ID, requested="workspace:latest"):
    return {
        "requested_reference": requested,
        "local_id": image_id,
        "repository_digests": [],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }


@pytest.fixture
def reserved_driver(monkeypatch):
    monkeypatch.setattr(settings, "server_auth_enabled", False)
    monkeypatch.setattr(settings, "traefik_internal_url", "http://traefik:80")
    monkeypatch.setattr(spawner_module, "asyncio", SimpleNamespace(sleep=AsyncMock()))
    driver = MagicMock()
    for name in (
        "resolve_image",
        "ensure_volume",
        "create_volume",
        "get_volume",
        "image_exists",
        "pull_image",
        "create_container",
        "start_container",
        "delete_container",
        "get_container_by_name",
        "prepare_immutable_toolchain_volume",
        "prepare_toolchain_volume",
        "get_image_env",
        "exec_in_container",
        "wait_for_container_ready",
    ):
        setattr(driver, name, AsyncMock())
    driver.resolve_image.return_value = identity()
    driver.resolve_image.side_effect = lambda reference: (
        identity(TOOLCHAIN_ID, TOOLCHAIN_ID)
        if reference == TOOLCHAIN_ID
        else driver.resolve_image.return_value
    )
    driver.get_container_by_name.return_value = None
    driver.create_container.return_value = "reserved-runtime"
    driver.wait_for_container_ready.return_value = True
    driver.get_volume.return_value = {"Name": "private-data"}
    driver.get_image_env.return_value = {"PATH": "/usr/bin"}
    driver.prepare_immutable_toolchain_volume.return_value = {
        "mounts": ["/opt/nuke"],
        "env": {"NUKE_HOME": "/opt/nuke"},
        "env_prepend": {"PATH": "/opt/nuke/bin"},
    }
    driver.immutable_toolchain_cache_name = DockerDriver.immutable_toolchain_cache_name
    return driver


def arguments(*, toolchain=False, mounts=None):
    return {
        "user_id": str(uuid4()),
        "username": "alice",
        "server_name": "experiment",
        "server_id": str(uuid4()),
        "image": "workspace:latest",
        "tool_image": "toolchain:latest" if toolchain else None,
        "tool_mounts": ["/opt/nuke"] if toolchain else None,
        "resolved_images": {
            "runtime": identity(),
            "toolchain": identity(TOOLCHAIN_ID, "toolchain:latest") if toolchain else None,
        },
        "volume_mounts": mounts
        if mounts is not None
        else [
            {
                "volume_id": str(uuid4()),
                "volume_name": "private-data",
                "mount_path": "/home/alice",
                "mode": "read_write",
                "is_primary": True,
            }
        ],
    }


@pytest.mark.asyncio
async def test_existing_runtime_is_preserved_for_explicit_reconciliation(reserved_driver):
    reserved_driver.get_container_by_name.return_value = "already-created"
    with pytest.raises(ContainerDriverError, match="reconciliation"):
        await ServerSpawner(driver=reserved_driver).spawn(**arguments())
    reserved_driver.delete_container.assert_not_awaited()
    reserved_driver.create_container.assert_not_awaited()
    reserved_driver.ensure_volume.assert_not_awaited()


@pytest.mark.asyncio
async def test_pinned_runtime_is_spawned_by_exact_id_without_tag_lookup_or_pull(reserved_driver):
    request = arguments()
    result = await ServerSpawner(driver=reserved_driver).spawn(**request)
    assert str(result.id) == request["server_id"]
    assert result.image == RUNTIME_ID
    assert result.status == "running" and result.health_status == "healthy"
    reserved_driver.resolve_image.assert_awaited_once_with(RUNTIME_ID)
    assert reserved_driver.create_container.call_args.kwargs["image"] == RUNTIME_ID
    reserved_driver.image_exists.assert_not_awaited()
    reserved_driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_pinned_runtime_never_substitutes_latest(reserved_driver):
    reserved_driver.resolve_image.side_effect = ImageResolutionError("artifact_missing", 404)
    with pytest.raises(ImageResolutionError, match="artifact_missing"):
        await ServerSpawner(driver=reserved_driver).spawn(**arguments())
    reserved_driver.pull_image.assert_not_awaited()
    reserved_driver.create_container.assert_not_awaited()
    reserved_driver.delete_container.assert_not_awaited()


@pytest.mark.parametrize(
    "changed", [{"local_id": TOOLCHAIN_ID}, {"os": "other"}, {"architecture": "arm64"}]
)
@pytest.mark.asyncio
async def test_pinned_runtime_identity_or_platform_mismatch_fails_before_mutation(
    reserved_driver, changed
):
    reserved_driver.resolve_image.return_value = identity() | changed
    with pytest.raises(ContainerDriverError, match="does not match approval"):
        await ServerSpawner(driver=reserved_driver).spawn(**arguments())
    reserved_driver.create_container.assert_not_awaited()
    reserved_driver.ensure_volume.assert_not_awaited()


@pytest.mark.asyncio
async def test_required_toolchain_uses_immutable_cache_and_readonly_mount(reserved_driver):
    request = arguments(toolchain=True)
    spawned = await ServerSpawner(driver=reserved_driver).spawn(**request)
    assert spawned._observed_toolchain_identity["local_id"] == TOOLCHAIN_ID
    expected_cache = DockerDriver.immutable_toolchain_cache_name(
        request["resolved_images"]["toolchain"], ["/opt/nuke"]
    )
    reserved_driver.prepare_immutable_toolchain_volume.assert_awaited_once_with(
        TOOLCHAIN_ID, expected_cache, ["/opt/nuke"]
    )
    reserved_driver.prepare_toolchain_volume.assert_not_awaited()
    reserved_driver.pull_image.assert_not_awaited()
    create = reserved_driver.create_container.call_args.kwargs
    assert create["volumes"][expected_cache] == {"bind": "/opt/nuke", "mode": "ro"}
    assert create["env"]["PATH"] == "/opt/nuke/bin:/usr/bin"
    assert create["env"]["NUKE_HOME"] == "/opt/nuke"
    assert all(
        call.args[1][-1] != "/opt/nuke" for call in reserved_driver.exec_in_container.call_args_list
    )


@pytest.mark.asyncio
async def test_required_toolchain_failure_never_degrades_to_runtime_only(reserved_driver):
    reserved_driver.prepare_immutable_toolchain_volume.side_effect = ImmutableToolchainCacheError(
        "toolchain_cache_mismatch"
    )
    with pytest.raises(ContainerDriverError, match="reconciliation"):
        await ServerSpawner(driver=reserved_driver).spawn(**arguments(toolchain=True))
    reserved_driver.create_container.assert_not_awaited()
    reserved_driver.delete_container.assert_not_awaited()
    reserved_driver.prepare_toolchain_volume.assert_not_awaited()


@pytest.mark.parametrize(
    "approval_has_toolchain,request_has_toolchain", [(True, False), (False, True)]
)
@pytest.mark.asyncio
async def test_toolchain_requirement_cannot_be_silently_added_or_dropped(
    reserved_driver, approval_has_toolchain, request_has_toolchain
):
    request = arguments(toolchain=approval_has_toolchain)
    request["tool_image"] = "toolchain:latest" if request_has_toolchain else None
    with pytest.raises(ContainerDriverError, match="does not match approval"):
        await ServerSpawner(driver=reserved_driver).spawn(**request)
    reserved_driver.create_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_toolchain_manifest_cannot_change_approved_mount_path(reserved_driver):
    reserved_driver.prepare_immutable_toolchain_volume.return_value = {
        "mounts": ["/etc"],
        "env": {},
    }
    with pytest.raises(ContainerDriverError, match="reconciliation"):
        await ServerSpawner(driver=reserved_driver).spawn(**arguments(toolchain=True))
    reserved_driver.create_container.assert_not_awaited()


@pytest.mark.parametrize("probes", [[False, True], [True, False], [False, False]])
@pytest.mark.asyncio
async def test_failed_internal_or_public_readiness_retains_runtime(reserved_driver, probes):
    reserved_driver.wait_for_container_ready.side_effect = probes
    with pytest.raises(ContainerDriverError, match="reconciliation"):
        await ServerSpawner(driver=reserved_driver).spawn(**arguments())
    reserved_driver.create_container.assert_awaited_once()
    reserved_driver.start_container.assert_awaited_once_with("reserved-runtime")
    reserved_driver.delete_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_create_conflict_does_not_delete_the_winner(reserved_driver):
    reserved_driver.create_container.side_effect = ContainerDriverError("name exists", 409)
    with pytest.raises(ContainerDriverError, match="reconciliation"):
        await ServerSpawner(driver=reserved_driver).spawn(**arguments())
    reserved_driver.delete_container.assert_not_awaited()


@pytest.mark.parametrize("name", [None, "", "../other", "/var/lib/docker", "x:y"])
@pytest.mark.asyncio
async def test_reserved_volume_cannot_fall_back_to_a_generated_name(reserved_driver, name):
    request = arguments()
    request["volume_mounts"][0]["volume_name"] = name
    with pytest.raises(ContainerDriverError, match="volume name"):
        await ServerSpawner(driver=reserved_driver).spawn(**request)
    reserved_driver.ensure_volume.assert_not_awaited()
    reserved_driver.create_container.assert_not_awaited()


@pytest.mark.parametrize("mounts", [None, []])
@pytest.mark.asyncio
async def test_reserved_launch_requires_explicit_volume_intent(reserved_driver, mounts):
    request = arguments()
    request["volume_mounts"] = mounts
    with pytest.raises(ContainerDriverError):
        await ServerSpawner(driver=reserved_driver).spawn(**request)
    reserved_driver.ensure_volume.assert_not_awaited()
    reserved_driver.create_container.assert_not_awaited()


@pytest.mark.parametrize("mount_path", ["/data", "/home/alice"])
@pytest.mark.asyncio
async def test_readonly_mounts_never_receive_permission_mutations(reserved_driver, mount_path):
    request = arguments(
        mounts=[
            {
                "volume_id": str(uuid4()),
                "volume_name": "private-data",
                "mount_path": mount_path,
                "mode": "read_only",
                "is_primary": True,
                "auto_created": True,
            }
        ]
    )
    await ServerSpawner(driver=reserved_driver).spawn(**request)
    assert reserved_driver.create_container.call_args.kwargs["volumes"]["private-data"] == {
        "bind": mount_path,
        "mode": "ro",
    }
    assert all(
        call.args[1][-1] != mount_path for call in reserved_driver.exec_in_container.call_args_list
    )


@pytest.mark.asyncio
async def test_missing_existing_data_volume_is_never_replaced_by_empty_volume(reserved_driver):
    reserved_driver.get_volume.return_value = None
    with pytest.raises(ContainerDriverError, match="volume is missing"):
        await ServerSpawner(driver=reserved_driver).spawn(**arguments())
    reserved_driver.ensure_volume.assert_not_awaited()
    reserved_driver.create_volume.assert_not_awaited()
    reserved_driver.create_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_readwrite_volume_keeps_its_permissions(reserved_driver):
    await ServerSpawner(driver=reserved_driver).spawn(**arguments())
    reserved_driver.exec_in_container.assert_not_awaited()
    reserved_driver.ensure_volume.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_newly_reserved_writable_volume_receives_initial_permissions(reserved_driver):
    request = arguments()
    request["volume_mounts"][0]["auto_created"] = True
    await ServerSpawner(driver=reserved_driver).spawn(**request)
    reserved_driver.ensure_volume.assert_awaited_once_with(
        "private-data", labels={"nukelab.managed": "true"}
    )
    reserved_driver.exec_in_container.assert_awaited_once_with(
        "reserved-runtime", ["chmod", "777", "/home/alice"], user="root", detach=True
    )
