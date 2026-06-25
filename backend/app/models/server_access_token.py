import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Integer, Index
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class ServerAccessToken(Base):
    """Tracks issued server access tokens for audit and revocation.

        Tokens themselves are short-lived JWTs (5 min default) signed with
        asymmetric keys. This table tracks issuance for:
        - Audit logging
    - Revocation before expiry
        - Rate limiting detection
    """

    __tablename__ = "server_access_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # JWT ID for revocation support
    jti = Column(String(64), nullable=False, unique=True, index=True)

    # Key ID used to sign this token (for key rotation)
    key_id = Column(String(32), nullable=False)

    # Token validity window
    issued_at = Column(DateTime, nullable=False, default=utc_now)
    expires_at = Column(DateTime, nullable=False)

    # Revocation
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String(255), nullable=True)

    # Usage tracking
    used_at = Column(DateTime, nullable=True)
    use_count = Column(Integer, default=0)

    # Security context
    client_ip = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # Token type: 'session' (normal), 'resume' (after reconnect), 'share' (shared link)
    token_type = Column(String(20), default="session")

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index("idx_server_access_tokens_server_user", "server_id", "user_id"),
        Index("idx_server_access_tokens_expires", "expires_at"),
        Index("idx_server_access_tokens_revoked", "revoked_at"),
    )
