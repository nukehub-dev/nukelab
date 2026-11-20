# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Public recreation input bounds and actor-specific logical volume requirements."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.environment_manifest import VolumeRequirement
from app.schemas.server_provenance import RecreationSource, ServerRecreateRequest
from app.services.server_recreation_service import (
    ProvenanceError,
    ServerRecreationService,
)
from tests.services.test_environment_provenance import manifest


@pytest.mark.parametrize("shape", ["neither", "both", "string", "oversized", "unknown"])
def test_recreation_source_requires_one_bounded_strict_manifest_or_launch(shape):
    payload = manifest().model_dump(mode="json")
    body = {"manifest": payload}
    if shape == "neither":
        body = {}
    elif shape == "both":
        body["source_launch_id"] = str(uuid4())
    elif shape == "string":
        body["manifest"] = "{}"
    elif shape == "oversized":
        body["manifest"]["template_label"] = "x" * 65537
    else:
        body["manifest"]["extra"] = True
    with pytest.raises(ValidationError):
        RecreationSource.model_validate(body)


def test_manifest_object_uses_json_uuid_semantics_without_weakening_manifest_strictness():
    payload = manifest().model_dump(mode="json")
    parsed = RecreationSource.model_validate({"manifest": payload})
    assert str(parsed.manifest.revision_id) == payload["revision_id"]
    assert parsed.manifest.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "mounts",
    [
        None,
        [],
        [{"volume_id": "/var/run/docker.sock", "mount_path": "/data"}],
        [{"volume_id": "", "mount_path": "/proc"}],
    ],
)
def test_recreation_requires_explicit_valid_volume_bindings(mounts):
    body = {"source_launch_id": str(uuid4()), "name": "new", "plan_id": str(uuid4())}
    if mounts is not None:
        body["volume_mounts"] = mounts
    with pytest.raises(ValidationError):
        ServerRecreateRequest.model_validate(body)


def test_preview_only_relocates_a_direct_home_requirement_and_preserves_modes():
    saved = manifest().model_copy(
        update={
            "volume_requirements": [
                VolumeRequirement(purpose="home", mount_path="/home/oldowner", mode="read_write"),
                VolumeRequirement(purpose="home", mount_path="/data", mode="read_only"),
                VolumeRequirement(
                    purpose="data",
                    mount_path="/home/oldowner/results",
                    mode="read_only",
                ),
            ]
        }
    )
    requirements = ServerRecreationService._volume_requirements(saved, "newowner")
    assert [item.mount_path for item in requirements] == [
        "/home/newowner",
        "/data",
        "/home/oldowner/results",
    ]
    assert [item.mode for item in requirements] == [
        "read_write",
        "read_only",
        "read_only",
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/home/old\nname",
        "/home/old\\name",
        "/proc",
        "/usr/local/lib",
        "/opt/tools/data",
    ],
)
def test_preview_rejects_unsafe_original_or_protected_destination(path):
    saved = manifest().model_copy(
        update={
            "volume_requirements": [
                VolumeRequirement(purpose="home", mount_path=path, mode="read_write")
            ]
        }
    )
    with pytest.raises(ProvenanceError, match="invalid_volume_requirement"):
        ServerRecreationService._volume_requirements(saved, "newowner", ["/opt/tools"])


def test_home_relocation_does_not_create_duplicate_destinations():
    saved = manifest().model_copy(
        update={
            "volume_requirements": [
                VolumeRequirement(purpose="home", mount_path="/home/first", mode="read_write"),
                VolumeRequirement(purpose="home", mount_path="/home/second", mode="read_write"),
            ]
        }
    )
    with pytest.raises(ProvenanceError, match="invalid_volume_requirement"):
        ServerRecreationService._volume_requirements(saved, "newowner")


def test_data_purpose_container_home_alias_matches_final_launch_normalization(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "container_user", "runtimeuser")
    saved = manifest().model_copy(
        update={
            "volume_requirements": [
                VolumeRequirement(purpose="data", mount_path="/home/runtimeuser", mode="read_only"),
                VolumeRequirement(purpose="home", mount_path="/data", mode="read_write"),
            ]
        }
    )
    requirements = ServerRecreationService._volume_requirements(saved, "researcher")
    assert [item.mount_path for item in requirements] == ["/home/researcher", "/data"]
    assert requirements[0].mode == "read_only"


def test_container_home_alias_collision_is_rejected(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "container_user", "runtimeuser")
    saved = manifest().model_copy(
        update={
            "volume_requirements": [
                VolumeRequirement(purpose="data", mount_path="/home/runtimeuser", mode="read_only"),
                VolumeRequirement(purpose="home", mount_path="/home/previous", mode="read_write"),
            ]
        }
    )
    with pytest.raises(ProvenanceError, match="invalid_volume_requirement"):
        ServerRecreationService._volume_requirements(saved, "researcher")


def test_empty_historic_requirements_are_not_recreated_by_guessing_a_home():
    with pytest.raises(ProvenanceError, match="invalid_volume_requirement"):
        ServerRecreationService._volume_requirements(manifest(), "researcher")
