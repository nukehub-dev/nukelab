import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, DateTime, BigInteger, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class VolumeBackup(Base):
    __tablename__ = "volume_backups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    volume_name = Column(String(255), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    backup_path = Column(String(500), nullable=True)
    status = Column(String(50), default="pending")  # pending, in_progress, completed, failed
    error_message = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<VolumeBackup {self.id}: {self.volume_name}>"
