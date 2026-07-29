# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Container runtime driver factory.

Selects the ContainerDriver implementation from settings.container_runtime
(env CONTAINER_RUNTIME, default "docker"). "docker" covers both Docker and
Podman; "kubernetes" is reserved for the future k3s driver.
"""

from app.config import settings
from app.container.driver import ContainerDriver, ContainerDriverError

_driver: ContainerDriver | None = None


def _create_driver() -> ContainerDriver:
    """Instantiate the driver for the configured runtime."""
    runtime = settings.container_runtime
    if runtime == "docker":
        from app.container.docker_driver import DockerDriver

        return DockerDriver()
    raise ContainerDriverError(
        f"Unknown CONTAINER_RUNTIME: {runtime!r}. Supported values: 'docker' (Docker or Podman)."
    )


async def get_driver() -> ContainerDriver:
    """Get the shared driver instance, connecting lazily."""
    global _driver
    if _driver is None:
        _driver = _create_driver()
    if not _driver.client:
        await _driver.connect()
    return _driver


async def get_fresh_driver() -> ContainerDriver:
    """Get a fresh, connected driver instance (for Celery workers)."""
    driver = _create_driver()
    await driver.connect()
    return driver
