import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class SharedWorkspace(Base):
    __tablename__ = "shared_workspaces"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_workspaces")
    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    volume_associations = relationship("WorkspaceVolume", back_populates="workspace", cascade="all, delete-orphan")
    invitations = relationship("WorkspaceInvitation", back_populates="workspace", cascade="all, delete-orphan")
    plan_access = relationship("WorkspacePlanAccess", back_populates="workspace", cascade="all, delete-orphan")
    
    def to_dict(self):
        try:
            member_count = len(self.members) if self.members else 0
        except:
            member_count = 0
        try:
            volume_count = len(self.volume_associations) if self.volume_associations else 0
        except:
            volume_count = 0
        owner_name = None
        owner_username = None
        try:
            if self.owner:
                owner_name = self.owner.display_name or self.owner.username
                owner_username = self.owner.username
        except:
            pass
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "owner_id": str(self.owner_id),
            "owner_name": owner_name,
            "owner_username": owner_username,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "member_count": member_count,
            "volume_count": volume_count,
        }

class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("shared_workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(20), default="read_write")  # read_only, read_write, admin
    joined_at = Column(DateTime, default=utc_now)
    
    # Relationships
    workspace = relationship("SharedWorkspace", back_populates="members")
    user = relationship("User", back_populates="workspace_memberships")
    
    def to_dict(self):
        return {
            "workspace_id": str(self.workspace_id),
            "user_id": str(self.user_id),
            "role": self.role,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
            "username": self.user.username if self.user else None,
            "email": self.user.email if self.user else None,
        }
