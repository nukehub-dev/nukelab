# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class VolumeOperation(Base):
    """Durable exclusion, retained until executor termination is proven."""

    __tablename__ = "volume_operations"
    operation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    volume_id = Column(
        UUID(as_uuid=True), ForeignKey("volumes.id", ondelete="RESTRICT"), primary_key=True
    )
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind = Column(String(20), nullable=False)  # writer, mount, backup, restore
    state = Column(String(30), nullable=False, default="reserved")
    fencing_token = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    helper_identity = Column(String(255), nullable=True)
    reason_code = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_volume_operations_active", "volume_id", "state"),
        Index(
            "uq_volume_operations_exclusive",
            "volume_id",
            unique=True,
            postgresql_where=text(
                "kind IN ('backup', 'restore') "
                "AND state IN ('reserved', 'running', 'recovery_required')"
            ),
        ),
    )
