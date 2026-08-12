# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.db.base import Base


class CreditRequest(Base):
    __tablename__ = "credit_requests"
    __table_args__ = (
        # At most one open (pending or needs_info) request per user; the
        # cheap pre-check in CreditRequestService.create_request is backed
        # by this index as the authoritative race guard (IntegrityError -> 400).
        Index(
            "uq_credit_requests_pending_per_user",
            "user_id",
            unique=True,
            postgresql_where="status IN ('pending', 'needs_info')",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    # "top_up" = one-time credit grant on approval; "allowance" = approval
    # sets the user's base daily_allowance instead (no ledger transaction).
    request_type = Column(String(20), nullable=False, default="top_up")
    status = Column(String(20), nullable=False, default="pending", index=True)
    reviewed_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_note = Column(Text, nullable=True)
    granted_amount = Column(Integer, nullable=True)
    # Plain column, no FK: credit_transactions is range-partitioned on
    # created_at and cannot be referenced by a foreign key.
    transaction_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "amount": self.amount,
            "reason": self.reason,
            "request_type": self.request_type,
            "status": self.status,
            "reviewed_by": str(self.reviewed_by) if self.reviewed_by else None,
            "review_note": self.review_note,
            "granted_amount": self.granted_amount,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


class CreditRequestMessage(Base):
    __tablename__ = "credit_request_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("credit_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable + SET NULL so the thread survives author account deletion.
    author_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body = Column(Text, nullable=False)
    # Internal reviewer notes are hidden from the requester and do not
    # flip the ball-in-court state or trigger requester notifications.
    is_internal = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    def to_dict(self):
        return {
            "id": str(self.id),
            "request_id": str(self.request_id),
            "author_id": str(self.author_id) if self.author_id else None,
            "body": self.body,
            "is_internal": self.is_internal,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
