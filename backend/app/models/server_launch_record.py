# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class ServerLaunchRecord(Base):
    __tablename__ = "server_launch_records"
    __table_args__ = (UniqueConstraint("server_id", "generation"),)

    # Operation identity supplied before runtime I/O; duplicate delivery reuses this ID.
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(
        UUID(as_uuid=True), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id = Column(
        UUID(as_uuid=True),
        ForeignKey("environment_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    generation = Column(Integer, nullable=False)
    manifest = Column(JSON, nullable=False)
    actual_runtime_identity = Column(JSON, nullable=False)
    actual_toolchain_identity = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


@event.listens_for(ServerLaunchRecord, "before_update")
def _append_only_launch(mapper, connection, target):
    raise ValueError("Launch provenance is append-only")
