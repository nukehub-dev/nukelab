import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class LoginEvent(Base):
    __tablename__ = "login_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    method = Column(String(20), default="password", nullable=False)  # "password" or "oauth"
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_login_events_timestamp_method", "timestamp", "method"),
    )
