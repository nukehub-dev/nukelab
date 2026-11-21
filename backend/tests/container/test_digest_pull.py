# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Exact-digest pull validation for the container runtime driver."""

from unittest.mock import AsyncMock, MagicMock

import aiodocker
import pytest

from app.container.docker_driver import DockerDriver
from app.container.driver import ContainerDriver, ContainerDriverError

DIGEST_REFERENCE = "registry.example.com:5000/team/runtime@sha256:" + "a" * 64
DOCKER_HUB_DIGEST_REFERENCE = "alpine@sha256:" + "b" * 64
TAG = "registry.example.com/team/runtime:approved"


def driver():
    runtime = DockerDriver()
    runtime.client = MagicMock()
    runtime.client.images.pull = AsyncMock()
    return runtime


@pytest.mark.asyncio
async def test_digest_reference_pulls_exactly_once_without_tag_rewrite():
    runtime = driver()

    await runtime.pull_image_by_digest(DIGEST_REFERENCE)

    runtime.client.images.pull.assert_awaited_once_with(DIGEST_REFERENCE)


@pytest.mark.asyncio
async def test_docker_hub_style_digest_reference_is_accepted():
    runtime = driver()

    await runtime.pull_image_by_digest(DOCKER_HUB_DIGEST_REFERENCE)

    runtime.client.images.pull.assert_awaited_once_with(DOCKER_HUB_DIGEST_REFERENCE)


@pytest.mark.parametrize(
    "reference",
    [
        TAG,
        "runtime",
        "https://registry.example.com/team/runtime@sha256:" + "a" * 64,
        "user:secret@registry.example.com/team/runtime@sha256:" + "a" * 64,
        "registry.example.com/team/runtime:tag@sha256:" + "a" * 64,
        "registry.example.com/team/runtime@sha256:" + "a" * 63,
        "registry.example.com/team/runtime@sha256:" + "a" * 65,
        "registry.example.com/team/runtime@sha256:" + "A" * 64,
        "registry.example.com/team/runtime@sha512:" + "a" * 64,
        "registry.example.com/team/runtime@sha256:" + "a" * 64 + "extra",
        "registry.example.com/team//runtime@sha256:" + "a" * 64,
        "registry.example.com/team/../runtime@sha256:" + "a" * 64,
        "registry.example.com:notaport/team/runtime@sha256:" + "a" * 64,
        "registry.example.com:5000:6000/team/runtime@sha256:" + "a" * 64,
        "registry.example.com/team/runtime@sha256:" + "a" * 64 + "\n",
        "registry.example.com/team/runtime@sha256:" + "a" * 64 + " ",
        "",
        None,
        "registry.example.com/" + "a" * 500 + "@sha256:" + "a" * 64,
    ],
)
@pytest.mark.asyncio
async def test_tags_urls_credentials_and_malformed_digests_never_reach_runtime(reference):
    runtime = driver()

    with pytest.raises(ContainerDriverError, match="invalid_digest_reference"):
        await runtime.pull_image_by_digest(reference)

    runtime.client.images.pull.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_error_is_mapped_through_the_driver_boundary():
    runtime = driver()
    runtime.client.images.pull.side_effect = aiodocker.DockerError(
        404, {"message": "manifest unknown"}
    )

    with pytest.raises(ContainerDriverError) as failure:
        await runtime.pull_image_by_digest(DIGEST_REFERENCE)

    assert failure.value.status == 404
    assert failure.value.message == "manifest unknown"


@pytest.mark.asyncio
async def test_legacy_tag_pull_keeps_its_existing_behavior():
    runtime = driver()

    await runtime.pull_image(TAG)

    runtime.client.images.pull.assert_awaited_once_with(TAG)


@pytest.mark.asyncio
async def test_unsupported_driver_fails_closed():
    class UnsupportedDriver:
        async def pull_image_by_digest(self, reference):
            return await ContainerDriver.pull_image_by_digest(self, reference)

    with pytest.raises(ContainerDriverError, match="unsupported"):
        await UnsupportedDriver().pull_image_by_digest(DIGEST_REFERENCE)
