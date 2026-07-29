# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class GpuAllocation(Base):
    """Exclusive reservation of one physical GPU device for a server.

    One server can hold several rows (one per allocated device). The UNIQUE
    constraint on device is the race-safety guard: concurrent spawns cannot
    reserve the same device twice.
    """

    __tablename__ = "gpu_allocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    device = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)
