# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded reconciliation scans over durable launch and volume journals."""

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.volume import Volume
from app.models.volume_backup import VolumeBackup
from app.models.volume_operation import VolumeOperation
from app.models.volume_restore import VolumeRestore
from app.models.worker_heartbeat import WorkerHeartbeat
from app.services import operation_reconciler as reconciler_module
from app.services.operation_finalizer import OperationFinalizer
from app.services.operation_reconciler import OperationReconciler, ReconcileReport
from app.services.operation_reconciliation import (
    Liveness,
    OperationKind,
    ReconcileDecision,
    ReconciliationService,
    RuntimeState,
    TerminalState,
)
from tests.services.test_operation_finalizer import (
    LOCAL_ID,
    FakeArtifactInspector,
    FakeDriver,
    completion_metadata,
    container_info,
    local_identity,
)
from tests.services.test_operation_finalizer import (
    add_launch as add_full_launch,
)

CONTAINER_STARTED_AT = "2026-11-21T09:00:00.000000000Z"


@asynccontextmanager
async def _bound_session(db: AsyncSession):
    async with AsyncSession(
        bind=db.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session


def session_factory(db: AsyncSession):
    return lambda: _bound_session(db)


@dataclass
class MinimalLaunch:
    server: Server
    operation: ServerLaunchOperation
    revision: EnvironmentRevision


def add_worker_row(
    db: AsyncSession,
    executor_id: uuid.UUID,
    *,
    state: str = "running",
    heartbeat_at=None,
) -> None:
    db.add(
        WorkerHeartbeat(
            executor_id=executor_id,
            hostname="worker-host",
            container_id="worker-container",
            container_started_at=CONTAINER_STARTED_AT,
            pid=1234,
            process_start_time="100",
            single_process_container=True,
            schema_version="nukelab-journal/v1",
            state=state,
            heartbeat_at=heartbeat_at or utc_now(),
        )
    )


async def add_minimal_launch(
    db: AsyncSession,
    user,
    *,
    state: str = "prepared",
    action: str = "create",
    created_at=None,
    executor_id=None,
    heartbeat_at=None,
    worker_state=None,
    previous_container_id=None,
    server_status: str = "starting",
    with_gpu: bool = False,
    with_mount: bool = False,
) -> MinimalLaunch:
    marker = uuid.uuid4().hex
    template = EnvironmentTemplate(
        name=f"template-{marker}",
        slug=f"template-{marker}",
        image="approved:latest",
        is_active=True,
        is_public=True,
    )
    db.add(template)
    await db.flush()
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint="a" * 64,
        template_fingerprint="b" * 64,
        configuration={},
        runtime_identity=local_identity(),
    )
    db.add(revision)
    await db.flush()
    server = Server(
        name=f"server-{marker}",
        user_id=user.id,
        status=server_status,
        container_id=previous_container_id if server_status == "stopping" else None,
    )
    db.add(server)
    await db.flush()
    operation = ServerLaunchOperation(
        server_id=server.id,
        owner_id=user.id,
        action=action,
        state=state,
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        heartbeat_at=heartbeat_at,
        revision_id=revision.id,
        request_payload=None,
        mounts=[],
        gpu_devices=[],
        username=user.username,
        resources={},
        generation=1,
        previous_container_id=previous_container_id,
        previous_status="running" if previous_container_id else None,
        created_at=created_at or utc_now(),
    )
    db.add(operation)
    await db.flush()
    if executor_id is not None and worker_state is not None:
        add_worker_row(db, executor_id, state=worker_state)
    if with_gpu:
        db.add(GpuAllocation(server_id=server.id, device=f"nvidia.com/gpu={marker}"))
    if with_mount:
        volume = Volume(
            name=f"volume-{marker}",
            display_name="Launch volume",
            owner_id=user.id,
            visibility="private",
            status="active",
            size_bytes=0,
            max_size_bytes=1024**3,
        )
        db.add(volume)
        await db.flush()
        db.add(
            VolumeOperation(
                operation_id=operation.id,
                volume_id=volume.id,
                owner_id=user.id,
                kind="mount",
                state="reserved",
                fencing_token=uuid.uuid4(),
            )
        )
    await db.flush()
    return MinimalLaunch(server=server, operation=operation, revision=revision)


async def add_backup_row(
    db: AsyncSession,
    user,
    *,
    status: str = "in_progress",
    created_at=None,
    executor_id=None,
    reserved_bytes: int = 1000,
    fencing_token=None,
    volume_guard: bool = False,
) -> VolumeBackup:
    marker = uuid.uuid4().hex
    volume = Volume(
        name=f"backup-source-{marker}",
        display_name="Source",
        owner_id=user.id,
        visibility="private",
        status="active",
        size_bytes=0,
        max_size_bytes=1024**3,
    )
    db.add(volume)
    await db.flush()
    backup = VolumeBackup(
        volume_name=volume.name,
        source_volume_id=volume.id,
        source_display_name=volume.display_name,
        user_id=user.id,
        status=status,
        format_version="nukelab.volume/v1",
        sha256="d" * 64,
        logical_bytes=4,
        member_count=1,
        max_logical_bytes=1024,
        reserved_bytes=reserved_bytes,
        fencing_token=fencing_token or uuid.uuid4(),
        executor_id=executor_id,
        created_at=created_at or utc_now(),
    )
    db.add(backup)
    await db.flush()
    if volume_guard:
        db.add(
            VolumeOperation(
                operation_id=backup.id,
                volume_id=volume.id,
                owner_id=user.id,
                kind="backup",
                state="running",
                fencing_token=backup.fencing_token,
            )
        )
    await db.flush()
    return backup


async def add_restore_row(
    db: AsyncSession,
    user,
    backup: VolumeBackup,
    *,
    status: str = "in_progress",
    created_at=None,
    executor_id=None,
    reserved_bytes: int = 500,
) -> VolumeRestore:
    marker = uuid.uuid4().hex
    destination = Volume(
        name=f"restore-destination-{marker}",
        display_name="Restored",
        owner_id=user.id,
        visibility="private",
        status="restoring",
        size_bytes=0,
        max_size_bytes=1024**3,
    )
    db.add(destination)
    await db.flush()
    restore = VolumeRestore(
        backup_id=backup.id,
        user_id=user.id,
        destination_volume_id=destination.id,
        destination_name=destination.name,
        display_name="Restored",
        max_size_bytes=1024,
        reserved_bytes=reserved_bytes,
        status=status,
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        created_at=created_at or utc_now(),
    )
    db.add(restore)
    await db.flush()
    return restore


def deferred_decision(kind: OperationKind, operation_id: uuid.UUID) -> ReconcileDecision:
    return ReconcileDecision(
        kind=kind,
        operation_id=operation_id,
        liveness=Liveness.ALIVE,
        proof_source="worker_heartbeat",
        runtime_state=RuntimeState.ABSENT,
        terminal_state=None,
        reason_code="runtime_absent",
    )


class RecordingInspection:
    """Minimal replacement for ``ReconciliationService`` that records order."""

    def __init__(self, *, decisions=None, error_ids=()):
        self.calls: list[tuple[OperationKind, uuid.UUID]] = []
        self.decisions = decisions or {}
        self.error_ids = set(error_ids)

    def __call__(self, db, driver, *, artifact_inspector=None, clock=None):
        return self

    async def inspect(self, kind, operation_id):
        self.calls.append((kind, operation_id))
        if operation_id in self.error_ids:
            raise RuntimeError("inspection failed")
        return self.decisions.get(operation_id) or deferred_decision(kind, operation_id)


async def _gpu_count(db: AsyncSession, server_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == server_id)
        )
    ) or 0


async def _refresh(db: AsyncSession, *rows) -> None:
    for row in rows:
        await db.refresh(row)


@pytest.mark.asyncio
async def test_scan_batches_active_rows_fairly_and_skips_terminal(
    db_session, test_user, monkeypatch
):
    now = utc_now()
    oldest = await add_minimal_launch(
        db_session,
        test_user,
        state="executing",
        created_at=now - timedelta(seconds=500),
    )
    newer = await add_minimal_launch(
        db_session,
        test_user,
        state="executing",
        created_at=now - timedelta(seconds=400),
    )
    backup = await add_backup_row(
        db_session,
        test_user,
        status="in_progress",
        created_at=now - timedelta(seconds=300),
    )
    restore = await add_restore_row(
        db_session,
        test_user,
        backup,
        status="in_progress",
        created_at=now - timedelta(seconds=200),
    )
    terminal_launch = await add_minimal_launch(
        db_session,
        test_user,
        state="succeeded",
        created_at=now - timedelta(seconds=600),
    )
    terminal_backup = await add_backup_row(
        db_session,
        test_user,
        status="completed",
        created_at=now - timedelta(seconds=600),
    )
    terminal_restore = await add_restore_row(
        db_session,
        test_user,
        terminal_backup,
        status="completed",
        created_at=now - timedelta(seconds=600),
    )

    inspection = RecordingInspection()
    monkeypatch.setattr(reconciler_module, "ReconciliationService", inspection)
    reconciler = OperationReconciler(session_factory(db_session), FakeDriver())

    report = await reconciler.scan(limit=3)

    assert report == ReconcileReport(
        scanned=3,
        finalized=0,
        deferred=3,
        recovery_required=0,
        errors=0,
        duration_seconds=report.duration_seconds,
    )
    assert inspection.calls == [
        (OperationKind.LAUNCH, oldest.operation.id),
        (OperationKind.BACKUP, backup.id),
        (OperationKind.RESTORE, restore.id),
    ]
    inspected_ids = {operation_id for _, operation_id in inspection.calls}
    assert inspected_ids.isdisjoint(
        {
            newer.operation.id,
            terminal_launch.operation.id,
            terminal_backup.id,
            terminal_restore.id,
        }
    )

    monkeypatch.setattr(settings, "recovery_scan_batch_size", 2)
    capped = RecordingInspection()
    monkeypatch.setattr(reconciler_module, "ReconciliationService", capped)

    second = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert second.scanned == 2
    assert capped.calls == [
        (OperationKind.LAUNCH, oldest.operation.id),
        (OperationKind.BACKUP, backup.id),
    ]


@pytest.mark.asyncio
async def test_prepared_row_inside_grace_is_deferred_without_inspection(
    db_session, test_user, monkeypatch
):
    row = await add_minimal_launch(
        db_session,
        test_user,
        state="prepared",
        created_at=utc_now() - timedelta(seconds=settings.recovery_prepared_grace_seconds - 1),
    )
    inspection = RecordingInspection()
    monkeypatch.setattr(reconciler_module, "ReconciliationService", inspection)

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.scanned == 1
    assert report.deferred == 1
    assert inspection.calls == []
    await db_session.refresh(row.operation)
    assert row.operation.state == "prepared"


@pytest.mark.asyncio
async def test_old_unclaimed_prepared_row_without_runtime_fails_with_proof(db_session, test_user):
    row = await add_minimal_launch(
        db_session,
        test_user,
        state="prepared",
        created_at=utc_now() - timedelta(seconds=settings.recovery_prepared_grace_seconds + 5),
        with_gpu=True,
        with_mount=True,
    )

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.scanned == 1
    assert report.finalized == 1
    await _refresh(db_session, row.operation, row.server)
    assert row.operation.state == "failed"
    assert row.operation.reason_code == "prepared_unclaimed"
    assert row.server.status == "error"
    assert row.server.status_reason == "prepared_unclaimed"
    assert await _gpu_count(db_session, row.server.id) == 0
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == row.operation.id)
    )
    assert guard.state == "succeeded"


@pytest.mark.asyncio
async def test_prepared_row_with_live_executor_is_deferred(db_session, test_user):
    executor_id = uuid.uuid4()
    row = await add_minimal_launch(
        db_session,
        test_user,
        state="prepared",
        executor_id=executor_id,
        worker_state="running",
        created_at=utc_now() - timedelta(seconds=settings.recovery_prepared_grace_seconds + 5),
        with_gpu=True,
    )

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.deferred == 1
    await db_session.refresh(row.operation)
    assert row.operation.state == "prepared"
    assert await _gpu_count(db_session, row.server.id) == 1


@pytest.mark.asyncio
async def test_prepared_row_with_ambiguous_executor_is_not_failed(db_session, test_user):
    row = await add_minimal_launch(
        db_session,
        test_user,
        state="prepared",
        executor_id=uuid.uuid4(),
        worker_state=None,
        created_at=utc_now() - timedelta(seconds=settings.recovery_prepared_grace_seconds + 5),
        with_gpu=True,
    )

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.recovery_required == 1
    await db_session.refresh(row.operation)
    assert row.operation.state == "uncertain"
    assert row.operation.reason_code == "runtime_absent"
    assert await _gpu_count(db_session, row.server.id) == 1


@pytest.mark.asyncio
async def test_prepared_row_with_present_runtime_is_not_failed_or_adopted(db_session, test_user):
    row = await add_minimal_launch(
        db_session,
        test_user,
        state="prepared",
        created_at=utc_now() - timedelta(seconds=settings.recovery_prepared_grace_seconds + 5),
        with_gpu=True,
    )
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=row.server.id,
        launch_id=row.operation.id,
        health="starting",
    )

    report = await OperationReconciler(session_factory(db_session), driver).scan()

    assert report.recovery_required == 1
    await _refresh(db_session, row.operation, row.server)
    assert row.operation.state == "uncertain"
    assert row.server.status == "starting"
    assert row.server.status_reason == "recovery_required"
    assert row.server.container_id is None
    assert await _gpu_count(db_session, row.server.id) == 1


@pytest.mark.asyncio
async def test_prepared_success_proof_is_downgraded_to_recovery_required(
    db_session, test_user, monkeypatch
):
    row = await add_minimal_launch(
        db_session,
        test_user,
        state="prepared",
        created_at=utc_now() - timedelta(seconds=settings.recovery_prepared_grace_seconds + 5),
    )
    decision = ReconcileDecision(
        kind=OperationKind.LAUNCH,
        operation_id=row.operation.id,
        liveness=Liveness.AMBIGUOUS,
        proof_source="launch_runtime",
        runtime_state=RuntimeState.PRESENT,
        terminal_state=TerminalState.SUCCEEDED,
        reason_code="runtime_verified",
        detail={"container_id": "container-unproven"},
    )
    inspection = RecordingInspection(decisions={row.operation.id: decision})
    monkeypatch.setattr(reconciler_module, "ReconciliationService", inspection)

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.recovery_required == 1
    await _refresh(db_session, row.operation, row.server)
    assert row.operation.state == "uncertain"
    assert row.operation.reason_code == "prepared_runtime_present"
    assert row.server.status == "starting"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ServerLaunchRecord)
            .where(ServerLaunchRecord.server_id == row.server.id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_executing_success_finalizes_once_and_second_scan_is_noop(db_session, test_user):
    fixture = await add_full_launch(db_session, test_user)
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
    )
    reconciler = OperationReconciler(session_factory(db_session), driver)

    first = await reconciler.scan()

    assert first.scanned == 1
    assert first.finalized == 1
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    record_count = await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord))
    assert operation.state == "succeeded"
    assert record_count == 1

    second = await reconciler.scan()

    assert second.scanned == 0
    assert second.finalized == 0
    assert (
        await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord))
    ) == record_count


@pytest.mark.asyncio
async def test_executing_ambiguous_marks_recovery_required_without_release(db_session, test_user):
    fixture = await add_full_launch(db_session, test_user, executor_state="stopped")
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    for _ in range(2):
        container_id = f"container-{uuid.uuid4().hex}"
        driver.containers[container_id] = container_info(
            container_id,
            server_id=fixture.server_id,
            launch_id=fixture.operation_id,
        )

    report = await OperationReconciler(session_factory(db_session), driver).scan()

    assert report.recovery_required == 1
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == fixture.operation_id)
    )
    assert operation.state == "uncertain"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == fixture.server_id)
        )
        == 1
    )
    assert guard.state == "reserved"
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_live_executor_with_unhealthy_runtime_is_deferred(db_session, test_user):
    fixture = await add_full_launch(db_session, test_user)
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
        health="starting",
    )

    report = await OperationReconciler(session_factory(db_session), driver).scan()

    assert report.deferred == 1
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    assert operation.state == "executing"
    assert server.status == "starting"
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_live_executor_with_stale_operation_heartbeat_is_a_stall_observation(
    db_session, test_user, monkeypatch
):
    fixture = await add_full_launch(
        db_session,
        test_user,
        operation_heartbeat_at=utc_now() - timedelta(seconds=400),
    )
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
        health="starting",
    )
    warning = Mock()
    monkeypatch.setattr(reconciler_module.logger, "warning", warning)

    report = await OperationReconciler(session_factory(db_session), driver).scan()

    assert report.deferred == 1
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    assert operation.state == "executing"
    warning.assert_called_once()
    assert warning.call_args.args[0] == ("Operation heartbeat is stale while its executor is alive")


@pytest.mark.asyncio
async def test_per_row_error_does_not_abort_other_rows(db_session, test_user, monkeypatch):
    now = utc_now()
    failing = await add_minimal_launch(
        db_session,
        test_user,
        state="prepared",
        created_at=now - timedelta(seconds=settings.recovery_prepared_grace_seconds + 20),
    )
    finalizing = await add_minimal_launch(
        db_session,
        test_user,
        state="prepared",
        created_at=now - timedelta(seconds=settings.recovery_prepared_grace_seconds + 10),
    )
    decision = ReconcileDecision(
        kind=OperationKind.LAUNCH,
        operation_id=finalizing.operation.id,
        liveness=Liveness.STOPPED,
        proof_source="graceful_marker",
        runtime_state=RuntimeState.ABSENT,
        terminal_state=TerminalState.FAILED,
        reason_code="runtime_absent",
    )
    inspection = RecordingInspection(
        decisions={finalizing.operation.id: decision},
        error_ids={failing.operation.id},
    )
    monkeypatch.setattr(reconciler_module, "ReconciliationService", inspection)

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.scanned == 2
    assert report.errors == 1
    assert report.finalized == 1
    await _refresh(db_session, failing.operation, finalizing.operation)
    assert failing.operation.state == "prepared"
    assert finalizing.operation.state == "failed"


@pytest.mark.asyncio
async def test_pending_volume_reservation_is_never_failed(db_session, test_user, monkeypatch):
    row = await add_backup_row(
        db_session,
        test_user,
        status="pending",
        created_at=utc_now() - timedelta(seconds=600),
        reserved_bytes=999,
    )
    monkeypatch.setattr(settings, "recovery_legacy_drain_confirmed", True)
    artifacts = FakeArtifactInspector(metadata=None)

    report = await OperationReconciler(
        session_factory(db_session), FakeDriver(), artifact_inspector=artifacts
    ).scan()

    assert report.deferred == 1
    await db_session.refresh(row)
    assert row.status == "pending"
    assert row.reserved_bytes == 999
    assert row.completed_at is None


@pytest.mark.asyncio
async def test_volume_recovery_required_retains_reservation(db_session, test_user):
    row = await add_backup_row(
        db_session,
        test_user,
        status="in_progress",
        executor_id=uuid.uuid4(),
        reserved_bytes=2048,
        volume_guard=True,
    )
    artifacts = FakeArtifactInspector(metadata=None)

    report = await OperationReconciler(
        session_factory(db_session), FakeDriver(), artifact_inspector=artifacts
    ).scan()

    assert report.recovery_required == 1
    await db_session.refresh(row)
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == row.id)
    )
    assert row.status == "recovery_required"
    assert row.reason_code == "helper_absent"
    assert row.reserved_bytes == 2048
    assert row.completed_at is None
    assert guard.state == "recovery_required"


@pytest.mark.asyncio
async def test_uncertain_row_without_new_proof_is_left_alone(db_session, test_user):
    row = await add_minimal_launch(
        db_session,
        test_user,
        state="uncertain",
        executor_id=uuid.uuid4(),
        worker_state=None,
        created_at=utc_now() - timedelta(seconds=600),
        with_gpu=True,
    )

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.recovery_required == 1
    await db_session.refresh(row.operation)
    assert row.operation.state == "uncertain"
    assert await _gpu_count(db_session, row.server.id) == 1


@pytest.mark.asyncio
async def test_durable_row_reconciles_without_delivery_and_redelivery_is_idempotent(
    db_session, test_user, monkeypatch
):
    fixture = await add_full_launch(db_session, test_user)
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
    )
    async with _bound_session(db_session) as inspect_db:
        decision = await ReconciliationService(inspect_db, driver).inspect(
            "launch", fixture.operation_id
        )
    assert decision.terminal_state is TerminalState.SUCCEEDED
    observed_fence = (
        await db_session.get(ServerLaunchOperation, fixture.operation_id, populate_existing=True)
    ).fencing_token

    original_finalize = OperationReconciler._finalize
    attempts = 0

    async def flaky_finalize(self, decision, expected_fence):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("database unavailable")
        return await original_finalize(self, decision, expected_fence)

    monkeypatch.setattr(OperationReconciler, "_finalize", flaky_finalize)
    reconciler = OperationReconciler(session_factory(db_session), driver)

    failed = await reconciler.scan()

    assert failed.errors == 1
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    assert operation.state == "executing"

    recovered = await reconciler.scan()

    assert recovered.finalized == 1
    assert (await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord))) == 1

    async with _bound_session(db_session) as replay_db:
        replayed = await OperationFinalizer(replay_db, driver).finalize(
            decision, expected_fence=observed_fence
        )
    assert replayed is False
    assert (await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord))) == 1


@pytest.mark.asyncio
async def test_volume_success_without_hooks_is_deferred(db_session, test_user):
    row = await add_backup_row(
        db_session,
        test_user,
        status="in_progress",
        executor_id=uuid.uuid4(),
        reserved_bytes=1000,
    )
    artifacts = FakeArtifactInspector(metadata=completion_metadata())

    report = await OperationReconciler(
        session_factory(db_session), FakeDriver(), artifact_inspector=artifacts
    ).scan()

    assert report.deferred == 1
    await db_session.refresh(row)
    assert row.status == "in_progress"
    assert row.reserved_bytes == 1000


@pytest.mark.asyncio
async def test_scan_selection_failure_is_reported_without_raising():
    def failing_factory():
        raise RuntimeError("database unavailable")

    report = await OperationReconciler(failing_factory, FakeDriver()).scan()

    assert report.scanned == 0
    assert report.errors == 1


@pytest.mark.asyncio
async def test_scan_rejects_an_invalid_limit_and_accepts_zero(db_session):
    reconciler = OperationReconciler(session_factory(db_session), FakeDriver())

    with pytest.raises(ValueError):
        await reconciler.scan(limit=-1)
    with pytest.raises(ValueError):
        await reconciler.scan(limit=True)

    empty = await reconciler.scan(limit=0)
    assert empty.scanned == 0


def test_report_is_bounded_and_contains_no_row_payloads():
    report = ReconcileReport(
        scanned=4,
        finalized=1,
        deferred=2,
        recovery_required=1,
        errors=0,
        duration_seconds=0.25,
    )

    assert report.as_dict() == {
        "scanned": 4,
        "finalized": 1,
        "deferred": 2,
        "recovery_required": 1,
        "errors": 0,
        "duration_seconds": 0.25,
    }
