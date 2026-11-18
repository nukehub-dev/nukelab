# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class VolumeBackup(Base):
    __tablename__ = "volume_backups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    volume_name = Column(String(255), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    source_volume_id = Column(
        UUID(as_uuid=True), ForeignKey("volumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_display_name = Column(String(255), nullable=True)
    source_metadata = Column(JSONB, nullable=True)
    format_version = Column(String(50), nullable=True)
    sha256 = Column(String(64), nullable=True)
    logical_bytes = Column(BigInteger, nullable=True)
    member_count = Column(Integer, nullable=True)
    max_logical_bytes = Column(BigInteger, nullable=True)
    reserved_bytes = Column(BigInteger, nullable=False, default=0)
    fencing_token = Column(UUID(as_uuid=True), nullable=True)
    helper_identity = Column(String(255), nullable=True)
    reason_code = Column(String(50), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    backup_path = Column(String(500), nullable=True)
    status = Column(String(50), default="pending")
    error_message = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<VolumeBackup {self.id}: {self.volume_name}>"
