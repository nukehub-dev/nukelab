# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Docker container runtime driver.

Implements the ContainerDriver interface via aiodocker. Covers both Docker
and Podman (via Podman's Docker-compatible API; detected at runtime for CDI
GPU injection). No aiodocker objects escape this module: aiodocker
DockerError is caught and re-raised as ContainerDriverError at the boundary.
"""

import asyncio
import hashlib
import io
import json
import logging
import os
import posixpath
import re
import shlex
import tarfile
import time
import uuid
from datetime import UTC, datetime

import aiodocker
import aiohttp

from app.config import settings
from app.container.driver import (
    ContainerDriver,
    ContainerDriverError,
    ImageResolutionError,
    ImmutableToolchainCacheError,
)

logger = logging.getLogger(__name__)


def _map_error(e: aiodocker.DockerError) -> ContainerDriverError:
    """Re-raise an aiodocker DockerError as a ContainerDriverError."""
    return ContainerDriverError(getattr(e, "message", str(e)), status=getattr(e, "status", None))


_MAX_DIGEST_REFERENCE_CHARS = 500
_DIGEST_REFERENCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}\Z")


def _valid_digest_reference(value: object) -> bool:
    """Return True only for a bounded ``repo@sha256:<64 lowercase hex>`` value.

    Repository path components must be non-empty and must not contain a tag.
    A registry port is the only permitted colon outside the digest separator.
    """
    if not isinstance(value, str) or not value or len(value) > _MAX_DIGEST_REFERENCE_CHARS:
        return False
    if value != value.strip() or any(ord(char) < 33 or ord(char) == 127 for char in value):
        return False
    if "://" in value or "\\" in value or value.count("@") != 1:
        return False
    if not _DIGEST_REFERENCE_RE.fullmatch(value):
        return False
    name = value.rsplit("@", 1)[0]
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    for index, part in enumerate(parts):
        if ":" not in part:
            continue
        if index != 0 or part.count(":") > 1:
            return False
        port = part.rsplit(":", 1)[1]
        if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
            return False
    return True


_BATCH_JOB_NAME_RE = re.compile(
    r"nukelab-job-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)
_BATCH_PREP_NAME_RE = re.compile(
    r"nukelab-job-prep-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)
_BATCH_IMAGE_ID_RE = re.compile(r"sha256:[a-f0-9]{64}")
_BATCH_VOLUME_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_BATCH_ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BATCH_LABEL_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_BATCH_MOUNT_KEYS = {"Type", "Source", "Target", "ReadOnly"}
_BATCH_FIXED_ENV = {
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
}
_BATCH_FORBIDDEN_TOOLCHAIN_TARGETS = (
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/usr",
    "/bin",
    "/lib",
    "/lib64",
)
_BATCH_FIXED_TMPFS_TARGETS = ("/tmp", "/home")
_BATCH_JOB_USER = "65532:65532"
_BATCH_MAX_ARGV_ITEMS = 64
_BATCH_MAX_ARGV_BYTES = 16384
_BATCH_MAX_ENV_ENTRIES = 128
_BATCH_MAX_ENV_KEY_CHARS = 128
_BATCH_MAX_ENV_VALUE_CHARS = 8192
_BATCH_MAX_ENV_BYTES = 32768
_BATCH_MAX_LABELS = 32
_BATCH_MAX_LABEL_KEY_CHARS = 128
_BATCH_MAX_LABEL_VALUE_CHARS = 1024
_BATCH_MAX_PATH_CHARS = 4096
_BATCH_MAX_VOLUME_NAME_CHARS = 255
_BATCH_MIN_MEMORY_BYTES = 64 * 1024**2
_BATCH_MAX_MEMORY_BYTES = 1024**4
_BATCH_MIN_PIDS = 16
_BATCH_MAX_PIDS = 4096
_BATCH_DEFAULT_TMPFS_BYTES = 64 * 1024**2
_BATCH_MIN_TMPFS_BYTES = 16 * 1024**2
_BATCH_MAX_TMPFS_BYTES = 1024**3
_BATCH_MAX_TIMEOUT_SECONDS = 24 * 3600
_BATCH_PREP_MAX_TIMEOUT_SECONDS = 300


def _batch_error(reason: str) -> ContainerDriverError:
    """Build a stable batch validation error without echoing owner data."""
    return ContainerDriverError(f"Invalid batch job request: {reason}")


def _valid_batch_absolute_path(value: object) -> bool:
    """Return True for a bounded, absolute, normalized, traversal-free path."""
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or len(value) > _BATCH_MAX_PATH_CHARS
        or "\x00" in value
        or value == "/"
        or posixpath.normpath(value) != value
    ):
        return False
    return all(part not in ("", ".", "..") for part in value.split("/")[1:])


def _validate_batch_name(name: object) -> str:
    if not isinstance(name, str):
        raise _batch_error("name")
    match = _BATCH_JOB_NAME_RE.fullmatch(name)
    if not match:
        raise _batch_error("name")
    job_id = match.group(1)
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError
    except ValueError:
        raise _batch_error("name") from None
    return job_id


def _valid_batch_image_reference(value: str) -> bool:
    """Require an exact digest reference with no tag before the digest."""
    if not _valid_digest_reference(value):
        return False
    parts = value.rsplit("@", 1)[0].split("/")
    for index, part in enumerate(parts):
        if ":" not in part:
            continue
        # A colon is a registry port only in a multi-component first segment.
        if index != 0 or len(parts) == 1:
            return False
        port = part.rsplit(":", 1)[1]
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return False
    return True


def _validate_batch_image(image: object) -> str:
    """Accept only a local image ID or an exact ``repo@sha256:<digest>``."""
    if not isinstance(image, str):
        raise _batch_error("image")
    if _BATCH_IMAGE_ID_RE.fullmatch(image) or _valid_batch_image_reference(image):
        return image
    raise _batch_error("image")


def _validate_batch_argv(argv: object) -> list[str]:
    if not isinstance(argv, list) or not argv or len(argv) > _BATCH_MAX_ARGV_ITEMS:
        raise _batch_error("argv")
    total_bytes = 0
    for arg in argv:
        if not isinstance(arg, str) or "\x00" in arg:
            raise _batch_error("argv")
        try:
            total_bytes += len(arg.encode("utf-8"))
        except UnicodeEncodeError:
            raise _batch_error("argv") from None
        if total_bytes > _BATCH_MAX_ARGV_BYTES:
            raise _batch_error("argv")
    if not argv[0] or argv[0].startswith("-"):
        raise _batch_error("argv")
    return list(argv)


def _validate_batch_mounts(mounts: object) -> list[dict]:
    """Allow exactly one writable /work mount and at most one toolchain mount."""
    if not isinstance(mounts, list) or not 1 <= len(mounts) <= 2:
        raise _batch_error("mounts")
    validated = []
    targets: set[str] = set()
    work_count = 0
    toolchain_count = 0
    for mount in mounts:
        if not isinstance(mount, dict) or set(mount) != _BATCH_MOUNT_KEYS:
            raise _batch_error("mount shape")
        mount_type = mount["Type"]
        source = mount["Source"]
        target = mount["Target"]
        read_only = mount["ReadOnly"]
        if mount_type not in ("volume", "bind") or type(read_only) is not bool:
            raise _batch_error("mount type")
        if not _valid_batch_absolute_path(target) or target in targets:
            raise _batch_error("mount target")
        if not isinstance(source, str) or "\x00" in source:
            raise _batch_error("mount source")
        if mount_type == "volume":
            if len(source) > _BATCH_MAX_VOLUME_NAME_CHARS or not _BATCH_VOLUME_NAME_RE.fullmatch(
                source
            ):
                raise _batch_error("mount source")
        elif not _valid_batch_absolute_path(source):
            raise _batch_error("mount source")

        if target == "/work":
            if read_only is not False:
                raise _batch_error("work mount")
            work_count += 1
        else:
            if read_only is not True:
                raise _batch_error("toolchain mount")
            if _batch_target_is_forbidden(target):
                raise _batch_error("toolchain target")
            toolchain_count += 1

        targets.add(target)
        validated.append(
            {
                "Type": mount_type,
                "Source": source,
                "Target": target,
                "ReadOnly": read_only,
            }
        )

    if work_count != 1 or toolchain_count > 1:
        raise _batch_error("mounts")
    return validated


def _batch_target_is_forbidden(target: str) -> bool:
    if target == "/work" or target.startswith("/work/"):
        return True
    if target in _BATCH_FIXED_TMPFS_TARGETS:
        return True
    return any(
        target == root or target.startswith(root + "/")
        for root in _BATCH_FORBIDDEN_TOOLCHAIN_TARGETS
    )


def _validate_bounded_labels(labels: object) -> dict[str, str]:
    if not isinstance(labels, dict) or len(labels) > _BATCH_MAX_LABELS:
        raise _batch_error("labels")
    validated: dict[str, str] = {}
    for key, value in labels.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or len(key) > _BATCH_MAX_LABEL_KEY_CHARS
            or not _BATCH_LABEL_KEY_RE.fullmatch(key)
            or len(value) > _BATCH_MAX_LABEL_VALUE_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise _batch_error("labels")
        validated[key] = value
    return validated


def _validate_batch_labels(labels: object, job_id: str) -> dict[str, str]:
    validated = _validate_bounded_labels(labels)
    if validated.get("nukelab.workload") != "job":
        raise _batch_error("labels")
    if validated.get("nukelab.job.id") != job_id:
        raise _batch_error("labels")
    fence = validated.get("nukelab.job.fence")
    try:
        uuid.UUID(fence)
    except (TypeError, ValueError):
        raise _batch_error("labels") from None
    return validated


def _validate_batch_prep_name(name: object) -> str:
    if not isinstance(name, str):
        raise _batch_error("name")
    match = _BATCH_PREP_NAME_RE.fullmatch(name)
    if not match:
        raise _batch_error("name")
    job_id = match.group(1)
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError
    except ValueError:
        raise _batch_error("name") from None
    return job_id


def _validate_batch_prep_labels(labels: object, job_id: str) -> dict[str, str]:
    validated = _validate_bounded_labels(labels)
    if validated.get("nukelab.managed", "true") != "true":
        raise _batch_error("labels")
    if validated.get("nukelab.batch.prep", job_id) != job_id:
        raise _batch_error("labels")
    validated["nukelab.managed"] = "true"
    validated["nukelab.batch.prep"] = job_id
    if len(validated) > _BATCH_MAX_LABELS:
        raise _batch_error("labels")
    return validated


def _validate_batch_volume(volume: object) -> str:
    if (
        not isinstance(volume, str)
        or len(volume) > _BATCH_MAX_VOLUME_NAME_CHARS
        or not _BATCH_VOLUME_NAME_RE.fullmatch(volume)
    ):
        raise _batch_error("volume")
    return volume


def _validate_batch_prep_timeout(timeout_seconds: object) -> int:
    if (
        type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= _BATCH_PREP_MAX_TIMEOUT_SECONDS
    ):
        raise _batch_error("timeout")
    return timeout_seconds


def _validate_batch_limits(limits: object) -> dict:
    allowed = {"cpu", "memory_bytes", "pids_limit", "tmpfs_bytes"}
    if (
        not isinstance(limits, dict)
        or not {"cpu", "memory_bytes", "pids_limit"} <= set(limits)
        or set(limits) - allowed
    ):
        raise _batch_error("limits")
    cpu = limits["cpu"]
    memory_bytes = limits["memory_bytes"]
    pids_limit = limits["pids_limit"]
    tmpfs_bytes = limits.get("tmpfs_bytes", _BATCH_DEFAULT_TMPFS_BYTES)
    if isinstance(cpu, bool) or not isinstance(cpu, (int, float)) or not 0.1 <= cpu <= 1024:
        raise _batch_error("limits")
    if type(memory_bytes) is not int or not (
        _BATCH_MIN_MEMORY_BYTES <= memory_bytes <= _BATCH_MAX_MEMORY_BYTES
    ):
        raise _batch_error("limits")
    if type(pids_limit) is not int or not _BATCH_MIN_PIDS <= pids_limit <= _BATCH_MAX_PIDS:
        raise _batch_error("limits")
    if type(tmpfs_bytes) is not int or not (
        _BATCH_MIN_TMPFS_BYTES <= tmpfs_bytes <= _BATCH_MAX_TMPFS_BYTES
    ):
        raise _batch_error("limits")
    return {
        "cpu": float(cpu),
        "memory_bytes": memory_bytes,
        "pids_limit": pids_limit,
        "tmpfs_bytes": tmpfs_bytes,
    }


def _validate_batch_env(env: object) -> dict[str, str]:
    if not isinstance(env, dict) or len(env) > _BATCH_MAX_ENV_ENTRIES:
        raise _batch_error("environment")
    validated: dict[str, str] = {}
    total_bytes = 0
    for key, value in env.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or len(key) > _BATCH_MAX_ENV_KEY_CHARS
            or not _BATCH_ENV_KEY_RE.fullmatch(key)
            or len(value) > _BATCH_MAX_ENV_VALUE_CHARS
            or "\x00" in value
        ):
            raise _batch_error("environment")
        if key in _BATCH_FIXED_ENV:
            raise _batch_error("environment")
        try:
            total_bytes += len(key.encode("utf-8")) + len(value.encode("utf-8"))
        except UnicodeEncodeError:
            raise _batch_error("environment") from None
        if total_bytes > _BATCH_MAX_ENV_BYTES:
            raise _batch_error("environment")
        validated[key] = value
    return validated


def _validate_batch_timeout(timeout_seconds: object) -> int | None:
    if timeout_seconds is None:
        return None
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= _BATCH_MAX_TIMEOUT_SECONDS:
        raise _batch_error("timeout")
    return timeout_seconds


class DockerDriver(ContainerDriver):
    # Toolchain volume composition.
    TOOLCHAIN_TARGET = "/toolchain-target"
    TOOLCHAIN_MANIFEST_FILE = "nukelab-toolchain.json"
    TOOLCHAIN_STAMP_FILE = ".nukelab-toolchain-stamp.json"
    TOOLCHAIN_LOCK_TIMEOUT = 15 * 60  # seconds; also the stale-lock age
    TOOLCHAIN_LOCK_POLL_INTERVAL = 2.0  # seconds

    def __init__(self):
        self.client: aiodocker.Docker | None = None
        self._available_cgroup_controllers: set[str] | None = None
        self._storage_support: bool | None = None
        self._lxcfs_support: bool | None = None
        self._is_podman: bool | None = None

    async def connect(self):
        """Connect to Docker/Podman socket"""
        self.client = aiodocker.Docker(url=f"unix://{settings.docker_socket}")

    async def close(self):
        """Close connection"""
        if self.client:
            await self.client.close()

    async def pull_image(self, image: str):
        """Pull Docker image"""
        try:
            await self.client.images.pull(image)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def pull_image_by_digest(self, reference: str) -> None:
        """Pull exactly an immutable ``repo@sha256:<digest>`` reference.

        The reference is validated before it reaches the runtime. Tags, URLs,
        credentials, control characters, and malformed or overlong values are
        rejected so a verified launch can never substitute a mutable tag.
        """
        if not _valid_digest_reference(reference):
            raise ImageResolutionError("invalid_digest_reference")
        try:
            await self.client.images.pull(reference)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def resolve_image(self, image: str) -> dict:
        """Resolve local metadata only; RepoDigests are unverified descriptors."""
        if (
            not isinstance(image, str)
            or len(image) > 500
            or "://" in image
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*(?:@sha256:[a-f0-9]{64})?", image)
        ):
            raise ImageResolutionError("invalid_image_reference")
        try:
            info = await self.client.images.get(image)
        except Exception as exc:
            status = getattr(exc, "status", None)
            raise ImageResolutionError(
                "artifact_missing" if status == 404 else "artifact_unavailable", status=status
            ) from None
        if not isinstance(info, dict):
            raise ImageResolutionError("image_identity_invalid")
        image_id = info.get("Id", "")
        if isinstance(image_id, str) and re.fullmatch(r"[a-f0-9]{64}", image_id):
            image_id = "sha256:" + image_id
        digests = info.get("RepoDigests") or []
        if (
            not isinstance(image_id, str)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)
            or not isinstance(digests, list)
            or len(digests) > 32
            or any(
                not isinstance(value, str)
                or len(value) > 500
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}", value)
                or "://" in value
                for value in digests
            )
            or any(
                not isinstance(info.get(key), str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", info[key])
                for key in ("Os", "Architecture")
            )
            or (image.startswith("sha256:") and image != image_id)
        ):
            raise ImageResolutionError("image_identity_invalid")
        return {
            "requested_reference": image,
            "local_id": image_id,
            "repository_digests": list(digests),
            "os": info["Os"],
            "architecture": info["Architecture"],
            "registry_verified": False,
        }

    async def is_podman(self) -> bool:
        """Whether the connected runtime is Podman."""
        return await self._detect_podman()

    async def _detect_podman(self) -> bool:
        """Detect whether the container runtime is Podman (cached).

        Podman's Docker-compatible /version endpoint reports a "Podman Engine"
        component, while Docker does not. Defaults to False (Docker) when the
        version call fails.
        """
        if self._is_podman is not None:
            return self._is_podman

        try:
            info = await self.client.version()
            self._is_podman = "podman" in str(info).lower()
        except Exception as e:
            logger.warning(f"Could not detect container engine type: {e}. Assuming Docker.")
            self._is_podman = False

        return self._is_podman

    async def _get_available_controllers(self) -> set[str]:
        """Detect available cgroup v2 controllers from the host"""
        if self._available_cgroup_controllers is not None:
            return self._available_cgroup_controllers

        controllers = set()
        try:
            # Root cgroup controllers
            cgroup_path = "/sys/fs/cgroup/cgroup.controllers"
            if os.path.exists(cgroup_path):
                with open(cgroup_path) as f:
                    controllers.update(f.read().strip().split())

            # Current user's subtree controllers
            subtree_path = "/sys/fs/cgroup/cgroup.subtree_control"
            if os.path.exists(subtree_path):
                with open(subtree_path) as f:
                    controllers.update(f.read().strip().split())
        except Exception as e:
            logger.warning(f"Could not detect cgroup controllers: {e}")

        self._available_cgroup_controllers = controllers
        return controllers

    async def _check_lxcfs_support(self) -> bool:
        """Check if lxcfs is available on the host for cgroup-aware /proc"""
        if self._lxcfs_support is not None:
            return self._lxcfs_support

        lxcfs_procs = [
            "/var/lib/lxcfs/proc/meminfo",
            "/var/lib/lxcfs/proc/cpuinfo",
            "/var/lib/lxcfs/proc/uptime",
        ]

        # Check if lxcfs proc files exist on the host
        for proc_file in lxcfs_procs:
            if not os.path.exists(proc_file):
                logger.info(
                    f"lxcfs not available ({proc_file} missing). "
                    f"Install and start lxcfs on the host for cgroup-aware /proc inside containers:\n"
                    f"  Ubuntu/Debian: sudo apt install lxcfs && sudo systemctl enable --now lxcfs\n"
                    f"  RHEL/CentOS:   sudo dnf install lxcfs && sudo systemctl enable --now lxcfs\n"
                    f"  Arch:          sudo pacman -S lxcfs && sudo systemctl enable --now lxcfs"
                )
                self._lxcfs_support = False
                return False

        logger.info("lxcfs detected. Cgroup-aware /proc will be mounted into containers.")
        self._lxcfs_support = True
        return True

    def _get_lxcfs_mounts(self) -> list:
        """Get lxcfs bind mounts for cgroup-aware /proc files"""
        if not self._lxcfs_support:
            return []

        mounts = []
        lxcfs_base = "/var/lib/lxcfs"
        proc_files = ["meminfo", "cpuinfo", "diskstats", "loadavg", "stat", "swaps", "uptime"]

        for proc_file in proc_files:
            host_path = f"{lxcfs_base}/proc/{proc_file}"
            if os.path.exists(host_path):
                mounts.append(f"{host_path}:/proc/{proc_file}:rw")

        return mounts

    def _get_cpu_env(self, cpu_limit: float | None) -> dict:
        """
        Return environment variables that tell common libraries how many
        threads/cores to use, and set LD_PRELOAD to intercept sysconf()
        and /proc/stat so programs see the plan's CPU count and the
        container's own CPU usage instead of host-wide values.
        """
        if not cpu_limit or cpu_limit < 1:
            cpu_limit = os.cpu_count() or 1
        n = int(cpu_limit)
        return {
            "OMP_NUM_THREADS": str(n),
            "MKL_NUM_THREADS": str(n),
            "OPENBLAS_NUM_THREADS": str(n),
            "VECLIB_MAXIMUM_THREADS": str(n),
            "NUMEXPR_NUM_THREADS": str(n),
            "NUKELAB_CPU_COUNT": str(n),
            "LD_PRELOAD": "/usr/local/lib/nukelab/libnukelab_cpu.so",
        }

    async def _inject_cpu_files(self, container, cpu_limit: float | None) -> None:
        """Inject system-wide CPU masking files into the container.

        Writes:
          - /etc/ld.so.preload   (root-only, survives any env clearing)
          - /etc/profile.d/nukelab-cpu.sh  (login shells get env vars)
        """
        if not cpu_limit or cpu_limit < 1:
            cpu_limit = os.cpu_count() or 1
        n = int(cpu_limit)

        # /etc/ld.so.preload — system-wide library preload, root-only
        preload_path = "/usr/local/lib/nukelab/libnukelab_cpu.so"
        ld_preload = f"{preload_path}\n"

        # /etc/profile.d/nukelab-cpu.sh — env vars for login shells
        # Preserve an existing LD_PRELOAD (e.g. libnss_wrapper.so) by appending
        # the CPU mask library instead of replacing it.
        profile_script = (
            f'export LD_PRELOAD="${{LD_PRELOAD:+${{LD_PRELOAD}}:}}{preload_path}"\n'
            f"export NUKELAB_CPU_COUNT={n}\n"
            f"export OMP_NUM_THREADS={n}\n"
            f"export MKL_NUM_THREADS={n}\n"
            f"export OPENBLAS_NUM_THREADS={n}\n"
            f"export VECLIB_MAXIMUM_THREADS={n}\n"
            f"export NUMEXPR_NUM_THREADS={n}\n"
        )

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            # /etc/ld.so.preload
            data = ld_preload.encode("utf-8")
            info = tarfile.TarInfo(name="ld.so.preload")
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))

            # /etc/profile.d/nukelab-cpu.sh
            data = profile_script.encode("utf-8")
            info = tarfile.TarInfo(name="profile.d/nukelab-cpu.sh")
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))

        tar_buffer.seek(0)

        try:
            await container.put_archive("/etc", tar_buffer.read())
        except Exception as e:
            logger.warning(f"Failed to inject CPU system files: {e}")

    async def _check_storage_support(self) -> bool:
        """Check if storage limits are supported (requires XFS with pquota, ZFS, etc.)"""
        if self._storage_support is not None:
            return self._storage_support

        try:
            # Ensure busybox is available for the test
            try:
                await self.client.images.get("busybox:latest")
            except Exception:
                try:
                    await self.client.images.pull("busybox:latest")
                except Exception as pull_err:
                    logger.warning(
                        f"Could not pull busybox for storage test: {pull_err}. "
                        f"Storage limits will be disabled."
                    )
                    self._storage_support = False
                    return False

            test_container = await self.client.containers.create(
                {"Image": "busybox:latest", "HostConfig": {"StorageOpt": {"size": "10m"}}},
                name=f"test-storage-{uuid.uuid4().hex[:8]}",
            )
            await test_container.delete(force=True)
            logger.info("Storage limits are supported by the current driver.")
            self._storage_support = True
            return True
        except Exception as e:
            logger.warning(
                f"Storage limits not supported: {e}. "
                f"Common in rootless dev environments (overlayfs). "
                f"Expected in production with XFS(pquota)/ZFS/Btrfs. "
                f"Disk limits will not be enforced."
            )
            self._storage_support = False
            return False

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
        """Create a new container with graceful cgroup fallback.

        Returns the new container's id.
        """
        env_vars = dict(env or {})
        cpu_env = self._get_cpu_env(cpu_limit)
        # Combine LD_PRELOAD so both nss-wrapper and the CPU-mask library load.
        if "LD_PRELOAD" in env_vars and "LD_PRELOAD" in cpu_env:
            env_vars["LD_PRELOAD"] = f"{env_vars['LD_PRELOAD']}:{cpu_env['LD_PRELOAD']}"
            del cpu_env["LD_PRELOAD"]

        config = {
            "Image": image,
            "Cmd": command.split() if command else None,
            "Labels": labels or {},
            "Env": [f"{k}={v}" for k, v in env_vars.items()]
            + [f"{k}={v}" for k, v in cpu_env.items()],
            "HostConfig": {
                "NetworkMode": network or settings.docker_network,
                "PublishAllPorts": False,
            },
        }

        # Add a short network alias so the backend health probe can use a
        # DNS-safe hostname instead of the potentially very long container name.
        # Container names can exceed the 63-byte DNS label limit, causing
        # getaddrinfo to fail with "label too long".
        net_name = network or settings.docker_network
        if network_aliases:
            config["NetworkingConfig"] = {
                "EndpointsConfig": {
                    net_name: {
                        "Aliases": list(network_aliases),
                    }
                }
            }

        if hostname:
            config["Hostname"] = hostname

        if ports:
            config["ExposedPorts"] = {f"{k}/tcp": {} for k in ports}
            config["HostConfig"]["PortBindings"] = {
                f"{k}/tcp": [{"HostPort": str(v)}] for k, v in ports.items()
            }

        if volumes:
            binds = []
            for host, container in volumes.items():
                if isinstance(container, dict):
                    # New format: {host: {"bind": path, "mode": "rw"}}
                    bind_str = f"{host}:{container['bind']}"
                    if "mode" in container:
                        bind_str += f":{container['mode']}"
                    binds.append(bind_str)
                else:
                    # Old format: {host: container_path}
                    binds.append(f"{host}:{container}")
            config["HostConfig"]["Binds"] = binds

        # --- lxcfs for cgroup-aware /proc (free, top, htop) ---
        await self._check_lxcfs_support()
        lxcfs_mounts = self._get_lxcfs_mounts()
        if lxcfs_mounts:
            if "Binds" not in config["HostConfig"]:
                config["HostConfig"]["Binds"] = []
            config["HostConfig"]["Binds"].extend(lxcfs_mounts)
            logger.info(f"Mounted lxcfs /proc files: {len(lxcfs_mounts)} files")

        # --- CPU limits with graceful fallback ---
        if cpu_limit:
            controllers = await self._get_available_controllers()
            has_cpu = "cpu" in controllers
            has_cpuset = "cpuset" in controllers

            if has_cpu:
                config["HostConfig"]["NanoCpus"] = int(cpu_limit * 1e9)
                logger.info(f"Applied CPU limit: {cpu_limit} cores (NanoCpus)")
            else:
                logger.warning(
                    f"CPU limit requested ({cpu_limit} cores) but 'cpu' cgroup controller "
                    f"is not available. Available: {sorted(controllers)}. "
                    f"CPU throttling will not be enforced. "
                    f"To enable on systemd systems: "
                    f"sudo mkdir -p /etc/systemd/system/user@.service.d/ && "
                    f"echo '[Service]\\nDelegate=cpu cpuset io memory pids' | sudo tee "
                    f"/etc/systemd/system/user@.service.d/delegate.conf && "
                    f"sudo systemctl daemon-reload"
                )

            if has_cpuset:
                # Cap affinity to available host cores to avoid failure
                # when plan requests more cores than the host has
                available_cores = os.cpu_count() or int(cpu_limit)
                pinned_cores = min(int(cpu_limit), available_cores)
                cpus = ",".join(str(i) for i in range(pinned_cores))
                config["HostConfig"]["CpusetCpus"] = cpus
                logger.info(
                    f"Applied CPU affinity: cores {cpus} (requested {cpu_limit}, host has {available_cores})"
                )
            else:
                logger.warning(
                    f"CPU affinity requested but 'cpuset' cgroup controller "
                    f"is not available. Available: {sorted(controllers)}. "
                    f"CPU pinning will not be enforced."
                )

        # --- Memory limits ---
        if memory_limit:
            controllers = await self._get_available_controllers()
            if "memory" in controllers:
                memory_bytes = self._parse_memory(memory_limit)
                config["HostConfig"]["Memory"] = memory_bytes
                config["HostConfig"]["MemorySwap"] = memory_bytes
                logger.info(f"Applied memory limit: {memory_limit} ({memory_bytes} bytes)")
            else:
                logger.warning(
                    f"Memory limit requested ({memory_limit}) but 'memory' cgroup controller "
                    f"is not available. Available: {sorted(controllers)}. "
                    f"Memory limits will not be enforced."
                )

        # --- Disk limits with graceful fallback ---
        if disk_limit:
            supports = await self._check_storage_support()
            if supports:
                try:
                    disk_bytes = self._parse_memory(disk_limit)
                    config["HostConfig"]["StorageOpt"] = {"size": f"{disk_bytes}b"}
                    logger.info(f"Applied disk limit: {disk_limit} ({disk_bytes} bytes)")
                except Exception as e:
                    logger.warning(f"Failed to parse/apply disk limit: {e}")
            else:
                logger.warning(
                    f"Disk limit requested ({disk_limit}) but storage quotas are not supported "
                    f"by the current storage driver or configuration. "
                    f"Expected in production with XFS(pquota), ZFS, or Btrfs. "
                    f"Disk limits will not be enforced."
                )

        # --- GPU (NVIDIA) device requests ---
        if gpu_limit > 0:
            if not settings.gpu_enabled:
                raise ValueError("GPU requested but GPU support is disabled (GPU_ENABLED=false)")
            if await self._detect_podman():
                # Podman uses CDI (Container Device Interface) for GPU injection.
                device_ids = gpu_devices or [settings.gpu_cdi_device]
                config["HostConfig"]["DeviceRequests"] = [
                    {
                        "Driver": "cdi",
                        "DeviceIDs": device_ids,
                        "Capabilities": [["gpu"]],
                    }
                ]
                logger.info(f"Applied GPU request via CDI device(s): {device_ids}")
            else:
                # Docker uses the nvidia container runtime driver. It takes
                # plain GPU indices/UUIDs, not CDI names: "nvidia.com/gpu=0"
                # becomes "0" (the part after "=").
                device_request = {
                    "Driver": "nvidia",
                    "Capabilities": [["gpu", "compute", "utility"]],
                }
                if gpu_devices:
                    device_request["DeviceIDs"] = [d.split("=", 1)[-1] for d in gpu_devices]
                else:
                    device_request["Count"] = gpu_limit
                config["HostConfig"]["DeviceRequests"] = [device_request]
                logger.info(
                    f"Applied GPU request: {device_request.get('DeviceIDs') or gpu_limit} NVIDIA GPU(s)"
                )

        # --- Container runtime hardening ---
        if settings.container_hardening_enabled:
            host_config = config["HostConfig"]
            # Set both HostConfig.User (for internal verification/tests) and
            # top-level Config.User (the Docker/Podman API field that actually
            # controls the container process user).
            host_config["User"] = f"{settings.container_uid}:{settings.container_gid}"
            config["User"] = f"{settings.container_uid}:{settings.container_gid}"
            if settings.container_drop_all_capabilities:
                host_config["CapDrop"] = ["ALL"]
            if settings.container_no_new_privileges:
                host_config["SecurityOpt"] = ["no-new-privileges:true"]
            if settings.container_readonly_rootfs:
                host_config["ReadonlyRootfs"] = True
                tmpfs_paths = settings.container_readonly_tmpfs_paths or []
                if tmpfs_paths:
                    host_config["Tmpfs"] = dict.fromkeys(tmpfs_paths, "mode=1777,size=100m")
            logger.info(
                "Applied container hardening: user=%s, cap_drop=%s, "
                "no_new_privileges=%s, readonly_rootfs=%s",
                host_config.get("User"),
                settings.container_drop_all_capabilities,
                settings.container_no_new_privileges,
                settings.container_readonly_rootfs,
            )

        # --- Container healthcheck (runtime-level, not image-level) ---
        # OCI image format drops Dockerfile HEALTHCHECK and Kubernetes ignores
        # it anyway, so the probe is defined here: a future k8s driver can
        # translate this same definition into pod liveness/startup probes.
        # The script exists in every environment image (environments/base) and
        # probes nginx, the auth sidecar, and $NUKELAB_HEALTH_PROBE_URLS.
        config["Healthcheck"] = {
            "Test": ["CMD", "/usr/local/bin/nukelab-healthcheck.sh"],
            "Interval": 30 * 10**9,
            "Timeout": 10 * 10**9,
            "StartPeriod": 90 * 10**9,
            "Retries": 3,
        }

        try:
            container = await self.client.containers.create(config, name=name)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e
        await self._inject_cpu_files(container, cpu_limit)
        return container.id

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

        Validation is fail-closed and happens before any runtime call. The
        caller has already proved local image identity; this method never
        pulls or substitutes an artifact, and it never starts the container.
        """
        job_id = _validate_batch_name(name)
        image = _validate_batch_image(image)
        argv = _validate_batch_argv(argv)
        mounts = _validate_batch_mounts(mounts)
        labels = _validate_batch_labels(labels, job_id)
        limits = _validate_batch_limits(limits)
        env = _validate_batch_env(env)
        if workdir != "/work":
            raise _batch_error("workdir")
        timeout_seconds = _validate_batch_timeout(timeout_seconds)

        if timeout_seconds is None:
            entrypoint = [argv[0]]
            command = argv[1:]
        else:
            entrypoint = ["/usr/bin/timeout"]
            command = [
                "--signal=TERM",
                "--kill-after=10",
                str(timeout_seconds),
                *argv,
            ]

        docker_mounts = [
            {
                "Type": mount["Type"],
                "Source": mount["Source"],
                "Target": mount["Target"],
                "ReadOnly": mount["ReadOnly"],
                **({"VolumeOptions": {"NoCopy": True}} if mount["Type"] == "volume" else {}),
            }
            for mount in mounts
        ]
        memory_bytes = limits["memory_bytes"]
        tmpfs_bytes = limits["tmpfs_bytes"]

        # The batch profile fixes the approved non-root identity. A customized
        # interactive setting can never weaken it to root or another user.
        user = _BATCH_JOB_USER

        config = {
            "Image": image,
            "Entrypoint": entrypoint,
            "Cmd": command,
            "User": user,
            "WorkingDir": workdir,
            "Env": [
                *(f"{key}={value}" for key, value in _BATCH_FIXED_ENV.items()),
                *(f"{key}={value}" for key, value in env.items()),
            ],
            "Labels": labels,
            "Healthcheck": {"Test": ["NONE"]},
            "HostConfig": {
                "Mounts": docker_mounts,
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "NetworkMode": "none",
                "PublishAllPorts": False,
                "Memory": memory_bytes,
                "MemorySwap": memory_bytes,
                "NanoCpus": int(limits["cpu"] * 1_000_000_000),
                "PidsLimit": limits["pids_limit"],
                "Tmpfs": {
                    "/tmp": (f"rw,nosuid,nodev,noexec,size={tmpfs_bytes},mode=1777"),
                    "/home": "rw,nosuid,nodev,noexec,size=16777216,mode=1777",
                },
                "RestartPolicy": {"Name": "no"},
                "AutoRemove": False,
                "LogConfig": {
                    "Type": "json-file",
                    "Config": {"max-size": "1m", "max-file": "1"},
                },
            },
        }
        try:
            container = await self.client.containers.create(config, name=name)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e
        return container.id

    async def prepare_batch_volume(
        self,
        *,
        name: str,
        image: str,
        volume: str,
        labels: dict[str, str],
        timeout_seconds: int = 30,
    ) -> None:
        """Fix job volume ownership with a bounded root helper, then remove it.

        The helper is the only trusted root process in the batch profile. It
        runs a fixed chmod against the single job volume with no network, no
        capabilities and no user-controlled arguments. Any uncertainty after
        creation is reported distinctly so the runtime can require recovery
        instead of starting the job.
        """
        job_id = _validate_batch_prep_name(name)
        image = _validate_batch_image(image)
        volume = _validate_batch_volume(volume)
        labels = _validate_batch_prep_labels(labels, job_id)
        timeout_seconds = _validate_batch_prep_timeout(timeout_seconds)

        config = {
            "Image": image,
            "Entrypoint": ["/bin/chmod"],
            "Cmd": ["0777", "/work"],
            "User": "0:0",
            "WorkingDir": "/",
            "Labels": labels,
            "Healthcheck": {"Test": ["NONE"]},
            "HostConfig": {
                "Mounts": [
                    {
                        "Type": "volume",
                        "Source": volume,
                        "Target": "/work",
                        "ReadOnly": False,
                        "VolumeOptions": {"NoCopy": True},
                    }
                ],
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "NetworkMode": "none",
                "Memory": 64 * 1024**2,
                "NanoCpus": 100_000_000,
                "PidsLimit": 16,
                "RestartPolicy": {"Name": "no"},
                "AutoRemove": False,
                "LogConfig": {
                    "Type": "json-file",
                    "Config": {"max-size": "1m", "max-file": "1"},
                },
            },
        }
        try:
            helper = await self.client.containers.create(config, name=name)
        except aiodocker.DockerError as error:
            raise _map_error(error) from error

        try:
            try:
                await helper.start()
                result = await asyncio.wait_for(helper.wait(), timeout=timeout_seconds)
                exit_code = result.get("StatusCode") if isinstance(result, dict) else None
                if type(exit_code) is not int or exit_code != 0:
                    raise ContainerDriverError("batch_volume_prepare_failed")
            except ContainerDriverError:
                raise
            except Exception as error:
                raise ContainerDriverError("batch_volume_prepare_failed") from error
        finally:
            try:
                await helper.delete(force=True)
            except aiodocker.DockerError as error:
                if getattr(error, "status", None) != 404:
                    raise ContainerDriverError("batch_volume_prepare_unknown") from error
            except Exception as error:
                raise ContainerDriverError("batch_volume_prepare_unknown") from error

    async def start_container(self, container_id: str):
        """Start a container"""
        try:
            container = await self.client.containers.get(container_id)
            await container.start()
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def wait_for_container_ready(
        self,
        container_name: str,
        health_url: str,
        timeout: int | None = None,
        interval: float | None = None,
        body_contains: str | None = None,
    ) -> bool:
        """Wait until the container responds successfully on health_url.

        The probe is issued from the backend container over the shared container
        network (e.g. http://<container_name>:8080/health), so it verifies both
        that the server process is up and that it is reachable on the internal
        network before Traefik has picked up the route.
        """
        timeout = timeout if timeout is not None else settings.container_readiness_timeout
        interval = interval if interval is not None else settings.container_readiness_interval
        deadline = asyncio.get_event_loop().time() + timeout

        logger.info(
            "Waiting up to %ss for container %s to become ready at %s",
            timeout,
            container_name,
            health_url,
        )

        while asyncio.get_event_loop().time() < deadline:
            try:
                timeout_obj = aiohttp.ClientTimeout(total=2)
                async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                    async with session.get(health_url) as resp:
                        if resp.status == 200:
                            if body_contains:
                                text = await resp.text()
                                if body_contains not in text:
                                    logger.debug(
                                        "Container %s returned 200 but body did not contain %r",
                                        container_name,
                                        body_contains,
                                    )
                                    await asyncio.sleep(interval)
                                    continue
                            logger.info("Container %s is ready", container_name)
                            return True
            except Exception as e:
                logger.debug("Container %s not ready yet: %s", container_name, e)
            await asyncio.sleep(interval)

        logger.warning("Container %s did not become ready within %ss", container_name, timeout)
        return False

    async def stop_container(self, container_id: str, timeout: int = 30):
        """Stop a container. Raises ContainerDriverError on failure."""
        try:
            container = await self.client.containers.get(container_id)
            await container.stop(timeout=timeout)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def delete_container(self, container_id: str, force: bool = True):
        """Delete a container. Raises ContainerDriverError on failure."""
        try:
            container = await self.client.containers.get(container_id)
            await container.delete(force=force)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def get_container_info(self, container_id: str) -> dict:
        """Get container info"""
        try:
            container = await self.client.containers.get(container_id)
            return await container.show()
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def get_container_status(self, container_id: str) -> str:
        """Return "running", "paused", or "stopped" for a container."""
        info = await self.get_container_info(container_id)
        state = info.get("State", {})
        if state.get("Running"):
            return "running"
        elif state.get("Paused"):
            return "paused"
        else:
            return "stopped"

    async def get_container_by_name(self, name: str) -> str | None:
        """Return the id of the container with this name, or None."""
        try:
            container = await self.client.containers.get(name)
            return container.id
        except Exception:
            return None

    async def version(self):
        """Get container runtime version info"""
        try:
            return await self.client.version()
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def list_containers(
        self, filters: dict | None = None, *, all: bool = False
    ) -> list[dict]:
        """List containers as inspect-shaped dicts."""
        try:
            containers = (
                await self.client.containers.list(filters=filters, all=True)
                if all
                else await self.client.containers.list(filters=filters)
            )
            return [await container.show() for container in containers]
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def create_recovery_helper(self, *, name, image, command, mounts, labels, limits):
        import uuid
        from pathlib import PurePosixPath

        try:
            operation_id = str(uuid.UUID(labels["nukelab.recovery.operation"]))
            uuid.UUID(labels["nukelab.recovery.fence"])
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ContainerDriverError("Invalid recovery identity") from None
        if name != "nukelab-recovery-" + operation_id or not re.fullmatch(
            r"sha256:[a-f0-9]{64}", image
        ):
            raise ContainerDriverError("Invalid recovery identity")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(arg, str) or "\x00" in arg for arg in command)
        ):
            raise ContainerDriverError("Invalid recovery command")
        allowed = {"/source": True, "/archive": True, "/target": False, "/artifact": False}
        targets = set()
        for mount in mounts:
            if (
                set(mount) != {"Type", "Source", "Target", "ReadOnly"}
                or mount["Target"] not in allowed
                or mount["ReadOnly"] is not allowed[mount["Target"]]
                or mount["Target"] in targets
            ):
                raise ContainerDriverError("Invalid recovery mount")
            targets.add(mount["Target"])
            source = mount["Source"]
            if mount["Type"] == "volume":
                if not isinstance(source, str) or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.-]*", source
                ):
                    raise ContainerDriverError("Invalid recovery mount")
            elif mount["Type"] == "bind":
                if (
                    mount["Target"] not in ("/archive", "/artifact")
                    or not isinstance(source, str)
                    or not source.startswith("/")
                    or ".." in PurePosixPath(source).parts
                    or "\x00" in source
                ):
                    raise ContainerDriverError("Invalid recovery mount")
            else:
                raise ContainerDriverError("Invalid recovery mount")
        if "/artifact" not in targets or ("/source" in targets) == ("/target" in targets):
            raise ContainerDriverError("Invalid recovery mounts")
        memory = limits.get("memory_bytes", 1024**3)
        if type(memory) is not int or not 64 * 1024**2 <= memory <= 4 * 1024**3:
            raise ContainerDriverError("Invalid recovery limits")
        mounts = [
            {
                **mount,
                **(
                    {"VolumeOptions": {"NoCopy": mount["Target"] == "/source"}}
                    if mount["Type"] == "volume"
                    else {}
                ),
            }
            for mount in mounts
        ]
        config = {
            "Image": image,
            "Cmd": command,
            "User": "65532:65532",
            "Labels": labels,
            "Env": ["PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1"],
            "Healthcheck": {"Test": ["NONE"]},
            "HostConfig": {
                "Mounts": mounts,
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "NetworkMode": "none",
                "Memory": memory,
                "NanoCpus": 1000000000,
                "PidsLimit": 64,
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=67108864,mode=1777"},
                "RestartPolicy": {"Name": "no"},
            },
        }
        try:
            helper = await self.client.containers.create(config=config, name=name)
            return helper.id
        except aiodocker.DockerError as error:
            raise _map_error(error) from error

    async def wait_recovery_helper(self, container_id, timeout):
        import asyncio

        try:
            helper = await self.client.containers.get(container_id)
            result = await asyncio.wait_for(helper.wait(), timeout=timeout)
            code = result.get("StatusCode")
            if type(code) is not int:
                raise ContainerDriverError("Unknown recovery helper result")
            return code
        except aiodocker.DockerError as error:
            raise _map_error(error) from error

    async def get_container_stats(self, container_id: str) -> dict:
        """Return one raw Docker-stats-shaped dict for a container."""
        try:
            container = await self.client.containers.get(container_id)
            stats = await container.stats(stream=False)
            return stats[0] if isinstance(stats, list) and stats else stats
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def get_container_top(self, container_id: str, ps_args: str | None = None) -> dict:
        """Return a Docker-top-shaped dict {"Titles": [...], "Processes": [[...]]}.

        aiodocker 0.24 has no top() helper, so query the REST endpoint
        directly (Podman's compat API implements it as well).
        """
        try:
            params = {"ps_args": ps_args} if ps_args else {}
            return await self.client._query_json(
                f"containers/{container_id}/top", method="GET", params=params
            )
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def get_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        since: int | None = None,
        timestamps: bool = True,
        stdout: bool = True,
        stderr: bool = True,
    ) -> str:
        """Get container logs"""
        try:
            container = await self.client.containers.get(container_id)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e
        kwargs = {
            "stdout": stdout,
            "stderr": stderr,
            "tail": tail,
            "timestamps": timestamps,
            "follow": False,
        }
        if since is not None:
            kwargs["since"] = since
        logs = await container.log(**kwargs)
        # aiodocker returns list of lines; join into single string
        if isinstance(logs, list):
            return "".join(logs)
        return logs

    async def stream_container_logs(
        self, container_id: str, tail: int = 100, stdout: bool = True, stderr: bool = True
    ):
        """Stream container logs as an async iterator of lines (str)."""
        try:
            container = await self.client.containers.get(container_id)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e
        logs = await container.log(
            stdout=stdout, stderr=stderr, tail=tail, follow=True, timestamps=True
        )
        return logs

    async def exec_in_container(
        self,
        container_id: str,
        cmd: list[str],
        user: str | None = None,
        detach: bool = False,
    ) -> str:
        """Run a command in a container and return its decoded output."""
        try:
            container = await self.client.containers.get(container_id)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e
        kwargs = {}
        if user:
            kwargs["user"] = user
        exec_instance = await container.exec(cmd, **kwargs)
        if detach:
            # Start the command in the background and return immediately.
            await exec_instance.start(detach=True)
            return ""
        output = b""
        async with exec_instance.start(detach=False) as stream:
            while True:
                message = await stream.read_out()
                if message is None:
                    break
                output += message.data
        return output.decode("utf-8", errors="replace")

    async def put_archive(self, container_id: str, path: str, data: bytes):
        """Write a tar archive of files into a container at path."""
        try:
            container = await self.client.containers.get(container_id)
            await container.put_archive(path, data)
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def ensure_volume(self, name: str, labels: dict | None = None):
        """Create a named volume if it doesn't exist."""
        try:
            await self.client.volumes.get(name)
        except Exception:
            try:
                await self.client.volumes.create(
                    {
                        "Name": name,
                        "Labels": labels or {},
                    }
                )
            except aiodocker.DockerError as e:
                raise _map_error(e) from e
            logger.info("Created volume: %s", name)

    async def create_volume(self, name: str, labels: dict | None = None):
        """Create a named volume, raising ContainerDriverError on failure."""
        try:
            await self.client.volumes.create(
                {
                    "Name": name,
                    "Labels": labels or {},
                }
            )
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    async def get_volume(self, name: str) -> dict | None:
        """Return volume info, or None when it does not exist."""
        try:
            volume = await self.client.volumes.get(name)
            return await volume.show()
        except aiodocker.DockerError as error:
            if error.status == 404:
                return None
            raise _map_error(error) from error
        except Exception as error:
            raise ContainerDriverError("Volume inspection failed") from error

    async def delete_volume(self, name: str):
        """Delete a volume; only verified absence is an idempotent success."""
        try:
            volume = await self.client.volumes.get(name)
            await volume.delete()
        except aiodocker.DockerError as error:
            if error.status != 404:
                raise _map_error(error) from error
        except Exception as error:
            raise ContainerDriverError("Volume deletion failed") from error

    async def _read_toolchain_manifest(
        self, image: str, volume_name: str
    ) -> tuple[dict, dict] | None:
        """Read the toolchain manifest and population stamp from a named volume.

        Runs a single hardened helper container that cats both files so the
        manifest is never served without its stamp. Returns ``(manifest,
        stamp)`` when both parse, or None when either cannot be read (volume
        missing, empty, or files absent/invalid). Errors are swallowed so
        callers can decide whether to fall back to population.
        """
        try:
            manifest_config = {
                "Image": image,
                "Entrypoint": [],
                "Cmd": [
                    "sh",
                    "-c",
                    f"cat /opt/nuke/{self.TOOLCHAIN_MANIFEST_FILE}"
                    " && printf '\\n---\\n'"
                    f" && cat /opt/nuke/{self.TOOLCHAIN_STAMP_FILE}",
                ],
                "HostConfig": {
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Source": volume_name,
                            "Target": "/opt/nuke",
                            "ReadOnly": True,
                        }
                    ],
                    "AutoRemove": False,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "ReadonlyRootfs": True,
                    "NetworkMode": "none",
                },
            }
            manifest_name = f"nukelab-toolchain-manifest-{uuid.uuid4().hex[:8]}"
            manifest_container = await self.client.containers.create(
                manifest_config, name=manifest_name
            )
            try:
                await manifest_container.start()
                wait_result = await manifest_container.wait()
                exit_code = wait_result.get("StatusCode", wait_result)
                if exit_code not in (0, "0"):
                    return None
                logs = await manifest_container.log(stdout=True, stderr=True)
                output = "".join(logs)
                manifest_text, sep, stamp_text = output.partition("\n---\n")
                if not sep:
                    return None
                return json.loads(manifest_text), json.loads(stamp_text)
            finally:
                try:
                    await manifest_container.delete(force=True)
                except Exception:
                    pass
        except Exception:
            return None

    @staticmethod
    def _toolchain_lock_name(volume_name: str) -> str:
        """Derive the lock container name for a toolchain volume."""
        digest = hashlib.sha256(volume_name.encode("utf-8")).hexdigest()[:12]
        return f"nukelab-toolchain-lock-{digest}"

    @staticmethod
    def _parse_docker_timestamp(value: str | None) -> float | None:
        """Parse a Docker RFC3339 timestamp to epoch seconds, or None."""
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.timestamp()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _image_ids_match(a: str | None, b: str | None) -> bool:
        """Compare image IDs across engine formats.

        Docker reports ``sha256:<hex>`` while podman's CLI may report the
        bare hex digest; comparing only the digest portion keeps the stamp
        check valid when the CLI (cache-toolchain) and the backend run on
        different engines.
        """
        if not a or not b:
            return False
        return a.rsplit(":", 1)[-1] == b.rsplit(":", 1)[-1]

    async def _acquire_toolchain_lock(self, image: str, volume_name: str):
        """Acquire the cross-process populate lock for a toolchain volume.

        Docker's atomic container-name creation acts as the semaphore: the
        lock container is created with the toolchain image (guaranteed local
        by then) and never started, so exactly one process holds the lock.
        API workers and Celery tasks both reach this path, so the lock must
        be engine-level, not in-process. Lock containers older than
        TOOLCHAIN_LOCK_TIMEOUT are treated as stale (a crashed populate never
        started the container, so age is the only signal) and force-deleted.
        """
        lock_name = self._toolchain_lock_name(volume_name)
        deadline = time.monotonic() + self.TOOLCHAIN_LOCK_TIMEOUT
        while True:
            try:
                return await self.client.containers.create(
                    {
                        "Image": image,
                        "Cmd": ["true"],
                        "Labels": {
                            "nukelab.managed": "true",
                            "nukelab.toolchain.lock": volume_name,
                        },
                        "HostConfig": {"AutoRemove": False},
                    },
                    name=lock_name,
                )
            except aiodocker.DockerError as e:
                if getattr(e, "status", None) != 409:
                    raise _map_error(e) from e

            # Name conflict: another process holds (or crashed holding) the lock.
            if time.monotonic() > deadline:
                raise ContainerDriverError(
                    f"Timed out waiting for toolchain lock {lock_name} for {volume_name}"
                )
            try:
                holder = await self.client.containers.get(lock_name)
                info = await holder.show()
                created = self._parse_docker_timestamp(info.get("Created"))
                if created is not None and time.time() - created > self.TOOLCHAIN_LOCK_TIMEOUT:
                    logger.warning("Removing stale toolchain lock container %s", lock_name)
                    await holder.delete(force=True)
                    continue
            except Exception:
                # Lock container disappeared or is uninspectable; retry acquire.
                continue
            await asyncio.sleep(self.TOOLCHAIN_LOCK_POLL_INTERVAL)

    async def _populate_toolchain_volume(
        self, image: str, volume_name: str, mount_paths: list[str], image_info: dict
    ):
        """Wipe and (re)populate a toolchain volume, then write the stamp.

        The helper container is hardened (all caps dropped except those
        ``cp -a`` needs to preserve ownership, no-new-privileges, read-only
        rootfs) but keeps the image's default user because ownership
        preservation requires it.
        """
        stamp = json.dumps(
            {
                "image_id": image_info.get("Id"),
                "repo_digests": image_info.get("RepoDigests") or [],
                "populated_at": datetime.now(UTC).isoformat(),
            }
        )
        stamp_path = f"{self.TOOLCHAIN_TARGET}/{self.TOOLCHAIN_STAMP_FILE}"

        # Wipe first so files deleted from a re-pushed image do not linger.
        # Each mount path's CONTENTS go to the volume root: consumers mount
        # the volume at that path (e.g. /opt/nuke) and must see the toolchain
        # tree directly. The contract is a single toolchain root per volume.
        copy_script = f"rm -rf {self.TOOLCHAIN_TARGET}/* {self.TOOLCHAIN_TARGET}/.[!.]*; "
        for path in mount_paths:
            copy_script += f"cp -a {path}/. {self.TOOLCHAIN_TARGET}/; "
        copy_script += f"printf '%s' {shlex.quote(stamp)} > {stamp_path}"

        populate_config = {
            "Image": image,
            "Cmd": ["sh", "-c", copy_script],
            "HostConfig": {
                "Mounts": [
                    {
                        "Type": "volume",
                        "Source": volume_name,
                        "Target": self.TOOLCHAIN_TARGET,
                    }
                ],
                "AutoRemove": False,
                "CapDrop": ["ALL"],
                "CapAdd": ["CHOWN", "FOWNER", "DAC_OVERRIDE", "SETUID", "SETGID"],
                "SecurityOpt": ["no-new-privileges:true"],
                "ReadonlyRootfs": True,
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=64m"},
            },
        }

        populate_name = f"nukelab-toolchain-populate-{uuid.uuid4().hex[:8]}"
        populate_container = None
        try:
            populate_container = await self.client.containers.create(
                populate_config, name=populate_name
            )
            await populate_container.start()
            wait_result = await populate_container.wait()
            exit_code = wait_result.get("StatusCode", wait_result)
            if exit_code not in (0, "0"):
                logs = await populate_container.log(stdout=True, stderr=True)
                raise ContainerDriverError(
                    f"Toolchain population failed for {image} (exit {exit_code}): {''.join(logs)}"
                )
        finally:
            if populate_container:
                try:
                    await populate_container.delete(force=True)
                except Exception:
                    pass

    @staticmethod
    def _immutable_cache_manifest(cached, identity: dict, mount_paths: list[str]) -> dict:
        if not isinstance(cached, tuple) or len(cached) != 2:
            raise ImmutableToolchainCacheError("toolchain_cache_incomplete")
        manifest, stamp = cached
        if (
            not isinstance(stamp, dict)
            or stamp.get("cache_version") != 1
            or stamp.get("image_id") != identity["local_id"]
            or stamp.get("os") != identity["os"]
            or stamp.get("architecture") != identity["architecture"]
            or stamp.get("mount_paths") != mount_paths
            or not isinstance(manifest, dict)
            or manifest.get("mounts") != mount_paths
            or any(
                not isinstance(manifest.get(key, {}), dict)
                or any(
                    not isinstance(name, str) or not isinstance(value, str)
                    for name, value in manifest.get(key, {}).items()
                )
                for key in ("env", "env_prepend")
            )
        ):
            raise ImmutableToolchainCacheError("toolchain_cache_mismatch")
        return manifest

    async def _populate_immutable_toolchain_volume(
        self, image: str, cache_name: str, mount_paths: list[str], identity: dict
    ):
        """Only a newly created volume may reach this helper; never wipe its tree."""
        stamp = json.dumps(
            {
                "cache_version": 1,
                "image_id": identity["local_id"],
                "os": identity["os"],
                "architecture": identity["architecture"],
                "mount_paths": mount_paths,
            },
            sort_keys=True,
        )
        source = shlex.quote(mount_paths[0] + "/.")
        stamp_path = f"{self.TOOLCHAIN_TARGET}/{self.TOOLCHAIN_STAMP_FILE}"
        script = (
            f"set -eu; cp -a -- {source} {self.TOOLCHAIN_TARGET}/; "
            f"test -f {self.TOOLCHAIN_TARGET}/{self.TOOLCHAIN_MANIFEST_FILE}; "
            f"printf '%s' {shlex.quote(stamp)} > {stamp_path}.partial; "
            f"mv -- {stamp_path}.partial {stamp_path}"
        )
        config = {
            "Image": image,
            "Entrypoint": [],
            "Cmd": ["sh", "-c", script],
            "Labels": {"nukelab.managed": "true", "nukelab.toolchain.populate": cache_name},
            "HostConfig": {
                "Mounts": [
                    {"Type": "volume", "Source": cache_name, "Target": self.TOOLCHAIN_TARGET}
                ],
                "AutoRemove": False,
                "NetworkMode": "none",
                "CapDrop": ["ALL"],
                "CapAdd": ["CHOWN", "FOWNER", "DAC_OVERRIDE", "SETUID", "SETGID"],
                "SecurityOpt": ["no-new-privileges:true"],
                "ReadonlyRootfs": True,
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=64m"},
            },
        }
        helper = None
        stopped = False
        try:
            helper = await self.client.containers.create(
                config, name="nukelab-toolchain-populate-" + uuid.uuid4().hex
            )
            await helper.start()
            result = await helper.wait()
            stopped = True
            exit_code = result.get("StatusCode") if isinstance(result, dict) else result
            if exit_code not in (0, "0"):
                raise ImmutableToolchainCacheError("toolchain_population_failed")
        except ImmutableToolchainCacheError:
            raise
        except Exception:
            raise ImmutableToolchainCacheError("toolchain_population_failed") from None
        finally:
            if helper is not None:
                try:
                    await helper.delete(force=True)
                except BaseException:
                    if not stopped:
                        # Database fencing cannot terminate a runtime writer.
                        raise ImmutableToolchainCacheError(
                            "toolchain_population_unknown", outcome_unknown=True
                        ) from None

    async def prepare_immutable_toolchain_volume(
        self, image: str, cache_name: str, mount_paths: list[str]
    ) -> dict:
        """Use only exact artifacts and never repair or rewrite an existing cache."""
        if not isinstance(image, str) or not (
            re.fullmatch(r"sha256:[a-f0-9]{64}", image)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}", image)
        ):
            raise ImageResolutionError("immutable_image_required")
        identity = await self.resolve_image(image)
        if cache_name != self.immutable_toolchain_cache_name(identity, mount_paths):
            raise ImmutableToolchainCacheError("toolchain_cache_name_mismatch")
        # A competing or crashed owner retains this atomic name indefinitely.
        # Only confirmed owner/helper reconciliation may remove an old lock.
        try:
            lock = await self.client.containers.create(
                {
                    "Image": identity["local_id"],
                    "Entrypoint": [],
                    "Cmd": ["true"],
                    "Labels": {
                        "nukelab.managed": "true",
                        "nukelab.toolchain.lock": cache_name,
                        "nukelab.toolchain.immutable": "true",
                    },
                    "HostConfig": {
                        "AutoRemove": False,
                        "NetworkMode": "none",
                        "CapDrop": ["ALL"],
                        "ReadonlyRootfs": True,
                        "SecurityOpt": ["no-new-privileges:true"],
                    },
                },
                name=self._toolchain_lock_name(cache_name),
            )
        except Exception as exc:
            raise ImmutableToolchainCacheError(
                "toolchain_cache_busy"
                if getattr(exc, "status", None) == 409
                else "toolchain_cache_unavailable"
            ) from None
        release_lock = True
        try:
            try:
                # Unlike get_volume(), inspection failure must not mean absent.
                await self.client.volumes.get(cache_name)
                exists = True
            except Exception as exc:
                if getattr(exc, "status", None) != 404:
                    raise ImmutableToolchainCacheError("toolchain_cache_unavailable") from None
                exists = False
            if exists:
                cached = await self._read_toolchain_manifest(identity["local_id"], cache_name)
                return self._immutable_cache_manifest(cached, identity, mount_paths)
            try:
                await self.client.volumes.create(
                    {
                        "Name": cache_name,
                        "Labels": {
                            "nukelab.managed": "true",
                            "nukelab.toolchain.immutable": "true",
                            "nukelab.toolchain.image": identity["local_id"],
                        },
                    }
                )
            except Exception:
                raise ImmutableToolchainCacheError("toolchain_cache_unavailable") from None
            await self._populate_immutable_toolchain_volume(
                identity["local_id"], cache_name, mount_paths, identity
            )
            cached = await self._read_toolchain_manifest(identity["local_id"], cache_name)
            return self._immutable_cache_manifest(cached, identity, mount_paths)
        except BaseException as exc:
            release_lock = not getattr(exc, "outcome_unknown", False)
            raise
        finally:
            if release_lock:
                try:
                    await lock.delete(force=True)
                except Exception:
                    # Leave a blocked cache for reconciliation; never delete another lock.
                    logger.warning("Immutable toolchain lock cleanup requires reconciliation")

    async def prepare_toolchain_volume(
        self, image: str, volume_name: str, mount_paths: list[str]
    ) -> dict:
        """Create or refresh a named volume with contents from a toolchain image.

        The volume is shared across all servers that use the same toolchain
        image. The fast path requires BOTH a parseable manifest AND a stamp
        whose ``image_id`` matches the current local image, so a re-pushed
        image tag invalidates the stale volume instead of being served
        forever. Population is serialized across processes with a lock
        container, and re-population wipes the target before copying so
        removed files do not linger.
        """
        await self.ensure_volume(volume_name, labels={"nukelab.managed": "true"})

        try:
            image_info = await self.client.images.get(image)
        except Exception as e:
            raise ContainerDriverError(
                f"Toolchain image {image} is not available locally: {e}"
            ) from e
        image_id = image_info.get("Id")

        # Fast path: reuse the volume without copying anything. This makes
        # repeated server spawns fast. Old volumes lack a stamp and get a
        # one-time automatic refresh here.
        cached = await self._read_toolchain_manifest(image, volume_name)
        if cached is not None and self._image_ids_match(cached[1].get("image_id"), image_id):
            logger.info("Reusing populated toolchain volume %s for %s", volume_name, image)
            return cached[0]
        if cached is not None:
            logger.info(
                "Toolchain volume %s is stale (image %s changed); re-populating",
                volume_name,
                image,
            )

        # Serialize population across processes; the loser of the race waits
        # and then re-checks before deciding to populate itself.
        lock_container = await self._acquire_toolchain_lock(image, volume_name)
        try:
            cached = await self._read_toolchain_manifest(image, volume_name)
            if cached is not None and self._image_ids_match(cached[1].get("image_id"), image_id):
                logger.info(
                    "Toolchain volume %s was populated while waiting for the lock", volume_name
                )
                return cached[0]

            logger.info("Populating toolchain volume %s from %s", volume_name, image)
            await self._populate_toolchain_volume(image, volume_name, mount_paths, image_info)

            # Read the manifest back from the freshly populated volume.
            cached = await self._read_toolchain_manifest(image, volume_name)
            if cached is None:
                raise ContainerDriverError(
                    f"Toolchain manifest missing after populating {image} into {volume_name}"
                )
            return cached[0]
        finally:
            try:
                await lock_container.delete(force=True)
            except Exception:
                pass

    async def image_exists(self, image: str) -> bool:
        """Return True when the image is present locally."""
        try:
            await self.client.images.get(image)
            return True
        except Exception:
            return False

    async def get_image_env(self, image: str) -> dict[str, str]:
        """Return the default environment variables defined by an image."""
        env: dict[str, str] = {}
        try:
            img = await self.client.images.get(image)
            config = img.get("Config") or img.get("ContainerConfig") or {}
            for line in config.get("Env") or []:
                if "=" in line:
                    key, value = line.split("=", 1)
                    env[key] = value
        except Exception as e:
            logger.warning("Could not read env from image %s: %s", image, e)
        return env

    async def list_images(self) -> list:
        """List images present on the host."""
        try:
            return await self.client.images.list()
        except aiodocker.DockerError as e:
            raise _map_error(e) from e

    def _parse_memory(self, memory_str: str) -> int:
        """Parse memory string to bytes"""
        memory_str = memory_str.lower()
        multipliers = {
            "b": 1,
            "k": 1024,
            "m": 1024**2,
            "g": 1024**3,
        }

        for suffix, multiplier in multipliers.items():
            if memory_str.endswith(suffix):
                return int(float(memory_str[:-1]) * multiplier)

        return int(memory_str)
