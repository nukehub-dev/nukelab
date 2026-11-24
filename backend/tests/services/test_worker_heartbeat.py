# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Process-local worker heartbeat registration and container identity."""

import asyncio
import os
import time
from unittest import mock

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.worker_heartbeat import WorkerHeartbeat as WorkerHeartbeatRow
from app.services import worker_heartbeat as heartbeat_module
from app.services.worker_heartbeat import (
    SCHEMA_VERSION,
    WorkerHeartbeat,
    read_process_start_time,
)


@pytest_asyncio.fixture
async def registry_engine():
    """Independent engine for rows committed by the heartbeat thread."""
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"command_timeout": settings.database_query_timeout_seconds},
    )
    yield engine
    await engine.dispose()


async def fetch_row(engine, executor_id):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await session.get(WorkerHeartbeatRow, executor_id)


async def wait_for_row(engine, executor_id, *, state="running", predicate=None, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = await fetch_row(engine, executor_id)
        if row is not None and row.state == state and (predicate is None or predicate(row)):
            return row
        await asyncio.sleep(0.02)
    raise AssertionError(f"Heartbeat row {executor_id} did not reach {state!r}")


async def remove_row(engine, executor_id):
    async with engine.begin() as connection:
        await connection.execute(
            delete(WorkerHeartbeatRow).where(WorkerHeartbeatRow.executor_id == executor_id)
        )


def make_heartbeat(**changes):
    values = {
        "single_process_container": False,
        "interval_seconds": 0.05,
        "database_url": settings.database_url,
        "stop_join_timeout_seconds": 2.0,
    }
    values.update(changes)
    return WorkerHeartbeat(**values)


@pytest.mark.asyncio
async def test_heartbeat_registers_and_marks_graceful_shutdown(registry_engine):
    heartbeat = make_heartbeat(single_process_container=True)
    try:
        heartbeat.start()
        heartbeat.start()  # idempotent: still one thread

        first = await wait_for_row(registry_engine, heartbeat.executor_id)
        first_beat = first.heartbeat_at
        second = await wait_for_row(
            registry_engine,
            heartbeat.executor_id,
            predicate=lambda row: row.heartbeat_at > first_beat,
        )

        assert first.schema_version == SCHEMA_VERSION
        assert first.hostname == heartbeat.hostname
        assert first.pid == heartbeat.pid
        assert first.process_start_time == heartbeat.process_start_time
        assert first.single_process_container is True
        assert first.container_id is None
        assert first.container_started_at is None

        heartbeat.stop(graceful=True)

        stopped = await fetch_row(registry_engine, heartbeat.executor_id)
        assert stopped is not None
        assert stopped.state == "stopped"
        assert stopped.executor_id == heartbeat.executor_id
        assert stopped.heartbeat_at >= second.heartbeat_at
        assert stopped.updated_at >= second.updated_at
        assert heartbeat.beats >= 2

        thread = heartbeat._thread
        heartbeat.start()
        assert heartbeat._thread is thread
        assert thread is not None and thread.is_alive() is False
    finally:
        heartbeat.stop(graceful=False)
        await remove_row(registry_engine, heartbeat.executor_id)


def test_stop_is_safe_when_never_started():
    heartbeat = make_heartbeat()

    heartbeat.stop()
    heartbeat.stop(graceful=False)

    assert heartbeat._thread is None


@pytest.mark.asyncio
async def test_abrupt_stop_leaves_running_row_without_marker(registry_engine):
    heartbeat = make_heartbeat(interval_seconds=0.05)
    try:
        heartbeat.start()
        await wait_for_row(registry_engine, heartbeat.executor_id)

        heartbeat.stop(graceful=False)
        after_stop = await fetch_row(registry_engine, heartbeat.executor_id)
        assert after_stop is not None
        assert after_stop.state == "running"
        last_beat = after_stop.heartbeat_at

        await asyncio.sleep(0.15)

        row = await fetch_row(registry_engine, heartbeat.executor_id)
        assert row is not None
        assert row.state == "running"
        assert row.heartbeat_at == last_beat
        assert heartbeat._thread is not None
        assert heartbeat._thread.is_alive() is False
    finally:
        heartbeat.stop(graceful=False)
        await remove_row(registry_engine, heartbeat.executor_id)


@pytest.mark.asyncio
async def test_heartbeat_thread_is_independent_of_the_event_loop(registry_engine):
    heartbeat = make_heartbeat(interval_seconds=0.05)
    try:
        heartbeat.start()
        first = await wait_for_row(registry_engine, heartbeat.executor_id)
        first_beat = first.heartbeat_at

        # Block the test's event loop; the heartbeat owns a separate loop.
        time.sleep(0.5)

        row = await fetch_row(registry_engine, heartbeat.executor_id)
        assert row is not None
        assert heartbeat.beats >= 2
        assert row.heartbeat_at > first_beat
    finally:
        heartbeat.stop(graceful=True)
        await remove_row(registry_engine, heartbeat.executor_id)


@pytest.mark.asyncio
async def test_container_identity_uses_driver_inspection():
    calls = []
    closed = []

    class FakeDriver:
        async def get_container_info(self, container_id):
            calls.append(container_id)
            return {
                "Id": "a" * 64,
                "State": {"StartedAt": "2026-11-21T10:35:41.299791044Z"},
            }

        async def close(self):
            closed.append(True)

    async def driver_factory():
        return FakeDriver()

    heartbeat = make_heartbeat(hostname="0123456789ab")
    await heartbeat.resolve_container_identity(driver_factory=driver_factory)

    assert calls == ["0123456789ab"]
    assert closed == [True]
    assert heartbeat.hostname == "0123456789ab"
    assert heartbeat.container_id == "a" * 64
    assert heartbeat.container_started_at == "2026-11-21T10:35:41.299791044Z"


@pytest.mark.asyncio
async def test_container_inspection_failure_keeps_process_identity():
    class UnavailableDriver:
        async def get_container_info(self, container_id):
            raise RuntimeError("docker socket unavailable")

        async def close(self):
            pass

    async def driver_factory():
        return UnavailableDriver()

    heartbeat = make_heartbeat(hostname="0123456789ab")
    with mock.patch.object(heartbeat_module.logger, "warning") as warning:
        await heartbeat.resolve_container_identity(driver_factory=driver_factory)

    messages = [str(call.args) for call in warning.call_args_list]
    assert any("RuntimeError" in message for message in messages)
    assert all("docker socket unavailable" not in message for message in messages)
    assert heartbeat.container_id is None
    assert heartbeat.container_started_at is None
    assert heartbeat.hostname == "0123456789ab"
    assert heartbeat.pid == os.getpid()
    assert heartbeat.process_start_time == read_process_start_time()


@pytest.mark.asyncio
async def test_non_container_hostname_skips_inspection():
    async def driver_factory():  # pragma: no cover - must not run
        raise AssertionError("inspection must not start for a non-container hostname")

    heartbeat = make_heartbeat(hostname="nukelab-backend")
    await heartbeat.resolve_container_identity(driver_factory=driver_factory)

    assert heartbeat.container_id is None
    assert heartbeat.container_started_at is None


@pytest.mark.asyncio
async def test_incomplete_container_identity_is_not_recorded():
    class IncompleteDriver:
        async def get_container_info(self, container_id):
            return {"Id": "a" * 64, "State": {}}

        async def close(self):
            pass

    async def driver_factory():
        return IncompleteDriver()

    heartbeat = make_heartbeat(hostname="0123456789ab")
    await heartbeat.resolve_container_identity(driver_factory=driver_factory)

    assert heartbeat.container_id is None
    assert heartbeat.container_started_at is None


def test_process_start_token_is_stable():
    first = read_process_start_time()
    second = read_process_start_time()

    assert first
    assert first == second


def test_process_start_token_parser_handles_parenthesized_comm():
    fields = ["4242", "(python worker) (test)"] + [str(index) for index in range(3, 53)]
    line = " ".join(fields)

    assert heartbeat_module._parse_process_start_token(line) == "22"
    assert heartbeat_module._parse_process_start_token("not a stat line") is None
    assert heartbeat_module._parse_process_start_token("1 (short) S 1") is None


def test_process_start_token_falls_back_when_proc_is_unavailable(monkeypatch):
    def unavailable(pid):
        raise FileNotFoundError("procfs unavailable")

    monkeypatch.setattr(heartbeat_module, "_read_proc_start_token", unavailable)
    monkeypatch.setattr(heartbeat_module, "_psutil_process_start_time", lambda pid: "1234.5")

    assert read_process_start_time() == "1234.5"


def test_psutil_process_start_time_is_a_string():
    token = heartbeat_module._psutil_process_start_time(os.getpid())

    assert token
    assert token == heartbeat_module._psutil_process_start_time(os.getpid())


def test_heartbeat_rejects_non_positive_timings():
    with pytest.raises(ValueError):
        WorkerHeartbeat(single_process_container=False, interval_seconds=0)
    with pytest.raises(ValueError):
        WorkerHeartbeat(
            single_process_container=False,
            interval_seconds=1,
            stop_join_timeout_seconds=0,
        )


@pytest.mark.asyncio
async def test_run_awaitable_sync_inside_an_active_event_loop():
    async def answer():
        return 42

    assert heartbeat_module._run_awaitable_sync(answer()) == 42


def test_pgbouncer_connect_args_match_application_session(monkeypatch):
    monkeypatch.setattr(settings, "pgbouncer_enabled", True)
    monkeypatch.setattr(
        settings, "database_pgbouncer_url", "postgresql+asyncpg://pooler:6432/nukelab"
    )

    assert heartbeat_module._application_database_url() == (
        "postgresql+asyncpg://pooler:6432/nukelab"
    )
    connect_args = heartbeat_module._database_connect_args()
    assert connect_args["statement_cache_size"] == 0
    assert connect_args["prepared_statement_name_func"]() == ""
    assert connect_args["command_timeout"] == settings.database_query_timeout_seconds


def test_direct_database_connect_args_do_not_disable_statement_cache(monkeypatch):
    monkeypatch.setattr(settings, "pgbouncer_enabled", False)
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://db:5432/nukelab")

    assert heartbeat_module._application_database_url() == ("postgresql+asyncpg://db:5432/nukelab")
    connect_args = heartbeat_module._database_connect_args()
    assert "statement_cache_size" not in connect_args
    assert "prepared_statement_name_func" not in connect_args


def test_engine_uses_nullpool_and_the_application_url(monkeypatch):
    monkeypatch.setattr(settings, "pgbouncer_enabled", False)
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://db:5432/nukelab")
    heartbeat = make_heartbeat()

    with mock.patch("app.services.worker_heartbeat.create_async_engine") as create_engine:
        heartbeat._create_engine()

    create_engine.assert_called_once()
    assert create_engine.call_args.args[0] == "postgresql+asyncpg://db:5432/nukelab"
    assert create_engine.call_args.kwargs["poolclass"] is NullPool
    assert create_engine.call_args.kwargs["echo"] is False


@pytest.mark.asyncio
async def test_database_failure_does_not_kill_the_heartbeat_thread():
    class FlakyConnection:
        def __init__(self, engine):
            self._engine = engine

        async def execute(self, statement):
            if self._engine.fail_next_execute:
                self._engine.fail_next_execute = False
                raise RuntimeError("FlakySecret database payload")

        async def commit(self):
            pass

        async def close(self):
            self._engine.closed += 1

    class FlakyEngine:
        def __init__(self):
            self.connects = 0
            self.disposes = 0
            self.closed = 0
            self.fail_next_execute = True

        async def connect(self):
            self.connects += 1
            if self.connects == 1:
                raise RuntimeError("FlakySecret connection payload")
            return FlakyConnection(self)

        async def dispose(self):
            self.disposes += 1

    engine = FlakyEngine()
    heartbeat = make_heartbeat(interval_seconds=0.02, engine_factory=lambda: engine)
    try:
        with mock.patch.object(heartbeat_module.logger, "warning") as warning:
            heartbeat.start()
            deadline = time.monotonic() + 5.0
            while engine.connects < 3 and time.monotonic() < deadline:
                await asyncio.sleep(0.02)

        messages = [str(call.args) for call in warning.call_args_list]
        assert engine.connects >= 3
        assert engine.disposes >= 2
        assert heartbeat.beats >= 1
        assert heartbeat._thread is not None
        assert heartbeat._thread.is_alive()
        assert any("RuntimeError" in message for message in messages)
        assert all("FlakySecret" not in message for message in messages)
    finally:
        heartbeat.stop(graceful=False)
