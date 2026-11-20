# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class EnvironmentRevision(Base):
    __tablename__ = "environment_revisions"
    __table_args__ = (UniqueConstraint("template_id", "fingerprint"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("environment_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fingerprint = Column(String(64), nullable=False)
    template_fingerprint = Column(String(64), nullable=False)
    configuration = Column(JSON, nullable=False)
    runtime_identity = Column(JSON, nullable=False)
    toolchain_identity = Column(JSON, nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


@event.listens_for(EnvironmentRevision, "before_update")
def _immutable_revision(mapper, connection, target):
    if any(attr.history.has_changes() for attr in inspect(target).attrs if attr.key != "revoked"):
        raise ValueError("Approved environment revisions are immutable")
