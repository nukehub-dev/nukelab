# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Process-lifetime executor registry used to judge operation liveness."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (Index("ix_worker_heartbeats_state_heartbeat_at", "state", "heartbeat_at"),)

    executor_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hostname = Column(String(255), nullable=False)
    container_id = Column(String(255), nullable=True)
    container_started_at = Column(String(64), nullable=True)
    pid = Column(Integer, nullable=False)
    process_start_time = Column(String(64), nullable=True)
    single_process_container = Column(Boolean, nullable=False, default=False)
    schema_version = Column(String(32), nullable=False)
    state = Column(String(16), nullable=False, default="running")
    heartbeat_at = Column(DateTime, nullable=False, default=utc_now)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
