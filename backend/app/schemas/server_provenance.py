# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Public verified-launch history and explicit, approved recreation selections."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.environment_manifest import (
    EnvironmentManifest,
    ImageIdentity,
    VolumeRequirement,
    canonical_json,
)
from app.schemas.server_launch import NormalizedVolumeMount


class ServerProvenanceResponse(BaseModel):
    state: Literal["recorded", "unrecorded"]
    launch_id: UUID | None = None
    generation: int | None = None
    captured_at: datetime | None = None
    manifest: EnvironmentManifest | None = None
    actual_runtime: ImageIdentity | None = None
    actual_toolchain: ImageIdentity | None = None
    can_recreate: bool = False
    recreation_reason_code: str | None = None


class RecreationSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_launch_id: UUID | None = None
    manifest: EnvironmentManifest | None = None

    @field_validator("manifest", mode="before")
    @classmethod
    def parse_manifest_json(cls, value):
        if value is None:
            return None
        if isinstance(value, EnvironmentManifest):
            value = value.model_dump(mode="json")
        if not isinstance(value, dict):
            raise ValueError("Manifest must be a JSON object")
        try:
            return EnvironmentManifest.parse_import(canonical_json(value))
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise ValueError("Invalid or oversized environment manifest") from None

    @model_validator(mode="after")
    def one_source(self):
        if (self.source_launch_id is None) == (self.manifest is None):
            raise ValueError("Select exactly one source launch or environment manifest")
        return self


class ServerRecreateRequest(RecreationSource):
    name: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")]
    plan_id: UUID
    volume_mounts: Annotated[list[NormalizedVolumeMount], Field(min_length=1, max_length=32)]


class RecreationPreviewResponse(BaseModel):
    manifest: EnvironmentManifest
    environment_label: str
    volume_requirements: Annotated[list[VolumeRequirement], Field(max_length=32)]
