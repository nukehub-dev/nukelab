# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Stable restore identity and quota/artifact pin for a new private destination."""

import uuid

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class VolumeRestore(Base):
    __tablename__ = "volume_restores"
    __table_args__ = (
        Index(
            "ix_volume_restores_recovery_scan",
            text("COALESCE(heartbeat_at, created_at)"),
            "id",
            postgresql_where=text("status IN ('pending', 'in_progress', 'recovery_required')"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    backup_id = Column(
        UUID(as_uuid=True),
        ForeignKey("volume_backups.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    destination_volume_id = Column(
        UUID(as_uuid=True), ForeignKey("volumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    destination_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    max_size_bytes = Column(BigInteger, nullable=False)
    reserved_bytes = Column(BigInteger, nullable=False, default=0)
    status = Column(String(30), nullable=False, default="pending")
    fencing_token = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    executor_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime, nullable=True)
    helper_identity = Column(String(255), nullable=True)
    reason_code = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    completed_at = Column(DateTime, nullable=True)
