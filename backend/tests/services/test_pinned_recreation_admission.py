# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Unavailable pinned artifacts fail before new runtime/storage reservations."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.models.credit_transaction import CreditTransaction
from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server
from app.models.server_queue import ServerQueue
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.services.server_launch_service import LaunchError, ServerLaunchService
from tests.services.test_server_launch_service import IMAGE_ID, OTHER_IMAGE_ID, runtime_driver
from tests.services.test_server_launch_service import launch_fixture as launch_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing", "identity", "architecture", "os"])
async def test_pinned_artifact_faults_have_no_compute_storage_or_credit_effects(
    db_session, launch_fixture, fault
):
    driver = runtime_driver()
    service = ServerLaunchService(db_session, driver)
    request = launch_fixture.request()
    revision_id = await service.resolve_revision(launch_fixture.owner_id, request)
    driver.resolve_image.reset_mock()
    driver.pull_image.reset_mock()
    if fault == "missing":
        driver.image_exists.return_value = False
    else:
        observed = {
            "requested_reference": IMAGE_ID,
            "local_id": OTHER_IMAGE_ID if fault == "identity" else IMAGE_ID,
            "repository_digests": [],
            "os": "windows" if fault == "os" else "linux",
            "architecture": "arm64" if fault == "architecture" else "amd64",
            "registry_verified": False,
        }
        driver.resolve_image = AsyncMock(return_value=observed)
    with pytest.raises(
        LaunchError, match="artifact_missing" if fault == "missing" else "revision_unavailable"
    ):
        await service.submit_pinned(launch_fixture.owner_id, request, revision_id)
    driver.pull_image.assert_not_awaited()
    if fault != "missing":
        driver.resolve_image.assert_awaited_once_with(IMAGE_ID)
    for model in (Server, ServerQueue, Volume, GpuAllocation, VolumeOperation, CreditTransaction):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
