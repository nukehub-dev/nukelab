from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.time_utils import utc_now
from app.db.base import Base


class ServerVolume(Base):
    __tablename__ = "server_volumes"

    server_id = Column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True
    )
    volume_id = Column(
        UUID(as_uuid=True), ForeignKey("volumes.id", ondelete="CASCADE"), primary_key=True
    )
    mount_path = Column(String(255), nullable=False, default="/data")
    mode = Column(String(20), default="read_write")  # read_write, read_only
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)

    server = relationship("Server", back_populates="volume_mounts")
    volume = relationship("Volume", back_populates="server_mounts")
