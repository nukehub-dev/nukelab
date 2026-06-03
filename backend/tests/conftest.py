"""
Test configuration and fixtures for NukeLab backend.
Uses transactional test isolation: each test runs inside a savepoint that is
rolled back at teardown, guaranteeing a clean database state without TRUNCATE.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import NullPool
from sqlalchemy import text

from app.main import app
from app.db.session import get_db
from app.db.base import Base
from app.models.user import User
from app.models.notification import Notification
from app.api.auth import get_password_hash

# Import all models to register them with Base.metadata
from app.models import *

# Test database URL (same server, different database)
TEST_DATABASE_URL = "postgresql+asyncpg://nukelab:nukelab123@postgres:5432/nukelab_test"

# Create test engine with NullPool to avoid connection issues
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    future=True,
    poolclass=NullPool,
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    """Create test database and tables before all tests, drop after."""
    admin_engine = create_async_engine(
        "postgresql+asyncpg://nukelab:nukelab123@postgres:5432/nukelab",
        future=True,
        poolclass=NullPool,
    )

    async with admin_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("DROP DATABASE IF EXISTS nukelab_test"))
        await conn.execute(text("CREATE DATABASE nukelab_test"))

    await admin_engine.dispose()

    # Create all tables in test database
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Patch app.db.session to use test_engine so middleware/tasks also
    # connect to the test database instead of the main database.
    from sqlalchemy.orm import sessionmaker
    import app.db.session as _session_module
    _original_engine = _session_module.engine
    _original_AsyncSessionLocal = _session_module.AsyncSessionLocal
    _session_module.engine = test_engine
    _session_module.AsyncSessionLocal = sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield

    # Restore original engine/sessionmaker
    _session_module.engine = _original_engine
    _session_module.AsyncSessionLocal = _original_AsyncSessionLocal

    # Cleanup: drop tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()
    await admin_engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    """Create a transactional session that rolls back after each test.

    Uses SQLAlchemy's ``join_transaction_mode="create_savepoint"`` so that
    ``session.commit()`` inside fixtures or endpoints commits a savepoint
    within the outer transaction rather than the real transaction.  At
    teardown the outer transaction is rolled back, undoing ALL changes.
    """
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        yield session
        await trans.rollback()
        await session.close()


@pytest.fixture(autouse=True)
def reset_role_permissions():
    """Reset in-memory role permissions to defaults before each test.

    Some tests modify ROLE_PERMISSIONS in memory (e.g. test_permissions.py).
    This fixture ensures subsequent tests start with clean defaults.
    """
    from app.core.roles import ROLE_PERMISSIONS, _DEFAULT_ROLE_PERMISSIONS

    # Restore defaults in-place so all imported references see the change
    for role, perms in _DEFAULT_ROLE_PERMISSIONS.items():
        ROLE_PERMISSIONS[role] = list(perms)
    yield


@pytest_asyncio.fixture
async def client(db_session):
    """Create test client with overridden database dependency."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session):
    """Create a test user."""
    user = User(
        username="testuser",
        email="test@example.com",
        password_hash=get_password_hash("testpass123"),
        first_name="Test",
        last_name="User",
        role="user",
        is_active=True,
        is_verified=True,
        nuke_balance=100,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user


@pytest_asyncio.fixture
async def admin_user(db_session):
    """Create an admin test user."""
    user = User(
        username="adminuser",
        email="admin@example.com",
        password_hash=get_password_hash("adminpass123"),
        first_name="Admin",
        last_name="User",
        role="admin",
        is_active=True,
        is_verified=True,
        nuke_balance=500,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user


@pytest_asyncio.fixture
async def user_token(test_user):
    """Generate JWT token for test user."""
    from app.api.auth import create_access_token

    return create_access_token(
        data={"sub": test_user.username, "role": test_user.role}
    )


@pytest_asyncio.fixture
async def admin_token(admin_user):
    """Generate JWT token for admin user."""
    from app.api.auth import create_access_token

    return create_access_token(
        data={"sub": admin_user.username, "role": admin_user.role}
    )


@pytest_asyncio.fixture
async def moderator_user(db_session):
    """Create a moderator test user."""
    user = User(
        username="moduser",
        email="mod@example.com",
        password_hash=get_password_hash("modpass123"),
        first_name="Mod",
        last_name="User",
        role="moderator",
        is_active=True,
        is_verified=True,
        nuke_balance=200,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user


@pytest_asyncio.fixture
async def support_user(db_session):
    """Create a support test user (no SERVERS_ACCESS_OTHERS)."""
    user = User(
        username="supportuser",
        email="support@example.com",
        password_hash=get_password_hash("supportpass123"),
        first_name="Support",
        last_name="User",
        role="support",
        is_active=True,
        is_verified=True,
        nuke_balance=100,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user


@pytest_asyncio.fixture
async def support_token(support_user):
    """Generate JWT token for support user."""
    from app.api.auth import create_access_token

    return create_access_token(
        data={"sub": support_user.username, "role": support_user.role}
    )


@pytest_asyncio.fixture
async def moderator_token(moderator_user):
    """Generate JWT token for moderator user."""
    from app.api.auth import create_access_token

    return create_access_token(
        data={"sub": moderator_user.username, "role": moderator_user.role}
    )


@pytest_asyncio.fixture
async def superadmin_user(db_session):
    """Create a super_admin test user."""
    user = User(
        username="superadmin",
        email="super@example.com",
        password_hash=get_password_hash("superpass123"),
        first_name="Super",
        last_name="Admin",
        role="super_admin",
        is_active=True,
        is_verified=True,
        nuke_balance=1000,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user


@pytest_asyncio.fixture
async def superadmin_token(superadmin_user):
    """Generate JWT token for super_admin user."""
    from app.api.auth import create_access_token

    return create_access_token(
        data={"sub": superadmin_user.username, "role": superadmin_user.role}
    )


@pytest_asyncio.fixture
async def api_token(db_session, test_user):
    """Create an API token for test user with default scopes."""
    from app.models.api_token import ApiToken
    from app.api.auth import get_password_hash
    import secrets

    raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
    token_hash = get_password_hash(raw_token)
    token_prefix = raw_token[:16]

    token = ApiToken(
        user_id=test_user.id,
        name="Test API Token",
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=["servers:read", "servers:start", "user:read"],
        is_active=True,
    )
    db_session.add(token)
    await db_session.commit()
    await db_session.refresh(token)

    # Return both the DB object and the raw token for tests to use
    from types import SimpleNamespace

    return SimpleNamespace(db_token=token, raw_token=raw_token)
