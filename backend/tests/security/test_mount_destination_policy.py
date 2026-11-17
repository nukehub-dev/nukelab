# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""User data cannot hide system security mounts or approved scientific artifacts."""

import pytest
from pydantic import ValidationError

from app.schemas.server_launch import NormalizedVolumeMount, validate_mount_destination


@pytest.mark.parametrize(
    "path",
    [
        "/proc",
        "/proc/cpuinfo",
        "/sys",
        "/sys/fs/cgroup",
        "/dev",
        "/dev/shm",
        "/etc",
        "/etc/nukelab",
        "/etc/nukelab/auth",
        "/etc/nukelab/auth/server-auth-public.pem",
        "/usr",
        "/usr/local/lib",
        "/usr/local/lib/nukelab",
        "/usr/local/lib/nukelab/libnukelab_cpu.so",
        "//proc",
        "/data/../proc",
    ],
)
def test_reserved_destinations_fail_before_volume_selection(path):
    with pytest.raises(ValidationError):
        NormalizedVolumeMount(volume_id="", mount_path=path)


@pytest.mark.parametrize(
    "path",
    [
        "/home/researcher",
        "/data",
        "/datasets/proc",
        "/proc-results",
        "/etc/custom",
        "/usr/local/share/data",
    ],
)
def test_unrelated_named_data_destinations_remain_valid(path):
    assert NormalizedVolumeMount(volume_id="", mount_path=path).mount_path == path


@pytest.mark.parametrize(
    "path", ["/opt", "/opt/nuke", "/opt/nuke/lib", "/opt/alternate", "/opt/alternate/data"]
)
def test_data_cannot_shadow_any_approved_toolchain_root(path):
    with pytest.raises(ValueError, match="protected"):
        validate_mount_destination(path, protected_paths=["/opt/nuke", "/opt/alternate"])


def test_shared_prefix_is_not_a_toolchain_overlap():
    validate_mount_destination("/opt/nuke-data", protected_paths=["/opt/nuke"])
