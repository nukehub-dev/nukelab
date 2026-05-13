import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class WorkspaceVolume(Base):
    __tablename__ = "workspace_volumes"
    
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("shared_workspaces.id", ondelete="CASCADE"), primary_key=True)
    volume_id = Column(UUID(as_uuid=True), ForeignKey("volumes.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(20), default="read_write")  # read_only, read_write
    added_at = Column(DateTime, default=datetime.utcnow)
    added_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relationships
    workspace = relationship("SharedWorkspace", back_populates="volume_associations")
    volume = relationship("Volume", back_populates="workspace_associations")
    added_by_user = relationship("User", foreign_keys=[added_by])
    
    def to_dict(self):
        data = {
            "workspace_id": str(self.workspace_id),
            "volume_id": str(self.volume_id),
            "role": self.role,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "added_by": str(self.added_by) if self.added_by else None,
        }
        # Only include volume if already loaded (avoid lazy loading in async)
        if "volume" not in inspect(self).unloaded and self.volume:
            data["volume"] = self.volume.to_dict()
        return data
