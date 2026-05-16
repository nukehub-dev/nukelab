import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, BigInteger, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy import inspect
from app.db.base import Base


class Volume(Base):
    __tablename__ = "volumes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    display_name = Column(String(255), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Sharing/visibility
    visibility = Column(String(20), default="private")  # private, workspace, public
    
    # Resource tracking
    size_bytes = Column(BigInteger, default=0)
    max_size_bytes = Column(BigInteger, nullable=True)
    
    # Status
    status = Column(String(20), default="active")  # active, archived, deleting, over_limit
    
    # Usage tracking
    server_count = Column(Integer, default=0)
    last_mounted_at = Column(DateTime, nullable=True)
    
    # Metadata
    description = Column(Text, nullable=True)
    labels = Column(JSONB, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    owner = relationship("User", back_populates="volumes")
    servers = relationship("Server", back_populates="volume")
    workspace_associations = relationship("WorkspaceVolume", back_populates="volume", cascade="all, delete-orphan")
    
    def to_dict(self):
        data = {
            "id": str(self.id),
            "name": self.name,
            "display_name": self.display_name,
            "owner_id": str(self.owner_id),
            "visibility": self.visibility,
            "size_bytes": self.size_bytes,
            "max_size_bytes": self.max_size_bytes,
            "status": self.status,
            "server_count": self.server_count,
            "last_mounted_at": self.last_mounted_at.isoformat() if self.last_mounted_at else None,
            "description": self.description,
            "labels": self.labels,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if "owner" not in inspect(self).unloaded and self.owner:
            data["owner"] = {
                "id": str(self.owner.id),
                "username": self.owner.username,
                "display_name": self.owner.display_name,
            }
        return data
