# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Backward-compatibility shim for the pre-driver container client.

The ContainerClient implementation moved to
app/container/docker_driver.py (DockerDriver); runtime selection lives in
app/container/factory.py. This module re-exports the old names so existing
imports and test patch seams keep working:

- ContainerClient (alias of DockerDriver)
- container_client (shared singleton) + get_container_client /
  get_fresh_container_client
- the aiodocker / aiohttp module attributes that tests patch
"""

import aiodocker  # noqa: F401  # re-exported: patched by tests
import aiohttp  # noqa: F401  # re-exported: patched by tests

from app.container.docker_driver import DockerDriver as ContainerClient
from app.container.factory import get_fresh_driver

# Singleton instance. Kept independent of the factory's singleton because
# tests patch this module attribute directly (app.container.client.container_client).
container_client = ContainerClient()


async def get_container_client():
    """Get initialized Docker client"""
    if not container_client.client:
        await container_client.connect()
    return container_client


async def get_fresh_container_client():
    """Get a fresh Docker client instance (for Celery workers)."""
    return await get_fresh_driver()
