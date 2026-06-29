# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid
from datetime import timedelta

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.time_utils import utc_now
from app.db.base import Base


class WorkspaceInvitation(Base):
    __tablename__ = "workspace_invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("shared_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    role = Column(String(20), default="read_write", nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    expires_at = Column(DateTime, default=lambda: utc_now() + timedelta(days=7), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_invitation"),)

    workspace = relationship("SharedWorkspace", back_populates="invitations")
    user = relationship(
        "User", foreign_keys=[user_id], back_populates="workspace_invitations_received"
    )
    inviter = relationship(
        "User", foreign_keys=[invited_by], back_populates="workspace_invitations_sent"
    )

    def to_dict(self):
        return {
            "id": str(self.id),
            "workspace_id": str(self.workspace_id),
            "user_id": str(self.user_id),
            "invited_by": str(self.invited_by) if self.invited_by else None,
            "role": self.role,
            "status": self.status,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "username": self.user.username if self.user else None,
            "display_name": self.user.display_name if self.user else None,
            "avatar_url": self.user.get_avatar_url() if self.user else None,
            "inviter_username": self.inviter.username if self.inviter else None,
            "inviter_display_name": self.inviter.display_name if self.inviter else None,
            "inviter_avatar_url": self.inviter.get_avatar_url() if self.inviter else None,
        }
