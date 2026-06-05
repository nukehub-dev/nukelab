import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, Text, Boolean, DateTime, Integer, Float, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class ServerPlan(Base):
    __tablename__ = "server_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    category = Column(String(50), default="cpu")
    
    # Resource limits
    cpu_limit = Column(Float, default=1.0)
    memory_limit = Column(String(50), default="2g")
    disk_limit = Column(String(50), default="10g")
    gpu_limit = Column(Integer, default=0)
    
    # Usage limits
    max_servers_per_user = Column(Integer, default=3)
    
    # Cost
    cost_per_hour = Column(Integer, default=1)
    cooldown_seconds = Column(Integer, default=0)
    
    # Usage limits
    max_servers_per_user = Column(Integer, default=3)
    max_runtime = Column(String(20), default="24h")
    idle_timeout = Column(String(20), default="1h")
    
    # Features
    allow_scheduling = Column(Boolean, default=True)
    allow_snapshots = Column(Boolean, default=False)
    
    # Restrictions
    is_public = Column(Boolean, default=False)
    visible_to_roles = Column(JSON, default=list)
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Scheduling
    priority = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relationships
    user_access = relationship("UserPlanAccess", back_populates="plan", cascade="all, delete-orphan")
    workspace_access = relationship("WorkspacePlanAccess", back_populates="plan", cascade="all, delete-orphan")
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "category": self.category,
            "cpu_limit": self.cpu_limit,
            "memory_limit": self.memory_limit,
            "disk_limit": self.disk_limit,
            "gpu_limit": self.gpu_limit,
            "max_servers_per_user": self.max_servers_per_user,
            "max_runtime": self.max_runtime,
            "idle_timeout": self.idle_timeout,
            "cost_per_hour": self.cost_per_hour,
            "cooldown_seconds": self.cooldown_seconds,
            "allow_scheduling": self.allow_scheduling,
            "allow_snapshots": self.allow_snapshots,
            "is_public": self.is_public,
            "visible_to_roles": self.visible_to_roles or [],
            "is_active": self.is_active,
            "priority": self.priority,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
