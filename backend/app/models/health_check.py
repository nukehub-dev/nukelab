# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class HealthCheck(Base):
    __tablename__ = "health_checks"
    __table_args__ = (
        Index("ix_health_checks_checked_at", "checked_at"),
        Index("ix_health_checks_server_checked_at", "server_id", "checked_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    container_id = Column(String(255), nullable=False)

    status = Column(String(50), nullable=False)
    exit_code = Column(Integer)
    output = Column(Text)

    consecutive_failures = Column(Integer, default=0)
    last_success_at = Column(DateTime)

    checked_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        return {
            "id": str(self.id),
            "server_id": str(self.server_id),
            "container_id": self.container_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "output": self.output,
            "consecutive_failures": self.consecutive_failures,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }
