"""
Request metrics model for HTTP-level observability.

Tracks latency, status codes, and error rates per endpoint.
"""

import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, INET
from app.db.base import Base
from app.core.time_utils import utc_now


class RequestMetric(Base):
    __tablename__ = "request_metrics"

    __table_args__ = (
        Index('ix_request_metrics_path_status', 'path', 'status_code'),
        Index('ix_request_metrics_created_at', 'created_at'),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    method = Column(String(10), nullable=False)
    path = Column(String(255), nullable=False, index=True)
    status_code = Column(Integer, nullable=False, index=True)
    duration_ms = Column(Float, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    ip_address = Column(INET, nullable=True)
    user_agent = Column(String, nullable=True)
    correlation_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, primary_key=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "user_id": str(self.user_id) if self.user_id else None,
            "ip_address": str(self.ip_address) if self.ip_address else None,
            "user_agent": self.user_agent,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
