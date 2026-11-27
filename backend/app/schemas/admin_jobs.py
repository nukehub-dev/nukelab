# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Sanitized read-only admin batch-job views.

Response models carry only bounded job metadata. Command arguments, log text,
environment values, secret references, image references, volume paths, runtime
identities, fencing tokens, executors, and raw daemon payloads never appear
here.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

AdminJobListState = Literal["active", "history", "all"]


class AdminJobEntry(BaseModel):
    """One batch job as seen by an operator."""

    id: UUID
    state: str
    reason_code: str | None = None
    owner_id: UUID
    owner_username: str | None = None
    owner_display_name: str | None = None
    environment_name: str | None = None
    environment_display_label: str | None = None
    plan_name: str | None = None
    volume_display_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    reservation_active: bool = False
    guard_active: bool = False
    heartbeat_age_seconds: int | None = None
    log_state: str
    cleanup_state: str
    cleanup_attempts: int = 0
    # No runtime finalizer exists for jobs in this release, so there is no
    # manual reconcile or reservation-release path.
    can_reconcile: bool = False


class AdminJobPagination(BaseModel):
    limit: int
    offset: int
    total: int
    has_more: bool


class AdminJobSummary(BaseModel):
    """Age-filtered state counts that remain stable under the state chip."""

    total: int
    queued: int
    starting: int
    running: int
    cancelling: int
    recovery_required: int
    succeeded: int
    failed: int
    cancelled: int
    timed_out: int
    expired: int


class AdminJobPage(BaseModel):
    items: list[AdminJobEntry]
    pagination: AdminJobPagination
    summary: AdminJobSummary
