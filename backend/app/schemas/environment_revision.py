# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Sanitized environment revision views and bounded admin actions.

Response models carry only durable metadata and normalized configuration names.
Environment-variable values, host paths, local image IDs, repository digest
lists, and raw runtime inspection payloads never appear here.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

REASON_MAX_LENGTH = 255


class EnvironmentRevisionActionRequest(BaseModel):
    """Bounded action input; unknown override fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(min_length=1, max_length=REASON_MAX_LENGTH)]

    @field_validator("reason")
    @classmethod
    def _bounded_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("reason must not contain control characters")
        return value


class VerifyArtifactsRequest(EnvironmentRevisionActionRequest):
    """Explicit admin verification of the template's current artifacts."""


class RevokeRevisionRequest(EnvironmentRevisionActionRequest):
    """Revoke one revision; the last selectable revision needs confirmation."""

    confirm_last_revision: bool = Field(default=False, strict=True)


class RevisionImageSummary(BaseModel):
    """Verified identity fields only; never local IDs or repository digests."""

    registry_verified: bool = False
    os: str | None = None
    architecture: str | None = None
    variant: str | None = None
    verified_reference: str | None = None
    manifest_digest: str | None = None
    index_digest: str | None = None
    descriptor_media_type: str | None = None


class RevisionVolumeSummary(BaseModel):
    """Template-declared container destination and mode; never a host path."""

    mount_path: str
    mode: Literal["read_only", "read_write"]


class RevisionConfigurationSummary(BaseModel):
    """Normalized configuration names; environment values are excluded."""

    image: str | None = None
    tool_image: str | None = None
    packages: list[str] = Field(default_factory=list)
    ports: list[str] = Field(default_factory=list)
    tool_mounts: list[str] = Field(default_factory=list)
    environment_variable_names: list[str] = Field(default_factory=list)
    volumes: list[RevisionVolumeSummary] = Field(default_factory=list)


class EnvironmentRevisionSummary(BaseModel):
    """One immutable revision row reduced to a safe admin view."""

    id: UUID
    template_id: UUID
    fingerprint: str
    portable_fingerprint: str | None = None
    portability: Literal["registry_verified", "local_only"]
    revoked: bool
    created_at: datetime | None = None
    runtime: RevisionImageSummary
    toolchain: RevisionImageSummary | None = None
    configuration: RevisionConfigurationSummary
    limitations: list[str] = Field(default_factory=list)


class EnvironmentRevisionPagination(BaseModel):
    limit: int
    offset: int
    total: int
    has_more: bool


class EnvironmentRevisionPage(BaseModel):
    items: list[EnvironmentRevisionSummary]
    pagination: EnvironmentRevisionPagination


class VerifyArtifactsResponse(BaseModel):
    success: Literal[True] = True
    data: EnvironmentRevisionSummary


class RevokeRevisionResponse(BaseModel):
    success: Literal[True] = True
    data: EnvironmentRevisionSummary
    template_has_selectable_revision: bool
    selectable_revision_count: int
    already_revoked: bool = False
