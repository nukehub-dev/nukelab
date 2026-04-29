"""
Credit service for managing user credits.
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status

from app.models.user import User
from app.models.credit_transaction import CreditTransaction


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
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get user's credit transaction history"""
        
        query = select(CreditTransaction).where(
            CreditTransaction.user_id == uuid.UUID(user_id)
        )
        
        if transaction_type:
            query = query.where(CreditTransaction.type == transaction_type)
        
        if from_date:
            query = query.where(CreditTransaction.created_at >= from_date)
        
        if to_date:
            query = query.where(CreditTransaction.created_at <= to_date)
        
        query = query.order_by(CreditTransaction.created_at.desc())
        
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
                "total_pages": (total + limit - 1) // limit
            }
        }
    
    async def _create_transaction(
        self,
        user_id: str,
        amount: int,
        transaction_type: str,
        description: str,
        actor_id: Optional[str] = None,
        server_id: Optional[str] = None,
        meta: Optional[Dict] = None
    ) -> CreditTransaction:
        """Create a credit transaction and update user balance"""
        
        # Get current balance
        current_balance = await self.get_balance(user_id)
        new_balance = current_balance + amount
        
        if new_balance < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient credits. Current: {current_balance}, Required: {abs(amount)}"
            )
        
        # Update user balance
        result = await self.db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
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
            meta=meta or {}
        )
        
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        
        return transaction
    
    async def grant_daily_allowance(self, user_id: str) -> CreditTransaction:
        """Grant daily allowance to a user"""
        result = await self.db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found or inactive"
            )
        
        # Check if already granted today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.db.execute(
            select(CreditTransaction).where(
                and_(
                    CreditTransaction.user_id == uuid.UUID(user_id),
                    CreditTransaction.type == "daily_allowance",
                    CreditTransaction.created_at >= today_start
                )
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Daily allowance already granted today"
            )
        
        return await self._create_transaction(
            user_id=user_id,
            amount=user.daily_allowance,
            transaction_type="daily_allowance",
            description=f"Daily allowance: {user.daily_allowance} credits"
        )
    
    async def consume_credits(
        self,
        user_id: str,
        amount: int,
        description: str,
        server_id: Optional[str] = None
    ) -> CreditTransaction:
        """Consume credits for server usage"""
        return await self._create_transaction(
            user_id=user_id,
            amount=-amount,
            transaction_type="server_usage",
            description=description,
            server_id=server_id
        )
    
    async def grant_credits(
        self,
        user_id: str,
        amount: int,
        actor_id: str,
        reason: str
    ) -> CreditTransaction:
        """Grant credits to a user (admin action)"""
        return await self._create_transaction(
            user_id=user_id,
            amount=amount,
            transaction_type="admin_grant",
            description=f"Admin grant: {reason}",
            actor_id=actor_id,
            meta={"reason": reason}
        )
    
    async def deduct_credits(
        self,
        user_id: str,
        amount: int,
        actor_id: str,
        reason: str
    ) -> CreditTransaction:
        """Deduct credits from a user (admin action)"""
        return await self._create_transaction(
            user_id=user_id,
            amount=-amount,
            transaction_type="admin_deduct",
            description=f"Admin deduction: {reason}",
            actor_id=actor_id,
            meta={"reason": reason}
        )
    
    async def check_sufficient_credits(
        self,
        user_id: str,
        required: int
    ) -> bool:
        """Check if user has sufficient credits"""
        balance = await self.get_balance(user_id)
        return balance >= required
    
    async def get_low_credit_users(
        self,
        threshold: int = 100
    ) -> List[Dict[str, Any]]:
        """Get users with low credits"""
        result = await self.db.execute(
            select(User).where(
                and_(
                    User.is_active == True,
                    User.nuke_balance <= threshold
                )
            ).order_by(User.nuke_balance.asc())
        )
        users = result.scalars().all()
        
        return [
            {
                "id": str(u.id),
                "username": u.username,
                "nuke_balance": u.nuke_balance,
                "daily_allowance": u.daily_allowance,
                "email": u.email,
            }
            for u in users
        ]
    
    async def get_credit_summary(self, user_id: str) -> Dict[str, Any]:
        """Get credit summary for a user"""
        balance = await self.get_balance(user_id)
        
        # Get today's consumption
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.db.execute(
            select(func.sum(CreditTransaction.amount)).where(
                and_(
                    CreditTransaction.user_id == uuid.UUID(user_id),
                    CreditTransaction.created_at >= today_start,
                    CreditTransaction.type == "server_usage"
                )
            )
        )
        today_consumed = result.scalar() or 0
        
        # Get total earned
        result = await self.db.execute(
            select(func.sum(CreditTransaction.amount)).where(
                and_(
                    CreditTransaction.user_id == uuid.UUID(user_id),
                    CreditTransaction.amount > 0
                )
            )
        )
        total_earned = result.scalar() or 0
        
        # Get total consumed
        result = await self.db.execute(
            select(func.sum(CreditTransaction.amount)).where(
                and_(
                    CreditTransaction.user_id == uuid.UUID(user_id),
                    CreditTransaction.amount < 0
                )
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
