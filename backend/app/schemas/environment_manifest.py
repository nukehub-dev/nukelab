# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded public environment manifests; never contain raw container configuration."""

import json
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

ShortText = Annotated[str, Field(min_length=1, max_length=500)]
Fingerprint = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
_PLATFORM_VARIANT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ImageIdentity(ManifestModel):
    requested_reference: ShortText
    local_id: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    repository_digests: Annotated[list[ShortText], Field(max_length=32)] = []
    os: Annotated[str, Field(min_length=1, max_length=32)]
    architecture: Annotated[str, Field(min_length=1, max_length=32)]
    registry_verified: bool = False
    verified_reference: ShortText | None = None
    manifest_digest: ShortText | None = None
    index_digest: ShortText | None = None
    descriptor_media_type: ShortText | None = None
    variant: ShortText | None = None

    @field_validator("variant")
    @classmethod
    def safe_variant(cls, value):
        if value is not None:
            value = value.lower()
            if not _PLATFORM_VARIANT_RE.fullmatch(value):
                raise ValueError("Invalid OCI platform variant")
        return value

    @model_serializer(mode="wrap")
    def _omit_null_variant(self, handler):
        data = handler(self)
        if isinstance(data, dict) and data.get("variant") is None:
            data.pop("variant", None)
        return data

    @field_validator("requested_reference", "verified_reference")
    @classmethod
    def reject_credentials(cls, value):
        if value is not None and (
            "://" in value
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*(?:@sha256:[a-f0-9]{64})?", value)
        ):
            raise ValueError("Image references must not contain credentials or URLs")
        return value

    @field_validator("repository_digests")
    @classmethod
    def safe_repository_digests(cls, values):
        for value in values:
            cls.reject_credentials(value)
        return values

    @model_validator(mode="after")
    def verified_artifact(self):
        if self.registry_verified:
            reference = self.verified_reference or ""
            digest = reference.rsplit("@", 1)[-1]
            if "@" not in reference or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise ValueError("Registry verification requires a pinned repository reference")
        elif self.verified_reference is not None:
            raise ValueError("An unverified image cannot advertise a verified reference")
        return self

    @property
    def spawn_reference(self) -> str:
        return self.verified_reference if self.registry_verified else self.local_id


class ManifestResources(ManifestModel):
    cpu: Annotated[float, Field(gt=0, le=100000, allow_inf_nan=False)]
    memory_mib: Annotated[int, Field(gt=0, le=2**50)]
    disk_mib: Annotated[int, Field(gt=0, le=2**50)]
    gpu_count: Annotated[int, Field(ge=0, le=10000)] = 0


class VolumeRequirement(ManifestModel):
    purpose: Annotated[str, Field(min_length=1, max_length=100)]
    mount_path: ShortText
    mode: Literal["read_only", "read_write"]

    @field_validator("mount_path")
    @classmethod
    def safe_path(cls, value):
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts or "\x00" in value:
            raise ValueError("Invalid container mount path")
        return value


class EnvironmentManifest(ManifestModel):
    schema_version: Literal["nukelab.environment/v1"] = "nukelab.environment/v1"
    revision_id: UUID
    revision_fingerprint: Fingerprint
    portable_fingerprint: Fingerprint | None = None
    template_label: Annotated[str, Field(min_length=1, max_length=255)]
    runtime: ImageIdentity
    toolchain: ImageIdentity | None = None
    toolchain_mounts: Annotated[list[ShortText], Field(max_length=32)] = []
    environment_variable_names: Annotated[
        list[Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")]],
        Field(max_length=256),
    ] = []
    environment_values: Literal["manual_input_required"] = "manual_input_required"
    resources: ManifestResources
    volume_requirements: Annotated[list[VolumeRequirement], Field(max_length=32)] = []
    portability: Literal["local_only", "registry_verified"]
    limitations: Annotated[list[ShortText], Field(max_length=32)] = []

    @field_validator("toolchain_mounts")
    @classmethod
    def safe_toolchain_paths(cls, values):
        return [VolumeRequirement.safe_path(value) for value in values]

    @model_validator(mode="after")
    def truthful_portability(self):
        if self.portability == "registry_verified":
            if self.portable_fingerprint is None:
                raise ValueError("Registry-verified manifests require a portable fingerprint")
            if not all(
                image.registry_verified for image in (self.runtime, self.toolchain) if image
            ):
                raise ValueError("Unverified artifacts cannot be portable")
        elif self.portable_fingerprint is not None:
            raise ValueError("Local-only manifests cannot advertise a portable fingerprint")
        return self

    @model_serializer(mode="wrap")
    def _omit_null_portable_fingerprint(self, handler):
        data = handler(self)
        if isinstance(data, dict) and data.get("portable_fingerprint") is None:
            data.pop("portable_fingerprint", None)
        return data

    @classmethod
    def parse_import(cls, raw: bytes | str):
        if len(raw.encode() if isinstance(raw, str) else raw) > 65536:
            raise ValueError("Manifest exceeds size limit")
        # Validate JSON directly so UUID strings retain their JSON representation semantics.
        return cls.model_validate_json(raw)

    def canonical_environment(self) -> dict:
        """Fields that must match server-owned approval; resources grant no entitlement."""
        data = self.model_dump(mode="json")
        return {
            key: data[key]
            for key in (
                "revision_id",
                "revision_fingerprint",
                "runtime",
                "toolchain",
                "toolchain_mounts",
                "environment_variable_names",
            )
        }


def canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
