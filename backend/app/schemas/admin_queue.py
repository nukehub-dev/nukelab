# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Sanitized read-only admin queue views.

Response models carry only bounded queue metadata. Persisted launch payloads,
claim tokens, request versions, plan snapshots, environment values, mounts,
volume identifiers, and raw failure text never appear here.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AdminQueueEntry(BaseModel):
    """One queue request as seen by an operator."""

    id: UUID
    owner_id: UUID
    server_id: UUID | None = None
    server_name: str
    environment_id: UUID
    plan_id: UUID
    status: str
    reason_code: str | None = None
    position: int | None = Field(default=None, ge=1)
    priority: int = 0
    requested_at: datetime | None = None
    started_at: datetime | None = None
    failed_at: datetime | None = None
    expires_at: datetime | None = None


class AdminQueuePagination(BaseModel):
    limit: int
    offset: int
    total: int
    has_more: bool


class AdminQueuePage(BaseModel):
    items: list[AdminQueueEntry]
    pagination: AdminQueuePagination
