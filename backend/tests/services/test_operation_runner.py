# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.operation_runner import (
    OperationDeadlineExceeded,
    operation_resources,
    run_operation,
)


def test_deadline_waits_for_cancellation_cleanup():
    events = []

    async def operation():
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            events.append("closed")

    with pytest.raises(OperationDeadlineExceeded) as error:
        run_operation(operation, timeout_seconds=0.001)
    assert error.value.outcome_unknown
    assert events == ["closed"]


def test_suppressed_cancellation_does_not_report_success():
    events = []

    async def operation():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0)
            events.append("late completion")
        return "success"

    with pytest.raises(OperationDeadlineExceeded):
        run_operation(operation, timeout_seconds=0.001)
    assert events == ["late completion"]


def test_unrelated_timeout_retains_original_error():
    async def operation():
        raise TimeoutError("runtime lookup")

    with pytest.raises(TimeoutError, match="runtime lookup") as error:
        run_operation(operation, timeout_seconds=1)
    assert not isinstance(error.value, OperationDeadlineExceeded)


def test_operations_create_separate_loops():
    async def operation():
        return asyncio.get_running_loop()

    first = run_operation(operation, timeout_seconds=1)
    second = run_operation(operation, timeout_seconds=1)
    assert first is not second
    assert first.is_closed() and second.is_closed()


@pytest.mark.asyncio
async def test_runner_refuses_nested_loop_without_constructing_coroutine():
    factory = MagicMock()
    with pytest.raises(RuntimeError, match="active event loop"):
        run_operation(factory, timeout_seconds=1)
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_resources_close_when_operation_fails():
    engine = MagicMock(dispose=AsyncMock())
    driver = MagicMock(close=AsyncMock())
    session = MagicMock()
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    session_factory = MagicMock(return_value=session_context)
    with (
        patch("app.services.operation_runner.create_async_engine", return_value=engine) as create,
        patch("app.services.operation_runner.async_sessionmaker", return_value=session_factory),
        patch("app.services.operation_runner.get_fresh_driver", AsyncMock(return_value=driver)),
    ):
        with pytest.raises(ValueError, match="operation failed"):
            async with operation_resources() as resources:
                assert resources.db is session
                assert resources.driver is driver
                raise ValueError("operation failed")
    assert create.call_args.kwargs["isolation_level"] == "READ COMMITTED"
    driver.close.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    session_context.__aexit__.assert_awaited_once()
