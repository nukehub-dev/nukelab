import time
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.config import settings
from app.core.logging import get_logger

# When DATABASE_PGBOUNCER_URL is set, the app routes through PgBouncer.
# In that mode we disable asyncpg prepared statements (transaction pooling
# breaks them) and switch SQLAlchemy to NullPool so PgBouncer is the single
# source of truth for connection pooling.
_use_pgbouncer = bool(settings.database_pgbouncer_url and settings.database_pgbouncer_url.strip())

_connect_args: dict = {
    "command_timeout": settings.database_query_timeout_seconds,
}
if _use_pgbouncer:
    _connect_args["statement_cache_size"] = 0
    _connect_args["prepared_statement_name_func"] = lambda: ""

# Build engine kwargs. When PgBouncer is the pooler, disable SQLAlchemy
# client-side pooling (NullPool) to avoid double-pooling and connection
# storms at scale.
_engine_kwargs: dict = {
    "echo": settings.database_echo,
    "future": True,
    "connect_args": _connect_args,
}

if _use_pgbouncer:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
        pool_pre_ping=settings.database_pool_pre_ping,
    )

# Select the appropriate database URL.
_db_url = settings.database_pgbouncer_url if _use_pgbouncer else settings.database_url
engine = create_async_engine(_db_url, **_engine_kwargs)

# ── SQLAlchemy slow query logging (gated by config) ─────────────────────────
def _attach_slow_query_listener():
    """Attach event listeners if slow-query logging is enabled in settings."""
    threshold = settings.observability_slow_query_threshold_ms
    if threshold <= 0:
        return  # Disabled via configuration

    logger = get_logger("sqlalchemy.slow_query")

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        total_time = (time.perf_counter() - context._query_start_time) * 1000
        if total_time > threshold:
            logger.warning(
                "Slow SQL query detected",
                extra={
                    "duration_ms": round(total_time, 2),
                    "statement": statement[:500],
                    "parameters": str(parameters)[:200],
                }
            )


_attach_slow_query_listener()

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


# Export async_session for seed scripts
async_session = AsyncSessionLocal


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
