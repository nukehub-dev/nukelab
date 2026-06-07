import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON, Index
from sqlalchemy.dialects.postgresql import UUID, INET
from app.db.base import Base

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        Index('ix_activity_logs_created_at', 'created_at'),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50), nullable=False, index=True)
    target_id = Column(UUID(as_uuid=True), nullable=True)
    details = Column(JSON, default=dict)
    before_state = Column(JSON, default=dict)
    after_state = Column(JSON, default=dict)
    request_id = Column(UUID(as_uuid=True), nullable=True)
    ip_address = Column(INET, nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, primary_key=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": str(self.target_id) if self.target_id else None,
            "details": self.details or {},
            "before_state": self.before_state or {},
            "after_state": self.after_state or {},
            "request_id": str(self.request_id) if self.request_id else None,
            "ip_address": str(self.ip_address) if self.ip_address else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
