# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for graceful shutdown coordinator."""

import asyncio
from unittest import mock

import pytest

from app.core.shutdown import (
    ShutdownCoordinator,
    get_shutdown_coordinator,
    is_shutting_down,
    reset_shutdown_coordinator,
)


class TestShutdownCoordinator:
    """Shutdown sequence tests."""

    def test_register_background_task(self):
        coord = ShutdownCoordinator()
        task = mock.Mock(spec=asyncio.Task)
        coord.register_background_task(task)
        assert task in coord._background_tasks

    @pytest.mark.asyncio
    async def test_cancel_background_tasks(self):
        coord = ShutdownCoordinator()

        async def dummy_task():
            await asyncio.sleep(100)

        task = asyncio.create_task(dummy_task())
        coord.register_background_task(task)

        await coord._cancel_background_tasks()

        assert task.done()
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_cancel_background_tasks_with_timeout(self):
        coord = ShutdownCoordinator()

        async def stubborn_task():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                # Swallow cancellation — should still be handled
                await asyncio.sleep(100)

        task = asyncio.create_task(stubborn_task())
        coord.register_background_task(task)

        # Should not hang indefinitely
        await asyncio.wait_for(coord._cancel_background_tasks(), timeout=10.0)

    @pytest.mark.asyncio
    async def test_shutdown_closes_websockets(self):
        coord = ShutdownCoordinator()
        ws_manager = mock.AsyncMock()

        await coord.shutdown(websocket_manager=ws_manager)

        ws_manager.close_all_connections.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_flushes_metrics(self):
        coord = ShutdownCoordinator()
        metrics_buf = mock.AsyncMock()

        await coord.shutdown(metrics_buffer=metrics_buf)

        metrics_buf.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_stops_redis_listener(self):
        coord = ShutdownCoordinator()
        ws_manager = mock.AsyncMock()

        await coord.shutdown(websocket_manager=ws_manager)

        ws_manager.stop_redis_listener.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_disposes_db_engine(self):
        coord = ShutdownCoordinator()
        db_engine = mock.AsyncMock()

        await coord.shutdown(db_engine=db_engine)

        db_engine.dispose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_redis_client(self):
        coord = ShutdownCoordinator()
        redis_client = mock.AsyncMock()

        await coord.shutdown(redis_client=redis_client)

        redis_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self):
        coord = ShutdownCoordinator()
        ws_manager = mock.AsyncMock()

        await coord.shutdown(websocket_manager=ws_manager)
        await coord.shutdown(websocket_manager=ws_manager)

        # Second call should be a no-op
        ws_manager.close_all_connections.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_gracefully_handles_exceptions(self):
        """Shutdown should continue even if individual steps fail."""
        coord = ShutdownCoordinator()
        ws_manager = mock.AsyncMock()
        ws_manager.close_all_connections.side_effect = Exception("ws boom")
        ws_manager.stop_redis_listener.side_effect = Exception("redis boom")
        metrics_buf = mock.AsyncMock()
        metrics_buf.shutdown.side_effect = Exception("metrics boom")
        db_engine = mock.Mock()
        db_engine.dispose.side_effect = Exception("db boom")
        redis_client = mock.AsyncMock()
        redis_client.close.side_effect = Exception("redis_client boom")

        # Should not raise
        await coord.shutdown(
            websocket_manager=ws_manager,
            metrics_buffer=metrics_buf,
            db_engine=db_engine,
            redis_client=redis_client,
        )

        assert coord._shutdown_complete

    @pytest.mark.asyncio
    async def test_shutdown_sets_shutting_down_flag(self):
        from app.core import shutdown as _shutdown_mod

        _shutdown_mod._is_shutting_down = False
        coord = ShutdownCoordinator()
        await coord.shutdown()
        assert is_shutting_down() is True

    def test_is_shutting_down_default_false(self):
        from app.core import shutdown as _shutdown_mod

        _shutdown_mod._is_shutting_down = False
        assert is_shutting_down() is False


class TestGlobalCoordinator:
    """Global singleton coordinator tests."""

    def test_get_shutdown_coordinator_returns_same_instance(self):
        reset_shutdown_coordinator()
        c1 = get_shutdown_coordinator()
        c2 = get_shutdown_coordinator()
        assert c1 is c2

    def test_reset_shutdown_coordinator_creates_new_instance(self):
        reset_shutdown_coordinator()
        c1 = get_shutdown_coordinator()
        reset_shutdown_coordinator()
        c2 = get_shutdown_coordinator()
        assert c1 is not c2
