# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Authorization hold for one paid batch job's maximum credit exposure."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class CreditHold(Base):
    """One user's held credits reserved for one job until settlement or release."""

    __tablename__ = "credit_holds"
    __table_args__ = (
        Index("ix_credit_holds_user_state", "user_id", "state"),
        Index("uq_credit_holds_job_id", "job_id", unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(
        UUID(as_uuid=True), ForeignKey("batch_jobs.id", ondelete="CASCADE"), nullable=False
    )
    amount = Column(Integer, nullable=False)
    state = Column(String(20), nullable=False, default="held", server_default="held")
    charged_credits = Column(Integer, nullable=False, default=0, server_default="0")
    unpaid_credits = Column(Integer, nullable=False, default=0, server_default="0")
    # No FK: credit_transactions is range-partitioned by created_at.
    transaction_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    settled_at = Column(DateTime, nullable=True)
