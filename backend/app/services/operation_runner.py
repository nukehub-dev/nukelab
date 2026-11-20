# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Joined, loop-owned execution for long Celery operations."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.container.driver import ContainerDriver
from app.container.factory import get_fresh_driver


class OperationDeadlineExceeded(TimeoutError):
    """The waiter finished; external effects still require reconciliation.

    This exception never authorizes releasing a runtime/volume reservation.
    """

    outcome_unknown = True


def run_operation[T](operation: Callable[[], Awaitable[T]], *, timeout_seconds: float) -> T:
    """Run in the current Celery thread and join cancellation before returning.

    The factory creates resources inside the operation loop. Cancellation is
    cooperative: if work suppresses it, this call keeps ownership until that work
    returns. An external helper may still require inspection after loop cleanup.
    """
    if timeout_seconds <= 0:
        raise ValueError("Operation timeout must be positive")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("run_operation cannot run inside an active event loop")

    async def execute() -> T:
        deadline = asyncio.timeout(timeout_seconds)
        try:
            async with deadline:
                result = await operation()
        except TimeoutError as exc:
            if deadline.expired():
                raise OperationDeadlineExceeded("Operation deadline exceeded") from exc
            raise
        if deadline.expired():
            raise OperationDeadlineExceeded("Operation completed after its deadline")
        return result

    return asyncio.run(execute())


@dataclass
class OperationResources:
    db: AsyncSession
    driver: ContainerDriver


@asynccontextmanager
async def operation_resources():
    """Allocate DB/driver resources within one job loop; close before loop exit."""
    connect_args: dict[str, Any] = {
        "command_timeout": settings.database_query_timeout_seconds,
    }
    if settings.pgbouncer_enabled:
        connect_args.update(statement_cache_size=0, prepared_statement_name_func=lambda: "")
    database_url = (
        settings.database_pgbouncer_url if settings.pgbouncer_enabled else settings.database_url
    )
    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        isolation_level="READ COMMITTED",
        connect_args=connect_args,
        echo=settings.database_echo,
    )
    driver = None
    try:
        driver = await get_fresh_driver()
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            yield OperationResources(db=db, driver=driver)
    finally:
        try:
            if driver is not None:
                await driver.close()
        finally:
            await engine.dispose()
