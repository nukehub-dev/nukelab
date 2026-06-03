"""Tests for database seeding."""

import pytest
from unittest import mock

from app.db.seed import seed_admin_user, seed_plans


class TestSeedAdminUser:
    @pytest.mark.asyncio
    async def test_skips_when_not_dev_mode(self, db_session):
        with mock.patch("app.db.seed.settings.dev_mode", False):
            await seed_admin_user(db_session)
        # Should not create anything

    @pytest.mark.asyncio
    async def test_creates_admin_when_not_exists(self, db_session):
        with mock.patch("app.db.seed.settings.dev_mode", True):
            with mock.patch("app.db.seed.settings.dev_admin_user", "devadmin"):
                with mock.patch("app.db.seed.settings.dev_admin_password", "devpass123"):
                    await seed_admin_user(db_session)

        from sqlalchemy import select
        from app.models.user import User
        result = await db_session.execute(select(User).where(User.username == "devadmin"))
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.role == "admin"
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_skips_when_admin_exists(self, db_session):
        from app.models.user import User
        from app.api.auth import get_password_hash
        existing = User(
            username="seedtest",
            email="seedtest@nukelab.local",
            password_hash=get_password_hash("pass"),
            role="admin",
            is_active=True,
            is_verified=True,
        )
        db_session.add(existing)
        await db_session.commit()

        with mock.patch("app.db.seed.settings.dev_mode", True):
            with mock.patch("app.db.seed.settings.dev_admin_user", "seedtest"):
                await seed_admin_user(db_session)

        # Should still be only one
        from sqlalchemy import select, func
        result = await db_session.execute(select(func.count()).select_from(User).where(User.username == "seedtest"))
        assert result.scalar() == 1


class TestSeedPlans:
    @pytest.mark.asyncio
    async def test_creates_default_plans(self, db_session):
        await seed_plans(db_session)

        from sqlalchemy import select
        from app.models.server_plan import ServerPlan
        result = await db_session.execute(select(ServerPlan).where(ServerPlan.slug == "small"))
        plan = result.scalar_one_or_none()
        assert plan is not None
        assert plan.name == "Small"

    @pytest.mark.asyncio
    async def test_skips_existing_plans(self, db_session):
        await seed_plans(db_session)
        # Run again
        await seed_plans(db_session)

        from sqlalchemy import select, func
        from app.models.server_plan import ServerPlan
        result = await db_session.execute(select(func.count()).select_from(ServerPlan))
        # Should not duplicate
        assert result.scalar() == 4
