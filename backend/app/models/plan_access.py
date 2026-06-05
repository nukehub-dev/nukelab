import uuid
from app.core.time_utils import utc_now
from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base


class UserPlanAccess(Base):
    __tablename__ = "user_plan_access"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("server_plans.id", ondelete="CASCADE"), primary_key=True)
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at = Column(DateTime, default=utc_now)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", foreign_keys=[user_id], back_populates="plan_access")
    plan = relationship("ServerPlan", back_populates="user_access")
    granted_by_user = relationship("User", foreign_keys=[granted_by])

    def to_dict(self):
        return {
            "user_id": str(self.user_id),
            "plan_id": str(self.plan_id),
            "granted_by": str(self.granted_by) if self.granted_by else None,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class WorkspacePlanAccess(Base):
    __tablename__ = "workspace_plan_access"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("shared_workspaces.id", ondelete="CASCADE"), primary_key=True)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("server_plans.id", ondelete="CASCADE"), primary_key=True)
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at = Column(DateTime, default=utc_now)
    expires_at = Column(DateTime, nullable=True)

    workspace = relationship("SharedWorkspace", back_populates="plan_access")
    plan = relationship("ServerPlan", back_populates="workspace_access")
    granted_by_user = relationship("User", foreign_keys=[granted_by])

    def to_dict(self):
        return {
            "workspace_id": str(self.workspace_id),
            "plan_id": str(self.plan_id),
            "granted_by": str(self.granted_by) if self.granted_by else None,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
