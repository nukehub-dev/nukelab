# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Owner-only recovery metadata: artifact locations and runtime identities stay private."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

BackupStatus = Literal[
    "pending",
    "in_progress",
    "completed",
    "failed",
    "recovery_required",
    "deleting",
    "delete_failed",
    "deleted",
]
RestoreStatus = Literal["pending", "in_progress", "completed", "failed", "recovery_required"]


class RecoveryCapability(BaseModel):
    enabled: bool
    reason_code: str | None = None
    message: str


class BackupEligibility(BaseModel):
    eligible: bool
    reason_code: str | None = None
    message: str


class BackupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID | None = None
    description: Annotated[str, Field(max_length=255)] | None = None


class RestoreCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID | None = None
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    max_size_bytes: Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


class VolumeBackupResponse(BaseModel):
    id: UUID
    source_volume_id: UUID | None = None
    source_display_name: str
    status: BackupStatus
    reason_code: str | None = None
    message: str
    description: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    compressed_bytes: int | None = None
    logical_bytes: int | None = None
    member_count: int | None = None
    can_restore: bool
    can_delete: bool


class VolumeRestoreResponse(BaseModel):
    id: UUID
    backup_id: UUID
    status: RestoreStatus
    reason_code: str | None = None
    message: str
    destination_volume_id: UUID | None = None
    destination_display_name: str
    created_at: datetime
    completed_at: datetime | None = None


class VolumeBackupPage(BaseModel):
    items: list[VolumeBackupResponse]
    total: int
    page: int
    page_size: int


class VolumeRestorePage(BaseModel):
    items: list[VolumeRestoreResponse]
    total: int
    page: int
    page_size: int
