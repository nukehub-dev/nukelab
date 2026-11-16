# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Immutable selection and non-destructive toolchain cache driver contracts."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import aiodocker
import pytest

from app.container.docker_driver import DockerDriver
from app.container.driver import ImageResolutionError, ImmutableToolchainCacheError
from app.schemas.environment_manifest import ImageIdentity

IMAGE_A = "sha256:" + "a" * 64
IMAGE_B = "sha256:" + "b" * 64
REPOSITORY_DIGEST = "registry/toolchain@sha256:" + "c" * 64
MOUNTS = ["/opt/nuke"]
MANIFEST = {"mounts": MOUNTS, "env": {"NUKE_HOME": "/opt/nuke"}}


def image_info(image_id=IMAGE_A, **changes):
    return {
        "Id": image_id,
        "RepoDigests": [REPOSITORY_DIGEST],
        "Os": "linux",
        "Architecture": "amd64",
        **changes,
    }


def identity():
    return {
        "requested_reference": "toolchain:latest",
        "local_id": IMAGE_A,
        "repository_digests": [REPOSITORY_DIGEST],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }


def stamp(**changes):
    return {
        "cache_version": 1,
        "image_id": IMAGE_A,
        "os": "linux",
        "architecture": "amd64",
        "mount_paths": MOUNTS,
        **changes,
    }


def docker_error(status=404):
    return aiodocker.DockerError(status, {"message": "private runtime diagnostic"})


def driver():
    result = DockerDriver()
    result.client = MagicMock()
    result.client.images.get = AsyncMock(return_value=image_info())
    result.client.images.pull = AsyncMock()
    result.client.volumes.get = AsyncMock(side_effect=docker_error())
    result.client.volumes.create = AsyncMock()
    lock = AsyncMock()
    result.client.containers.create = AsyncMock(return_value=lock)
    result._read_toolchain_manifest = AsyncMock(return_value=(MANIFEST, stamp()))
    return result, lock


@pytest.mark.asyncio
async def test_resolution_is_plain_local_metadata_not_registry_verification():
    runtime, _ = driver()
    resolved = await runtime.resolve_image("toolchain:latest")
    assert resolved == identity()
    assert ImageIdentity.model_validate(resolved).spawn_reference == IMAGE_A
    runtime.client.images.pull.assert_not_awaited()
    json.dumps(resolved)


@pytest.mark.asyncio
async def test_podman_bare_local_image_id_is_canonicalized():
    runtime, _ = driver()
    runtime.client.images.get.return_value = image_info("a" * 64, RepoDigests=None)
    resolved = await runtime.resolve_image("toolchain:latest")
    assert resolved["local_id"] == IMAGE_A
    assert resolved["repository_digests"] == []


@pytest.mark.asyncio
async def test_tag_repush_does_not_change_the_previously_selected_artifact():
    runtime, _ = driver()
    images = {"toolchain:latest": image_info(IMAGE_A), IMAGE_A: image_info(IMAGE_A)}
    runtime.client.images.get.side_effect = lambda ref: images[ref]
    old = await runtime.resolve_image("toolchain:latest")
    images["toolchain:latest"] = image_info(IMAGE_B)
    current = await runtime.resolve_image("toolchain:latest")
    assert current["local_id"] == IMAGE_B
    assert (await runtime.resolve_image(old["local_id"]))["local_id"] == IMAGE_A
    assert runtime.immutable_toolchain_cache_name(
        old, MOUNTS
    ) != runtime.immutable_toolchain_cache_name(current, MOUNTS)


@pytest.mark.parametrize(
    "reference",
    ["https://registry/image", "user:secret@registry/image", "image\nvalue", "", "x" * 501, None],
)
@pytest.mark.asyncio
async def test_invalid_reference_rejected_before_runtime(reference):
    runtime, _ = driver()
    with pytest.raises(ImageResolutionError, match="invalid_image_reference"):
        await runtime.resolve_image(reference)
    runtime.client.images.get.assert_not_awaited()


@pytest.mark.parametrize(
    "info",
    [
        None,
        {},
        image_info(Id="bad"),
        image_info(Architecture=None),
        image_info(Os=""),
        image_info(RepoDigests="bad"),
        image_info(RepoDigests=[None]),
        image_info(RepoDigests=["https://user:secret@registry/image"]),
        image_info(RepoDigests=[REPOSITORY_DIGEST] * 33),
        image_info(IMAGE_B),
    ],
)
@pytest.mark.asyncio
async def test_incomplete_or_conflicting_identity_fails_closed(info):
    runtime, _ = driver()
    runtime.client.images.get.return_value = info
    with pytest.raises(ImageResolutionError, match="image_identity_invalid"):
        await runtime.resolve_image(IMAGE_A)


@pytest.mark.parametrize(
    "error,code",
    [
        (docker_error(), "artifact_missing"),
        (docker_error(503), "artifact_unavailable"),
        (RuntimeError("secret"), "artifact_unavailable"),
    ],
)
@pytest.mark.asyncio
async def test_missing_pinned_artifact_never_pulls_or_substitutes(error, code):
    runtime, _ = driver()
    runtime.client.images.get.side_effect = error
    with pytest.raises(ImageResolutionError, match=code) as failure:
        await runtime.resolve_image(IMAGE_A)
    assert "secret" not in str(failure.value)
    assert "private" not in str(failure.value)
    runtime.client.images.get.assert_awaited_once_with(IMAGE_A)
    runtime.client.images.pull.assert_not_awaited()


def test_cache_key_includes_artifact_platform_and_layout():
    original = DockerDriver.immutable_toolchain_cache_name(identity(), MOUNTS)
    assert original.startswith("nukelab-toolchain-v2-")
    for changed, mounts in [
        (identity() | {"local_id": IMAGE_B}, MOUNTS),
        (identity() | {"architecture": "arm64"}, MOUNTS),
        (identity() | {"os": "other"}, MOUNTS),
        (identity(), ["/opt/tools"]),
    ]:
        assert DockerDriver.immutable_toolchain_cache_name(changed, mounts) != original


@pytest.mark.parametrize(
    "invalid_identity",
    [
        None,
        {},
        {"local_id": None},
        identity() | {"os": None},
        identity() | {"architecture": "x" * 33},
    ],
)
def test_invalid_plain_identity_cannot_select_cache(invalid_identity):
    with pytest.raises(ImmutableToolchainCacheError, match="invalid_toolchain_layout"):
        DockerDriver.immutable_toolchain_cache_name(invalid_identity, MOUNTS)


@pytest.mark.parametrize(
    "mounts",
    [
        [],
        ["/a", "/b"],
        ["/"],
        ["relative"],
        ["/a/../b"],
        ["/a/./b"],
        ["/a//b"],
        ["/a;echo"],
        ["/toolchain-target"],
        [None],
    ],
)
def test_unsafe_or_unsupported_cache_layouts_rejected(mounts):
    with pytest.raises(ImmutableToolchainCacheError, match="invalid_toolchain_layout"):
        DockerDriver.immutable_toolchain_cache_name(identity(), mounts)


@pytest.mark.parametrize(
    "reference", ["toolchain:latest", "a" * 64, "registry/toolchain@sha256:bad"]
)
@pytest.mark.asyncio
async def test_cache_requires_pinned_image(reference):
    runtime, _ = driver()
    with pytest.raises(ImageResolutionError, match="immutable_image_required"):
        await runtime.prepare_immutable_toolchain_volume(reference, "ignored", MOUNTS)
    runtime.client.images.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_rejects_legacy_or_wrong_identity_name_before_mutation():
    runtime, _ = driver()
    with pytest.raises(ImmutableToolchainCacheError, match="toolchain_cache_name_mismatch"):
        await runtime.prepare_immutable_toolchain_volume(IMAGE_A, "legacy-tag-volume", MOUNTS)
    runtime.client.containers.create.assert_not_awaited()
    runtime.client.volumes.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_valid_cache_is_read_only_reused():
    runtime, lock = driver()
    runtime.client.volumes.get.side_effect = None
    runtime._populate_immutable_toolchain_volume = AsyncMock()
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    assert await runtime.prepare_immutable_toolchain_volume(IMAGE_A, cache, MOUNTS) == MANIFEST
    runtime._populate_immutable_toolchain_volume.assert_not_awaited()
    runtime.client.volumes.create.assert_not_awaited()
    runtime._read_toolchain_manifest.assert_awaited_once_with(IMAGE_A, cache)
    lock.delete.assert_awaited_once_with(force=True)


@pytest.mark.parametrize(
    "cached,code",
    [
        (None, "toolchain_cache_incomplete"),
        ((MANIFEST, stamp(image_id=IMAGE_B)), "toolchain_cache_mismatch"),
        ((MANIFEST, stamp(mount_paths=["/other"])), "toolchain_cache_mismatch"),
        ((MANIFEST, stamp(cache_version=None)), "toolchain_cache_mismatch"),
        ((MANIFEST, stamp(os="other")), "toolchain_cache_mismatch"),
        ((MANIFEST, stamp(architecture="arm64")), "toolchain_cache_mismatch"),
        (({"mounts": ["/other"]}, stamp()), "toolchain_cache_mismatch"),
        (({"mounts": MOUNTS, "env": {"PATH": []}}, stamp()), "toolchain_cache_mismatch"),
        (({"mounts": MOUNTS, "env_prepend": []}, stamp()), "toolchain_cache_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_existing_cache_mismatch_never_wipes_or_repopulates(cached, code):
    runtime, lock = driver()
    runtime.client.volumes.get.side_effect = None
    runtime._read_toolchain_manifest.return_value = cached
    runtime._populate_immutable_toolchain_volume = AsyncMock()
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    with pytest.raises(ImmutableToolchainCacheError, match=code):
        await runtime.prepare_immutable_toolchain_volume(IMAGE_A, cache, MOUNTS)
    runtime._populate_immutable_toolchain_volume.assert_not_awaited()
    runtime.client.volumes.create.assert_not_awaited()
    lock.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_competing_lock_is_never_inspected_or_ttl_deleted():
    runtime, lock = driver()
    runtime.client.containers.create.side_effect = docker_error(409)
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    with pytest.raises(ImmutableToolchainCacheError, match="toolchain_cache_busy"):
        await runtime.prepare_immutable_toolchain_volume(IMAGE_A, cache, MOUNTS)
    runtime.client.containers.get.assert_not_called()
    lock.delete.assert_not_awaited()
    runtime.client.volumes.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_lock_create_failure_is_sanitized():
    runtime, _ = driver()
    runtime.client.containers.create.side_effect = RuntimeError("private diagnostic")
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    with pytest.raises(ImmutableToolchainCacheError, match="toolchain_cache_unavailable"):
        await runtime.prepare_immutable_toolchain_volume(IMAGE_A, cache, MOUNTS)


@pytest.mark.asyncio
async def test_uninspectable_volume_is_not_treated_as_missing():
    runtime, lock = driver()
    runtime.client.volumes.get.side_effect = docker_error(503)
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    with pytest.raises(ImmutableToolchainCacheError, match="toolchain_cache_unavailable"):
        await runtime.prepare_immutable_toolchain_volume(IMAGE_A, cache, MOUNTS)
    runtime.client.volumes.create.assert_not_awaited()
    lock.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_cache_populates_by_local_id_even_if_selected_by_repository_digest():
    runtime, lock = driver()
    runtime._populate_immutable_toolchain_volume = AsyncMock()
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    assert (
        await runtime.prepare_immutable_toolchain_volume(REPOSITORY_DIGEST, cache, MOUNTS)
        == MANIFEST
    )
    runtime._populate_immutable_toolchain_volume.assert_awaited_once_with(
        IMAGE_A, cache, MOUNTS, identity() | {"requested_reference": REPOSITORY_DIGEST}
    )
    runtime._read_toolchain_manifest.assert_awaited_once_with(IMAGE_A, cache)
    lock.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_new_cache_creation_is_sanitized_and_releases_owned_lock():
    runtime, lock = driver()
    runtime.client.volumes.create.side_effect = docker_error(500)
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    with pytest.raises(ImmutableToolchainCacheError, match="toolchain_cache_unavailable"):
        await runtime.prepare_immutable_toolchain_volume(IMAGE_A, cache, MOUNTS)
    lock.delete.assert_awaited_once()


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.asyncio
async def test_population_uncertainty_retains_lock(unknown):
    runtime, lock = driver()
    runtime._populate_immutable_toolchain_volume = AsyncMock(
        side_effect=ImmutableToolchainCacheError(
            "toolchain_population_failed", outcome_unknown=unknown
        )
    )
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    with pytest.raises(ImmutableToolchainCacheError):
        await runtime.prepare_immutable_toolchain_volume(IMAGE_A, cache, MOUNTS)
    assert lock.delete.await_count == (0 if unknown else 1)


@pytest.mark.asyncio
async def test_owned_lock_cleanup_failure_does_not_delete_some_other_lock():
    runtime, lock = driver()
    runtime._populate_immutable_toolchain_volume = AsyncMock()
    lock.delete.side_effect = docker_error(500)
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    assert await runtime.prepare_immutable_toolchain_volume(IMAGE_A, cache, MOUNTS) == MANIFEST
    lock.delete.assert_awaited_once()
    runtime.client.containers.get.assert_not_called()


@pytest.mark.asyncio
async def test_population_helper_has_no_wipe_and_publishes_stamp_last():
    runtime, helper = driver()
    helper.wait.return_value = {"StatusCode": 0}
    cache = runtime.immutable_toolchain_cache_name(identity(), MOUNTS)
    await runtime._populate_immutable_toolchain_volume(IMAGE_A, cache, MOUNTS, identity())
    config = runtime.client.containers.create.call_args.args[0]
    assert config["Image"] == IMAGE_A
    assert config["Entrypoint"] == []
    script = config["Cmd"][-1]
    assert "set -eu; cp -a -- " in script
    assert "rm " not in script
    assert script.index("cp -a") < script.index("printf") < script.index("mv --")
    assert config["HostConfig"]["NetworkMode"] == "none"
    assert config["HostConfig"]["ReadonlyRootfs"] is True
    assert config["HostConfig"]["CapDrop"] == ["ALL"]
    helper.delete.assert_awaited_once_with(force=True)


@pytest.mark.parametrize("result", [{"StatusCode": 7}, {}, 1])
@pytest.mark.asyncio
async def test_population_failure_is_not_a_completed_cache(result):
    runtime, helper = driver()
    helper.wait.return_value = result
    with pytest.raises(ImmutableToolchainCacheError, match="toolchain_population_failed"):
        await runtime._populate_immutable_toolchain_volume(IMAGE_A, "cache", MOUNTS, identity())
    helper.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_helper_start_failure_with_unconfirmed_termination_is_unknown():
    runtime, helper = driver()
    helper.start.side_effect = docker_error(500)
    helper.delete.side_effect = docker_error(500)
    with pytest.raises(
        ImmutableToolchainCacheError, match="toolchain_population_unknown"
    ) as failure:
        await runtime._populate_immutable_toolchain_volume(IMAGE_A, "cache", MOUNTS, identity())
    assert failure.value.outcome_unknown is True


@pytest.mark.asyncio
async def test_stopped_helper_delete_failure_does_not_claim_live_unknown_writer():
    runtime, helper = driver()
    helper.wait.return_value = 0
    helper.delete.side_effect = docker_error(500)
    await runtime._populate_immutable_toolchain_volume(IMAGE_A, "cache", MOUNTS, identity())


@pytest.mark.asyncio
async def test_helper_creation_failure_is_sanitized():
    runtime, _ = driver()
    runtime.client.containers.create.side_effect = RuntimeError("private diagnostic")
    with pytest.raises(ImmutableToolchainCacheError, match="toolchain_population_failed"):
        await runtime._populate_immutable_toolchain_volume(IMAGE_A, "cache", MOUNTS, identity())


@pytest.mark.asyncio
async def test_cancellation_cleans_mutating_helper_before_propagating():
    runtime, helper = driver()
    helper.wait.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await runtime._populate_immutable_toolchain_volume(IMAGE_A, "cache", MOUNTS, identity())
    helper.delete.assert_awaited_once_with(force=True)
