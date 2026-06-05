import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class AlertHistory(Base):
    __tablename__ = "alert_history"
    __table_args__ = (
        Index('ix_alert_history_created_at', 'created_at'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    server_id = Column(UUID(as_uuid=True), ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    metric_value = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)

    status = Column(String(50), default="fired")

    admin_notified = Column(Boolean, default=False)
    user_notified = Column(Boolean, default=False)
    email_sent = Column(Boolean, default=False)
    webhook_sent = Column(Boolean, default=False)

    acknowledged_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime)
    notes = Column(Text)

    resolved_at = Column(DateTime)
    resolved_value = Column(Float)

    fired_at = Column(DateTime, default=utc_now)
    created_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        return {
            "id": str(self.id),
            "rule_id": str(self.rule_id) if self.rule_id else None,
            "server_id": str(self.server_id) if self.server_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "status": self.status,
            "acknowledged": self.acknowledged_at is not None,
            "acknowledged_by": str(self.acknowledged_by) if self.acknowledged_by else None,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "fired_at": self.fired_at.isoformat() if self.fired_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
