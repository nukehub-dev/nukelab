import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

class ServerQueue(Base):
    __tablename__ = "server_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    environment_id = Column(UUID(as_uuid=True), ForeignKey("environment_templates.id"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("server_plans.id"), nullable=False)
    
    # Status: pending, scheduled, starting, failed, cancelled
    status = Column(String(50), default="pending", nullable=False)
    priority = Column(Integer, default=0)
    
    # Server name (pre-generated)
    server_name = Column(String(255), nullable=False)
    
    # Timestamps
    requested_at = Column(DateTime, default=datetime.utcnow)
    scheduled_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    
    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "environment_id": str(self.environment_id),
            "plan_id": str(self.plan_id),
            "status": self.status,
            "priority": self.priority,
            "server_name": self.server_name,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
