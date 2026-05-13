import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    metric_type = Column(String(50), nullable=False)
    operator = Column(String(10), nullable=False)
    threshold = Column(Float, nullable=False)

    scope = Column(String(50), nullable=False, default="global")
    target_id = Column(UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=True)

    duration_seconds = Column(Integer, nullable=False, default=60)
    cooldown_seconds = Column(Integer, nullable=False, default=300)

    notify_admin = Column(Boolean, default=True)
    notify_user = Column(Boolean, default=True)
    email_enabled = Column(Boolean, default=False)
    webhook_url = Column(Text)

    is_active = Column(Boolean, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def evaluate(self, value: float) -> bool:
        """Evaluate if the metric value triggers this rule"""
        ops = {
            ">": lambda x, y: x > y,
            "<": lambda x, y: x < y,
            ">=": lambda x, y: x >= y,
            "<=": lambda x, y: x <= y,
            "==": lambda x, y: x == y,
            "!=": lambda x, y: x != y,
        }
        return ops.get(self.operator, lambda x, y: False)(value, self.threshold)

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "metric_type": self.metric_type,
            "operator": self.operator,
            "threshold": self.threshold,
            "scope": self.scope,
            "target_id": str(self.target_id) if self.target_id else None,
            "duration_seconds": self.duration_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "notify_admin": self.notify_admin,
            "notify_user": self.notify_user,
            "email_enabled": self.email_enabled,
            "webhook_url": self.webhook_url,
            "is_active": self.is_active,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
