"""
Test configuration and fixtures for NukeLab backend tests.
Uses isolated test database with table truncation for clean state between tests.
"""

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
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

# Test session factory
TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# List of tables to truncate (in reverse dependency order)
TRUNCATE_TABLES = [
    "alert_history",
    "alert_rules",
    "server_metrics",
    "server_queue",
    "credit_transactions",
    "notifications",
    "resource_quotas",
    "environment_templates",
    "server_volumes",
    "workspace_volumes",
    "user_plan_access",
    "workspace_plan_access",
    "workspace_members",
    "shared_workspaces",
    "servers",
    "volumes",
    "api_tokens",
    "system_metrics",
    "health_checks",
    "activity_logs",
    "server_plans",
    "refresh_tokens",
    "users",
]


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    """Create test database and tables before all tests, drop after."""
    # Connect to default database to create test database
    admin_engine = create_async_engine(
        "postgresql+asyncpg://nukelab:nukelab123@postgres:5432/nukelab",
        future=True,
        poolclass=NullPool,
    )
    
    async with admin_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        # Drop and recreate test database
        try:
            await conn.execute(text("DROP DATABASE IF EXISTS nukelab_test"))
        except Exception:
            pass
        await conn.execute(text("CREATE DATABASE nukelab_test"))
    
    await admin_engine.dispose()
    
    # Create all tables in test database
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # Cleanup
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    """Create a fresh database session for each test."""
    async with TestSessionLocal() as session:
        yield session
        await session.close()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(db_session):
    """Truncate all tables before each test to ensure clean state."""
    for table in TRUNCATE_TABLES:
        try:
            await db_session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
        except Exception:
            pass  # Table might not exist
    await db_session.commit()
    yield


@pytest_asyncio.fixture
async def client(db_session):
    """Create test client with overridden database dependency."""
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
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
    # Cleanup happens via clean_tables fixture


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
    # Cleanup happens via clean_tables fixture


@pytest_asyncio.fixture
async def user_token(test_user):
    """Generate JWT token for test user."""
    from app.api.auth import create_access_token
    return create_access_token(data={"sub": test_user.username})


@pytest_asyncio.fixture
async def admin_token(admin_user):
    """Generate JWT token for admin user."""
    from app.api.auth import create_access_token
    return create_access_token(data={"sub": admin_user.username})


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
