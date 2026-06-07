import time
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings
from app.core.logging import get_logger

engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    future=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_pool_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    pool_recycle=settings.database_pool_recycle,
    pool_pre_ping=settings.database_pool_pre_ping,
    connect_args={
        "command_timeout": settings.database_query_timeout_seconds,
    },
)

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
