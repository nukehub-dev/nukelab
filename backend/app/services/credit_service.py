"""
Credit service for managing user credits.
"""

import uuid
from datetime import datetime, timedelta, UTC
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status

from app.models.user import User
from app.models.credit_transaction import CreditTransaction
from app.services.notification_service import NotificationService
from app.core.logging import get_logger

logger = get_logger(__name__)


class CreditService:
    """Credit business logic"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_balance(self, user_id: str) -> int:
        """Get user's current credit balance"""
        result = await self.db.execute(
            select(User.nuke_balance).where(User.id == uuid.UUID(user_id))
        )
        balance = result.scalar_one_or_none()
        return balance if balance is not None else 0

    async def get_transaction_history(
        self,
        user_id: str,
        transaction_type: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        limit: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        """Get user's credit transaction history"""

        query = select(CreditTransaction).where(CreditTransaction.user_id == uuid.UUID(user_id))

        if transaction_type:
            query = query.where(CreditTransaction.type == transaction_type)

        if from_date:
            query = query.where(CreditTransaction.created_at >= from_date)

        if to_date:
            query = query.where(CreditTransaction.created_at <= to_date)

        # Dynamic sorting
        sort_column = getattr(CreditTransaction, sort_by, CreditTransaction.created_at)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # Apply pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        transactions = result.scalars().all()

        return {
            "transactions": [t.to_dict() for t in transactions],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        }

    async def _create_transaction(
        self,
        user_id: str,
        amount: int,
        transaction_type: str,
        description: str,
        actor_id: Optional[str] = None,
        server_id: Optional[str] = None,
        meta: Optional[Dict] = None,
    ) -> CreditTransaction:
        """Create a credit transaction and update user balance"""

        # Get current balance
        current_balance = await self.get_balance(user_id)
        new_balance = current_balance + amount

        if new_balance < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient credits. Current: {current_balance}, Required: {abs(amount)}",
            )

        # Update user balance
        result = await self.db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one()
        user.nuke_balance = new_balance

        # Create transaction record
        transaction = CreditTransaction(
            user_id=uuid.UUID(user_id),
            amount=amount,
            balance_after=new_balance,
            type=transaction_type,
            description=description,
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            server_id=uuid.UUID(server_id) if server_id else None,
            meta=meta or {},
        )

        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)

        return transaction

    async def grant_daily_allowance(self, user_id: str) -> CreditTransaction:
        """Grant daily allowance to a user"""
        result = await self.db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found or inactive"
            )

        # Check if already granted today
        today_start = (
            datetime.now(UTC)
            .replace(tzinfo=None)
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )
        result = await self.db.execute(
            select(CreditTransaction).where(
                and_(
                    CreditTransaction.user_id == uuid.UUID(user_id),
                    CreditTransaction.type == "daily_allowance",
                    CreditTransaction.created_at >= today_start,
                )
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Daily allowance already granted today",
            )

        transaction = await self._create_transaction(
            user_id=user_id,
            amount=user.daily_allowance,
            transaction_type="daily_allowance",
            description=f"Daily allowance: {user.daily_allowance} credits",
        )

        # Notify user
        notif_service = NotificationService(self.db)
        await notif_service.daily_allowance(
            user_id=user_id, amount=user.daily_allowance, new_balance=transaction.balance_after
        )

        return transaction

    async def consume_credits(
        self, user_id: str, amount: int, description: str, server_id: Optional[str] = None
    ) -> CreditTransaction:
        """Consume credits for server usage"""
        return await self._create_transaction(
            user_id=user_id,
            amount=-amount,
            transaction_type="server_usage",
            description=description,
            server_id=server_id,
        )

    async def reconcile_server_billing(self, server, plan) -> int:
        """
        Reconcile exact billing when a server stops.
        Calculates exact runtime cost and bills the difference
        from what was already charged via periodic ticks.
        Returns the additional amount billed (0 if nothing to bill).
        """
        if not server.started_at or not server.stopped_at:
            return 0
        if not plan or plan.cost_per_hour <= 0:
            return 0

        # Exact runtime in seconds
        duration = server.stopped_at - server.started_at
        duration_seconds = duration.total_seconds()

        if duration_seconds <= 0:
            return 0

        # Exact cost for the full runtime
        exact_cost = int((duration_seconds / 3600) * plan.cost_per_hour)
        if exact_cost <= 0:
            exact_cost = 1  # Minimum 1 credit

        # What was already billed via ticks
        already_billed = server.total_cost or 0

        # Amount still owed
        additional_cost = exact_cost - already_billed

        if additional_cost > 0:
            # Check balance first; if insufficient, record what we can and move on
            # (server stopping must never be blocked by credit issues)
            balance = await self.get_balance(str(server.user_id))
            if balance >= additional_cost:
                await self.consume_credits(
                    user_id=str(server.user_id),
                    amount=additional_cost,
                    description=f"Server usage reconciliation: '{server.name}' ({self._format_duration(duration_seconds)} at {plan.cost_per_hour} NUKE/hour)",
                    server_id=str(server.id),
                )
                server.total_cost = already_billed + additional_cost
                return additional_cost
            else:
                # Charge what we can, mark remainder as debt (balance hits 0)
                if balance > 0:
                    await self.consume_credits(
                        user_id=str(server.user_id),
                        amount=balance,
                        description=f"Partial server usage reconciliation: '{server.name}' ({self._format_duration(duration_seconds)} at {plan.cost_per_hour} NUKE/hour). Remaining {additional_cost - balance} NUKE unpaid.",
                        server_id=str(server.id),
                    )
                    server.total_cost = already_billed + balance
                # Log unpaid amount for future reference
                logger.warning(
                    "[CREDIT] Server %s stopped with unpaid balance: %s NUKE (user had %s)",
                    server.id,
                    additional_cost - balance,
                    balance,
                )
                return balance if balance > 0 else 0

        return 0

    def _format_duration(self, seconds: int) -> str:
        """Format seconds into a human-readable duration"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    async def grant_credits(
        self, user_id: str, amount: int, actor_id: str, reason: str
    ) -> CreditTransaction:
        """Grant credits to a user (admin action)"""
        return await self._create_transaction(
            user_id=user_id,
            amount=amount,
            transaction_type="admin_grant",
            description=f"Admin grant: {reason}",
            actor_id=actor_id,
            meta={"reason": reason},
        )

    async def deduct_credits(
        self, user_id: str, amount: int, actor_id: str, reason: str
    ) -> CreditTransaction:
        """Deduct credits from a user (admin action)"""
        return await self._create_transaction(
            user_id=user_id,
            amount=-amount,
            transaction_type="admin_deduct",
            description=f"Admin deduction: {reason}",
            actor_id=actor_id,
            meta={"reason": reason},
        )

    async def check_sufficient_credits(self, user_id: str, required: int) -> bool:
        """Check if user has sufficient credits"""
        balance = await self.get_balance(user_id)
        return balance >= required

    async def get_low_credit_users(
        self, threshold: int = 100, page: int = 1, limit: int = 50
    ) -> Dict[str, Any]:
        """Get users with low credits"""
        # Get total count
        count_query = select(func.count()).select_from(
            select(User)
            .where(and_(User.is_active == True, User.nuke_balance <= threshold))
            .subquery()
        )
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # Get paginated results
        offset = (page - 1) * limit
        result = await self.db.execute(
            select(User)
            .where(and_(User.is_active == True, User.nuke_balance <= threshold))
            .order_by(User.nuke_balance.asc())
            .offset(offset)
            .limit(limit)
        )
        users = result.scalars().all()

        return {
            "count": total,
            "users": [
                {
                    "id": str(u.id),
                    "username": u.username,
                    "nuke_balance": u.nuke_balance,
                    "daily_allowance": u.daily_allowance,
                    "email": u.email,
                }
                for u in users
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        }

    async def get_credit_summary(self, user_id: str) -> Dict[str, Any]:
        """Get credit summary for a user"""
        balance = await self.get_balance(user_id)

        # Get today's consumption
        today_start = (
            datetime.now(UTC)
            .replace(tzinfo=None)
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )
        result = await self.db.execute(
            select(func.sum(CreditTransaction.amount)).where(
                and_(
                    CreditTransaction.user_id == uuid.UUID(user_id),
                    CreditTransaction.created_at >= today_start,
                    CreditTransaction.type == "server_usage",
                )
            )
        )
        today_consumed = result.scalar() or 0

        # Get total earned
        result = await self.db.execute(
            select(func.sum(CreditTransaction.amount)).where(
                and_(CreditTransaction.user_id == uuid.UUID(user_id), CreditTransaction.amount > 0)
            )
        )
        total_earned = result.scalar() or 0

        # Get total consumed
        result = await self.db.execute(
            select(func.sum(CreditTransaction.amount)).where(
                and_(CreditTransaction.user_id == uuid.UUID(user_id), CreditTransaction.amount < 0)
            )
        )
        total_consumed = abs(result.scalar() or 0)

        return {
            "user_id": user_id,
            "current_balance": balance,
            "today_consumed": abs(today_consumed),
            "total_earned": total_earned,
            "total_consumed": total_consumed,
        }
