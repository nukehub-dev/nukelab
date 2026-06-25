import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.time_utils import utc_now
from app.db.base import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String(255), nullable=False)
    # Deterministic SHA-256 lookup hash for O(1) token verification at scale.
    # Bcrypt hashes are non-deterministic, so we index a fast SHA-256 of the
    # plaintext for DB lookup, then verify with bcrypt in memory.
    token_lookup = Column(String(64), nullable=True, index=True)

    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    user_agent = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)

    user = relationship("User")

    def __repr__(self):
        return f"<RefreshToken {self.id} for user {self.user_id}>"

    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "user_agent": self.user_agent,
            "ip_address": self.ip_address,
        }
