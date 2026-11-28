# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Sanitized admin batch-job views and bounded operator action requests.

Response models carry only bounded job metadata. Command arguments, log text,
environment values, secret references, image references, volume paths, runtime
identities, fencing tokens, executors, and raw daemon payloads never appear
here.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

AdminJobListState = Literal["active", "history", "all"]
AdminJobReconcileOutcome = Literal["applied", "already_terminal", "no_change"]
AdminJobCancelOutcome = Literal[
    "cancelled",
    "cancellation_requested",
    "already_cancelling",
    "already_terminal",
]

REASON_MIN_LENGTH = 8
REASON_MAX_LENGTH = 500


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
    # True only for an active recovery_required row when the caller may reconcile.
    can_reconcile: bool = False
    # True only for queued/starting/running rows when the caller may cancel.
    can_cancel: bool = False


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


class AdminJobReconcileRequest(BaseModel):
    """Reconcile input: a bounded operator reason only.

    ``extra="forbid"`` rejects force/override fields and any other unknown
    input with 422 before the handler runs.
    """

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(min_length=REASON_MIN_LENGTH, max_length=REASON_MAX_LENGTH)]

    @field_validator("reason")
    @classmethod
    def _bounded_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < REASON_MIN_LENGTH:
            raise ValueError(f"reason must be at least {REASON_MIN_LENGTH} characters")
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
            raise ValueError("reason must not contain control characters")
        return value


class AdminJobReconcileResult(BaseModel):
    """Proof-only reconcile outcome with the current sanitized job row."""

    job: AdminJobEntry
    applied: bool
    already_terminal: bool
    outcome: AdminJobReconcileOutcome
    terminal_state: str | None = None
    proof_source: str | None = None
    reason_code: str | None = None


class AdminJobCancelRequest(AdminJobReconcileRequest):
    """Cancel input: a bounded operator reason only.

    Inherits ``extra="forbid"``, so force/release/override fields are rejected
    with 422 before the handler runs.
    """


class AdminJobCancelResult(BaseModel):
    """Control-plane cancellation outcome with the current sanitized job row.

    ``applied`` is true only when a state transition occurred. A running job
    reports ``cancellation_requested`` and keeps its reservation and volume
    guard until runtime proof confirms termination.
    """

    job: AdminJobEntry
    applied: bool
    already_terminal: bool
    outcome: AdminJobCancelOutcome
    previous_state: str | None = None
