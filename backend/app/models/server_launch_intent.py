# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

from sqlalchemy import Column, DateTime, ForeignKey, String, event
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class ServerLaunchIntent(Base):
    """Immutable provisioning intent committed before any external launch work."""

    __tablename__ = "server_launch_intents"

    server_id = Column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("environment_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_payload = Column(JSONB, nullable=False)
    mounts = Column(JSONB, nullable=False)
    gpu_devices = Column(JSONB, nullable=False)
    environment_slug = Column(String(255), nullable=False)
    username = Column(String(255), nullable=False)
    queue_id = Column(
        UUID(as_uuid=True), ForeignKey("server_queue.id", ondelete="SET NULL"), nullable=True
    )
    claim_token = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


@event.listens_for(ServerLaunchIntent, "before_update")
def _immutable_intent(mapper, connection, target):
    raise ValueError("Launch intent is immutable")
