# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Immutable action intent and fenced executor state for a stable server identity."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, event, inspect, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class ServerLaunchOperation(Base):
    __tablename__ = "server_launch_operations"
    __table_args__ = (
        Index(
            "uq_server_launch_operations_active",
            "server_id",
            unique=True,
            postgresql_where=text("state IN ('prepared', 'executing', 'uncertain')"),
        ),
        Index(
            "ix_server_launch_operations_recovery_scan",
            text("COALESCE(heartbeat_at, created_at)"),
            "id",
            postgresql_where=text("state IN ('prepared', 'executing', 'uncertain')"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    action = Column(String(20), nullable=False)
    state = Column(String(20), nullable=False, default="prepared")
    fencing_token = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    executor_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime, nullable=True)
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("environment_revisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    request_payload = Column(JSONB, nullable=True)
    mounts = Column(JSONB, nullable=False)
    previous_mounts = Column(JSONB, nullable=False, default=list)
    gpu_devices = Column(JSONB, nullable=False)
    username = Column(String(255), nullable=False)
    environment_slug = Column(String(255), nullable=True)
    resources = Column(JSONB, nullable=False)
    generation = Column(Integer, nullable=True)
    previous_container_id = Column(String(255), nullable=True)
    previous_status = Column(String(50), nullable=True)
    reason_code = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)
    finished_at = Column(DateTime, nullable=True)


@event.listens_for(ServerLaunchOperation, "before_update")
def _immutable_operation(mapper, connection, target):
    mutable = {
        "state",
        "reason_code",
        "updated_at",
        "finished_at",
        "executor_id",
        "heartbeat_at",
    }
    if any(attr.history.has_changes() for attr in inspect(target).attrs if attr.key not in mutable):
        raise ValueError("Server operation intent is immutable")
