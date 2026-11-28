# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Credit authorization holds for paid batch jobs.

A hold reserves a user's maximum possible batch-job charge until the job reaches
a proof-backed terminal result. Callers own the surrounding transaction; every
operation in this module flushes but never commits. The user row is always
locked before any hold row so concurrent holds, settlements and interactive
debits serialize on one ordered lock set.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.credit_hold import CreditHold
from app.models.credit_transaction import CreditTransaction
from app.models.user import User

logger = get_logger(__name__)

HELD = "held"
SETTLED = "settled"
RELEASED = "released"
NONE = "none"
BATCH_JOB_USAGE_TYPE = "batch_job_usage"


class CreditHoldError(Exception):
    """Typed hold failure carrying a stable machine-readable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class HoldSettlement:
    """Result of one idempotent hold settlement."""

    charged: int
    refunded: int
    state: str
    transaction_id: uuid.UUID | None
    unpaid: int


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _no_hold() -> HoldSettlement:
    return HoldSettlement(
        charged=0,
        refunded=0,
        state=NONE,
        transaction_id=None,
        unpaid=0,
    )


class CreditHoldService:
    """Create, release and settle one job-scoped credit hold at a time."""

    @staticmethod
    async def _held_total(db: AsyncSession, user_id: uuid.UUID) -> int:
        value = await db.scalar(
            select(func.coalesce(func.sum(CreditHold.amount), 0)).where(
                CreditHold.user_id == user_id,
                CreditHold.state == HELD,
            )
        )
        return int(value or 0)

    @staticmethod
    async def held_total(db: AsyncSession, user_id: uuid.UUID | str) -> int:
        return await CreditHoldService._held_total(db, _as_uuid(user_id))

    @staticmethod
    async def spendable_balance(db: AsyncSession, user_id: uuid.UUID | str) -> int:
        """Return balance minus every active hold; a missing user has none."""
        uid = _as_uuid(user_id)
        balance = await db.scalar(select(User.nuke_balance).where(User.id == uid))
        if balance is None:
            return 0
        return int(balance) - await CreditHoldService._held_total(db, uid)

    @staticmethod
    async def _locked_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
        return await db.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    @staticmethod
    async def create_hold(
        db: AsyncSession,
        *,
        user_id: uuid.UUID | str,
        job_id: uuid.UUID | str,
        amount: int,
    ) -> CreditHold:
        """Lock the user, prove spendable balance, then insert one held row."""
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise CreditHoldError("invalid_amount")
        uid = _as_uuid(user_id)
        jid = _as_uuid(job_id)
        user = await CreditHoldService._locked_user(db, uid)
        if user is None:
            raise CreditHoldError("user_not_found")
        existing = await db.scalar(
            select(CreditHold)
            .where(CreditHold.job_id == jid)
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            raise CreditHoldError("hold_exists")
        held = await CreditHoldService._held_total(db, uid)
        if int(user.nuke_balance or 0) - held < amount:
            raise CreditHoldError("insufficient_credits")
        hold = CreditHold(
            user_id=uid,
            job_id=jid,
            amount=amount,
            state=HELD,
            charged_credits=0,
            unpaid_credits=0,
            created_at=utc_now(),
        )
        db.add(hold)
        await db.flush()
        return hold

    @staticmethod
    async def release(db: AsyncSession, job_id: uuid.UUID | str) -> bool:
        """Idempotently release one held row without charging anything."""
        hold = await db.scalar(
            select(CreditHold)
            .where(CreditHold.job_id == _as_uuid(job_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if hold is None or hold.state != HELD:
            return False
        hold.state = RELEASED
        hold.charged_credits = 0
        hold.unpaid_credits = 0
        hold.settled_at = utc_now()
        await db.flush()
        return True

    @staticmethod
    async def settle(
        db: AsyncSession,
        *,
        job_id: uuid.UUID | str,
        charge: int,
        description: str,
        meta: dict[str, Any] | None = None,
    ) -> HoldSettlement:
        """Charge actual usage up to the hold and the current balance.

        Never raises for an insufficient balance: the charge is clamped and the
        unpaid remainder is reported. The end state is stored on the hold and a
        repeat call returns the same result without a second transaction.
        """
        jid = _as_uuid(job_id)
        hold = await db.scalar(
            select(CreditHold)
            .where(CreditHold.job_id == jid)
            .execution_options(populate_existing=True)
        )
        if hold is None:
            return _no_hold()
        user = await CreditHoldService._locked_user(db, hold.user_id)
        hold = await db.scalar(
            select(CreditHold)
            .where(CreditHold.job_id == jid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if hold is None:
            return _no_hold()
        if hold.state == SETTLED:
            return CreditHoldService._stored_settlement(hold)
        if hold.state == RELEASED:
            return HoldSettlement(
                charged=0,
                refunded=0,
                state=RELEASED,
                transaction_id=None,
                unpaid=0,
            )

        requested = int(charge or 0)
        bounded = max(0, min(requested, int(hold.amount)))
        balance = max(0, int(user.nuke_balance or 0)) if user is not None else 0
        charged = min(bounded, balance)
        # Unpaid is the part of the requested bill the balance could not cover.
        # Refund is only the authorization that was never billable; an unpaid
        # remainder is debt, not a refund.
        unpaid = bounded - charged
        refunded = int(hold.amount) - bounded
        new_balance = balance - charged

        transaction_id: uuid.UUID | None = None
        if charged > 0:
            if user is not None:
                user.nuke_balance = new_balance
            payload = dict(meta or {})
            payload.update(
                {
                    "job_id": str(jid),
                    "charged": charged,
                    "refunded": refunded,
                    "unpaid": unpaid,
                }
            )
            transaction = CreditTransaction(
                user_id=hold.user_id,
                amount=-charged,
                balance_after=new_balance,
                type=BATCH_JOB_USAGE_TYPE,
                description=description,
                meta=payload,
            )
            db.add(transaction)
            await db.flush()
            transaction_id = transaction.id

        hold.state = SETTLED
        hold.charged_credits = charged
        hold.unpaid_credits = unpaid
        hold.transaction_id = transaction_id
        hold.settled_at = utc_now()
        await db.flush()

        if unpaid > 0 or refunded > 0:
            logger.info(
                "Batch job credit hold settled",
                extra={
                    "job_id": str(jid),
                    "held_amount": int(hold.amount),
                    "charged": charged,
                    "refunded": refunded,
                    "unpaid": unpaid,
                },
            )
        return HoldSettlement(
            charged=charged,
            refunded=refunded,
            state=SETTLED,
            transaction_id=transaction_id,
            unpaid=unpaid,
        )

    @staticmethod
    def _stored_settlement(hold: CreditHold) -> HoldSettlement:
        charged = int(hold.charged_credits or 0)
        unpaid = int(hold.unpaid_credits or 0)
        return HoldSettlement(
            charged=charged,
            refunded=int(hold.amount) - charged - unpaid,
            state=SETTLED,
            transaction_id=hold.transaction_id,
            unpaid=unpaid,
        )


__all__ = [
    "BATCH_JOB_USAGE_TYPE",
    "CreditHoldError",
    "CreditHoldService",
    "HELD",
    "HoldSettlement",
    "NONE",
    "RELEASED",
    "SETTLED",
]
