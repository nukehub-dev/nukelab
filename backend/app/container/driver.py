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

import hashlib
import json
import re
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


class ImageResolutionError(ContainerDriverError):
    """An approved local artifact could not be resolved without substitution."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code, status=status)
        self.code = code


class ImmutableToolchainCacheError(ContainerDriverError):
    """A cache cannot be reused safely; uncertain helpers retain their lock."""

    def __init__(self, code: str, *, outcome_unknown: bool = False):
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown


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

    async def pull_image_by_digest(self, reference: str) -> None:
        """Pull exactly one ``repo@sha256:<digest>`` reference.

        Drivers that cannot guarantee digest-only pulls must fail closed rather
        than silently accepting a tag or another artifact.
        """
        raise ContainerDriverError("Image pulls by digest are unsupported")

    @abstractmethod
    async def resolve_image(self, image: str) -> dict:
        """Inspect an existing local artifact, returning a plain immutable identity.

        Return requested_reference, canonical local_id (sha256:<hex>),
        repository_digests, os, architecture and registry_verified=False.
        Local metadata never establishes registry retrievability. Never pull,
        change tags or substitute another artifact when the selection is missing.
        """

    @staticmethod
    def immutable_toolchain_cache_name(identity: dict, mount_paths: list[str]) -> str:
        """Key one immutable cache by local artifact, platform and approved layout."""
        if (
            not isinstance(identity, dict)
            or not isinstance(identity.get("local_id"), str)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", identity["local_id"])
            or any(
                not isinstance(identity.get(key), str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", identity[key])
                for key in ("os", "architecture")
            )
            or not isinstance(mount_paths, list)
            or len(mount_paths) != 1
            or not isinstance(mount_paths[0], str)
            or not re.fullmatch(r"/[A-Za-z0-9][A-Za-z0-9._/-]*", mount_paths[0])
            or any(part in ("", ".", "..") for part in mount_paths[0].split("/")[1:])
            or mount_paths[0] == "/toolchain-target"
            or mount_paths[0].startswith("/toolchain-target/")
        ):
            raise ImmutableToolchainCacheError("invalid_toolchain_layout")
        key = json.dumps(
            {
                "version": 1,
                "local_id": identity["local_id"],
                "os": identity["os"],
                "architecture": identity["architecture"],
                "mount_paths": mount_paths,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "nukelab-toolchain-v2-" + hashlib.sha256(key.encode()).hexdigest()

    @abstractmethod
    async def prepare_immutable_toolchain_volume(
        self, image: str, cache_name: str, mount_paths: list[str]
    ) -> dict:
        """Populate a new identity-keyed cache, or verify and reuse an existing one.

        image must be a pinned local ID or repository digest. Obtain cache_name
        from immutable_toolchain_cache_name with resolve_image's identity.
        Existing caches are never wiped/repopulated, including incomplete ones.
        Unknown lock/helper outcomes require reconciliation, never TTL takeover.
        Returns the validated toolchain manifest; required failure is fatal.
        """

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

    async def create_batch_container(
        self,
        *,
        name: str,
        image: str,
        argv: list[str],
        mounts: list[dict],
        labels: dict[str, str],
        limits: dict,
        env: dict[str, str],
        workdir: str = "/work",
        timeout_seconds: int | None = None,
    ) -> str:
        """Create an unstarted hardened headless job container and return its id.

        The batch profile is deliberately separate from interactive servers:
        it runs a literal argument vector with no network, ports, health probe
        or restart policy, and it requires a read-only rootfs with mandatory
        resource bounds. Drivers that cannot provide every control must fail
        closed instead of degrading the profile.
        """
        raise ContainerDriverError("Batch job containers are unsupported")

    async def prepare_batch_volume(
        self,
        *,
        name: str,
        image: str,
        volume: str,
        labels: dict[str, str],
        timeout_seconds: int = 30,
    ) -> None:
        """Prepare a batch volume for use by the fixed non-root job identity.

        Drivers that cannot provide a bounded, trusted ownership fixup must
        fail closed rather than starting a job whose volume is unusable.
        """
        raise ContainerDriverError("Batch job volume preparation is unsupported")

    @abstractmethod
    async def stop_container(self, container_id: str, timeout: int = 30):
        """Stop a container. Raises ContainerDriverError on runtime failure."""

    @abstractmethod
    async def delete_container(self, container_id: str, force: bool = True):
        """Delete a container. Raises ContainerDriverError on runtime failure."""

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
        body_contains: str | None = None,
    ) -> bool:
        """Wait until the container responds successfully on health_url.

        Args:
            body_contains: If set, the response body must contain this string
                (case-sensitive) for the probe to be considered successful.
                Useful to distinguish the container's /health body from a
                fallback SPA shell served by the reverse proxy.
        """

    @abstractmethod
    async def list_containers(
        self, filters: dict | None = None, *, all: bool = False
    ) -> list[dict]:
        """List containers as inspect-shaped dicts (Config.Labels, Id, State)."""

    async def create_recovery_helper(
        self,
        *,
        name: str,
        image: str,
        command: list[str],
        mounts: list[dict],
        labels: dict,
        limits: dict,
    ) -> str:
        """Create an unstarted, hardened helper; unsupported drivers fail closed."""
        raise ContainerDriverError("Volume recovery helpers are unsupported")

    async def wait_recovery_helper(self, container_id: str, timeout: float) -> int:
        raise ContainerDriverError("Volume recovery helpers are unsupported")

    @abstractmethod
    async def get_container_stats(self, container_id: str) -> dict:
        """Return one raw Docker-stats-shaped dict for a container.

        A Kubernetes driver must synthesize the same shape (cpu_stats,
        memory_stats, blkio_stats, networks, pids_stats), e.g. from cAdvisor.
        """

    @abstractmethod
    async def get_container_top(self, container_id: str, ps_args: str | None = None) -> dict:
        """Return a Docker-top-shaped dict {"Titles": [...], "Processes": [[...]]}."""

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
        """Return volume info; only verified absence returns None. Raise on unknown state."""

    @abstractmethod
    async def delete_volume(self, name: str):
        """Delete a volume; verified absence is idempotent, runtime failures raise."""

    @abstractmethod
    async def prepare_toolchain_volume(
        self, image: str, volume_name: str, mount_paths: list[str]
    ) -> dict:
        """Create or refresh a volume populated from a toolchain image.

        Returns the toolchain manifest (parsed JSON) so callers know which
        paths to mount and which environment variables to inject.

        Implementations must be idempotent and safe under concurrent callers
        (API workers and Celery tasks both reach this path): population must
        be serialized across processes, and a populated volume must only be
        reused when it provably matches the current local image (a stamp
        recorded at populate time), so re-pushed image tags invalidate the
        cached volume. This lets multiple servers share one toolchain volume
        and avoids copying multi-gigabyte images on every spawn.

        For Docker/Podman this runs a temporary container to copy image
        contents into a named volume only when the volume is not already
        populated. Each mount path's contents are copied into the volume
        root, because consumers mount the volume at that path (e.g. the
        volume mounted at /opt/nuke must directly contain bin/, etc/).
        The supported contract is a single toolchain root per volume.
        For Kubernetes this becomes an init container in the pod
        spec and the driver can return a manifest read from the image
        metadata.
        """

    @abstractmethod
    async def image_exists(self, image: str) -> bool:
        """Return True when the image is present locally."""

    @abstractmethod
    async def get_image_env(self, image: str) -> dict[str, str]:
        """Return the default environment variables defined by an image."""

    @abstractmethod
    async def list_images(self) -> list:
        """List images present on the host."""

    @abstractmethod
    async def version(self) -> dict:
        """Return container runtime version info."""

    async def is_podman(self) -> bool:
        """Whether the runtime is Podman. Docker-specific; False elsewhere."""
        return False
