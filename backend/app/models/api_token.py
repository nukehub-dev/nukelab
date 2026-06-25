import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, Boolean, DateTime, Integer, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(255), nullable=False)
    token_hash = Column(String(255), nullable=False, index=True)
    token_prefix = Column(String(16), nullable=True, index=True)
    scopes = Column(JSON, default=list)

    # Usage tracking
    last_used_at = Column(DateTime, nullable=True)
    usage_count = Column(Integer, default=0)

    # Lifecycle
    created_at = Column(DateTime, default=utc_now)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    # Relationship
    user = relationship("User", back_populates="api_tokens")

    def __repr__(self):
        return f"<ApiToken {self.name} for user {self.user_id}>"

    def to_dict(self, include_hash=False):
        """Serialize token to dictionary"""
        data = {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "name": self.name,
            "scopes": self.scopes or [],
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "is_active": self.is_active,
        }
        if include_hash:
            data["token_hash"] = self.token_hash
        return data
