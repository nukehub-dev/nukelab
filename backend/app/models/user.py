import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID, INET
from sqlalchemy.orm import relationship
from app.db.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(String(50), default="user", nullable=False)
    
    # Credits & Quotas
    credit_balance = Column(Integer, default=500)
    daily_allowance = Column(Integer, default=500)
    last_credit_reset = Column(DateTime, nullable=True)
    
    # Profile (flexible JSONB)
    # Stores: avatar, timezone, phone, department, organization, etc.
    profile = Column(JSON, default=dict)
    
    # Preferences (app-specific settings)
    # Stores: theme, language, default_environment, default_plan, notifications
    preferences = Column(JSON, default=dict)
    
    # Security tracking
    # Stores: last_ip, login_count, failed_attempts, locked_until, mfa_enabled
    security = Column(JSON, default=dict)
    
    # Status
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    email_verified_at = Column(DateTime, nullable=True)
    
    # Audit
    last_login = Column(DateTime, nullable=True)
    last_ip_address = Column(INET, nullable=True)
    login_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    api_tokens = relationship("ApiToken", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username}>"
    
    def to_dict(self):
        """Serialize user to dictionary"""
        return {
            "id": str(self.id),
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "credit_balance": self.credit_balance,
            "profile": self.profile or {},
            "preferences": self.preferences or {},
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
