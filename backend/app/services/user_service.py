"""
User service for business logic.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_password_hash
from app.core.permissions import Permission
from app.core.roles import VALID_ROLES, get_role_level, is_valid_role
from app.core.security import has_permission
from app.models.user import User


class UserService:
    """User business logic"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> User | None:
        """Get user by ID"""
        result = await self.db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        """Get user by username"""
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Get user by email"""
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def list_users(
        self,
        role: str | None = None,
        status: str | None = None,
        search: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List users with filtering and pagination"""

        # Build query
        query = select(User)

        # Apply filters
        if role and role != "all":
            query = query.where(User.role == role)

        if status:
            if status == "active":
                query = query.where(User.is_active.is_(True))
            elif status == "disabled":
                query = query.where(User.is_active.is_(False))

        if search:
            search_filter = or_(
                User.username.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.first_name.ilike(f"%{search}%"),
                User.last_name.ilike(f"%{search}%"),
            )
            query = query.where(search_filter)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # Apply sorting
        sort_column = getattr(User, sort_by, User.created_at)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Apply pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        users = result.scalars().all()

        return {
            "users": users,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        }

    async def create_user(
        self,
        username: str,
        email: str,
        password: str,
        role: str = "user",
        first_name: str | None = None,
        last_name: str | None = None,
        avatar_url: str | None = None,
        use_gravatar: bool = True,
        credits: int = 500,
        created_by: User | None = None,
    ) -> User:
        """Create a new user"""

        # Validate role
        if not is_valid_role(role):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}",
            )

        # Check username uniqueness
        existing = await self.get_by_username(username)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Username already exists"
            )

        # Check email uniqueness
        existing = await self.get_by_email(email)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

        # Create user
        user = User(
            username=username,
            email=email,
            password_hash=get_password_hash(password),
            role=role,
            first_name=first_name,
            last_name=last_name,
            avatar_url=avatar_url,
            nuke_balance=credits,
            daily_allowance=credits,
            is_active=True,
            is_verified=True,
            preferences={"use_gravatar": use_gravatar},
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def update_user(
        self, user_id: str, data: dict[str, Any], updated_by: User | None = None
    ) -> User:
        """Update user"""
        user = await self.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Update allowed fields
        allowed_fields = [
            "first_name",
            "last_name",
            "email",
            "avatar_url",
            "profile",
            "preferences",
            "profile_visibility",
        ]

        # Only users with users:update permission can update role
        if "role" in data and updated_by:
            if not has_permission(updated_by, Permission.USERS_UPDATE):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions to update role",
                )
            # Hierarchy check: can only modify users at or below your own level
            updater_level = get_role_level(updated_by.role)
            target_level = get_role_level(user.role)
            if target_level > updater_level:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot modify users with higher privileges",
                )
            # Hierarchy check: can only assign roles at or below your own level
            new_role_level = get_role_level(data["role"])
            if new_role_level > updater_level:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot assign roles higher than your own",
                )
            if is_valid_role(data["role"]):
                user.role = data["role"]
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

        # Only users with credits management permission can update credits
        if "nuke_balance" in data and data["nuke_balance"] is not None and updated_by:
            # Only enforce if credits are actually changing
            if user.nuke_balance != data["nuke_balance"]:
                if not has_permission(updated_by, Permission.CREDITS_GRANT) and not has_permission(
                    updated_by, Permission.CREDITS_DEDUCT
                ):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Insufficient permissions to update credits",
                    )
                user.nuke_balance = data["nuke_balance"]

        for field in allowed_fields:
            if field in data:
                setattr(user, field, data[field])

        user.updated_at = datetime.now(UTC).replace(tzinfo=None)
        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def delete_user(self, user_id: str) -> None:
        """Hard delete user. DB-level CASCADE/SET NULL handles related records."""
        import os

        from app.config import settings

        user = await self.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Clean up local avatar files if any exist
        avatars_dir = os.path.join(settings.upload_dir, "avatars")
        if os.path.isdir(avatars_dir):
            for old_file in os.listdir(avatars_dir):
                if old_file.startswith(str(user.id)):
                    os.remove(os.path.join(avatars_dir, old_file))

        await self.db.delete(user)
        await self.db.commit()

    async def disable_user(
        self, user_id: str, disabled: bool = True, reason: str | None = None
    ) -> User:
        """Enable or disable user"""
        user = await self.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        user.is_active = not disabled

        # Update security tracking
        security = dict(user.security or {})
        if disabled:
            security["disabled_reason"] = reason
            security["disabled_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
        else:
            security.pop("disabled_reason", None)
            security.pop("disabled_at", None)

        user.security = security
        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        """Change user password"""
        from app.api.auth import verify_password

        user = await self.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Verify current password
        if not verify_password(current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
            )

        # Update password
        user.password_hash = get_password_hash(new_password)

        # Update security tracking
        security = dict(user.security or {})
        security["password_changed_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
        user.security = security

        await self.db.commit()
        return True

    async def discover_users(self, search: str | None = None, limit: int = 50) -> list[User]:
        """Discover public users for collaboration.

        Returns only users with profile_visibility='public'.
        Filters by username, first_name, or last_name if search is provided.
        """
        query = select(User).where(User.profile_visibility == "public", User.is_active)

        if search:
            search_filter = or_(
                User.username.ilike(f"%{search}%"),
                User.first_name.ilike(f"%{search}%"),
                User.last_name.ilike(f"%{search}%"),
            )
            query = query.where(search_filter)

        query = query.order_by(User.username.asc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_user_stats(self, user_id: str) -> dict[str, Any]:
        """Get user statistics"""
        from app.models.server import Server

        user = await self.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Count servers
        result = await self.db.execute(select(func.count()).where(Server.user_id == user.id))
        server_count = result.scalar()

        result = await self.db.execute(
            select(func.count()).where(and_(Server.user_id == user.id, Server.status == "running"))
        )
        running_count = result.scalar()

        return {
            "user_id": str(user.id),
            "server_count": server_count,
            "running_servers": running_count,
            "nuke_balance": user.nuke_balance,
            "daily_allowance": user.daily_allowance,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
        }
