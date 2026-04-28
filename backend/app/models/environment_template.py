import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class EnvironmentTemplate(Base):
    __tablename__ = "environment_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Docker
    image = Column(String(500), nullable=False)
    dockerfile = Column(Text, nullable=True)
    
    # Configuration
    packages = Column(JSON, default=list)
    environment_variables = Column(JSON, default=dict)
    volumes = Column(JSON, default=list)
    ports = Column(JSON, default=list)
    
    # Branding
    icon = Column(String(50), default="🖥️")
    color = Column(String(7), default="#3B82F6")
    category = Column(String(50), default="base")
    
    # Status
    is_active = Column(Boolean, default=True)
    is_public = Column(Boolean, default=True)
    
    # Ownership
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "image": self.image,
            "dockerfile": self.dockerfile,
            "packages": self.packages or [],
            "environment_variables": self.environment_variables or {},
            "volumes": self.volumes or [],
            "ports": self.ports or [],
            "icon": self.icon,
            "color": self.color,
            "category": self.category,
            "is_active": self.is_active,
            "is_public": self.is_public,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
