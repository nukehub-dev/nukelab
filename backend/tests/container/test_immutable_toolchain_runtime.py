# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Opt-in daemon integration using disposable, uniquely labelled tiny artifacts.

Run with --run-container-integration against an isolated local/CI Docker daemon.
Requires cached postgres:17-alpine; never pulls, publishes, prunes or mounts host
paths. The fixture copies only shell utilities/libraries into a scratch image,
avoiding PostgreSQL's inherited data-volume declaration and entrypoint.
"""

import asyncio
import io
import json
import tarfile
import uuid

import aiodocker
import pytest

from app.container.docker_driver import DockerDriver
from app.schemas.environment_manifest import ImageIdentity

OWNER_LABEL = "nukelab.test.owner"
MOUNTS = ["/opt/nuke"]


def build_context(owner: str, value: str) -> io.BytesIO:
    dockerfile = (
        "FROM postgres:17-alpine AS tools\n"
        "FROM scratch\n"
        "COPY --from=tools /bin/ /bin/\n"
        "COPY --from=tools /lib/ /lib/\n"
        "COPY toolchain/ /opt/nuke/\n"
        f'LABEL {OWNER_LABEL}="{owner}"\n'
        "USER 0:0\n"
    )
    manifest = json.dumps({"mounts": MOUNTS, "env": {}, "env_prepend": {}})
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for directory in ("toolchain", "toolchain/bin"):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for name, content in {
            "Dockerfile": dockerfile,
            "toolchain/nukelab-toolchain.json": manifest,
            "toolchain/bin/value": value + "\n",
        }.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    output.seek(0)
    return output


async def build_fixture(driver: DockerDriver, owner: str, tag: str, value: str) -> dict:
    # Aiodocker is intentionally confined to this disposable runtime test.
    with build_context(owner, value) as context:
        output = await driver.client.images.build(
            fileobj=context,
            encoding="gzip",
            tag=tag,
            pull=False,
            labels={OWNER_LABEL: owner},
            rm=True,
            forcerm=True,
        )
    assert not any(item.get("error") or item.get("errorDetail") for item in output), output
    image = await driver.client.images.get(tag)
    assert image["Config"]["Labels"][OWNER_LABEL] == owner
    assert not image["Config"].get("Volumes"), "Fixture must not create anonymous data volumes"
    return await driver.resolve_image(tag)


async def create_reader(driver: DockerDriver, owner: str, image: str, cache: str):
    reader = await driver.client.containers.create(
        {
            "Image": image,
            "Entrypoint": [],
            "Cmd": ["sh", "-c", "sleep 120"],
            "User": "65532:65532",
            "Labels": {OWNER_LABEL: owner},
            "HostConfig": {
                "Mounts": [
                    {"Type": "volume", "Source": cache, "Target": "/opt/nuke", "ReadOnly": True}
                ],
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "AutoRemove": False,
            },
        },
        name="nukelab-test-reader-" + owner + "-" + uuid.uuid4().hex[:8],
    )
    await reader.start()
    return reader


async def cleanup_owned(driver: DockerDriver, owner: str, caches: set[str]):
    """Delete only resources whose unique owner or exact image lineage is proven."""
    images = await driver.client.images.list(
        all=True, filters=json.dumps({"label": [f"{OWNER_LABEL}={owner}"]})
    )
    image_ids = {image["Id"] for image in images}
    # Image labels are inherited by helper containers, and exact fixture-image
    # lineage provides a second ownership proof for runtime-specific label merges.
    containers = (
        await driver.client.containers.list(
            all=True, filters=json.dumps({"ancestor": list(image_ids)})
        )
        if image_ids
        else []
    )
    for container in containers:
        info = await container.show()
        config = info.get("Config", {})
        labels = config.get("Labels") or {}
        if labels.get(OWNER_LABEL) == owner or config.get("Image") in image_ids:
            await container.delete(force=True)
    for cache in caches:
        try:
            volume = await driver.client.volumes.get(cache)
            info = await volume.show()
        except aiodocker.DockerError as exc:
            if exc.status == 404:
                continue
            raise
        labels = info.get("Labels") or {}
        assert labels.get("nukelab.toolchain.immutable") == "true"
        assert labels.get("nukelab.toolchain.image") in image_ids
        await volume.delete()
    for image_id in image_ids:
        current = await driver.client.images.get(image_id)
        assert current["Config"]["Labels"][OWNER_LABEL] == owner
        await driver.client.images.delete(image_id, force=True, noprune=True)


@pytest.mark.asyncio
async def test_retagging_keeps_captured_artifact_and_live_toolchain_cache_unchanged(request):
    if not request.config.getoption("--run-container-integration", default=False):
        pytest.skip("Opt-in disposable Docker runtime fixture")
    owner = uuid.uuid4().hex
    tag = "nukelab-test-toolchain-" + owner + ":mutable"
    driver = DockerDriver()
    caches: set[str] = set()
    await driver.connect()
    try:
        async with asyncio.timeout(120):
            # Fail the explicitly requested rehearsal if its prerequisite is absent.
            await driver.client.images.get("postgres:17-alpine")
            artifact_a = await build_fixture(driver, owner, tag, "A")
            assert artifact_a["registry_verified"] is False
            assert (
                ImageIdentity.model_validate(artifact_a).spawn_reference == artifact_a["local_id"]
            )
            cache_a = driver.immutable_toolchain_cache_name(artifact_a, MOUNTS)
            caches.add(cache_a)
            manifest_a = await driver.prepare_immutable_toolchain_volume(
                artifact_a["local_id"], cache_a, MOUNTS
            )
            assert manifest_a["mounts"] == MOUNTS
            reader = await create_reader(driver, owner, artifact_a["local_id"], cache_a)
            assert (
                await driver.exec_in_container(reader.id, ["cat", "/opt/nuke/bin/value"])
            ).strip() == "A"

            artifact_b = await build_fixture(driver, owner, tag, "B")
            assert artifact_b["local_id"] != artifact_a["local_id"]
            assert (await driver.resolve_image(tag))["local_id"] == artifact_b["local_id"]
            assert (await driver.resolve_image(artifact_a["local_id"]))["local_id"] == artifact_a[
                "local_id"
            ]
            cache_b = driver.immutable_toolchain_cache_name(artifact_b, MOUNTS)
            caches.add(cache_b)
            assert cache_b != cache_a
            await driver.prepare_immutable_toolchain_volume(artifact_b["local_id"], cache_b, MOUNTS)
            # Reusing A after tag replacement may only verify/read its cache.
            await driver.prepare_immutable_toolchain_volume(artifact_a["local_id"], cache_a, MOUNTS)
            assert (
                await driver.exec_in_container(reader.id, ["cat", "/opt/nuke/bin/value"])
            ).strip() == "A"
            reader_b = await create_reader(driver, owner, artifact_b["local_id"], cache_b)
            assert (
                await driver.exec_in_container(reader_b.id, ["cat", "/opt/nuke/bin/value"])
            ).strip() == "B"
    finally:
        try:
            await cleanup_owned(driver, owner, caches)
        finally:
            await driver.close()
