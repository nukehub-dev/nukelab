# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Public queue metadata; persisted launch payloads are never serialized directly."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

QueueStatus = Literal["pending", "scheduled", "starting", "started", "failed", "cancelled"]


class QueueResources(BaseModel):
    cpu: float
    memory_mib: int
    disk_mib: int
    gpu_count: int = 0


class QueueRequestSummary(BaseModel):
    name: str
    plan_id: UUID
    environment_id: UUID
    resources: QueueResources


class QueueEntryResponse(BaseModel):
    id: UUID
    request: QueueRequestSummary
    status: QueueStatus
    position: int | None = Field(default=None, ge=1)
    reason_code: str | None = None
    message: str
    requested_at: datetime
    expires_at: datetime | None = None
    started_at: datetime | None = None
    server_id: UUID | None = None
    can_cancel: bool


class QueuePageResponse(BaseModel):
    items: list[QueueEntryResponse]
    total: int
    page: int
    page_size: int


class QueuedServerResponse(BaseModel):
    queued: Literal[True] = True
    queue_id: UUID
    queue_position: int | None = Field(default=None, ge=1)
    message: str
    request: QueueRequestSummary
