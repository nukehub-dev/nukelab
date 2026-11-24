# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin revision responses expose bounded names and never raw values."""

import pytest

from app.services.environment_revision_admin_service import (
    CONFIGURATION_NOT_DISPLAYABLE,
    ENVIRONMENT_NAMES_NOT_DISPLAYABLE,
    ENVIRONMENT_NAMES_TRUNCATED,
    MAX_ENVIRONMENT_NAMES,
    MAX_LIMITATIONS,
    MAX_PACKAGES,
    MAX_PORTS,
    MAX_VOLUMES,
    PACKAGES_NOT_DISPLAYABLE,
    PACKAGES_TRUNCATED,
    PORTS_NOT_DISPLAYABLE,
    PORTS_TRUNCATED,
    RUNTIME_IDENTITY_NOT_DISPLAYABLE,
    RUNTIME_REFERENCE_NOT_DISPLAYABLE,
    TOOL_MOUNTS_NOT_DISPLAYABLE,
    TOOLCHAIN_REFERENCE_NOT_DISPLAYABLE,
    VOLUME_CONFIGURATION_LOCAL_ONLY,
    VOLUMES_TRUNCATED,
    _bounded_limitations,
    _configuration_summary,
    _container_path,
    _image_summary,
)


def test_missing_image_identity_is_empty():
    summary, limitations = _image_summary(None, limitation=RUNTIME_IDENTITY_NOT_DISPLAYABLE)

    assert summary.registry_verified is False
    assert limitations == []


def test_invalid_image_identity_is_reported_as_a_limitation():
    summary, limitations = _image_summary(
        {"local_id": "not-a-digest"}, limitation=RUNTIME_IDENTITY_NOT_DISPLAYABLE
    )

    assert summary.registry_verified is False
    assert limitations == [RUNTIME_IDENTITY_NOT_DISPLAYABLE]


def test_unsafe_verified_reference_is_rejected_by_the_identity_schema():
    summary, limitations = _image_summary(
        {
            "requested_reference": "registry.example/runtime:latest",
            "local_id": "sha256:" + "a" * 64,
            "os": "linux",
            "architecture": "amd64",
            "registry_verified": True,
            "verified_reference": "https://registry.example/runtime@sha256:" + "b" * 64,
            "manifest_digest": "sha256:" + "b" * 64,
            "descriptor_media_type": "application/vnd.oci.image.manifest.v1+json",
        },
        limitation=RUNTIME_IDENTITY_NOT_DISPLAYABLE,
    )

    assert summary.registry_verified is False
    assert summary.verified_reference is None
    assert limitations == [RUNTIME_IDENTITY_NOT_DISPLAYABLE]


def test_verified_image_summary_discloses_only_safe_identity_fields():
    digest = "sha256:" + "b" * 64
    summary, limitations = _image_summary(
        {
            "requested_reference": "registry.example/runtime:latest",
            "local_id": "sha256:" + "a" * 64,
            "repository_digests": ["registry.example/runtime@" + digest],
            "os": "linux",
            "architecture": "amd64",
            "variant": "v2",
            "registry_verified": True,
            "verified_reference": "registry.example/runtime@" + digest,
            "manifest_digest": digest,
            "index_digest": "sha256:" + "c" * 64,
            "descriptor_media_type": "application/vnd.oci.image.manifest.v1+json",
        },
        limitation=RUNTIME_IDENTITY_NOT_DISPLAYABLE,
    )

    assert limitations == []
    assert summary.verified_reference == "registry.example/runtime@" + digest
    assert summary.manifest_digest == digest
    assert summary.variant == "v2"


def test_non_mapping_configuration_is_not_displayable():
    summary, limitations = _configuration_summary("not-a-configuration")

    assert summary.image is None
    assert summary.packages == []
    assert limitations == [CONFIGURATION_NOT_DISPLAYABLE]


def test_unsafe_references_are_not_displayed():
    _, limitations = _configuration_summary(
        {
            "image": "https://registry.example/runtime",
            "tool_image": "registry.example/toolchain@sha256:" + "f" * 64,
        }
    )

    assert RUNTIME_REFERENCE_NOT_DISPLAYABLE in limitations
    assert TOOLCHAIN_REFERENCE_NOT_DISPLAYABLE not in limitations


@pytest.mark.parametrize(
    "packages", [123, ["numpy", ""], ["numpy", "x" * 201], ["numpy", "bad\x00package"]]
)
def test_invalid_packages_are_not_displayed(packages):
    summary, limitations = _configuration_summary({"packages": packages})

    assert summary.packages == []
    assert PACKAGES_NOT_DISPLAYABLE in limitations


def test_packages_are_deduplicated_sorted_and_truncated():
    summary, limitations = _configuration_summary(
        {"packages": ["scipy"] + [f"package-{index:03d}" for index in range(MAX_PACKAGES)]}
    )

    assert limitations == [PACKAGES_TRUNCATED]
    assert len(summary.packages) == MAX_PACKAGES
    assert summary.packages == sorted(set(summary.packages))


@pytest.mark.parametrize(
    "ports",
    [123, [True], [-1], [70000.5], ["not-a-port"], ["80", "bad"], ["80", ""]],
)
def test_invalid_ports_are_not_displayed(ports):
    summary, limitations = _configuration_summary({"ports": ports})

    assert summary.ports == []
    assert PORTS_NOT_DISPLAYABLE in limitations


def test_ports_are_normalized_and_truncated():
    summary, limitations = _configuration_summary(
        {"ports": ["080", 443] + [str(index) for index in range(MAX_PORTS + 1)]}
    )

    assert limitations == [PORTS_TRUNCATED]
    assert summary.ports == [str(index) for index in range(MAX_PORTS)]


@pytest.mark.parametrize(
    "mounts",
    ["/data", ["/data", "/cache"], [123], ["/toolchain-target"], ["relative"]],
)
def test_invalid_tool_mounts_are_not_displayed(mounts):
    summary, limitations = _configuration_summary({"tool_mounts": mounts})

    assert summary.tool_mounts == []
    assert TOOL_MOUNTS_NOT_DISPLAYABLE in limitations


def test_tool_mount_path_is_normalized():
    summary, limitations = _configuration_summary({"tool_mounts": ["/opt//cache"]})

    assert limitations == []
    assert summary.tool_mounts == ["/opt/cache"]


@pytest.mark.parametrize(
    "values", [["TOKEN"], {"1INVALID": "value"}, {"TOKEN": "value", "bad-name": "value"}]
)
def test_invalid_environment_name_maps_are_not_displayed(values):
    summary, limitations = _configuration_summary({"environment_variables": values})

    assert summary.environment_variable_names == []
    assert ENVIRONMENT_NAMES_NOT_DISPLAYABLE in limitations


def test_environment_names_are_sorted_deduplicated_and_truncated():
    values = {f"VAR_{index:03d}": "secret" for index in range(MAX_ENVIRONMENT_NAMES + 1)}
    summary, limitations = _configuration_summary({"environment_variables": values})

    assert limitations == [ENVIRONMENT_NAMES_TRUNCATED]
    assert len(summary.environment_variable_names) == MAX_ENVIRONMENT_NAMES
    assert summary.environment_variable_names == sorted(summary.environment_variable_names)


@pytest.mark.parametrize(
    "volumes",
    [
        "not-a-list",
        [{"mount_path": "/data"}],
        [{"mount_path": "/data", "mode": "append", "extra": True}],
        [{"mount_path": "relative", "mode": "read_write"}],
        [{"mount_path": 1, "mode": "read_write"}],
    ],
)
def test_invalid_volume_configurations_are_local_only(volumes):
    summary, limitations = _configuration_summary({"volumes": volumes})

    assert summary.volumes == []
    assert limitations == [VOLUME_CONFIGURATION_LOCAL_ONLY]


def test_volumes_are_normalized_deduplicated_and_truncated():
    volumes = [
        {"mount_path": f"/data/{index:02d}", "mode": "read_only"} for index in range(MAX_VOLUMES)
    ]
    volumes += [
        {"mount_path": "/data/00", "mode": "read_only"},
        {"mount_path": "/data/extra", "mode": "read_write"},
    ]
    summary, limitations = _configuration_summary({"volumes": volumes})

    assert limitations == [VOLUMES_TRUNCATED]
    assert len(summary.volumes) == MAX_VOLUMES
    assert summary.volumes[0].mount_path == "/data/00"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("relative", None),
        ("//double", None),
        ("/data/../escape", None),
        ("/data/\x00name", None),
        ("/data//cache", "/data/cache"),
    ],
)
def test_container_paths_are_bounded(value, expected):
    assert _container_path(value) == expected


def test_limitations_are_deduplicated_and_bounded():
    values = ["one", "one"] + [f"value-{index}" for index in range(20)]

    bounded = _bounded_limitations(values)

    assert bounded[0] == "one"
    assert len(bounded) == MAX_LIMITATIONS
