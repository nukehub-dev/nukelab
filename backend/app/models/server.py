import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Float, Integer, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class Server(Base):
    __tablename__ = "servers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    environment_id = Column(UUID(as_uuid=True), nullable=True)
    plan_id = Column(UUID(as_uuid=True), nullable=True)
    
    # Docker
    container_id = Column(String(255), nullable=True)
    image = Column(String(255), nullable=True)
    volume_id = Column(UUID(as_uuid=True), ForeignKey("volumes.id", ondelete="SET NULL"), nullable=True)
    volume_mode = Column(String(20), default="read_write")  # read_write, read_only
    status = Column(String(50), default="pending", nullable=False)
    
    # Resources
    allocated_cpu = Column(Float, default=1.0)
    allocated_memory = Column(String(50), default="2g")
    allocated_disk = Column(String(50), default="10g")
    allocated_gpu = Column(Integer, default=0)
    
    # Networking
    internal_port = Column(Integer, default=3000)
    external_url = Column(String(500), nullable=True)
    
    # Health tracking
    health_status = Column(String(20), default="unknown")
    health_check_config = Column(JSON, default=dict)
    last_health_check = Column(DateTime, nullable=True)
    
    # State tracking
    status_reason = Column(String(255), nullable=True)
    stopped_by = Column(UUID(as_uuid=True), nullable=True)
    stop_reason = Column(String(255), nullable=True)
    
    # Billing and cost tracking
    total_cost = Column(Integer, default=0)
    last_billed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="servers")
    volume = relationship("Volume", back_populates="servers")
    volume_mounts = relationship("ServerVolume", back_populates="server", cascade="all, delete-orphan")
    
    # Timestamps
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    last_activity = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Server {self.name} ({self.status})>"
