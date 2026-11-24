# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Process-lifetime executor registration for crash-safe operation recovery.

Each operation-executing process (uvicorn API workers and the Celery worker
process) registers one row in ``worker_heartbeats``. A daemon thread owns its
own event loop, engine, and connection, so registration is independent of
request handling and long operations. The thread refreshes the row every
``WORKER_HEARTBEAT_INTERVAL_SECONDS`` and writes a truthful ``stopped`` marker
only when the process shuts down gracefully after draining its work.

A stale ``running`` row is an observation, not proof that the process died.
Runtime/container identity remains the termination proof for consumers.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import os
import re
import socket
import threading
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.container.factory import get_fresh_driver
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.worker_heartbeat import WorkerHeartbeat as WorkerHeartbeatRow

logger = get_logger(__name__)

SCHEMA_VERSION = "nukelab-journal/v1"

_SHORT_CONTAINER_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")
_STOP_JOIN_TIMEOUT_SECONDS = 5.0

DriverFactory = Callable[[], Awaitable[Any]]


def _application_database_url() -> str:
    """Return the database URL used by the rest of the application."""
    if settings.pgbouncer_enabled:
        return settings.database_pgbouncer_url
    return settings.database_url


def _database_connect_args() -> dict[str, Any]:
    """Build asyncpg connect args, matching the application session setup."""
    connect_args: dict[str, Any] = {
        "command_timeout": settings.database_query_timeout_seconds,
    }
    if settings.pgbouncer_enabled:
        # Transaction pooling breaks server-side prepared statements.
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: ""
    return connect_args


def _parse_process_start_token(stat_line: str) -> str | None:
    """Extract field 22 (starttime) from a ``/proc/<pid>/stat`` line.

    The comm field is parenthesized and may itself contain spaces or closing
    parentheses, so split after the final ``)`` instead of tokenizing the line.
    """
    closing_paren = stat_line.rfind(")")
    if closing_paren == -1:
        return None
    fields = stat_line[closing_paren + 1 :].split()
    if len(fields) < 20:
        return None
    token = fields[19]
    return token if token.isdigit() else None


def _read_proc_start_token(pid: int) -> str:
    path = "/proc/self/stat" if pid == os.getpid() else f"/proc/{pid}/stat"
    with open(path, encoding="ascii") as stat_file:
        return stat_file.read()


def _psutil_process_start_time(pid: int) -> str | None:
    try:
        import psutil

        return str(psutil.Process(pid).create_time())
    except Exception:
        return None


def read_process_start_time(pid: int | None = None) -> str | None:
    """Return an opaque process start token.

    ``/proc`` is the primary source. ``psutil`` is only a fallback when procfs
    is unavailable; a present but malformed stat line yields no token rather
    than a different identity.
    """
    target_pid = os.getpid() if pid is None else pid
    try:
        stat_line = _read_proc_start_token(target_pid)
    except OSError:
        return _psutil_process_start_time(target_pid)
    return _parse_process_start_token(stat_line)


class WorkerHeartbeat:
    """Register and refresh one process lifetime in ``worker_heartbeats``."""

    def __init__(
        self,
        *,
        single_process_container: bool,
        interval_seconds: float | None = None,
        database_url: str | None = None,
        hostname: str | None = None,
        pid: int | None = None,
        process_start_time: str | None = None,
        container_id: str | None = None,
        container_started_at: str | None = None,
        schema_version: str = SCHEMA_VERSION,
        engine_factory: Callable[[], AsyncEngine] | None = None,
        stop_join_timeout_seconds: float = _STOP_JOIN_TIMEOUT_SECONDS,
    ) -> None:
        interval = (
            float(settings.worker_heartbeat_interval_seconds)
            if interval_seconds is None
            else float(interval_seconds)
        )
        if interval <= 0:
            raise ValueError("Heartbeat interval must be positive.")
        if stop_join_timeout_seconds <= 0:
            raise ValueError("Stop join timeout must be positive.")

        self.executor_id = uuid.uuid4()
        self.hostname = hostname or socket.gethostname()
        self.container_id = container_id
        self.container_started_at = container_started_at
        self.pid = os.getpid() if pid is None else pid
        self.process_start_time = (
            read_process_start_time(self.pid) if process_start_time is None else process_start_time
        )
        self.single_process_container = bool(single_process_container)
        self.schema_version = schema_version
        self.heartbeat_at = utc_now()
        self.beats = 0

        self._interval_seconds = interval
        self._database_url = database_url or _application_database_url()
        self._engine_factory = engine_factory
        self._stop_join_timeout_seconds = stop_join_timeout_seconds

        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._graceful_stop = True

    async def resolve_container_identity(
        self, *, driver_factory: DriverFactory | None = None
    ) -> None:
        """Inspect the process's own container and record its incarnation.

        Docker Compose normally sets the hostname to the 12-hex short container
        ID; only that exact shape is used as an inspection candidate. Any
        inspection failure leaves the container fields empty and never blocks
        process startup. The full container ID and exact ``State.StartedAt``
        are both required because a restart keeps the ID but changes the start
        time.
        """
        if not _SHORT_CONTAINER_ID_PATTERN.fullmatch(self.hostname):
            return

        factory = driver_factory or get_fresh_driver
        driver = None
        try:
            driver = await factory()
            info = await driver.get_container_info(self.hostname)
            container_id = info.get("Id") if isinstance(info, dict) else None
            state = info.get("State") if isinstance(info, dict) else None
            container_started_at = state.get("StartedAt") if isinstance(state, dict) else None
            if (
                isinstance(container_id, str)
                and container_id
                and isinstance(container_started_at, str)
                and container_started_at
            ):
                self.container_id = container_id
                self.container_started_at = container_started_at
            else:
                logger.warning("Worker heartbeat container inspection returned incomplete identity")
        except Exception as exc:
            logger.warning(
                "Worker heartbeat container inspection failed (%s); "
                "continuing with process identity",
                type(exc).__name__,
            )
        finally:
            close = getattr(driver, "close", None)
            if close is not None:
                with contextlib.suppress(Exception):
                    await close()

    def start(self) -> None:
        """Start the daemon heartbeat thread once for this process lifetime."""
        with self._state_lock:
            if self._thread is not None:
                return
            thread = threading.Thread(
                target=self._thread_main,
                name=f"worker-heartbeat-{self.executor_id}",
                daemon=True,
            )
            self._thread = thread
        thread.start()

    def stop(self, graceful: bool = True) -> None:
        """Signal the thread and join it with a bounded timeout.

        ``graceful=False`` never writes a ``stopped`` marker, leaving the row
        in its last ``running`` state as the abrupt-termination signature. The
        marker is written by the heartbeat thread itself, and only when the
        caller requested a graceful stop after in-flight work was drained.
        """
        with self._state_lock:
            thread = self._thread
            if thread is None:
                return
            if self._stop_requested:
                return
            self._stop_requested = True
            self._graceful_stop = bool(graceful)
            self._stop_event.set()

        if thread is threading.current_thread():
            return

        thread.join(timeout=self._stop_join_timeout_seconds)
        if thread.is_alive():
            logger.warning(
                "Worker heartbeat thread did not stop within %.1fs",
                self._stop_join_timeout_seconds,
            )

    def _create_engine(self) -> AsyncEngine:
        if self._engine_factory is not None:
            return self._engine_factory()
        return create_async_engine(
            self._database_url,
            poolclass=NullPool,
            connect_args=_database_connect_args(),
            echo=False,
        )

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_heartbeat_loop())
        except Exception as exc:
            logger.warning("Worker heartbeat thread stopped unexpectedly (%s)", type(exc).__name__)
        finally:
            with contextlib.suppress(Exception):
                loop.run_until_complete(loop.shutdown_asyncgens())
            asyncio.set_event_loop(None)
            loop.close()

    async def _run_heartbeat_loop(self) -> None:
        engine = self._create_engine()
        connection: AsyncConnection | None = None
        try:
            while True:
                stopping = self._stop_event.is_set()
                if stopping and not self._graceful_stop:
                    break

                state = "stopped" if stopping else "running"
                try:
                    if connection is None:
                        connection = await engine.connect()
                    await self._write_beat(connection, state)
                except Exception as exc:
                    await self._reset_database(engine, connection)
                    connection = None
                    logger.warning(
                        "Worker heartbeat database write failed (%s); "
                        "will reconnect on the next beat",
                        type(exc).__name__,
                    )
                    if stopping:
                        break
                    self._stop_event.wait(self._interval_seconds)
                    continue

                if stopping:
                    break
                self._stop_event.wait(self._interval_seconds)
        finally:
            await self._reset_database(engine, connection)

    async def _write_beat(self, connection: AsyncConnection, state: str) -> None:
        now = utc_now()
        table = WorkerHeartbeatRow.__table__
        statement = postgres_insert(table).values(
            executor_id=self.executor_id,
            hostname=self.hostname,
            container_id=self.container_id,
            container_started_at=self.container_started_at,
            pid=self.pid,
            process_start_time=self.process_start_time,
            single_process_container=self.single_process_container,
            schema_version=self.schema_version,
            state=state,
            heartbeat_at=now,
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.executor_id],
            set_={
                "hostname": statement.excluded.hostname,
                "container_id": statement.excluded.container_id,
                "container_started_at": statement.excluded.container_started_at,
                "pid": statement.excluded.pid,
                "process_start_time": statement.excluded.process_start_time,
                "single_process_container": statement.excluded.single_process_container,
                "schema_version": statement.excluded.schema_version,
                "state": statement.excluded.state,
                "heartbeat_at": statement.excluded.heartbeat_at,
                "updated_at": statement.excluded.updated_at,
            },
        )
        await connection.execute(statement)
        await connection.commit()
        self.heartbeat_at = now
        self.beats += 1

    @staticmethod
    async def _reset_database(engine: AsyncEngine, connection: AsyncConnection | None) -> None:
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.close()
        with contextlib.suppress(Exception):
            await engine.dispose()


def _run_awaitable_sync(awaitable: Awaitable[Any]) -> Any:
    """Run a coroutine to completion for synchronous lifecycle hooks."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    # A loop is already running in this thread; use a private loop in a helper
    # thread instead of nesting event loops.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, awaitable).result()


_api_worker_heartbeat: WorkerHeartbeat | None = None
_celery_worker_heartbeat: WorkerHeartbeat | None = None


def current_executor_id() -> uuid.UUID | None:
    """Return this process's registered executor ID, if a heartbeat exists.

    Tests and legacy paths have no registered heartbeat and get ``None``;
    callers must not invent an executor identity in that case.
    """
    for heartbeat in (_api_worker_heartbeat, _celery_worker_heartbeat):
        if heartbeat is not None:
            return heartbeat.executor_id
    return None


async def start_api_worker_heartbeat(
    *,
    driver_factory: DriverFactory | None = None,
    heartbeat_factory: Callable[[], WorkerHeartbeat] | None = None,
) -> WorkerHeartbeat:
    """Start the heartbeat for one API worker process.

    The backend runs multiple uvicorn workers in one container, so a new
    executor ID in that container does not prove an older process exited.
    """
    global _api_worker_heartbeat
    if _api_worker_heartbeat is not None:
        return _api_worker_heartbeat

    heartbeat = (
        heartbeat_factory()
        if heartbeat_factory is not None
        else WorkerHeartbeat(single_process_container=False)
    )
    await heartbeat.resolve_container_identity(driver_factory=driver_factory)
    heartbeat.start()
    _api_worker_heartbeat = heartbeat
    return heartbeat


def stop_api_worker_heartbeat() -> None:
    """Stop the API worker heartbeat; safe when it was never started."""
    global _api_worker_heartbeat
    heartbeat = _api_worker_heartbeat
    _api_worker_heartbeat = None
    if heartbeat is not None:
        heartbeat.stop(graceful=True)


def start_celery_worker_heartbeat(
    *,
    driver_factory: DriverFactory | None = None,
    heartbeat_factory: Callable[[], WorkerHeartbeat] | None = None,
) -> WorkerHeartbeat:
    """Start the heartbeat for the Celery worker process.

    This is wired to ``worker_ready``; Celery Beat imports the same module but
    never emits that signal, so Beat does not register.
    """
    global _celery_worker_heartbeat
    if _celery_worker_heartbeat is not None:
        return _celery_worker_heartbeat

    heartbeat = (
        heartbeat_factory()
        if heartbeat_factory is not None
        else WorkerHeartbeat(single_process_container=True)
    )
    _run_awaitable_sync(heartbeat.resolve_container_identity(driver_factory=driver_factory))
    heartbeat.start()
    _celery_worker_heartbeat = heartbeat
    return heartbeat


def stop_celery_worker_heartbeat() -> None:
    """Stop the Celery worker heartbeat; safe when it was never started."""
    global _celery_worker_heartbeat
    heartbeat = _celery_worker_heartbeat
    _celery_worker_heartbeat = None
    if heartbeat is not None:
        heartbeat.stop(graceful=True)
