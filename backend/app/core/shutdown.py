"""
Graceful shutdown coordinator.

Ensures clean teardown of:
- Background asyncio tasks
- WebSocket connections
- Request metrics buffer flush
- Redis connections
- Database engine
"""

import asyncio
import time
from typing import List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

# Global shutdown-in-progress flag (read by health endpoint)
_is_shutting_down = False


def is_shutting_down() -> bool:
    """Return True if the application is currently shutting down."""
    return _is_shutting_down


class ShutdownCoordinator:
    """Coordinates graceful application shutdown."""

    def __init__(self):
        self._background_tasks: List[asyncio.Task] = []
        self._shutdown_complete = False

    def register_background_task(self, task: asyncio.Task) -> None:
        """Track a background task so it can be cancelled on shutdown."""
        self._background_tasks.append(task)

    async def shutdown(
        self,
        websocket_manager=None,
        metrics_buffer=None,
        db_engine=None,
        redis_client=None,
    ) -> None:
        """Run the full shutdown sequence.

        Order matters:
        1. Cancel background tasks (stops new work)
        2. Close WebSocket connections (drain active clients)
        3. Flush metrics buffer (persist in-flight data)
        4. Stop Redis listener
        5. Dispose DB engine (close connection pool)

        Each step has a tight timeout so the total elapsed time stays well
        under Docker's default 10s SIGKILL window.
        """
        global _is_shutting_down
        if self._shutdown_complete:
            return

        _is_shutting_down = True
        started = time.perf_counter()
        logger.info("shutdown_started", extra={"action": "graceful_shutdown"})

        # 1. Cancel background tasks (3s — they should exit quickly)
        await self._cancel_background_tasks(timeout=3.0)

        # 2. Close WebSocket connections (parallel, bounded by timeout)
        if websocket_manager is not None:
            try:
                await asyncio.wait_for(
                    websocket_manager.close_all_connections(timeout=3.0),
                    timeout=4.0,
                )
                logger.info("websockets_closed")
            except Exception:
                logger.exception("websocket_close_failed")

        # 3. Flush metrics buffer (5s — includes yielding for fire-and-forget tasks)
        if metrics_buffer is not None:
            try:
                await asyncio.wait_for(metrics_buffer.shutdown(), timeout=5.0)
                logger.info("metrics_buffer_flushed")
            except Exception:
                logger.exception("metrics_buffer_flush_failed")

        # 4. Stop Redis listener / close Redis client
        if websocket_manager is not None:
            try:
                await asyncio.wait_for(
                    websocket_manager.stop_redis_listener(), timeout=3.0
                )
                logger.info("redis_listener_stopped")
            except Exception:
                logger.exception("redis_listener_stop_failed")

        if redis_client is not None:
            try:
                await asyncio.wait_for(redis_client.close(), timeout=3.0)
                logger.info("redis_client_closed")
            except Exception:
                logger.exception("redis_client_close_failed")

        # 5. Dispose database engine (async dispose closes the pool)
        if db_engine is not None:
            try:
                await asyncio.wait_for(db_engine.dispose(), timeout=3.0)
                logger.info("db_engine_disposed")
            except Exception:
                logger.exception("db_engine_dispose_failed")

        elapsed = round((time.perf_counter() - started) * 1000, 2)
        self._shutdown_complete = True
        logger.info("shutdown_complete", extra={"elapsed_ms": elapsed})

    async def _cancel_background_tasks(self, timeout: float = 3.0) -> None:
        """Cancel and await all tracked background tasks."""
        if not self._background_tasks:
            return

        # Cancel all tasks
        for task in self._background_tasks:
            if not task.done():
                task.cancel()

        # Wait for them to finish (with timeout to avoid hanging)
        done, pending = await asyncio.wait(
            self._background_tasks,
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED,
        )

        # Force-cancel any that are still pending
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info(
            "background_tasks_cancelled",
            extra={"done": len(done), "pending": len(pending)},
        )


# Global coordinator instance
_shutdown_coordinator: Optional[ShutdownCoordinator] = None


def get_shutdown_coordinator() -> ShutdownCoordinator:
    """Get (or create) the global shutdown coordinator."""
    global _shutdown_coordinator
    if _shutdown_coordinator is None:
        _shutdown_coordinator = ShutdownCoordinator()
    return _shutdown_coordinator


def reset_shutdown_coordinator() -> None:
    """Reset the global coordinator (useful for tests)."""
    global _shutdown_coordinator
    _shutdown_coordinator = None
