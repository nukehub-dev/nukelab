import uuid
import hashlib
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
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(String(50), default="user", nullable=False)
    
    # OAuth tracking
    oauth_provider = Column(String(50), nullable=True)
    oauth_id = Column(String(255), nullable=True)
    
    # NUKE Currency & Quotas
    nuke_balance = Column(Integer, default=100)
    daily_allowance = Column(Integer, default=100)
    last_nuke_reset = Column(DateTime, nullable=True)
    
    # Avatar
    avatar_url = Column(String(500), nullable=True)
    
    # Profile visibility
    profile_visibility = Column(String(20), default="private", nullable=False)
    
    # Profile (flexible JSONB)
    # Stores: timezone, phone, department, organization, etc.
    profile = Column(JSON, default=dict)
    
    # Preferences (app-specific settings)
    # Stores: theme, accent_color, oled_mode, language, default_environment, default_plan, notifications
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
    servers = relationship("Server", back_populates="user", cascade="all, delete-orphan")
    volumes = relationship("Volume", back_populates="owner", cascade="all, delete-orphan")
    api_tokens = relationship("ApiToken", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    owned_workspaces = relationship("SharedWorkspace", back_populates="owner", cascade="all, delete-orphan")
    workspace_memberships = relationship("WorkspaceMember", back_populates="user", cascade="all, delete-orphan")
    workspace_invitations_received = relationship("WorkspaceInvitation", foreign_keys="WorkspaceInvitation.user_id", back_populates="user", cascade="all, delete-orphan")
    workspace_invitations_sent = relationship("WorkspaceInvitation", foreign_keys="WorkspaceInvitation.invited_by", back_populates="inviter", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username}>"
    
    @property
    def display_name(self):
        """Return full name or username"""
        if self.first_name or self.last_name:
            parts = [p for p in [self.first_name, self.last_name] if p]
            return " ".join(parts)
        return self.username
    
    def get_gravatar_url(self, size=200, default="identicon"):
        """Generate Gravatar URL from email"""
        email_hash = hashlib.md5(self.email.lower().strip().encode()).hexdigest()
        return f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d={default}&r=pg"
    
    def get_avatar_url(self, size=200):
        """Get avatar URL (Gravatar or custom)"""
        prefs = self.preferences or {}
        use_gravatar = prefs.get('use_gravatar', False)

        if use_gravatar:
            return self.get_gravatar_url(size=size)
        if self.avatar_url:
            return self.avatar_url
        return ""
    
    def to_dict(self):
        """Serialize user to dictionary"""
        return {
            "id": str(self.id),
            "username": self.username,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "display_name": self.display_name,
            "avatar_url": self.get_avatar_url(),
            "role": self.role,
            "nuke_balance": self.nuke_balance,
            "profile": self.profile or {},
            "preferences": self.preferences or {},
            "profile_visibility": self.profile_visibility or "private",
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
