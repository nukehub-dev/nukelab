"""IP restriction model for allowlist/blocklist."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class IPRestriction(Base):
    """IP allowlist/blocklist entries.

    Logic:
      - If any active 'allow' entries exist: ONLY matching IPs are permitted.
      - Otherwise: matching 'block' entries are denied, everything else allowed.
    """

    __tablename__ = "ip_restrictions"
    __table_args__ = (Index("ix_ip_restrictions_type_active", "restriction_type", "is_active"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ip_range = Column(String(50), nullable=False)
    restriction_type = Column(String(10), nullable=False)  # 'allow' or 'block'
    note = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        return {
            "id": str(self.id),
            "ip_range": self.ip_range,
            "restriction_type": self.restriction_type,
            "note": self.note,
            "is_active": self.is_active,
            "created_by_id": str(self.created_by_id) if self.created_by_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
