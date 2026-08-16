# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.time_utils import utc_now
from app.db.base import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint = Column(Text, nullable=False)
    keys = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="push_subscriptions")

    __table_args__ = (
        # Each endpoint is unique per user (mirrors the migration's unique
        # index). Endpoints are treated as secrets and must never be logged.
        Index(
            "uq_push_subscriptions_endpoint_per_user",
            "user_id",
            "endpoint",
            unique=True,
        ),
    )
