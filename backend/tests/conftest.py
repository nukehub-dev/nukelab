"""
Test configuration and fixtures for NukeLab backend.
Uses transactional test isolation: each test runs inside a savepoint that is
rolled back at teardown, guaranteeing a clean database state without TRUNCATE.
"""

import os

# Force all app code to connect to the test database.  Must happen BEFORE any
# app module is imported so that app.db.session.engine is created with the test
# URL and every module that imports AsyncSessionLocal gets a sessionmaker
# bound to the test database.
TEST_DATABASE_URL = "postgresql+asyncpg://nukelab:nukelab123@postgres:5432/nukelab_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import asyncio

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

# Create test engine with NullPool to avoid connection issues
# Each test gets a fresh connection that is closed immediately after
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
        # Force-close any leftover connections from a previous aborted run
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = 'nukelab_test' AND pid <> pg_backend_pid()"
            )
        )
        # Wait up to 3s for backends to actually terminate before dropping
        for _ in range(30):
            result = await conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = 'nukelab_test' AND pid <> pg_backend_pid()"
                )
            )
            remaining = result.scalar()
            if remaining == 0:
                break
            await asyncio.sleep(0.1)
        await conn.execute(text("DROP DATABASE IF EXISTS nukelab_test"))
        await conn.execute(text("CREATE DATABASE nukelab_test"))

    await admin_engine.dispose()

    # Create pg_stat_statements extension in test database (matches production)
    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))

    # Create all tables in test database
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Create partitions for time-series tables so INSERTs don't fail
    from datetime import datetime, timezone
    from dateutil.relativedelta import relativedelta

    now = datetime.now(timezone.utc)
    start = now.strftime("%Y-%m-01")
    end = (now + relativedelta(months=1)).strftime("%Y-%m-01")
    partitioned = {
        "activity_logs": "created_at",
        "server_metrics": "collected_at",
        "request_metrics": "created_at",
    }
    async with test_engine.begin() as conn:
        for table in partitioned:
            await conn.execute(
                text(f'CREATE TABLE IF NOT EXISTS "{table}_default" PARTITION OF "{table}" DEFAULT')
            )
            part_name = f"{table}_y{now.year}m{now.month:02d}"
            await conn.execute(
                text(
                    f'CREATE TABLE IF NOT EXISTS "{part_name}" PARTITION OF "{table}" '
                    f"FOR VALUES FROM ('{start}') TO ('{end}')"
                )
            )

    # Patch the global engine/sessionmaker so middleware, tasks, and any code
    # that imports AsyncSessionLocal directly use the test database.  This is
    # the same technique that commit 0830330756 used and is needed because
    # some modules cache the engine/sessionmaker at import time.
    #
    # We use a separate pooled engine (not the NullPool test_engine) so that
    # the dispose_stale_pool fixture can forcibly close any leaked connections
    # between tests instead of relying on every session to be closed explicitly.
    import app.db.session as _session_module
    from sqlalchemy.orm import sessionmaker

    _original_engine = _session_module.engine
    _original_async_session_local = _session_module.AsyncSessionLocal

    _patched_engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
        pool_size=5,
        max_overflow=10,
        pool_timeout=10,
        pool_recycle=300,
        pool_pre_ping=True,
    )
    _session_module.engine = _patched_engine
    _session_module.AsyncSessionLocal = sessionmaker(
        _patched_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield

    # Close any leaked connections on the patched engine before restoring.
    await _patched_engine.dispose()

    # Restore original engine/sessionmaker before teardown so the live dev
    # server (if it shares the module) is not left pointing at the patched engine.
    _session_module.engine = _original_engine
    _session_module.AsyncSessionLocal = _original_async_session_local

    # Cleanup: terminate any leaked connections (e.g. from middleware background
    # tasks) so DROP TABLE doesn't hang waiting for locks.
    async with admin_engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = 'nukelab_test' AND pid <> pg_backend_pid()"
            )
        )
        for _ in range(30):
            result = await conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = 'nukelab_test' AND pid <> pg_backend_pid()"
                )
            )
            remaining = result.scalar()
            if remaining == 0:
                break
            await asyncio.sleep(0.1)

    # Cleanup: drop tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()
    await admin_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def dispose_stale_pool():
    """Dispose all global SQLAlchemy engine pools before every test.

    pytest-asyncio creates a fresh event loop for each async test.  The
    module-level ``app.db.session.engine`` (used by middleware, tasks, etc.)
    keeps connections in its pool that are tied to the *previous* test's
    event loop.  When asyncpg tries to reuse one of those connections it
    can either raise ``RuntimeError: Event loop is closed`` or, worse, the
    ``pool_pre_ping`` checkout can hang indefinitely.  Disposing the pool
    *before* every test guarantees the test starts with a clean set of
    connections.

    We also dispose ``app.main.engine`` because many modules imported
    ``AsyncSessionLocal`` at load time, binding them to the original engine
    rather than the patched test engine.
    """
    from sqlalchemy.ext.asyncio import AsyncEngine

    import app.db.session as _session_module

    if isinstance(_session_module.engine, AsyncEngine):
        await _session_module.engine.dispose()
    try:
        from app.main import engine as _main_engine

        if isinstance(_main_engine, AsyncEngine):
            await _main_engine.dispose()
    except Exception:
        pass
    yield


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
def reset_maintenance_mode():
    """Reset maintenance mode to disabled before and after each test.

    Tests that toggle maintenance mode via the system API mutate the global
    settings singleton.  This fixture ensures subsequent tests don't get
    503 Service Unavailable from MaintenanceMiddleware.
    """
    from app.config import settings

    settings.maintenance_mode = False
    settings.maintenance_message = ""
    yield
    settings.maintenance_mode = False
    settings.maintenance_message = ""


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

    # Rebuild the expansion cache so permission lookups reflect the reset
    from app.core.roles import _rebuild_expansion_cache

    _rebuild_expansion_cache()
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

    return create_access_token(data={"sub": test_user.username, "role": test_user.role})


@pytest_asyncio.fixture
async def admin_token(admin_user):
    """Generate JWT token for admin user."""
    from app.api.auth import create_access_token

    return create_access_token(data={"sub": admin_user.username, "role": admin_user.role})


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

    return create_access_token(data={"sub": support_user.username, "role": support_user.role})


@pytest_asyncio.fixture
async def moderator_token(moderator_user):
    """Generate JWT token for moderator user."""
    from app.api.auth import create_access_token

    return create_access_token(data={"sub": moderator_user.username, "role": moderator_user.role})


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

    return create_access_token(data={"sub": superadmin_user.username, "role": superadmin_user.role})


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


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the slowapi rate limiter before each test to avoid 429 errors."""
    from app.api.auth import limiter

    if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
        limiter._storage.reset()
    # Also clear Redis-backed rate limit keys used by RateLimitMiddleware
    try:
        import redis as sync_redis
        from app.config import settings

        sync_r = sync_redis.from_url(settings.redis_url)
        keys = sync_r.keys("rl:*")
        if keys:
            sync_r.delete(*keys)
        sync_r.close()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def reset_cache():
    """Flush Redis DB before each test to prevent cross-test state leakage.
    This clears ALL keys (cache, rate limits, WebSocket state, etc.).
    Safe because tests run in isolation with no concurrent app traffic.
    """
    try:
        import redis as sync_redis
        from app.config import settings

        sync_r = sync_redis.from_url(settings.redis_url)
        sync_r.flushdb()
        sync_r.close()
    except Exception:
        pass
    yield


@pytest_asyncio.fixture(autouse=True)
async def reset_cached_redis_clients():
    """Close and clear all cached Redis client references before each test.

    Redis clients created by a previous test's event loop become invalid
    when pytest-asyncio closes that loop and opens a new one. Using a
    stale client causes 'Event loop is closed' errors.
    """
    # 1. Global Redis client singleton
    try:
        from app.core import redis_client as _rc

        if _rc._redis_client is not None:
            await _rc._redis_client.aclose()
            _rc._redis_client = None
    except Exception:
        pass

    # 2. MetricsWebSocketManager singleton
    try:
        from app.websocket.metrics_socket import manager as _ws_mgr

        if _ws_mgr.redis_client is not None:
            await _ws_mgr.redis_client.aclose()
            _ws_mgr.redis_client = None
        _ws_mgr._running = False
        _ws_mgr._shutting_down = False
    except Exception:
        pass

    yield


@pytest.fixture(autouse=True)
def reset_ip_restriction_cache():
    """Reset IP restriction in-memory cache before each test."""
    from app.middleware.ip_restriction import _invalidate_cache

    _invalidate_cache()
    yield


@pytest.fixture(autouse=True)
def reset_shutdown_coordinator():
    """Reset global shutdown coordinator before each test."""
    from app.core.shutdown import reset_shutdown_coordinator

    reset_shutdown_coordinator()
    yield


@pytest.fixture(autouse=True)
def cleanup_tmp_cache_files():
    """Remove temporary cache files created by system metrics collector."""
    import os
    import glob

    for f in glob.glob("/tmp/nukelab_*_cache.json"):
        try:
            os.remove(f)
        except OSError:
            pass
    yield
    # Also cleanup after test
    for f in glob.glob("/tmp/nukelab_*_cache.json"):
        try:
            os.remove(f)
        except OSError:
            pass
