import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

class ResourceQuota(Base):
    __tablename__ = "resource_quotas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, unique=True)
    role = Column(String(50), nullable=True, unique=True)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("server_plans.id", ondelete="CASCADE"), nullable=True, unique=True)
    
    # Limits
    max_cpu_total = Column(Float, default=8.0)
    max_memory_total = Column(String(50), default="16g")
    max_disk_total = Column(String(50), default="100g")
    max_gpu_total = Column(Integer, default=0)
    max_servers_total = Column(Integer, default=5)
    
    # Current usage (updated by scheduler)
    usage_cpu = Column(Float, default=0.0)
    usage_memory_mb = Column(Integer, default=0)
    usage_disk_mb = Column(Integer, default=0)
    usage_gpu = Column(Integer, default=0)
    usage_servers = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "role": self.role,
            "plan_id": str(self.plan_id) if self.plan_id else None,
            "limits": {
                "max_cpu_total": self.max_cpu_total,
                "max_memory_total": self.max_memory_total,
                "max_disk_total": self.max_disk_total,
                "max_gpu_total": self.max_gpu_total,
                "max_servers_total": self.max_servers_total,
            },
            "usage": {
                "cpu": self.usage_cpu,
                "memory_mb": self.usage_memory_mb,
                "disk_mb": self.usage_disk_mb,
                "gpu": self.usage_gpu,
                "servers": self.usage_servers,
            },
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
