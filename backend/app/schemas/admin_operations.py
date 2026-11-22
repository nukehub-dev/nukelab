# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Sanitized admin operation views and proof-only reconciliation requests.

Response models deliberately carry only durable, bounded metadata. Request
payloads, mounts, environment values, runtime identities/paths, tokens, and raw
inspection payloads never appear here.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

AdminOperationKind = Literal["launch", "backup", "restore"]
AdminOperationTargetType = Literal["server", "volume"]
AdminLiveness = Literal["alive", "stopped", "ambiguous"]
AdminRuntimeState = Literal["present", "absent", "ambiguous"]
AdminTerminalState = Literal["succeeded", "failed", "recovery_required"]

REASON_MAX_LENGTH = 255


class AdminOperationPagination(BaseModel):
    limit: int
    offset: int
    total: int
    has_more: bool


class AdminOperation(BaseModel):
    """One operation row with sanitized diagnostics."""

    kind: AdminOperationKind
    id: UUID
    state: str
    action: str | None = None
    owner_id: UUID | None = None
    owner_username: str | None = None
    target_type: AdminOperationTargetType | None = None
    target_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    reason_code: str | None = None
    evidence_reason_code: str | None = None
    recovery_required: bool = False
    heartbeat_age_seconds: int | None = None
    liveness: AdminLiveness | None = None
    proof_source: str | None = None
    runtime_state: AdminRuntimeState | None = None
    diagnostics: dict[str, str] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)


class AdminOperationPage(BaseModel):
    items: list[AdminOperation]
    pagination: AdminOperationPagination


class AdminOperationReconcileRequest(BaseModel):
    """Reconcile input: a bounded operator reason only.

    ``extra="forbid"`` rejects force/override fields and any other unknown
    input with 422 before the handler runs.
    """

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


class AdminOperationReconcileResult(AdminOperation):
    previous_state: str
    applied: bool
    terminal_state: AdminTerminalState | None = None
