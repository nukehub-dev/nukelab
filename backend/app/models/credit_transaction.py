import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, JSON, Index
from sqlalchemy.dialects.postgresql import UUID, INET
from app.db.base import Base

class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    __table_args__ = (
        Index('ix_credit_transactions_created_at', 'created_at'),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    type = Column(String(50), nullable=False, index=True)
    description = Column(Text, nullable=True)
    server_id = Column(UUID(as_uuid=True), ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    plan_id = Column(UUID(as_uuid=True), nullable=True)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "amount": self.amount,
            "balance_after": self.balance_after,
            "type": self.type,
            "description": self.description,
            "server_id": str(self.server_id) if self.server_id else None,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "metadata": self.meta or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
