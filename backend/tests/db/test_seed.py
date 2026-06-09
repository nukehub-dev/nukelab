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

"""Coverage-focused tests for utility modules and easy wins."""

import pytest
from unittest import mock
from cryptography.fernet import InvalidToken

class TestDbSeed:
    """app/db/seed.py coverage."""

    @pytest.mark.asyncio
    async def test_seed_admin_user_dev_mode(self, db_session):
        from app.db.seed import seed_admin_user
        with mock.patch("app.db.seed.settings.dev_mode", True):
            with mock.patch("app.db.seed.settings.dev_admin_user", "seedadmin"):
                with mock.patch("app.db.seed.settings.dev_admin_password", "seedpass"):
                    await seed_admin_user(db_session)
                    from app.models.user import User
                    result = await db_session.execute(
                        __import__('sqlalchemy').select(User).where(User.username == "seedadmin")
                    )
                    user = result.scalar_one_or_none()
                    assert user is not None
                    assert user.role == "admin"

    @pytest.mark.asyncio
    async def test_seed_admin_user_not_dev_mode(self, db_session):
        from app.db.seed import seed_admin_user
        with mock.patch("app.db.seed.settings.dev_mode", False):
            result = await seed_admin_user(db_session)
            assert result is None

    @pytest.mark.asyncio
    async def test_seed_admin_user_already_exists(self, db_session, test_user):
        from app.db.seed import seed_admin_user
        with mock.patch("app.db.seed.settings.dev_mode", True):
            with mock.patch("app.db.seed.settings.dev_admin_user", test_user.username):
                result = await seed_admin_user(db_session)
                assert result is None

    @pytest.mark.asyncio
    async def test_seed_plans(self, db_session):
        from app.db.seed import seed_plans
        await seed_plans(db_session)
        from app.models.server_plan import ServerPlan
        result = await db_session.execute(
            __import__('sqlalchemy').select(ServerPlan).where(ServerPlan.slug == "small")
        )
        plan = result.scalar_one_or_none()
        assert plan is not None

    @pytest.mark.asyncio
    async def test_seed_plans_idempotent(self, db_session):
        from app.db.seed import seed_plans
        await seed_plans(db_session)
        await seed_plans(db_session)

    @pytest.mark.asyncio
    async def test_seed_plans_exception_handling(self, db_session):
        """Should log error when plan creation fails."""
        from app.db.seed import seed_plans
        from app.services.plan_service import PlanService

        with mock.patch.object(PlanService, "get_by_slug", side_effect=Exception("db error")):
            await seed_plans(db_session)  # should not raise

    @pytest.mark.asyncio
    async def test_seed_all(self, db_session):
        """seed_all should run both seeders."""
        from app.db.seed import seed_all

        class _AsyncCtx:
            def __init__(self, obj):
                self._obj = obj
            async def __aenter__(self):
                return self._obj
            async def __aexit__(self, *args):
                return False

        def _fake_session():
            return _AsyncCtx(db_session)

        with mock.patch("app.db.seed.async_session", _fake_session):
            with mock.patch("app.db.seed.settings.dev_mode", True):
                with mock.patch("app.db.seed.settings.dev_admin_user", "seedalladmin"):
                    with mock.patch("app.db.seed.settings.dev_admin_password", "seedallpass"):
                        await seed_all()

        from sqlalchemy import select
        from app.models.user import User
        result = await db_session.execute(select(User).where(User.username == "seedalladmin"))
        user = result.scalar_one_or_none()
        assert user is not None



