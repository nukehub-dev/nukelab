# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Fenced operation heartbeat refreshes only while the active row matches."""

import asyncio
import time
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
import pytest_asyncio
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.user import User
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.services import worker_heartbeat as heartbeat_module
from app.services.operation_heartbeat import operation_heartbeat
from app.services.worker_heartbeat import (
    current_executor_id,
    start_api_worker_heartbeat,
    stop_api_worker_heartbeat,
)
from tests.conftest import test_engine


@pytest_asyncio.fixture
async def recovery_context():
    """Commit real fenced rows on independent connections and clean them up."""
    marker = uuid.uuid4().hex
    owner_id, server_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(test_engine) as db, db.begin():
        db.add(
            User(
                id=owner_id,
                username=f"heartbeat-{marker}",
                email=f"heartbeat-{marker}@example.test",
                role="user",
                is_active=True,
            )
        )
        await db.flush()
        db.add(
            Server(
                id=server_id,
                name=f"heartbeat-{marker}",
                user_id=owner_id,
                status="starting",
            )
        )
    try:
        yield SimpleNamespace(
            owner_id=owner_id,
            server_id=server_id,
            session_factory=async_sessionmaker(test_engine, expire_on_commit=False),
        )
    finally:
        async with AsyncSession(test_engine) as cleanup, cleanup.begin():
            await cleanup.execute(delete(VolumeRestore).where(VolumeRestore.user_id == owner_id))
            await cleanup.execute(delete(VolumeBackup).where(VolumeBackup.user_id == owner_id))
            await cleanup.execute(
                delete(ServerLaunchOperation).where(ServerLaunchOperation.owner_id == owner_id)
            )
            await cleanup.execute(delete(Server).where(Server.user_id == owner_id))
            await cleanup.execute(delete(User).where(User.id == owner_id))


async def create_launch_operation(context, *, state="executing"):
    operation_id, token = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(test_engine) as db, db.begin():
        db.add(
            ServerLaunchOperation(
                id=operation_id,
                server_id=context.server_id,
                owner_id=context.owner_id,
                action="create",
                state=state,
                fencing_token=token,
                mounts=[],
                gpu_devices=[],
                username="heartbeat",
                resources={"cpu": 1.0, "memory": "1g", "disk": "1g", "gpu": 0},
                generation=1,
            )
        )
    return operation_id, token


async def create_recovery_rows(context):
    operation_id, token = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(test_engine) as db, db.begin():
        db.add(
            VolumeBackup(
                id=operation_id,
                volume_name=f"volume-{operation_id}",
                user_id=context.owner_id,
                status="in_progress",
                fencing_token=token,
                reserved_bytes=0,
            )
        )
        db.add(
            VolumeRestore(
                id=operation_id,
                backup_id=operation_id,
                user_id=context.owner_id,
                destination_name=f"restore-{operation_id}",
                display_name="Restored volume",
                max_size_bytes=1024**3,
                status="in_progress",
                fencing_token=token,
                reserved_bytes=0,
            )
        )
    return operation_id, token


async def fetch(model, identifier):
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        return await db.get(model, identifier)


async def wait_for(loader, predicate, *, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        row = await loader()
        if row is not None and predicate(row):
            return row
        if time.monotonic() >= deadline:
            raise AssertionError("Operation heartbeat condition was not reached")
        await asyncio.sleep(0.02)


class FailingSession:
    """Async session stand-in that fails the guarded update once."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def begin(self):
        return self

    async def execute(self, statement):
        raise RuntimeError("Secret database connection detail")

    async def commit(self):  # pragma: no cover - execute always fails first
        raise AssertionError("commit must not run after a failed beat")


class FlakySessionFactory:
    def __init__(self, real_factory):
        self.real_factory = real_factory
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls == 1:
            return FailingSession()
        return self.real_factory()


@pytest.mark.asyncio
async def test_active_launch_heartbeat_refreshes_then_stops_when_terminal(recovery_context):
    operation_id, token = await create_launch_operation(recovery_context)
    executor_id = uuid.uuid4()

    async def load():
        return await fetch(ServerLaunchOperation, operation_id)

    async with operation_heartbeat(
        recovery_context.session_factory,
        kind="launch",
        operation_id=operation_id,
        fencing_token=token,
        executor_id=executor_id,
        interval=0.05,
    ):
        first = await wait_for(
            load,
            lambda row: row.executor_id == executor_id and row.heartbeat_at is not None,
        )
        await wait_for(load, lambda row: row.heartbeat_at > first.heartbeat_at)

        async with AsyncSession(test_engine) as db, db.begin():
            row = await db.get(
                ServerLaunchOperation,
                operation_id,
                populate_existing=True,
                with_for_update=True,
            )
            row.state = "succeeded"

        await asyncio.sleep(0.2)
        stopped = await load()

    assert stopped.state == "succeeded"
    assert stopped.executor_id == executor_id
    final = await load()
    assert final.heartbeat_at == stopped.heartbeat_at
    await asyncio.sleep(0.15)
    assert (await load()).heartbeat_at == final.heartbeat_at


@pytest.mark.asyncio
async def test_terminal_row_starts_no_heartbeat_and_changes_nothing(recovery_context):
    operation_id, token = await create_launch_operation(recovery_context, state="succeeded")
    executor_id = uuid.uuid4()
    entered = False

    async with operation_heartbeat(
        recovery_context.session_factory,
        kind="launch",
        operation_id=operation_id,
        fencing_token=token,
        executor_id=executor_id,
        interval=0.05,
    ):
        entered = True
        await asyncio.sleep(0.15)

    row = await fetch(ServerLaunchOperation, operation_id)
    assert entered is True
    assert row.state == "succeeded"
    assert row.executor_id is None
    assert row.heartbeat_at is None


@pytest.mark.asyncio
async def test_missing_executor_identity_leaves_the_executor_unset(recovery_context):
    operation_id, token = await create_launch_operation(recovery_context)

    async def load():
        return await fetch(ServerLaunchOperation, operation_id)

    async with operation_heartbeat(
        recovery_context.session_factory,
        kind="launch",
        operation_id=operation_id,
        fencing_token=token,
        executor_id=None,
        interval=0.05,
    ):
        await wait_for(load, lambda row: row.heartbeat_at is not None)
        await asyncio.sleep(0.1)

    row = await load()
    assert row.executor_id is None
    assert row.heartbeat_at is not None


@pytest.mark.asyncio
async def test_changed_fence_stops_without_refreshing_after_the_change(recovery_context):
    operation_id, token = await create_launch_operation(recovery_context)
    executor_id = uuid.uuid4()

    async def load():
        return await fetch(ServerLaunchOperation, operation_id)

    async with operation_heartbeat(
        recovery_context.session_factory,
        kind="launch",
        operation_id=operation_id,
        fencing_token=token,
        executor_id=executor_id,
        interval=0.05,
    ):
        await wait_for(load, lambda row: row.executor_id == executor_id)

        replacement = uuid.uuid4()
        async with AsyncSession(test_engine) as db, db.begin():
            await db.execute(
                update(ServerLaunchOperation.__table__)
                .where(ServerLaunchOperation.id == operation_id)
                .values(fencing_token=replacement)
            )

        baseline = (await load()).heartbeat_at
        assert baseline is not None
        await asyncio.sleep(0.2)
        unchanged = await load()

    assert unchanged.fencing_token == replacement
    assert unchanged.heartbeat_at == baseline
    assert unchanged.executor_id == executor_id


@pytest.mark.asyncio
async def test_database_error_is_logged_and_a_later_beat_resumes(recovery_context):
    operation_id, token = await create_launch_operation(recovery_context)
    executor_id = uuid.uuid4()
    factory = FlakySessionFactory(recovery_context.session_factory)

    async def load():
        return await fetch(ServerLaunchOperation, operation_id)

    with mock.patch("app.services.operation_heartbeat.logger.warning") as warning:
        async with operation_heartbeat(
            factory,
            kind="launch",
            operation_id=operation_id,
            fencing_token=token,
            executor_id=executor_id,
            interval=0.05,
        ):
            resumed = await wait_for(load, lambda row: row.executor_id == executor_id)
            assert resumed.heartbeat_at is not None
            assert factory.calls >= 2

    messages = [str(call.args) for call in warning.call_args_list]
    assert any("RuntimeError" in message for message in messages)
    assert all("Secret database connection detail" not in message for message in messages)


@pytest.mark.parametrize(
    ("kind", "target_model", "untouched_model", "active_state"),
    [
        ("backup", VolumeBackup, VolumeRestore, "in_progress"),
        ("restore", VolumeRestore, VolumeBackup, "in_progress"),
    ],
)
@pytest.mark.asyncio
async def test_kind_maps_to_its_table_and_active_state(
    recovery_context, kind, target_model, untouched_model, active_state
):
    operation_id, token = await create_recovery_rows(recovery_context)
    executor_id = uuid.uuid4()

    async def load_target():
        return await fetch(target_model, operation_id)

    async with operation_heartbeat(
        recovery_context.session_factory,
        kind=kind,
        operation_id=operation_id,
        fencing_token=token,
        executor_id=executor_id,
        interval=0.05,
    ):
        row = await wait_for(
            load_target,
            lambda current: current.executor_id == executor_id and current.heartbeat_at is not None,
        )
        await wait_for(load_target, lambda current: current.heartbeat_at > row.heartbeat_at)

    target = await load_target()
    untouched = await fetch(untouched_model, operation_id)
    assert target.status == active_state
    assert target.executor_id == executor_id
    assert target.heartbeat_at is not None
    assert untouched.executor_id is None
    assert untouched.heartbeat_at is None


@pytest.mark.asyncio
async def test_unsupported_kind_and_non_positive_interval_are_rejected(recovery_context):
    operation_id, token = await create_launch_operation(recovery_context)

    with pytest.raises(ValueError, match="Unsupported operation heartbeat kind"):
        async with operation_heartbeat(
            recovery_context.session_factory,
            kind="delete",
            operation_id=operation_id,
            fencing_token=token,
            executor_id=None,
        ):
            pass  # pragma: no cover - context entry raises

    with pytest.raises(ValueError, match="must be positive"):
        async with operation_heartbeat(
            recovery_context.session_factory,
            kind="launch",
            operation_id=operation_id,
            fencing_token=token,
            executor_id=None,
            interval=0,
        ):
            pass  # pragma: no cover - context entry raises


def test_current_executor_id_is_none_without_a_registered_heartbeat(monkeypatch):
    monkeypatch.setattr(heartbeat_module, "_api_worker_heartbeat", None)
    monkeypatch.setattr(heartbeat_module, "_celery_worker_heartbeat", None)

    assert current_executor_id() is None


@pytest.mark.asyncio
async def test_current_executor_id_returns_the_registered_heartbeat(monkeypatch):
    class FakeHeartbeat:
        def __init__(self):
            self.executor_id = uuid.uuid4()

        async def resolve_container_identity(self, *, driver_factory=None):
            pass

        def start(self):
            pass

        def stop(self, graceful: bool = True):
            pass

    async def no_driver():
        return None

    monkeypatch.setattr(heartbeat_module, "_celery_worker_heartbeat", None)
    heartbeat = FakeHeartbeat()
    try:
        started = await start_api_worker_heartbeat(
            driver_factory=no_driver,
            heartbeat_factory=lambda: heartbeat,
        )

        assert started is heartbeat
        assert current_executor_id() == heartbeat.executor_id
    finally:
        stop_api_worker_heartbeat()
        heartbeat_module._api_worker_heartbeat = None


class TestOperationHeartbeatSettings:
    """Operation and recovery timings stay positive and ordered."""

    _KEYS = (
        "OPERATION_HEARTBEAT_INTERVAL_SECONDS",
        "OPERATION_HEARTBEAT_STALE_SECONDS",
        "RECOVERY_SCAN_INTERVAL_SECONDS",
        "RECOVERY_INITIAL_DELAY_SECONDS",
        "RECOVERY_PREPARED_GRACE_SECONDS",
        "RECOVERY_SCAN_BATCH_SIZE",
        "RECOVERY_STALL_WARNING_SECONDS",
        "RECOVERY_LEGACY_DRAIN_CONFIRMED",
    )

    def _clear(self, monkeypatch):
        for key in self._KEYS:
            monkeypatch.delenv(key, raising=False)

    def test_defaults(self, monkeypatch):
        self._clear(monkeypatch)

        settings = Settings()

        assert settings.operation_heartbeat_interval_seconds == 10
        assert settings.operation_heartbeat_stale_seconds == 90
        assert settings.recovery_scan_interval_seconds == 30
        assert settings.recovery_initial_delay_seconds == 60
        assert settings.recovery_prepared_grace_seconds == 60
        assert settings.recovery_scan_batch_size == 200
        assert settings.recovery_stall_warning_seconds == 300
        assert settings.recovery_legacy_drain_confirmed is False

    def test_environment_overrides(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("OPERATION_HEARTBEAT_INTERVAL_SECONDS", "15")
        monkeypatch.setenv("OPERATION_HEARTBEAT_STALE_SECONDS", "120")
        monkeypatch.setenv("RECOVERY_LEGACY_DRAIN_CONFIRMED", "true")

        settings = Settings()

        assert settings.operation_heartbeat_interval_seconds == 15
        assert settings.operation_heartbeat_stale_seconds == 120
        assert settings.recovery_legacy_drain_confirmed is True

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("OPERATION_HEARTBEAT_INTERVAL_SECONDS", "0"),
            ("OPERATION_HEARTBEAT_INTERVAL_SECONDS", "-1"),
            ("OPERATION_HEARTBEAT_STALE_SECONDS", "0"),
            ("OPERATION_HEARTBEAT_STALE_SECONDS", "-1"),
            ("RECOVERY_SCAN_INTERVAL_SECONDS", "0"),
            ("RECOVERY_INITIAL_DELAY_SECONDS", "0"),
            ("RECOVERY_PREPARED_GRACE_SECONDS", "0"),
            ("RECOVERY_SCAN_BATCH_SIZE", "0"),
            ("RECOVERY_STALL_WARNING_SECONDS", "0"),
        ],
    )
    def test_non_positive_values_are_rejected(self, monkeypatch, key, value):
        self._clear(monkeypatch)
        monkeypatch.setenv(key, value)

        with pytest.raises(ValueError):
            Settings()

    def test_operation_stale_threshold_must_exceed_the_interval(self, monkeypatch):
        self._clear(monkeypatch)

        with pytest.raises(ValueError, match="OPERATION_HEARTBEAT_STALE_SECONDS"):
            Settings(
                operation_heartbeat_interval_seconds=10,
                operation_heartbeat_stale_seconds=10,
            )

        with pytest.raises(ValueError, match="OPERATION_HEARTBEAT_STALE_SECONDS"):
            Settings(
                operation_heartbeat_interval_seconds=10,
                operation_heartbeat_stale_seconds=5,
            )
