# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Durable single-run batch job intent, journal and bounded log payload."""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.time_utils import utc_now
from app.db.base import Base

ACTIVE_JOB_STATES = ("queued", "starting", "running", "cancelling", "recovery_required")
TERMINAL_JOB_STATES = ("succeeded", "failed", "cancelled", "timed_out", "expired")


class BatchJob(Base):
    """One owner-scoped noninteractive request and its execution journal."""

    __tablename__ = "batch_jobs"
    __table_args__ = (
        Index(
            "uq_batch_jobs_owner_idempotency",
            "user_id",
            "idempotency_key_hash",
            unique=True,
        ),
        Index("ix_batch_jobs_owner_history", "user_id", "created_at", "id"),
        Index(
            "ix_batch_jobs_pending_dispatch",
            "created_at",
            "id",
            postgresql_where=sql_text("state = 'queued'"),
        ),
        Index(
            "ix_batch_jobs_queued_expiry",
            "queue_expires_at",
            "id",
            postgresql_where=sql_text("state = 'queued'"),
        ),
        Index(
            "ix_batch_jobs_active_recovery",
            "state",
            "heartbeat_at",
            "id",
            postgresql_where=sql_text(
                "state IN ('starting', 'running', 'cancelling', 'recovery_required')"
            ),
        ),
        Index(
            "ix_batch_jobs_unreleased_reservations",
            "reserved_at",
            "id",
            postgresql_where=sql_text("reservation_active = true"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(120), nullable=False)
    idempotency_key_hash = Column(String(64), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)

    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("environment_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("server_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    volume_id = Column(
        UUID(as_uuid=True),
        ForeignKey("volumes.id", ondelete="SET NULL"),
        nullable=True,
    )

    argv = Column(JSONB, nullable=False)
    max_runtime_seconds = Column(Integer, nullable=False)

    # Public state plus the sanitized wait/proof reason.
    state = Column(String(30), nullable=False, default="queued")
    reason_code = Column(String(64), nullable=True)
    state_changed_at = Column(DateTime, nullable=False, default=utc_now)

    # Queue and execution checkpoints. Naive UTC.
    queue_expires_at = Column(DateTime, nullable=True)
    reserved_at = Column(DateTime, nullable=True)
    create_requested_at = Column(DateTime, nullable=True)
    start_requested_at = Column(DateTime, nullable=True)
    start_observed_at = Column(DateTime, nullable=True)
    deadline_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    stop_requested_at = Column(DateTime, nullable=True)

    # Immutable submission snapshots. Never expose configuration/environment values.
    revision_snapshot = Column(JSONB, nullable=False)
    plan_snapshot = Column(JSONB, nullable=False)
    volume_snapshot = Column(JSONB, nullable=False)

    # Reservation/volume exclusion retained until runtime termination is proven.
    reservation_active = Column(Boolean, nullable=False, default=False, server_default="false")
    volume_operation_id = Column(UUID(as_uuid=True), nullable=True)
    reserved_cpu = Column(Float, nullable=True)
    reserved_memory_mib = Column(Integer, nullable=True)
    reserved_disk_mib = Column(Integer, nullable=True)
    volume_fencing_token = Column(UUID(as_uuid=True), nullable=True)

    # Separately idempotent container cleanup after the terminal result is durable.
    cleanup_state = Column(String(20), nullable=False, default="pending", server_default="pending")
    cleanup_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_cleanup_at = Column(DateTime, nullable=True)

    # Observed runtime identity and fenced executor liveness.
    container_id = Column(String(255), nullable=True)
    container_name = Column(String(255), nullable=True)
    runtime_identity = Column(JSONB, nullable=True)
    executor_id = Column(UUID(as_uuid=True), nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    fencing_token = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)

    # Immutable terminal result written with the first terminal transition.
    exit_code = Column(Integer, nullable=True)
    outcome_code = Column(String(30), nullable=True)
    proof_class = Column(String(30), nullable=True)
    result_recorded_at = Column(DateTime, nullable=True)

    # Bounded log metadata; payload lives in batch_job_logs.
    log_state = Column(String(20), nullable=False, default="pending", server_default="pending")
    log_truncated = Column(Boolean, nullable=False, default=False, server_default="false")
    log_size_bytes = Column(Integer, nullable=False, default=0, server_default="0")
    log_expires_at = Column(DateTime, nullable=True)

    # Zero-cost pilot by default; paid fields stay ready for a proven settlement contract.
    billing_mode = Column(
        String(20), nullable=False, default="zero_cost", server_default="zero_cost"
    )
    charged_credits = Column(Integer, nullable=False, default=0, server_default="0")
    billing_transaction_id = Column(UUID(as_uuid=True), nullable=True)

    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class BatchJobLog(Base):
    """One byte-bounded retained log tail per job; payload-free row when purged."""

    __tablename__ = "batch_job_logs"
    __table_args__ = (Index("ix_batch_job_logs_expires_at", "expires_at"),)

    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("batch_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    text = Column(Text, nullable=False)
    encoding = Column(String(20), nullable=False, default="utf-8", server_default="utf-8")
    truncated = Column(Boolean, nullable=False, default=False, server_default="false")
    size_bytes = Column(Integer, nullable=False, default=0, server_default="0")
    captured_at = Column(DateTime, nullable=False, default=utc_now)
    expires_at = Column(DateTime, nullable=True)
