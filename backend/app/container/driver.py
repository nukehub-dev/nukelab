# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Container runtime driver interface.

All container orchestration goes through a ContainerDriver so a future
KubernetesDriver (k3s) can plug in without touching spawn/quota/API logic.
The DockerDriver implementation covers both Docker and Podman (via Podman's
Docker-compatible API).

Contract for implementations:

- Methods return plain data (dicts, strings, lists, bools). No
  runtime-specific objects (e.g. aiodocker DockerContainer) may escape the
  driver boundary.
- Runtime-specific errors are caught and re-raised as ContainerDriverError
  (which carries .message and .status like aiodocker.DockerError).
- get_container_stats returns the raw Docker-stats-shaped dict; a Kubernetes
  driver must synthesize the same shape (e.g. from cAdvisor metrics).
"""

from abc import ABC, abstractmethod
from typing import Any


class ContainerDriverError(Exception):
    """Error raised by container runtime drivers.

    Mirrors the attributes callers used on aiodocker.DockerError (.message,
    .status) so error handling at call sites stays identical.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status


class ContainerDriver(ABC):
    """Abstract container runtime driver (plain-data method surface)."""

    # Runtime-specific connection handle (e.g. aiodocker.Docker). Consumers
    # must never touch it; it exists so lazy connect() checks work.
    client: Any = None

    @abstractmethod
    async def connect(self):
        """Connect to the container runtime."""

    @abstractmethod
    async def close(self):
        """Close the runtime connection."""

    @abstractmethod
    async def pull_image(self, image: str):
        """Pull a container image."""

    @abstractmethod
    async def create_container(
        self,
        name: str,
        image: str,
        command: str | None = None,
        ports: dict | None = None,
        volumes: dict | None = None,
        env: dict | None = None,
        labels: dict | None = None,
        network: str | None = None,
        cpu_limit: float | None = None,
        memory_limit: str | None = None,
        disk_limit: str | None = None,
        gpu_limit: int = 0,
        gpu_devices: list[str] | None = None,
        hostname: str | None = None,
        network_aliases: list[str] | None = None,
    ) -> str:
        """Create a container and return its id."""

    @abstractmethod
    async def start_container(self, container_id: str):
        """Start a container."""

    @abstractmethod
    async def stop_container(self, container_id: str, timeout: int = 30):
        """Stop a container."""

    @abstractmethod
    async def delete_container(self, container_id: str, force: bool = True):
        """Delete a container (best-effort; errors are swallowed)."""

    @abstractmethod
    async def get_container_info(self, container_id: str) -> dict:
        """Return the runtime's inspect dict for a container."""

    @abstractmethod
    async def get_container_status(self, container_id: str) -> str:
        """Return "running", "paused", or "stopped".

        Raises ContainerDriverError when the lookup fails (e.g. status 404
        when the container is gone).
        """

    @abstractmethod
    async def get_container_by_name(self, name: str) -> str | None:
        """Return the id of the container with this name, or None."""

    @abstractmethod
    async def wait_for_container_ready(
        self,
        container_name: str,
        health_url: str,
        timeout: int | None = None,
        interval: float | None = None,
    ) -> bool:
        """Wait until the container responds successfully on health_url."""

    @abstractmethod
    async def list_containers(self, filters: dict | None = None) -> list[dict]:
        """List containers as inspect-shaped dicts (Config.Labels, Id, State)."""

    @abstractmethod
    async def get_container_stats(self, container_id: str) -> dict:
        """Return one raw Docker-stats-shaped dict for a container.

        A Kubernetes driver must synthesize the same shape (cpu_stats,
        memory_stats, blkio_stats, networks, pids_stats), e.g. from cAdvisor.
        """

    @abstractmethod
    async def get_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        since: int | None = None,
        timestamps: bool = True,
        stdout: bool = True,
        stderr: bool = True,
    ) -> str:
        """Return container logs as a single string."""

    @abstractmethod
    async def stream_container_logs(
        self, container_id: str, tail: int = 100, stdout: bool = True, stderr: bool = True
    ):
        """Return an async iterator of log lines (str), following new output."""

    @abstractmethod
    async def exec_in_container(
        self,
        container_id: str,
        cmd: list[str],
        user: str | None = None,
        detach: bool = False,
    ) -> str:
        """Run a command in a container and return its output ("" when detached)."""

    @abstractmethod
    async def put_archive(self, container_id: str, path: str, data: bytes):
        """Write a tar archive of files into a container at path."""

    @abstractmethod
    async def ensure_volume(self, name: str, labels: dict | None = None):
        """Create a volume if it does not exist."""

    @abstractmethod
    async def create_volume(self, name: str, labels: dict | None = None):
        """Create a volume, raising ContainerDriverError on failure."""

    @abstractmethod
    async def get_volume(self, name: str) -> dict | None:
        """Return volume info, or None when it does not exist."""

    @abstractmethod
    async def delete_volume(self, name: str):
        """Delete a volume (best-effort; errors are swallowed)."""

    @abstractmethod
    async def image_exists(self, image: str) -> bool:
        """Return True when the image is present locally."""

    @abstractmethod
    async def list_images(self) -> list:
        """List images present on the host."""

    @abstractmethod
    async def version(self) -> dict:
        """Return container runtime version info."""

    async def is_podman(self) -> bool:
        """Whether the runtime is Podman. Docker-specific; False elsewhere."""
        return False
