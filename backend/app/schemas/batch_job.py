# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Public batch job DTOs. Snapshots never expose raw configuration or environment values."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

JobState = Literal[
    "queued",
    "starting",
    "running",
    "cancelling",
    "recovery_required",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "expired",
]
JobListState = Literal["active", "history", "all"]
JobOutcome = Literal[
    "succeeded", "failed", "cancelled", "timed_out", "expired", "runtime_unverifiable"
]
BillingMode = Literal["zero_cost", "paid"]
JobLogState = Literal["pending", "available", "truncated", "unavailable", "expired"]


class JobLimits(BaseModel):
    max_active_jobs: int
    max_queued_jobs: int
    default_runtime_seconds: int
    max_runtime_seconds: int
    queue_ttl_seconds: int
    max_argv_items: int
    max_input_bytes: int
    log_tail_bytes: int
    log_retention_seconds: int


class JobCapabilitiesResponse(BaseModel):
    enabled: bool
    can_submit: bool
    billing_mode: BillingMode
    secrets_enabled: bool = False
    storage_limits_enforced: bool
    storage_enforcement_required: bool
    reason_code: str | None = None
    limits: JobLimits


class EligibleRevision(BaseModel):
    revision_id: UUID
    environment_id: UUID
    environment_name: str
    display_label: str
    fingerprint: str
    portable_fingerprint: str | None = None
    image_reference: str | None = None
    supports_jobs: bool = True
    reason_code: str | None = None


class EligibleRevisionsResponse(BaseModel):
    items: list[EligibleRevision]


class BatchJobSubmitRequest(BaseModel):
    name: str
    revision_id: UUID
    plan_id: UUID
    volume_id: UUID
    argv: list[str]
    max_runtime_seconds: int | None = None


class JobEnvironmentSummary(BaseModel):
    revision_id: UUID
    environment_id: UUID
    name: str
    display_label: str
    fingerprint: str
    image_reference: str | None = None


class JobPlanSummary(BaseModel):
    id: UUID
    name: str
    cpu: float
    memory_mib: int
    disk_mib: int
    gpu_count: int
    cost_per_hour: int


class JobVolumeSummary(BaseModel):
    id: UUID
    display_name: str
    available: bool


class JobRuntimeLimits(BaseModel):
    max_runtime_seconds: int


class JobResult(BaseModel):
    exit_code: int | None = None
    outcome_code: JobOutcome
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: int | None = None
    proof: str | None = None


class JobLogSummary(BaseModel):
    state: JobLogState
    truncated: bool
    size_bytes: int
    expires_at: datetime | None = None


class JobBilling(BaseModel):
    mode: BillingMode
    charged: int = 0
    authorized: int = 0
    rate_per_hour: int = 0
    state: str = "none"


class BatchJobSummary(BaseModel):
    id: UUID
    name: str
    state: JobState
    reason_code: str | None = None
    environment_name: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    can_cancel: bool


class BatchJobListResponse(BaseModel):
    items: list[BatchJobSummary]
    next_cursor: str | None = None


class BatchJobDetail(BaseModel):
    id: UUID
    name: str
    state: JobState
    reason_code: str | None = None
    reason_message: str | None = None
    created_at: datetime
    updated_at: datetime
    queue_expires_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    deadline_at: datetime | None = None
    can_cancel: bool
    replayed: bool = False
    environment: JobEnvironmentSummary
    plan: JobPlanSummary
    volume: JobVolumeSummary
    argv: list[str]
    limits: JobRuntimeLimits
    result: JobResult | None = None
    logs: JobLogSummary
    billing: JobBilling


class JobLogsResponse(BaseModel):
    state: JobLogState
    text: str | None = None
    truncated: bool = False
    size_bytes: int = 0
    expires_at: datetime | None = None
    encoding: str | None = None
