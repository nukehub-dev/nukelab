# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Startup and shutdown wiring for API and Celery worker heartbeats."""

import os
import subprocess
import sys
import uuid
from unittest import mock

import pytest

from app.main import app, lifespan
from app.services import worker_heartbeat as heartbeat_module
from app.services.worker_heartbeat import (
    start_api_worker_heartbeat,
    start_celery_worker_heartbeat,
    stop_api_worker_heartbeat,
    stop_celery_worker_heartbeat,
)


class FakeHeartbeat:
    def __init__(self, single_process_container: bool):
        self.executor_id = uuid.uuid4()
        self.single_process_container = single_process_container
        self.resolve_calls = 0
        self.start_calls = 0
        self.stop_calls = []

    async def resolve_container_identity(self, *, driver_factory=None):
        self.resolve_calls += 1

    def start(self):
        self.start_calls += 1

    def stop(self, graceful: bool = True):
        self.stop_calls.append(graceful)


@pytest.fixture(autouse=True)
def reset_heartbeat_singletons():
    heartbeat_module.stop_api_worker_heartbeat()
    heartbeat_module.stop_celery_worker_heartbeat()
    heartbeat_module._api_worker_heartbeat = None
    heartbeat_module._celery_worker_heartbeat = None
    yield
    heartbeat_module.stop_api_worker_heartbeat()
    heartbeat_module.stop_celery_worker_heartbeat()
    heartbeat_module._api_worker_heartbeat = None
    heartbeat_module._celery_worker_heartbeat = None


async def no_driver():
    return None


@pytest.mark.asyncio
async def test_api_heartbeat_starts_and_stops_once():
    created = []

    def heartbeat_factory():
        heartbeat = FakeHeartbeat(single_process_container=False)
        created.append(heartbeat)
        return heartbeat

    first = await start_api_worker_heartbeat(
        driver_factory=no_driver, heartbeat_factory=heartbeat_factory
    )
    second = await start_api_worker_heartbeat(
        driver_factory=no_driver, heartbeat_factory=heartbeat_factory
    )

    assert first is second
    assert len(created) == 1
    assert first.resolve_calls == 1
    assert first.start_calls == 1
    assert first.single_process_container is False

    stop_api_worker_heartbeat()
    stop_api_worker_heartbeat()

    assert first.stop_calls == [True]


@pytest.mark.asyncio
async def test_api_heartbeat_constructs_multi_process_container_identity():
    with mock.patch.object(heartbeat_module, "WorkerHeartbeat") as heartbeat_class:
        instance = heartbeat_class.return_value
        instance.resolve_container_identity = mock.AsyncMock()
        instance.start = mock.Mock()

        await start_api_worker_heartbeat(driver_factory=no_driver)

    heartbeat_class.assert_called_once_with(single_process_container=False)
    instance.resolve_container_identity.assert_awaited_once()
    instance.start.assert_called_once_with()


def test_celery_heartbeat_starts_and_stops_once():
    created = []

    def heartbeat_factory():
        heartbeat = FakeHeartbeat(single_process_container=True)
        created.append(heartbeat)
        return heartbeat

    first = start_celery_worker_heartbeat(
        driver_factory=no_driver, heartbeat_factory=heartbeat_factory
    )
    second = start_celery_worker_heartbeat(
        driver_factory=no_driver, heartbeat_factory=heartbeat_factory
    )

    assert first is second
    assert len(created) == 1
    assert first.resolve_calls == 1
    assert first.start_calls == 1
    assert first.single_process_container is True

    stop_celery_worker_heartbeat()
    stop_celery_worker_heartbeat()

    assert first.stop_calls == [True]


def test_celery_heartbeat_constructs_single_process_container_identity():
    with mock.patch.object(heartbeat_module, "WorkerHeartbeat") as heartbeat_class:
        instance = heartbeat_class.return_value
        instance.resolve_container_identity = mock.AsyncMock()
        instance.start = mock.Mock()

        start_celery_worker_heartbeat(driver_factory=no_driver)

    heartbeat_class.assert_called_once_with(single_process_container=True)
    instance.resolve_container_identity.assert_awaited_once()
    instance.start.assert_called_once_with()


@pytest.mark.asyncio
async def test_lifespan_starts_after_startup_and_stops_before_shutdown():
    events = []

    async def fake_startup():
        events.append("startup")

    async def fake_start_heartbeat():
        events.append("start_heartbeat")
        return FakeHeartbeat(single_process_container=False)

    def fake_stop_heartbeat():
        events.append("stop_heartbeat")

    class FakeCoordinator:
        async def shutdown(self, **kwargs):
            events.append("coordinator_shutdown")

    with (
        mock.patch("app.main.startup", fake_startup),
        mock.patch("app.main.start_api_worker_heartbeat", fake_start_heartbeat),
        mock.patch("app.main.stop_api_worker_heartbeat", fake_stop_heartbeat),
        mock.patch("app.main.get_shutdown_coordinator", return_value=FakeCoordinator()),
        mock.patch("app.core.redis_client.get_redis_client", return_value=None),
    ):
        async with lifespan(app):
            events.append("serving")

    assert events == [
        "startup",
        "start_heartbeat",
        "serving",
        "stop_heartbeat",
        "coordinator_shutdown",
    ]


@pytest.mark.asyncio
async def test_lifespan_stops_heartbeat_when_serving_raises():
    events = []

    async def fake_startup():
        events.append("startup")

    async def fake_start_heartbeat():
        events.append("start_heartbeat")
        return FakeHeartbeat(single_process_container=False)

    def fake_stop_heartbeat():
        events.append("stop_heartbeat")

    class FakeCoordinator:
        async def shutdown(self, **kwargs):
            events.append("coordinator_shutdown")

    with (
        mock.patch("app.main.startup", fake_startup),
        mock.patch("app.main.start_api_worker_heartbeat", fake_start_heartbeat),
        mock.patch("app.main.stop_api_worker_heartbeat", fake_stop_heartbeat),
        mock.patch("app.main.get_shutdown_coordinator", return_value=FakeCoordinator()),
        mock.patch("app.core.redis_client.get_redis_client", return_value=None),
    ):
        with pytest.raises(RuntimeError):
            async with lifespan(app):
                raise RuntimeError("serving failed")

    assert events == [
        "startup",
        "start_heartbeat",
        "stop_heartbeat",
        "coordinator_shutdown",
    ]


def test_celery_signal_handlers_delegate_once(monkeypatch):
    import app.worker as worker

    calls = []
    monkeypatch.setattr(worker, "start_celery_worker_heartbeat", lambda: calls.append("start"))
    monkeypatch.setattr(worker, "stop_celery_worker_heartbeat", lambda: calls.append("stop"))

    worker.start_worker_heartbeat(sender=None)
    worker.start_worker_heartbeat(sender=None)
    worker.stop_worker_heartbeat(sender=None)
    worker.stop_worker_heartbeat(sender=None)

    assert calls == ["start", "start", "stop", "stop"]


def test_celery_signals_are_connected(monkeypatch):
    import app.worker as worker

    calls = []
    monkeypatch.setattr(worker, "start_celery_worker_heartbeat", lambda: calls.append("start"))
    monkeypatch.setattr(worker, "stop_celery_worker_heartbeat", lambda: calls.append("stop"))

    worker.worker_ready.send(sender=None)
    worker.worker_shutdown.send(sender=None)

    assert calls == ["start", "stop"]


def test_importing_worker_module_does_not_start_heartbeat():
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = (
        "import threading\n"
        "import app.worker\n"
        "names = [thread.name for thread in threading.enumerate()]\n"
        "assert not any(name.startswith('worker-heartbeat') for name in names), names\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=backend_root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
