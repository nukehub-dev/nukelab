# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Persistable launch intent shared by direct and deferred server creation."""

import posixpath
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VolumeMode = Literal["read_only", "read_write"]
VolumeSelection = UUID | Literal[""]


_PROTECTED_MOUNT_PATHS = (
    "/proc",
    "/sys",
    "/dev",
    "/etc/nukelab/auth",
    "/usr/local/lib/nukelab",
)


def validate_mount_destination(path: str, *, protected_paths: Iterable[str] = ()) -> None:
    """User data must not hide runtime security mounts or approved toolchain data."""
    target = PurePosixPath(path)
    for root in (*_PROTECTED_MOUNT_PATHS, *protected_paths):
        protected = PurePosixPath(root)
        if target == protected or target in protected.parents or protected in target.parents:
            raise ValueError("Volume mount overlaps a protected container path")


class NormalizedVolumeMount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    volume_id: VolumeSelection
    mount_path: str = Field(default="/data", min_length=1, max_length=255)
    mode: VolumeMode = "read_write"
    max_size_bytes: Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)] | None = None
    is_primary: bool = False

    @field_validator("mount_path")
    @classmethod
    def canonical_mount_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or ".." in value.split("/")
        ):
            raise ValueError("Mount path must be an absolute container path without traversal")
        path = "/" + posixpath.normpath(value).lstrip("/")
        if path == "/":
            raise ValueError("Cannot mount over the container root")
        validate_mount_destination(path)
        return path


class NormalizedLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    plan_id: UUID
    environment_id: UUID
    volume_mounts: list[NormalizedVolumeMount] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def consistent_mounts(self):
        paths = [mount.mount_path for mount in self.volume_mounts]
        if len(paths) != len(set(paths)):
            raise ValueError("Volume mount paths must be distinct")
        selections = [mount.volume_id for mount in self.volume_mounts if mount.volume_id != ""]
        if len(selections) != len(set(selections)):
            raise ValueError("A volume can only be selected once per server")
        if [mount.is_primary for mount in self.volume_mounts] != [True] + [False] * (
            len(self.volume_mounts) - 1
        ):
            raise ValueError("The first volume mount must be the only primary mount")
        return self
