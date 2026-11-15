# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.environment_manifest import EnvironmentManifest, ImageIdentity, ManifestResources
from app.services.environment_revision_service import (
    ConfigurationChanged,
    EnvironmentRevisionService,
    RevisionUnavailable,
    fingerprint,
    template_configuration,
)
from app.services.server_provenance_service import ServerProvenanceService, build_manifest


def image(**changes):
    return ImageIdentity(
        **{
            "requested_reference": "workspace:latest",
            "local_id": "sha256:" + "a" * 64,
            "repository_digests": ["registry/workspace@sha256:" + "b" * 64],
            "os": "linux",
            "architecture": "amd64",
            **changes,
        }
    )


def revision():
    return SimpleNamespace(
        id=uuid4(),
        fingerprint="c" * 64,
        runtime_identity=image().model_dump(mode="json"),
        toolchain_identity=None,
        configuration={"tool_mounts": [], "environment_variables": {"TOKEN": "secret-value"}},
    )


def manifest(rev=None):
    return build_manifest(
        rev or revision(),
        template_label="Workspace",
        resources=ManifestResources(
            cpu=1.0,
            memory_mib=2048,
            disk_mib=10240,
        ),
    )


def session_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def test_local_repository_metadata_is_not_portability_proof():
    identity = image()
    assert identity.spawn_reference == identity.local_id
    exported = manifest()
    assert exported.portability == "local_only"
    assert "secret-value" not in exported.model_dump_json()
    assert exported.environment_variable_names == ["TOKEN"]


def test_manifest_round_trip_and_names_only():
    exported = manifest()
    assert EnvironmentManifest.parse_import(exported.model_dump_json()) == exported


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "nukelab.environment/v2"},
        {"environment_variables": {"TOKEN": "stolen"}},
        {"privileged": True},
        {"runtime": {"image": "attacker"}},
        {"toolchain_mounts": ["/opt/../etc"]},
        {"portability": "registry_verified"},
        {
            "volume_requirements": [
                {"purpose": "data", "mount_path": "../../etc", "mode": "read_write"}
            ]
        },
        {"environment_variable_names": ["TOKEN=secret"]},
        {"resources": {"cpu": 1, "memory_mib": -1, "disk_mib": 1}},
    ],
)
def test_untrusted_manifest_rejects_unsafe_or_unknown_fields(changes):
    payload = manifest().model_dump(mode="json") | changes
    with pytest.raises(ValidationError):
        EnvironmentManifest.parse_import(json.dumps(payload))


def test_manifest_input_size_is_bounded():
    with pytest.raises(ValueError, match="size limit"):
        EnvironmentManifest.parse_import(b" " * 65537)


@pytest.mark.parametrize(
    "reference",
    ["https://user:secret@registry/image", "user:secret@registry/image", "image\nsecret"],
)
def test_image_credentials_cannot_escape_into_manifest(reference):
    with pytest.raises(ValidationError):
        image(requested_reference=reference)


def test_verified_identity_requires_a_pinned_reference():
    with pytest.raises(ValidationError):
        image(registry_verified=True, verified_reference="workspace:latest")
    verified = image(
        registry_verified=True, verified_reference="registry/workspace@sha256:" + "b" * 64
    )
    assert verified.spawn_reference == verified.verified_reference


def test_configuration_fingerprint_is_order_independent_and_sensitive():
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})
    assert fingerprint({"a": 1}) != fingerprint({"a": 2})


@pytest.mark.asyncio
async def test_recreation_only_returns_existing_approval_and_checks_identity():
    rev = revision()
    revisions = SimpleNamespace(require_available=AsyncMock(return_value=rev))
    service = ServerProvenanceService(MagicMock(), revisions)
    exported = manifest(rev)
    assert await service.validate_recreation(exported.model_dump_json()) is rev
    payload = exported.model_dump(mode="json")
    payload["runtime"]["local_id"] = "sha256:" + "d" * 64
    with pytest.raises(RevisionUnavailable):
        await service.validate_recreation(json.dumps(payload))


@pytest.mark.asyncio
async def test_revoked_revision_is_not_importable():
    revisions = SimpleNamespace(require_available=AsyncMock(side_effect=RevisionUnavailable()))
    service = ServerProvenanceService(MagicMock(), revisions)
    with pytest.raises(RevisionUnavailable):
        await service.validate_recreation(manifest().model_dump_json())


@pytest.mark.asyncio
async def test_unknown_legacy_provenance_is_explicit():
    db = MagicMock(execute=AsyncMock(return_value=session_result(None)))
    service = ServerProvenanceService(db, MagicMock())
    assert await service.latest_owned(uuid4(), uuid4()) == {"state": "unrecorded", "manifest": None}


@pytest.mark.asyncio
async def test_capture_rechecks_configuration_after_resolution_before_write():
    template = SimpleNamespace(
        id=uuid4(),
        is_active=True,
        image="workspace:latest",
        tool_image=None,
        tool_mounts=[],
        environment_variables={"A": "new"},
        packages=[],
        volumes=[],
        ports=[],
    )
    authorize = AsyncMock()
    db = MagicMock(execute=AsyncMock(return_value=session_result(template)), flush=AsyncMock())
    service = EnvironmentRevisionService(db, authorize)
    with pytest.raises(ConfigurationChanged):
        await service.capture(template.id, expected_template_fingerprint="0" * 64, runtime=image())
    authorize.assert_awaited_once_with(template)
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_capture_never_approves_artifact_outside_template():
    template = SimpleNamespace(
        id=uuid4(),
        is_active=True,
        image="workspace:latest",
        tool_image=None,
        tool_mounts=[],
        environment_variables={},
        packages=[],
        volumes=[],
        ports=[],
    )
    db = MagicMock(execute=AsyncMock(return_value=session_result(template)), flush=AsyncMock())
    service = EnvironmentRevisionService(db, AsyncMock())
    with pytest.raises(ConfigurationChanged):
        await service.capture(
            template.id,
            expected_template_fingerprint=fingerprint(template_configuration(template)),
            runtime=image(requested_reference="attacker:latest"),
        )
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_observed_identity_mismatch_cannot_be_recorded():
    rev = revision()
    service = ServerProvenanceService(
        MagicMock(), SimpleNamespace(require_available=AsyncMock(return_value=rev))
    )
    with pytest.raises(RevisionUnavailable):
        await service.record_launch(
            operation_id=uuid4(),
            server_id=uuid4(),
            owner_id=uuid4(),
            generation=1,
            manifest=manifest(rev),
            actual_runtime=image(local_id="sha256:" + "d" * 64),
            actual_toolchain=None,
        )
    service.db.add.assert_not_called()
