# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Proof-backed volume completion hooks and recovery execution heartbeats."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.volume import Volume
from app.models.volume_backup import VolumeBackup
from app.models.volume_operation import VolumeOperation
from app.models.volume_restore import VolumeRestore
from app.services import volume_backup_service as volume_service_module
from app.services.operation_reconciler import OperationReconciler
from app.services.operation_reconciliation import (
    PROOF_RECOVERY_ARTIFACT,
    Liveness,
    OperationKind,
    ReconcileDecision,
    RuntimeState,
    TerminalState,
)
from app.services.volume_backup_service import RecoveryPolicy, VolumeBackupService
from app.services.volume_finalization import VolumeFinalizationHooks

POLICY = RecoveryPolicy(30, 20, 10**10, 10**11, 1024**2, 10)
METADATA = {
    "sha256": "d" * 64,
    "compressed_bytes": 10,
    "logical_bytes": 4,
    "member_count": 1,
    "executor_terminated": True,
}


@asynccontextmanager
async def _bound_session(db: AsyncSession):
    async with AsyncSession(
        bind=db.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session


def _factory(db: AsyncSession):
    return lambda: _bound_session(db)


class ReadOnlyDriver:
    """Runtime double whose mutating methods are hard failures."""

    def __init__(self):
        self.containers: dict[str, dict] = {}
        self.named: dict[str, str] = {}
        self.mutations: list[str] = []

    async def get_container_by_name(self, name):
        return self.named.get(name)

    async def get_container_info(self, identifier):
        info = self.containers.get(identifier)
        if info is None:
            from app.container.driver import ContainerDriverError

            raise ContainerDriverError("not found", status=404)
        return dict(info)

    async def list_containers(self, filters=None, *, all=False):
        return [dict(value) for value in self.containers.values()]

    async def _mutate(self, name):
        self.mutations.append(name)
        raise AssertionError(f"mutating driver method called: {name}")

    async def create_volume(self, name, labels=None):
        await self._mutate("create_volume")

    async def delete_volume(self, name):
        await self._mutate("delete_volume")

    async def create_recovery_helper(self, **kwargs):
        await self._mutate("create_recovery_helper")

    async def delete_container(self, identifier, force=False):
        await self._mutate("delete_container")

    async def stop_container(self, identifier, timeout=30):
        await self._mutate("stop_container")

    async def start_container(self, identifier):
        await self._mutate("start_container")


class FakeArtifacts:
    def __init__(self, metadata=None, *, archive_matches=True):
        self.metadata = metadata
        self.archive_matches = archive_matches
        self.reads = 0
        self.archive_checks = 0

    def read_completion(self, **kwargs):
        self.reads += 1
        return dict(self.metadata) if self.metadata is not None else None

    def backup_archive_matches(self, *, backup_id, metadata):
        self.archive_checks += 1
        return self.archive_matches


class RecordingFactory:
    """Bound session factory that signals after two completed heartbeat ticks."""

    def __init__(self, db: AsyncSession):
        self._db = db
        self.completed = 0
        self.beats = asyncio.Event()

    @asynccontextmanager
    async def _session(self):
        async with _bound_session(self._db) as session:
            yield session
        self.completed += 1
        if self.completed >= 2:
            self.beats.set()

    def __call__(self):
        return self._session()


class FailingSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def begin(self):
        return self

    async def execute(self, statement):
        raise RuntimeError("Heartbeat database unavailable")


class FailingFactory:
    def __call__(self):
        return FailingSession()


def _decision(kind: OperationKind, operation_id: uuid.UUID) -> ReconcileDecision:
    return ReconcileDecision(
        kind=kind,
        operation_id=operation_id,
        liveness=Liveness.STOPPED,
        proof_source=PROOF_RECOVERY_ARTIFACT,
        runtime_state=RuntimeState.PRESENT,
        terminal_state=TerminalState.SUCCEEDED,
        reason_code="artifact_verified",
    )


def _hooks(db: AsyncSession, artifacts, driver: ReadOnlyDriver | None = None):
    return VolumeFinalizationHooks(
        _factory(db),
        driver or ReadOnlyDriver(),
        policy=POLICY,
        artifact_inspector=artifacts,
    )


async def _volume(db, owner_id, *, status="active", size_bytes=0):
    volume = Volume(
        name="private-" + uuid.uuid4().hex,
        display_name="Private",
        owner_id=owner_id,
        visibility="private",
        status=status,
        size_bytes=size_bytes,
        max_size_bytes=1024**2,
    )
    db.add(volume)
    await db.flush()
    return volume


async def _backup_row(
    db,
    owner_id,
    *,
    status="in_progress",
    reserved_bytes=1000,
    sha256="d" * 64,
    guard_state="running",
):
    volume = await _volume(db, owner_id)
    backup = VolumeBackup(
        volume_name=volume.name,
        source_volume_id=volume.id,
        source_display_name=volume.display_name,
        user_id=owner_id,
        status=status,
        format_version="nukelab.volume/v1",
        sha256=sha256,
        size_bytes=10,
        logical_bytes=4,
        member_count=1,
        max_logical_bytes=1024,
        reserved_bytes=reserved_bytes,
        fencing_token=uuid.uuid4(),
    )
    db.add(backup)
    await db.flush()
    db.add(
        VolumeOperation(
            operation_id=backup.id,
            volume_id=volume.id,
            owner_id=owner_id,
            kind="backup",
            state=guard_state,
            fencing_token=backup.fencing_token,
        )
    )
    await db.flush()
    return backup, volume


async def _restore_row(
    db,
    owner_id,
    backup,
    *,
    status="in_progress",
    destination_status="restoring",
    destination_size=0,
    reserved_bytes=500,
    guard_state="running",
):
    destination = await _volume(
        db, owner_id, status=destination_status, size_bytes=destination_size
    )
    restore = VolumeRestore(
        backup_id=backup.id,
        user_id=owner_id,
        destination_volume_id=destination.id,
        destination_name=destination.name,
        display_name="Restored",
        max_size_bytes=1024,
        reserved_bytes=reserved_bytes,
        status=status,
        fencing_token=uuid.uuid4(),
    )
    db.add(restore)
    await db.flush()
    db.add(
        VolumeOperation(
            operation_id=restore.id,
            volume_id=destination.id,
            owner_id=owner_id,
            kind="restore",
            state=guard_state,
            fencing_token=restore.fencing_token,
        )
    )
    await db.flush()
    return restore, destination


async def _completed_backup(db, owner_id):
    backup, _ = await _backup_row(
        db,
        owner_id,
        status="completed",
        reserved_bytes=0,
        guard_state="succeeded",
    )
    return backup


async def _guard(db, operation_id):
    return await db.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == operation_id)
    )


@pytest.mark.asyncio
async def test_backup_hook_completes_once_with_verified_completion(db_session, test_user):
    backup, _ = await _backup_row(db_session, test_user.id)
    artifacts = FakeArtifacts(METADATA)
    driver = ReadOnlyDriver()
    hooks = _hooks(db_session, artifacts, driver)
    decision = _decision(OperationKind.BACKUP, backup.id)

    assert (
        await hooks.finish_backup(
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            decision=decision,
        )
        is True
    )

    row = await db_session.get(VolumeBackup, backup.id, populate_existing=True)
    guard = await _guard(db_session, backup.id)
    assert row.status == "completed"
    assert row.reserved_bytes == 0
    assert row.sha256 == METADATA["sha256"]
    assert row.size_bytes == METADATA["compressed_bytes"]
    assert row.logical_bytes == METADATA["logical_bytes"]
    assert row.member_count == METADATA["member_count"]
    assert row.completed_at is not None
    assert guard.state == "succeeded"
    assert artifacts.reads == 1
    assert artifacts.archive_checks == 1
    assert driver.mutations == []

    assert (
        await hooks.finish_backup(
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            decision=decision,
        )
        is False
    )
    assert artifacts.reads == 1
    assert driver.mutations == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata,archive_matches",
    [
        (None, True),
        ({**METADATA, "sha256": "not-a-digest"}, True),
        ({**METADATA, "logical_bytes": 10**6}, True),
        ({**METADATA, "member_count": 11}, True),
        ({**METADATA, "compressed_bytes": True}, True),
        (METADATA, False),
    ],
)
async def test_backup_hook_rejects_unverified_or_missing_completion(
    db_session, test_user, metadata, archive_matches
):
    backup, _ = await _backup_row(db_session, test_user.id)
    artifacts = FakeArtifacts(metadata, archive_matches=archive_matches)
    driver = ReadOnlyDriver()

    assert (
        await _hooks(db_session, artifacts, driver).finish_backup(
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            decision=_decision(OperationKind.BACKUP, backup.id),
        )
        is False
    )

    row = await db_session.get(VolumeBackup, backup.id, populate_existing=True)
    guard = await _guard(db_session, backup.id)
    assert row.status == "in_progress"
    assert row.reserved_bytes == 1000
    assert row.sha256 == "d" * 64
    assert guard.state == "running"
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_backup_hook_requires_active_matching_fence(db_session, test_user):
    backup, _ = await _backup_row(db_session, test_user.id)
    artifacts = FakeArtifacts(METADATA)
    hooks = _hooks(db_session, artifacts)

    assert (
        await hooks.finish_backup(
            backup_id=backup.id,
            fencing_token=uuid.uuid4(),
            decision=_decision(OperationKind.BACKUP, backup.id),
        )
        is False
    )
    row = await db_session.get(VolumeBackup, backup.id, populate_existing=True)
    assert row.status == "in_progress" and row.reserved_bytes == 1000
    assert artifacts.reads == 0

    for terminal in (TerminalState.RECOVERY_REQUIRED, TerminalState.FAILED, None):
        decision = ReconcileDecision(
            kind=OperationKind.BACKUP,
            operation_id=backup.id,
            liveness=Liveness.STOPPED,
            proof_source=PROOF_RECOVERY_ARTIFACT,
            runtime_state=RuntimeState.PRESENT,
            terminal_state=terminal,
            reason_code="artifact_verified",
        )
        assert (
            await hooks.finish_backup(
                backup_id=backup.id,
                fencing_token=backup.fencing_token,
                decision=decision,
            )
            is False
        )
    assert artifacts.reads == 0


@pytest.mark.asyncio
async def test_backup_hook_rejects_a_terminal_row_with_matching_fence(db_session, test_user):
    backup, _ = await _backup_row(
        db_session,
        test_user.id,
        status="failed",
        guard_state="failed",
    )
    artifacts = FakeArtifacts(METADATA)
    driver = ReadOnlyDriver()

    assert (
        await _hooks(db_session, artifacts, driver).finish_backup(
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            decision=_decision(OperationKind.BACKUP, backup.id),
        )
        is False
    )
    row = await db_session.get(VolumeBackup, backup.id, populate_existing=True)
    assert row.status == "failed" and row.reserved_bytes == 1000
    assert artifacts.reads == 0
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_backup_hook_rejects_a_still_running_helper(db_session, test_user):
    backup, _ = await _backup_row(db_session, test_user.id)
    driver = ReadOnlyDriver()
    helper = "helper-container"
    driver.named["nukelab-recovery-" + str(backup.id)] = helper
    driver.containers[helper] = {
        "Id": helper,
        "Config": {
            "Labels": {
                "nukelab.recovery.operation": str(backup.id),
                "nukelab.recovery.fence": str(backup.fencing_token),
                "nukelab.recovery.backup": str(backup.id),
            }
        },
        "State": {"Running": True, "Status": "running"},
    }
    artifacts = FakeArtifacts(METADATA)

    assert (
        await _hooks(db_session, artifacts, driver).finish_backup(
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            decision=_decision(OperationKind.BACKUP, backup.id),
        )
        is False
    )
    row = await db_session.get(VolumeBackup, backup.id, populate_existing=True)
    assert row.status == "in_progress" and row.reserved_bytes == 1000
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_restore_hook_activates_destination_exactly_once(db_session, test_user):
    backup = await _completed_backup(db_session, test_user.id)
    restore, destination = await _restore_row(db_session, test_user.id, backup)
    artifacts = FakeArtifacts(METADATA)
    driver = ReadOnlyDriver()
    hooks = _hooks(db_session, artifacts, driver)
    decision = _decision(OperationKind.RESTORE, restore.id)

    assert (
        await hooks.finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=decision,
        )
        is True
    )

    row = await db_session.get(VolumeRestore, restore.id, populate_existing=True)
    volume = await db_session.get(Volume, destination.id, populate_existing=True)
    guard = await _guard(db_session, restore.id)
    assert row.status == "completed"
    assert row.reserved_bytes == 0
    assert row.completed_at is not None
    assert volume.status == "active"
    assert volume.size_bytes == METADATA["logical_bytes"]
    assert guard.state == "succeeded"
    assert driver.mutations == []
    assert artifacts.archive_checks == 0

    assert (
        await hooks.finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=decision,
        )
        is False
    )
    assert artifacts.reads == 1
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_restore_hook_missing_metadata_leaves_recovery_required(db_session, test_user):
    backup = await _completed_backup(db_session, test_user.id)
    restore, destination = await _restore_row(
        db_session,
        test_user.id,
        backup,
        status="recovery_required",
        guard_state="recovery_required",
    )
    artifacts = FakeArtifacts(None)
    driver = ReadOnlyDriver()

    assert (
        await _hooks(db_session, artifacts, driver).finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=_decision(OperationKind.RESTORE, restore.id),
        )
        is False
    )

    row = await db_session.get(VolumeRestore, restore.id, populate_existing=True)
    volume = await db_session.get(Volume, destination.id, populate_existing=True)
    guard = await _guard(db_session, restore.id)
    assert row.status == "recovery_required"
    assert row.reserved_bytes == 500
    assert volume.status == "restoring"
    assert volume.size_bytes == 0
    assert guard.state == "recovery_required"
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_restore_hook_rejects_a_mismatched_backup_digest(db_session, test_user):
    backup = await _completed_backup(db_session, test_user.id)
    restore, destination = await _restore_row(db_session, test_user.id, backup)
    artifacts = FakeArtifacts({**METADATA, "sha256": "e" * 64})

    assert (
        await _hooks(db_session, artifacts).finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=_decision(OperationKind.RESTORE, restore.id),
        )
        is False
    )
    row = await db_session.get(VolumeRestore, restore.id, populate_existing=True)
    volume = await db_session.get(Volume, destination.id, populate_existing=True)
    assert row.status == "in_progress" and row.reserved_bytes == 500
    assert volume.status == "restoring" and volume.size_bytes == 0


@pytest.mark.asyncio
async def test_restore_hook_completes_an_active_destination_without_downgrade(
    db_session, test_user
):
    backup = await _completed_backup(db_session, test_user.id)
    restore, destination = await _restore_row(
        db_session,
        test_user.id,
        backup,
        destination_status="active",
        destination_size=METADATA["logical_bytes"],
    )
    artifacts = FakeArtifacts(METADATA)
    driver = ReadOnlyDriver()

    assert (
        await _hooks(db_session, artifacts, driver).finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=_decision(OperationKind.RESTORE, restore.id),
        )
        is True
    )
    row = await db_session.get(VolumeRestore, restore.id, populate_existing=True)
    volume = await db_session.get(Volume, destination.id, populate_existing=True)
    assert row.status == "completed" and row.reserved_bytes == 0
    assert volume.status == "active"
    assert volume.size_bytes == METADATA["logical_bytes"]
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_restore_hook_never_changes_an_active_destination_on_size_mismatch(
    db_session, test_user
):
    backup = await _completed_backup(db_session, test_user.id)
    restore, destination = await _restore_row(
        db_session,
        test_user.id,
        backup,
        destination_status="active",
        destination_size=9,
    )
    artifacts = FakeArtifacts(METADATA)
    driver = ReadOnlyDriver()

    assert (
        await _hooks(db_session, artifacts, driver).finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=_decision(OperationKind.RESTORE, restore.id),
        )
        is False
    )
    row = await db_session.get(VolumeRestore, restore.id, populate_existing=True)
    volume = await db_session.get(Volume, destination.id, populate_existing=True)
    assert row.status == "in_progress" and row.reserved_bytes == 500
    assert volume.status == "active" and volume.size_bytes == 9
    assert driver.mutations == []


def _runtime(metadata=None):
    runtime = Mock()
    runtime.check_helper = AsyncMock()
    runtime.assert_detached = AsyncMock()
    runtime.capture = AsyncMock(return_value=metadata or dict(METADATA))
    runtime.restore = AsyncMock(return_value=metadata or dict(METADATA))
    runtime.available_bytes.return_value = 10**12
    return runtime


def _fast_heartbeat(monkeypatch):
    real = volume_service_module.operation_heartbeat

    def heartbeat(session_factory=None, *, kind, operation_id, fencing_token, executor_id):
        return real(
            session_factory,
            kind=kind,
            operation_id=operation_id,
            fencing_token=fencing_token,
            executor_id=executor_id,
            interval=0.02,
        )

    monkeypatch.setattr(volume_service_module, "operation_heartbeat", heartbeat)


async def _wait_for_second_beat(factory):
    await asyncio.wait_for(factory.beats.wait(), timeout=5)


def _finish_observations(db, model, finish):
    observed = []

    async def wrapper(identifier, token, **kwargs):
        row = await db.get(model, identifier, populate_existing=True)
        observed.append(row.heartbeat_at)
        await asyncio.sleep(0.05)
        row = await db.get(model, identifier, populate_existing=True)
        observed.append(row.heartbeat_at)
        return await finish(identifier, token, **kwargs)

    return observed, wrapper


@pytest.mark.asyncio
async def test_backup_heartbeat_runs_during_io_and_stops_before_finalization(
    db_session, test_user, monkeypatch
):
    _fast_heartbeat(monkeypatch)
    factory = RecordingFactory(db_session)
    runtime = _runtime()
    service = VolumeBackupService(
        db_session,
        runtime,
        POLICY,
        heartbeat_session_factory=factory,
    )
    volume = await _volume(db_session, test_user.id)
    await db_session.commit()

    io_started = []

    async def capture(*args, **kwargs):
        io_started.append(utc_now())
        await _wait_for_second_beat(factory)
        return dict(METADATA)

    runtime.capture.side_effect = capture
    pending = await service.reserve_backup(test_user.id, volume.id)
    observed, wrapper = _finish_observations(db_session, VolumeBackup, service._finish_backup)
    monkeypatch.setattr(service, "_finish_backup", wrapper)

    result = await service.execute_backup(pending.id)

    assert result.status == "completed"
    assert factory.completed >= 2
    assert observed[0] is not None and observed[0] > io_started[0]
    assert observed[0] == observed[1]


@pytest.mark.asyncio
async def test_restore_heartbeat_runs_during_io_and_stops_before_finalization(
    db_session, test_user, monkeypatch
):
    _fast_heartbeat(monkeypatch)
    monkeypatch.setattr(settings, "xfs_quota_enabled", False)
    factory = RecordingFactory(db_session)
    runtime = _runtime()
    service = VolumeBackupService(
        db_session,
        runtime,
        POLICY,
        heartbeat_session_factory=factory,
    )
    backup, _ = await _backup_row(db_session, test_user.id, status="completed", reserved_bytes=0)
    await db_session.commit()

    io_started = []

    async def restore(*args, **kwargs):
        io_started.append(utc_now())
        await _wait_for_second_beat(factory)
        return dict(METADATA)

    runtime.restore.side_effect = restore
    pending = await service.reserve_restore(test_user.id, backup.id, "Restored", 1024**2)
    observed, wrapper = _finish_observations(db_session, VolumeRestore, service._finish_restore)
    monkeypatch.setattr(service, "_finish_restore", wrapper)

    result = await service.execute_restore(pending.id)

    assert result.status == "completed"
    assert factory.completed >= 2
    assert observed[0] is not None and observed[0] > io_started[0]
    assert observed[0] == observed[1]


@pytest.mark.asyncio
async def test_heartbeat_database_failure_does_not_fail_backup(db_session, test_user, monkeypatch):
    _fast_heartbeat(monkeypatch)
    service = VolumeBackupService(
        db_session,
        _runtime(),
        POLICY,
        heartbeat_session_factory=FailingFactory(),
    )
    volume = await _volume(db_session, test_user.id)
    await db_session.commit()

    pending = await service.reserve_backup(test_user.id, volume.id)
    result = await service.execute_backup(pending.id)

    assert result.status == "completed"
    row = await db_session.get(VolumeBackup, pending.id, populate_existing=True)
    assert row.status == "completed" and row.heartbeat_at is None


@pytest.mark.asyncio
async def test_heartbeat_database_failure_does_not_fail_restore(db_session, test_user, monkeypatch):
    _fast_heartbeat(monkeypatch)
    monkeypatch.setattr(settings, "xfs_quota_enabled", False)
    service = VolumeBackupService(
        db_session,
        _runtime(),
        POLICY,
        heartbeat_session_factory=FailingFactory(),
    )
    backup, _ = await _backup_row(db_session, test_user.id, status="completed", reserved_bytes=0)
    await db_session.commit()

    pending = await service.reserve_restore(test_user.id, backup.id, "Restored", 1024**2)
    result = await service.execute_restore(pending.id)

    assert result.status == "completed"
    row = await db_session.get(VolumeRestore, pending.id, populate_existing=True)
    assert row.status == "completed" and row.heartbeat_at is None


@pytest.mark.asyncio
async def test_reconciler_completes_proof_backed_backup_and_second_scan_is_noop(
    db_session, test_user
):
    backup, _ = await _backup_row(db_session, test_user.id, reserved_bytes=1000)
    artifacts = FakeArtifacts(METADATA)
    driver = ReadOnlyDriver()
    hooks = _hooks(db_session, artifacts, driver)
    reconciler = OperationReconciler(
        _factory(db_session),
        driver,
        artifact_inspector=artifacts,
        volume_hooks=hooks,
    )

    first = await reconciler.scan()
    second = await reconciler.scan()

    assert first.finalized == 1
    assert second.scanned == 0 and second.finalized == 0
    row = await db_session.get(VolumeBackup, backup.id, populate_existing=True)
    guard = await _guard(db_session, backup.id)
    assert row.status == "completed" and row.reserved_bytes == 0
    assert guard.state == "succeeded"
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_reconciler_completes_proof_backed_restore_and_second_scan_is_noop(
    db_session, test_user
):
    backup = await _completed_backup(db_session, test_user.id)
    restore, destination = await _restore_row(
        db_session,
        test_user.id,
        backup,
        destination_status="restoring",
        destination_size=0,
    )
    artifacts = FakeArtifacts(METADATA)
    driver = ReadOnlyDriver()
    hooks = _hooks(db_session, artifacts, driver)
    reconciler = OperationReconciler(
        _factory(db_session),
        driver,
        artifact_inspector=artifacts,
        volume_hooks=hooks,
    )

    first = await reconciler.scan()
    second = await reconciler.scan()

    assert first.finalized == 1
    assert second.scanned == 0 and second.finalized == 0
    row = await db_session.get(VolumeRestore, restore.id, populate_existing=True)
    volume = await db_session.get(Volume, destination.id, populate_existing=True)
    guard = await _guard(db_session, restore.id)
    assert row.status == "completed" and row.reserved_bytes == 0
    assert volume.status == "active" and volume.size_bytes == METADATA["logical_bytes"]
    assert guard.state == "succeeded"
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_executor_termination_requires_exact_helper_proof(db_session, test_user):
    from app.container.driver import ContainerDriverError

    backup, _ = await _backup_row(db_session, test_user.id)
    driver = ReadOnlyDriver()
    hooks = _hooks(db_session, FakeArtifacts(METADATA), driver)
    name = "nukelab-recovery-" + str(backup.id)

    async def lookup_failure(value):
        raise RuntimeError("runtime unavailable")

    driver.get_container_by_name = lookup_failure
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is False
    )

    async def non_string_identity(value):
        return 123

    driver.get_container_by_name = non_string_identity
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is False
    )

    async def named_helper(value):
        assert value == name
        return "helper"

    driver.get_container_by_name = named_helper
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is True
    )

    async def unavailable(value):
        raise ContainerDriverError("runtime unavailable", status=500)

    driver.get_container_info = unavailable
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is False
    )

    async def unexpected(value):
        raise RuntimeError("unexpected runtime failure")

    driver.get_container_info = unexpected
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is False
    )

    async def container_lookup(identifier):
        return dict(driver.containers[identifier])

    driver.get_container_info = container_lookup
    labels = {
        "nukelab.recovery.operation": str(backup.id),
        "nukelab.recovery.fence": str(backup.fencing_token),
        "nukelab.recovery.backup": str(backup.id),
    }
    driver.containers["helper"] = {
        "Id": "other-container",
        "Config": {"Labels": labels},
        "State": {"Running": False, "Status": "exited"},
    }
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is False
    )

    driver.containers["helper"] = {
        "Id": "helper",
        "Config": {},
        "State": {"Running": False, "Status": "exited"},
    }
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is False
    )

    driver.containers["helper"] = {
        "Id": "helper",
        "Config": {"Labels": {**labels, "nukelab.recovery.fence": str(uuid.uuid4())}},
        "State": {"Running": False, "Status": "exited"},
    }
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is False
    )

    driver.containers["helper"] = {
        "Id": "helper",
        "Config": {"Labels": labels},
        "State": {"Running": "no", "Status": "exited"},
    }
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is False
    )

    driver.containers["helper"] = {
        "Id": "helper",
        "Config": {"Labels": labels},
        "State": {"Running": False, "Status": "removing"},
    }
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is False
    )

    driver.containers["helper"] = {
        "Id": "helper",
        "Config": {"Labels": labels},
        "State": {"Running": False, "Status": "exited"},
    }
    assert (
        await hooks._executor_terminated(
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
        )
        is True
    )


@pytest.mark.asyncio
async def test_finish_hooks_reject_mismatched_operations_and_unknown_rows(db_session, test_user):
    backup, _ = await _backup_row(db_session, test_user.id)
    hooks = _hooks(db_session, FakeArtifacts(METADATA))
    assert (
        await hooks.finish_backup(
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            decision=_decision(OperationKind.BACKUP, uuid.uuid4()),
        )
        is False
    )
    assert (
        await hooks.finish_backup(
            backup_id=uuid.uuid4(),
            fencing_token=uuid.uuid4(),
            decision=_decision(OperationKind.BACKUP, uuid.uuid4()),
        )
        is False
    )

    completed_backup = await _completed_backup(db_session, test_user.id)
    restore, _ = await _restore_row(db_session, test_user.id, completed_backup)
    assert (
        await hooks.finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=_decision(OperationKind.BACKUP, restore.id),
        )
        is False
    )
    assert (
        await hooks.finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=_decision(OperationKind.RESTORE, uuid.uuid4()),
        )
        is False
    )
    assert (
        await hooks.finish_restore(
            restore_id=uuid.uuid4(),
            fencing_token=uuid.uuid4(),
            decision=_decision(OperationKind.RESTORE, uuid.uuid4()),
        )
        is False
    )


@pytest.mark.asyncio
async def test_restore_hook_rejects_invalid_backup_digest_and_bounds(db_session, test_user):
    backup = await _completed_backup(db_session, test_user.id)
    restore, _ = await _restore_row(db_session, test_user.id, backup)
    hooks = _hooks(db_session, FakeArtifacts(METADATA))

    backup.sha256 = "not-a-digest"
    await db_session.flush()
    assert (
        await hooks.finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=_decision(OperationKind.RESTORE, restore.id),
        )
        is False
    )

    backup.sha256 = METADATA["sha256"]
    restore.max_size_bytes = 0
    await db_session.flush()
    assert (
        await hooks.finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=_decision(OperationKind.RESTORE, restore.id),
        )
        is False
    )


@pytest.mark.asyncio
async def test_completion_and_archive_failures_are_not_proof(db_session, test_user, monkeypatch):
    backup, _ = await _backup_row(db_session, test_user.id)
    hooks = _hooks(db_session, FakeArtifacts(METADATA))

    assert (
        await hooks._completion(
            kind=OperationKind.BACKUP,
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            maximum=0,
        )
        is None
    )
    assert (
        await hooks._completion(
            kind=OperationKind.BACKUP,
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            maximum=1024,
        )
        == METADATA
    )
    assert hooks._valid_metadata(["not", "a", "mapping"], maximum=1024) is False

    async def failure(*args, **kwargs):
        raise RuntimeError("artifact read failed")

    monkeypatch.setattr(hooks, "_completion", failure)
    assert (
        await hooks.finish_backup(
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            decision=_decision(OperationKind.BACKUP, backup.id),
        )
        is False
    )

    class RaisingArtifacts(FakeArtifacts):
        def read_completion(self, **kwargs):
            raise RuntimeError("artifact read failed")

        def backup_archive_matches(self, *, backup_id, metadata):
            raise RuntimeError("archive read failed")

    raising = _hooks(db_session, RaisingArtifacts(METADATA))
    assert (
        await raising._completion(
            kind=OperationKind.BACKUP,
            operation_id=backup.id,
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            maximum=1024,
        )
        is None
    )
    assert await raising._archive_matches(backup.id, METADATA) is False
    assert (
        await raising.finish_backup(
            backup_id=backup.id,
            fencing_token=backup.fencing_token,
            decision=_decision(OperationKind.BACKUP, backup.id),
        )
        is False
    )

    completed_backup = await _completed_backup(db_session, test_user.id)
    restore, _ = await _restore_row(db_session, test_user.id, completed_backup)
    restore_hooks = _hooks(db_session, FakeArtifacts(METADATA))
    monkeypatch.setattr(restore_hooks, "_executor_terminated", AsyncMock(return_value=False))
    assert (
        await restore_hooks.finish_restore(
            restore_id=restore.id,
            fencing_token=restore.fencing_token,
            decision=_decision(OperationKind.RESTORE, restore.id),
        )
        is False
    )
