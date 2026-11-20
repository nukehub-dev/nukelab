# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.operation_runner import OperationDeadlineExceeded
from app.services.server_queue_dispatch_service import QueueDispatchResult, run_queue_dispatch


def test_worker_boundary_owns_loop_resources_until_dispatch_finishes():
    events = []
    resources = SimpleNamespace(db=object(), driver=object())

    @asynccontextmanager
    async def acquire():
        events.append("connected")
        try:
            yield resources
        finally:
            events.append("closed")

    async def dispatch(**kwargs):
        assert events == ["connected"]
        assert kwargs == {"batch_size": 7}
        return QueueDispatchResult(started=1)

    with (
        patch("app.services.operation_runner.operation_resources", acquire),
        patch("app.services.server_queue_dispatch_service.ServerQueueDispatchService") as factory,
    ):
        factory.return_value.dispatch = AsyncMock(side_effect=dispatch)
        assert run_queue_dispatch(timeout_seconds=1, batch_size=7).started == 1
        factory.assert_called_once_with(resources.db, resources.driver)
    assert events == ["connected", "closed"]


def test_worker_deadline_joins_cleanup_and_retains_uncertain_outcome():
    events = []

    @asynccontextmanager
    async def acquire():
        try:
            yield SimpleNamespace(db=object(), driver=object())
        finally:
            await asyncio.sleep(0)
            events.append("closed")

    async def dispatch(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            events.append("dispatch finished")

    with (
        patch("app.services.operation_runner.operation_resources", acquire),
        patch("app.services.server_queue_dispatch_service.ServerQueueDispatchService") as factory,
    ):
        factory.return_value.dispatch = AsyncMock(side_effect=dispatch)
        with pytest.raises(OperationDeadlineExceeded) as error:
            run_queue_dispatch(timeout_seconds=0.001)
        assert error.value.outcome_unknown
    assert events == ["dispatch finished", "closed"]
