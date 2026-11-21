# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Fixed portable-identity vectors and fail-closed configuration normalization."""

import json
import re
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.environment_manifest import EnvironmentManifest, ImageIdentity
from app.services.portable_environment import (
    CONFIGURATION_NOT_PORTABLE,
    REGISTRY_VERIFICATION_REQUIRED,
    VOLUME_CONFIGURATION_LOCAL_ONLY,
    PortableIdentityUnavailable,
    portable_environment_identity,
)

DIGEST_1 = "sha256:" + "1" * 64
DIGEST_2 = "sha256:" + "2" * 64
DIGEST_3 = "sha256:" + "3" * 64
LOCAL_ID = "sha256:" + "a" * 64
REPOSITORY_DIGEST = "registry/workspace@sha256:" + "b" * 64
VARIANT_IDENTITY_KEYS = {
    "requested_reference",
    "local_id",
    "repository_digests",
    "os",
    "architecture",
    "registry_verified",
    "verified_reference",
    "manifest_digest",
    "index_digest",
    "descriptor_media_type",
}

BASE_CANONICAL_BYTES = (
    b'{"configuration":{'
    b'"environment_variable_names":["CUDA_VISIBLE_DEVICES","TOKEN"],'
    b'"packages":["numpy==2.1.0","scipy==1.14.1"],'
    b'"ports":["8080"],'
    b'"tool_mounts":["/opt/nuke"],'
    b'"volume_mounts":["read_write:/data"]},'
    b'"runtime":{'
    b'"architecture":"amd64",'
    b'"manifest_digest":"sha256:1111111111111111111111111111111111111111111111111111111111111111",'
    b'"os":"linux",'
    b'"variant":null},'
    b'"schema":"nukelab.portable-environment/v1",'
    b'"toolchain":null}'
)

VARIANT_CANONICAL_BYTES = (
    b'{"configuration":{'
    b'"environment_variable_names":["CUDA_VISIBLE_DEVICES","TOKEN"],'
    b'"packages":["numpy==2.1.0","scipy==1.14.1"],'
    b'"ports":["8080"],'
    b'"tool_mounts":["/opt/nuke"],'
    b'"volume_mounts":["read_write:/data"]},'
    b'"runtime":{'
    b'"architecture":"arm64",'
    b'"manifest_digest":"sha256:2222222222222222222222222222222222222222222222222222222222222222",'
    b'"os":"linux",'
    b'"variant":"v8"},'
    b'"schema":"nukelab.portable-environment/v1",'
    b'"toolchain":null}'
)

TOOLCHAIN_CANONICAL_BYTES = (
    b'{"configuration":{'
    b'"environment_variable_names":["CUDA_VISIBLE_DEVICES","TOKEN"],'
    b'"packages":["numpy==2.1.0","scipy==1.14.1"],'
    b'"ports":["8080"],'
    b'"tool_mounts":["/opt/nuke"],'
    b'"volume_mounts":["read_write:/data"]},'
    b'"runtime":{'
    b'"architecture":"amd64",'
    b'"manifest_digest":"sha256:1111111111111111111111111111111111111111111111111111111111111111",'
    b'"os":"linux",'
    b'"variant":null},'
    b'"schema":"nukelab.portable-environment/v1",'
    b'"toolchain":{'
    b'"architecture":"amd64",'
    b'"manifest_digest":"sha256:3333333333333333333333333333333333333333333333333333333333333333",'
    b'"os":"linux",'
    b'"variant":"v2"}}'
)

MINIMAL_CANONICAL_BYTES = (
    b'{"configuration":{'
    b'"environment_variable_names":[],'
    b'"packages":[],'
    b'"ports":[],'
    b'"tool_mounts":[],'
    b'"volume_mounts":[]},'
    b'"runtime":{'
    b'"architecture":"amd64",'
    b'"manifest_digest":"sha256:1111111111111111111111111111111111111111111111111111111111111111",'
    b'"os":"linux",'
    b'"variant":null},'
    b'"schema":"nukelab.portable-environment/v1",'
    b'"toolchain":null}'
)

INTEGER_PORT_CANONICAL_BYTES = (
    b'{"configuration":{'
    b'"environment_variable_names":["CUDA_VISIBLE_DEVICES","TOKEN"],'
    b'"packages":["numpy==2.1.0","scipy==1.14.1"],'
    b'"ports":["3000"],'
    b'"tool_mounts":["/opt/nuke"],'
    b'"volume_mounts":["read_write:/data"]},'
    b'"runtime":{'
    b'"architecture":"amd64",'
    b'"manifest_digest":"sha256:1111111111111111111111111111111111111111111111111111111111111111",'
    b'"os":"linux",'
    b'"variant":null},'
    b'"schema":"nukelab.portable-environment/v1",'
    b'"toolchain":null}'
)


def configuration(**changes):
    return {
        "image": "ghcr.io/nukehub-dev/nukelab-workspace:stable",
        "tool_image": None,
        "tool_mounts": ["/opt/nuke"],
        "environment_variables": {"CUDA_VISIBLE_DEVICES": "0", "TOKEN": "private-value"},
        "packages": ["numpy==2.1.0", "scipy==1.14.1"],
        "volumes": [{"mount_path": "/data", "mode": "read_write"}],
        "ports": [8080],
        **changes,
    }


def runtime_identity(**changes):
    values = {
        "requested_reference": "ghcr.io/nukehub-dev/nukelab-workspace:stable",
        "local_id": LOCAL_ID,
        "repository_digests": [REPOSITORY_DIGEST],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": True,
        "verified_reference": (
            "ghcr.io/nukehub-dev/nukelab-workspace@sha256:"
            "1111111111111111111111111111111111111111111111111111111111111111"
        ),
        "manifest_digest": DIGEST_1,
        **changes,
    }
    return ImageIdentity(**values)


def toolchain_identity(**changes):
    values = {
        "requested_reference": "ghcr.io/nukehub-dev/toolchain:stable",
        "local_id": "sha256:" + "c" * 64,
        "repository_digests": ["registry/toolchain@sha256:" + "d" * 64],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": True,
        "verified_reference": (
            "ghcr.io/nukehub-dev/toolchain@sha256:"
            "3333333333333333333333333333333333333333333333333333333333333333"
        ),
        "manifest_digest": DIGEST_3,
        **changes,
    }
    return ImageIdentity(**values)


def local_runtime(**changes):
    values = {
        "requested_reference": "workspace:latest",
        "local_id": LOCAL_ID,
        "repository_digests": [REPOSITORY_DIGEST],
        "os": "linux",
        "architecture": "amd64",
        **changes,
    }
    return ImageIdentity(**values)


def manifest_payload(**changes):
    values = {
        "schema_version": "nukelab.environment/v1",
        "revision_id": "00000000-0000-4000-8000-000000000001",
        "revision_fingerprint": "c" * 64,
        "template_label": "Workspace",
        "runtime": local_runtime().model_dump(mode="json"),
        "toolchain": None,
        "toolchain_mounts": [],
        "environment_variable_names": ["TOKEN"],
        "environment_values": "manual_input_required",
        "resources": {"cpu": 1.0, "memory_mib": 2048, "disk_mib": 10240},
        "volume_requirements": [],
        "portability": "local_only",
        "limitations": [],
        **changes,
    }
    return values


def parse_manifest(payload):
    return EnvironmentManifest.parse_import(json.dumps(payload))


def assert_unavailable(code, configuration_value=None, runtime=None, toolchain=None):
    with pytest.raises(PortableIdentityUnavailable) as failure:
        portable_environment_identity(
            configuration_value if configuration_value is not None else configuration(),
            runtime if runtime is not None else runtime_identity(),
            toolchain,
        )
    assert failure.value.code == code


def test_base_environment_has_fixed_canonical_bytes_and_fingerprint():
    identity = portable_environment_identity(configuration(), runtime_identity(), None)
    assert identity.canonical_bytes == BASE_CANONICAL_BYTES
    assert (
        identity.fingerprint == "001c856a9594856132a57ab313182356e51f2aabaab628356806428adb197348"
    )
    assert re.fullmatch(r"[a-f0-9]{64}", identity.fingerprint)


def test_variant_environment_has_fixed_canonical_bytes_and_fingerprint():
    identity = portable_environment_identity(
        configuration(),
        runtime_identity(
            architecture="arm64",
            manifest_digest=DIGEST_2,
            verified_reference=(
                "ghcr.io/nukehub-dev/nukelab-workspace@sha256:"
                "2222222222222222222222222222222222222222222222222222222222222222"
            ),
            variant="v8",
        ),
        None,
    )
    assert identity.canonical_bytes == VARIANT_CANONICAL_BYTES
    assert (
        identity.fingerprint == "61c63f03fc8d06a892f70d75b86087f9b017ce1838267f81b03f4ca5bc0327d5"
    )


def test_toolchain_environment_has_fixed_canonical_bytes_and_fingerprint():
    identity = portable_environment_identity(
        configuration(),
        runtime_identity(),
        toolchain_identity(variant="v2"),
    )
    assert identity.canonical_bytes == TOOLCHAIN_CANONICAL_BYTES
    assert (
        identity.fingerprint == "a4723b5f4815bb8d0a339dc4e0592643c79032044b1efc1b23d69d574ccee296"
    )


def test_empty_configuration_has_fixed_canonical_bytes_and_fingerprint():
    identity = portable_environment_identity(
        {
            "tool_mounts": [],
            "packages": [],
            "ports": [],
            "volumes": [],
            "environment_variables": {},
        },
        runtime_identity(),
        None,
    )
    assert identity.canonical_bytes == MINIMAL_CANONICAL_BYTES
    assert (
        identity.fingerprint == "14779f62255ae1be9286332ec5794fa46327193f62e56db5f74d53a78c0c6d6a"
    )


def test_integer_and_decimal_port_forms_normalize_once():
    identity = portable_environment_identity(
        configuration(ports=[3000, "3000"]), runtime_identity(), None
    )
    assert identity.canonical_bytes == INTEGER_PORT_CANONICAL_BYTES
    assert (
        identity.fingerprint == "8c0c8ce220e119355acc0516d68358297643383f6284d1d242b7eb1f767ab39a"
    )


def test_repository_index_reference_and_media_type_do_not_change_identity():
    base = portable_environment_identity(configuration(), runtime_identity(), None)
    mirrored = portable_environment_identity(
        configuration(),
        runtime_identity(
            requested_reference="mirror.example/nukelab/workspace:latest",
            repository_digests=["mirror.example/nukelab/workspace@sha256:" + "e" * 64],
            verified_reference=(
                "mirror.example/nukelab/workspace@sha256:"
                "1111111111111111111111111111111111111111111111111111111111111111"
            ),
            index_digest="sha256:" + "f" * 64,
            descriptor_media_type="application/vnd.oci.image.manifest.v1+json",
        ),
        None,
    )
    assert mirrored.canonical_bytes == base.canonical_bytes
    assert mirrored.fingerprint == base.fingerprint


def test_variant_changes_the_fingerprint_without_changing_the_digest():
    plain = portable_environment_identity(configuration(), runtime_identity(), None)
    variant = portable_environment_identity(configuration(), runtime_identity(variant="v8"), None)
    assert plain.fingerprint != variant.fingerprint


def test_order_deduplication_and_equivalent_ports_normalize_to_one_identity():
    left = configuration(
        tool_mounts=["/opt/nuke"],
        packages=["scipy==1.14.1", "numpy==2.1.0", "numpy==2.1.0"],
        ports=["8081", 8080, "8080", "08080"],
        environment_variables={"TOKEN": "left", "CUDA_VISIBLE_DEVICES": "0"},
        volumes=[
            {"mount_path": "/data", "mode": "read_write"},
            {"mount_path": "/cache", "mode": "read_only"},
            {"mount_path": "/data", "mode": "read_write"},
        ],
    )
    right = configuration(
        tool_mounts=["/opt/nuke"],
        packages=["numpy==2.1.0", "scipy==1.14.1"],
        ports=[8080, "8081"],
        environment_variables={"CUDA_VISIBLE_DEVICES": "different", "TOKEN": "right"},
        volumes=[
            {"mount_path": "/cache", "mode": "read_only"},
            {"mount_path": "/data", "mode": "read_write"},
        ],
    )
    left_identity = portable_environment_identity(left, runtime_identity(), None)
    right_identity = portable_environment_identity(right, runtime_identity(), None)
    assert left_identity.canonical_bytes == right_identity.canonical_bytes
    assert left_identity.fingerprint == right_identity.fingerprint
    payload = json.loads(left_identity.canonical_bytes)
    assert payload["configuration"]["tool_mounts"] == ["/opt/nuke"]
    assert payload["configuration"]["packages"] == ["numpy==2.1.0", "scipy==1.14.1"]
    assert payload["configuration"]["ports"] == ["8080", "8081"]
    assert payload["configuration"]["volume_mounts"] == [
        "read_only:/cache",
        "read_write:/data",
    ]


def test_tags_environment_values_ids_and_timestamps_are_excluded():
    base = portable_environment_identity(configuration(), runtime_identity(), None)
    altered = configuration(
        image="other-workspace:mutable-tag",
        tool_image="other-toolchain:mutable-tag",
        environment_variables={"TOKEN": "different-value", "CUDA_VISIBLE_DEVICES": "9"},
        revision_id="3f1e4d5c-0000-4000-8000-000000000099",
        template_id="3f1e4d5c-0000-4000-8000-000000000098",
        created_at="2026-11-21T00:00:00Z",
    )
    altered_identity = portable_environment_identity(altered, runtime_identity(), None)
    assert altered_identity.canonical_bytes == base.canonical_bytes
    assert altered_identity.fingerprint == base.fingerprint
    serialized = altered_identity.canonical_bytes.decode()
    assert "different-value" not in serialized
    assert "mutable-tag" not in serialized
    assert "3f1e4d5c" not in serialized
    assert "2026-11-21" not in serialized


@pytest.mark.parametrize(
    "identity",
    [
        local_runtime(),
        runtime_identity(manifest_digest=None),
        runtime_identity(manifest_digest="sha512:" + "1" * 128),
        runtime_identity(manifest_digest="sha256:" + "A" * 64),
    ],
)
def test_runtime_requires_registry_verification_and_sha256_manifest_digest(identity):
    assert identity.variant is None
    assert_unavailable(REGISTRY_VERIFICATION_REQUIRED, runtime=identity)


def test_toolchain_requires_registry_verification_when_present():
    assert_unavailable(
        REGISTRY_VERIFICATION_REQUIRED,
        runtime=runtime_identity(),
        toolchain=local_runtime(),
    )
    assert_unavailable(
        REGISTRY_VERIFICATION_REQUIRED,
        runtime=runtime_identity(),
        toolchain=toolchain_identity(manifest_digest=None),
    )


@pytest.mark.parametrize(
    "volumes",
    [
        ["/host/data:/data"],
        ["named-volume:/data:ro"],
        [{"bind": "/data", "mode": "ro"}],
        [{"mount_path": "data", "mode": "read_write"}],
        [{"mount_path": "/data"}],
        [{"mount_path": "/data", "mode": "ro"}],
        [{"mount_path": "/data", "mode": ["read_only"]}],
        [{"mount_path": "/data/../etc", "mode": "read_only"}],
        [{"mount_path": "/data\x00", "mode": "read_only"}],
        [{"mount_path": "/data", "mode": "read_write", "source": "/host/data"}],
        [{"mount_path": "/data", "mode": "read_write", "host_path": "/host/data"}],
        [{"mount_path": "/data", "mode": "read_write", "volume_id": "volume-1"}],
        [{"mount_path": "/data", "mode": "read_write", "name": "data"}],
        [{"mount_path": "/data", "mode": "read_write", "size_bytes": 1024}],
        [{"mount_path": "/data", "mode": "read_write", "purpose": "data"}],
        [{"mount_path": "/data", "mode": "read_write"}, "/cache:/cache"],
        [None],
        "not-a-list",
    ],
)
def test_unsupported_volume_shapes_are_local_only(volumes):
    assert_unavailable(
        VOLUME_CONFIGURATION_LOCAL_ONLY,
        configuration_value=configuration(volumes=volumes),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"packages": ["", "numpy"]},
        {"packages": ["   "]},
        {"packages": ["numpy\n2.1"]},
        {"packages": [123]},
        {"packages": "numpy"},
        {"ports": [True]},
        {"ports": ["+8080"]},
        {"ports": ["-1"]},
        {"ports": [80.5]},
        {"ports": ["80x"]},
        {"ports": ["9" * 5000]},
        {"ports": "8080"},
        {"environment_variables": {"TOKEN=secret": "value"}},
        {"environment_variables": {"1TOKEN": "value"}},
        {"environment_variables": {"A" * 129: "value"}},
        {"environment_variables": ["TOKEN"]},
    ],
)
def test_malformed_configuration_is_not_portable(changes):
    assert_unavailable(
        CONFIGURATION_NOT_PORTABLE,
        configuration_value=configuration(**changes),
    )


@pytest.mark.parametrize(
    "tool_mounts",
    [
        ["/opt/nuke", "/opt/tools"],
        ["relative"],
        ["/opt/nuke/"],
        ["/opt/./nuke"],
        ["/opt//nuke"],
        ["/opt/../etc"],
        ["/opt/nuke\x00"],
        ["/toolchain-target"],
        ["/toolchain-target/cache"],
        [" /opt/nuke"],
        ["/opt/nuke "],
        ["/"],
        [123],
        [None],
        "/opt/nuke",
    ],
)
def test_tool_mounts_must_match_the_approved_single_absolute_layout(tool_mounts):
    assert_unavailable(
        CONFIGURATION_NOT_PORTABLE,
        configuration_value=configuration(tool_mounts=tool_mounts),
    )


def test_single_absolute_tool_mount_is_accepted():
    identity = portable_environment_identity(
        configuration(tool_mounts=["/opt/tools"]), runtime_identity(), None
    )
    payload = json.loads(identity.canonical_bytes)
    assert payload["configuration"]["tool_mounts"] == ["/opt/tools"]


def test_empty_tool_mounts_are_not_replaced_by_an_invented_default():
    identity = portable_environment_identity(
        configuration(tool_mounts=[]), runtime_identity(), toolchain_identity()
    )
    payload = json.loads(identity.canonical_bytes)
    assert payload["configuration"]["tool_mounts"] == []
    assert payload["toolchain"] is not None


def test_toolchain_is_included_when_present_and_null_when_absent():
    absent = json.loads(
        portable_environment_identity(configuration(), runtime_identity(), None).canonical_bytes
    )
    present = json.loads(
        portable_environment_identity(
            configuration(), runtime_identity(), toolchain_identity(variant="v2")
        ).canonical_bytes
    )
    present_without_variant = json.loads(
        portable_environment_identity(
            configuration(), runtime_identity(), toolchain_identity()
        ).canonical_bytes
    )
    assert absent["toolchain"] is None
    assert present["toolchain"] == {
        "architecture": "amd64",
        "manifest_digest": DIGEST_3,
        "os": "linux",
        "variant": "v2",
    }
    assert present_without_variant["toolchain"]["variant"] is None


def test_canonical_bytes_have_no_numbers_booleans_or_ascii_escapes():
    identity = portable_environment_identity(
        configuration(packages=["numpy==2.1.0", "café"]), runtime_identity(), None
    )
    assert "café".encode() in identity.canonical_bytes
    assert b"\\u00e9" not in identity.canonical_bytes

    def assert_strings_only(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert isinstance(key, str)
                assert_strings_only(item)
        elif isinstance(value, list):
            for item in value:
                assert_strings_only(item)
        else:
            assert value is None or isinstance(value, str)

    assert_strings_only(json.loads(identity.canonical_bytes))


@pytest.mark.parametrize(
    "variant",
    ["v8", "v8.1", "a_b-c", "A1", "v" * 32],
)
def test_valid_platform_variants_are_accepted(variant):
    assert local_runtime(variant=variant).variant == variant.lower()


@pytest.mark.parametrize(
    "variant",
    [
        "",
        "-v8",
        ".v8",
        "_v8",
        "v 8",
        "v8/1",
        "v8@1",
        "https://registry/v8",
        "user:secret@registry/v8",
        "v8\n",
        "v8\x00",
        "v" * 33,
    ],
)
def test_invalid_platform_variants_are_rejected(variant):
    with pytest.raises(ValidationError):
        local_runtime(variant=variant)


def test_image_identity_omits_only_null_variant_and_keeps_other_nulls():
    plain = local_runtime()
    dumps = (
        plain.model_dump(),
        plain.model_dump(mode="json"),
        json.loads(plain.model_dump_json()),
    )
    for data in dumps:
        assert "variant" not in data
        assert data["verified_reference"] is None
        assert data["manifest_digest"] is None
        assert data["index_digest"] is None
        assert data["descriptor_media_type"] is None
        assert set(data) == VARIANT_IDENTITY_KEYS

    variant = local_runtime(variant="v8")
    variant_dumps = (
        variant.model_dump(),
        variant.model_dump(mode="json"),
        json.loads(variant.model_dump_json()),
    )
    for data in variant_dumps:
        assert data["variant"] == "v8"
        assert set(data) == VARIANT_IDENTITY_KEYS | {"variant"}


def test_nested_manifest_serialization_applies_variant_rules():
    payload = manifest_payload(
        toolchain=local_runtime(variant="v2").model_dump(mode="json"),
        toolchain_mounts=["/opt/nuke"],
    )
    manifest = parse_manifest(payload)
    data = manifest.model_dump(mode="json")
    assert "variant" not in data["runtime"]
    assert data["toolchain"]["variant"] == "v2"
    assert "portable_fingerprint" not in data

    encoded = json.loads(manifest.model_dump_json())
    assert "variant" not in encoded["runtime"]
    assert encoded["toolchain"]["variant"] == "v2"
    assert "portable_fingerprint" not in encoded

    plain_toolchain = parse_manifest(
        manifest_payload(toolchain=local_runtime().model_dump(mode="json"))
    )
    plain_data = plain_toolchain.model_dump(mode="json")
    assert "variant" not in plain_data["runtime"]
    assert "variant" not in plain_data["toolchain"]


def test_local_only_manifest_keeps_the_2_2_shape():
    manifest = parse_manifest(manifest_payload())
    for data in (manifest.model_dump(mode="json"), json.loads(manifest.model_dump_json())):
        assert "portable_fingerprint" not in data
        assert "variant" not in data["runtime"]
        assert set(data["runtime"]) == VARIANT_IDENTITY_KEYS
    assert manifest.portable_fingerprint is None
    assert manifest.runtime.variant is None


def test_old_manifest_without_new_fields_remains_parseable():
    payload = manifest_payload()
    assert "portable_fingerprint" not in payload
    assert "variant" not in payload["runtime"]
    manifest = EnvironmentManifest.parse_import(json.dumps(payload))
    assert manifest.schema_version == "nukelab.environment/v1"
    assert manifest.portable_fingerprint is None
    assert manifest.runtime.variant is None


def test_registry_verified_manifest_requires_a_valid_portable_fingerprint():
    verified_runtime = runtime_identity().model_dump(mode="json")
    registry_verified = manifest_payload(
        runtime=verified_runtime,
        portability="registry_verified",
    )
    with pytest.raises(ValidationError, match="portable fingerprint"):
        parse_manifest(registry_verified)

    for invalid in ("d" * 63, "d" * 65, "D" * 64, "not-a-fingerprint"):
        with pytest.raises(ValidationError):
            parse_manifest(registry_verified | {"portable_fingerprint": invalid})

    accepted = parse_manifest(registry_verified | {"portable_fingerprint": "d" * 64})
    assert accepted.portable_fingerprint == "d" * 64
    assert accepted.model_dump(mode="json")["portable_fingerprint"] == "d" * 64
    assert EnvironmentManifest.parse_import(accepted.model_dump_json()) == accepted


def test_local_only_manifest_must_not_advertise_a_portable_fingerprint():
    with pytest.raises(ValidationError, match="Local-only"):
        parse_manifest(manifest_payload(portable_fingerprint="d" * 64))


def test_registry_verified_manifest_round_trips_variant_and_fingerprint():
    payload = manifest_payload(
        runtime=runtime_identity(variant="v8").model_dump(mode="json"),
        portability="registry_verified",
        portable_fingerprint="d" * 64,
    )
    manifest = parse_manifest(payload)
    assert manifest.runtime.variant == "v8"
    assert manifest.canonical_environment()["runtime"]["variant"] == "v8"
    data = manifest.model_dump(mode="json")
    assert data["runtime"]["variant"] == "v8"
    assert data["portable_fingerprint"] == "d" * 64
    assert EnvironmentManifest.parse_import(manifest.model_dump_json()) == manifest


def test_manifest_revision_id_is_still_a_uuid():
    manifest = parse_manifest(manifest_payload())
    assert isinstance(manifest.revision_id, UUID)
