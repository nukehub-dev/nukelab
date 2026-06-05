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



