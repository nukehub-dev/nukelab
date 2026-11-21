# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Proof-gated operation finalization against real journal rows."""

import asyncio
import copy
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utc_now
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server
from app.models.server_launch_intent import ServerLaunchIntent
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.server_volume import ServerVolume
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_backup import VolumeBackup
from app.models.volume_operation import VolumeOperation
from app.models.volume_restore import VolumeRestore
from app.models.worker_heartbeat import WorkerHeartbeat
from app.services.operation_finalizer import OperationFinalizer
from app.services.operation_reconciliation import (
    Liveness,
    OperationKind,
    ReconcileDecision,
    ReconciliationService,
    RuntimeState,
    TerminalState,
)
from app.services.server_launch_validation import normalize_launch_request
from tests.conftest import test_engine

LOCAL_ID = "sha256:" + "a" * 64
MANIFEST_DIGEST = "sha256:" + "c" * 64
VERIFIED_REFERENCE = "registry.example.test/nukelab/runtime@" + MANIFEST_DIGEST
CONTAINER_STARTED_AT = "2026-11-21T09:00:00.000000000Z"


class FakeDriver:
    """Read-only runtime double; every mutating method is a hard failure."""

    def __init__(self):
        self.containers: dict[str, dict] = {}
        self.images: dict[str, dict] = {}
        self.named: dict[str, str] = {}
        self.mutations: list[str] = []
        self.unavailable = False
        self.ready = True
        self.readiness_probes: list[tuple[str, str]] = []

    async def get_container_info(self, identifier):
        self._fail_if_unavailable()
        info = self.containers.get(identifier)
        if info is None:
            from app.container.driver import ContainerDriverError

            raise ContainerDriverError("not found", status=404)
        return copy.deepcopy(info)

    async def list_containers(self, filters=None, *, all=False):
        self._fail_if_unavailable()
        return [copy.deepcopy(value) for value in self.containers.values()]

    async def get_container_by_name(self, name):
        self._fail_if_unavailable()
        return self.named.get(name)

    async def resolve_image(self, reference):
        self._fail_if_unavailable()
        identity = self.images.get(reference)
        if identity is None:
            from app.container.driver import ContainerDriverError

            raise ContainerDriverError("image missing", status=404)
        return copy.deepcopy(identity)

    async def wait_for_container_ready(
        self, container_name, health_url, timeout=None, interval=None, body_contains=None
    ):
        self._fail_if_unavailable()
        self.readiness_probes.append((container_name, health_url))
        return self.ready

    async def _mutate(self, name):
        self.mutations.append(name)
        raise AssertionError(f"mutating driver method called: {name}")

    async def pull_image(self, image):
        await self._mutate("pull_image")

    async def create_container(self, *args, **kwargs):
        await self._mutate("create_container")

    async def start_container(self, container_id):
        await self._mutate("start_container")

    async def stop_container(self, container_id, timeout=30):
        await self._mutate("stop_container")

    async def delete_container(self, container_id, force=True):
        await self._mutate("delete_container")

    async def create_recovery_helper(self, **kwargs):
        await self._mutate("create_recovery_helper")

    async def wait_recovery_helper(self, container_id, timeout):
        await self._mutate("wait_recovery_helper")

    async def ensure_volume(self, name, labels=None):
        await self._mutate("ensure_volume")

    async def create_volume(self, name, labels=None):
        await self._mutate("create_volume")

    async def delete_volume(self, name):
        await self._mutate("delete_volume")

    def _fail_if_unavailable(self):
        if self.unavailable:
            from app.container.driver import ContainerDriverError

            raise ContainerDriverError("runtime unavailable", status=500)


class FakeArtifactInspector:
    def __init__(self, *, metadata=None, archive_matches=True):
        self.metadata = metadata
        self.archive_matches = archive_matches
        self.reads = 0

    def read_completion(self, **kwargs):
        self.reads += 1
        return copy.deepcopy(self.metadata)

    def backup_archive_matches(self, *, backup_id, metadata):
        return self.archive_matches


class RecordingVolumeHooks:
    def __init__(self, db, *, complete_backup=False, complete_restore=False):
        self.db = db
        self.complete_backup = complete_backup
        self.complete_restore = complete_restore
        self.calls: list[tuple[str, uuid.UUID, uuid.UUID, TerminalState | None]] = []

    async def finish_backup(self, *, backup_id, fencing_token, decision):
        self.calls.append(("backup", backup_id, fencing_token, decision.terminal_state))
        if not self.complete_backup:
            return False
        row = await self.db.get(VolumeBackup, backup_id, populate_existing=True)
        row.status = "completed"
        row.reserved_bytes = 0
        row.completed_at = utc_now()
        await self.db.commit()
        return True

    async def finish_restore(self, *, restore_id, fencing_token, decision):
        self.calls.append(("restore", restore_id, fencing_token, decision.terminal_state))
        if not self.complete_restore:
            return False
        row = await self.db.get(VolumeRestore, restore_id, populate_existing=True)
        row.status = "completed"
        row.reserved_bytes = 0
        row.completed_at = utc_now()
        await self.db.commit()
        return True


def local_identity(*, local_id=LOCAL_ID, architecture="amd64"):
    return {
        "requested_reference": "approved:latest",
        "local_id": local_id,
        "repository_digests": [],
        "os": "linux",
        "architecture": architecture,
        "registry_verified": False,
    }


def verified_identity():
    return {
        "requested_reference": "registry.example.test/nukelab/runtime:latest",
        "local_id": LOCAL_ID,
        "repository_digests": [VERIFIED_REFERENCE],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": True,
        "verified_reference": VERIFIED_REFERENCE,
        "manifest_digest": MANIFEST_DIGEST,
        "descriptor_media_type": "application/vnd.oci.image.manifest.v1+json",
    }


def container_info(
    container_id,
    *,
    server_id,
    launch_id,
    image=LOCAL_ID,
    running=True,
    health="healthy",
):
    return {
        "Id": container_id,
        "Image": image,
        "Config": {
            "Labels": {
                "nukelab.server.id": str(server_id),
                "nukelab.launch.id": str(launch_id),
            }
        },
        "State": {
            "Running": running,
            "Status": "running" if running else "exited",
            "StartedAt": CONTAINER_STARTED_AT,
            "Health": {"Status": health},
        },
    }


def completion_metadata(*, sha256="d" * 64):
    return {
        "sha256": sha256,
        "compressed_bytes": 10,
        "logical_bytes": 4,
        "member_count": 1,
    }


async def add_worker(
    db,
    executor_id,
    *,
    state="running",
    heartbeat_at=None,
    container_id="worker-container",
    container_started_at=CONTAINER_STARTED_AT,
):
    db.add(
        WorkerHeartbeat(
            executor_id=executor_id,
            hostname="worker-host",
            container_id=container_id,
            container_started_at=container_started_at,
            pid=1234,
            process_start_time="100",
            single_process_container=False,
            schema_version="nukelab-journal/v1",
            state=state,
            heartbeat_at=heartbeat_at or utc_now(),
        )
    )
    await db.flush()


@dataclass
class LaunchFixture:
    server_id: uuid.UUID
    operation_id: uuid.UUID
    revision_id: uuid.UUID
    template_id: uuid.UUID
    plan_id: uuid.UUID
    volume_id: uuid.UUID
    queue_id: uuid.UUID | None
    queue_claim_token: uuid.UUID | None
    username: str


async def add_launch(
    db,
    owner,
    *,
    action="create",
    executor_state="running",
    operation_heartbeat_at=None,
    worker_heartbeat_at=None,
    previous_container_id=None,
    server_status="starting",
    with_gpu=True,
    with_queue=True,
    commit=True,
):
    marker = uuid.uuid4().hex
    plan = ServerPlan(
        name=f"plan-{marker}",
        slug=f"plan-{marker}",
        cpu_limit=1.0,
        memory_limit="1g",
        disk_limit="2g",
        gpu_limit=0,
        cost_per_hour=0,
        is_active=True,
        is_public=True,
    )
    template = EnvironmentTemplate(
        name=f"template-{marker}",
        slug=f"template-{marker}",
        image="approved:latest",
        is_active=True,
        is_public=True,
    )
    db.add_all([plan, template])
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
    volume = Volume(
        name=f"volume-{marker}",
        display_name="Launch volume",
        owner_id=owner.id,
        visibility="private",
        status="active",
        size_bytes=0,
        max_size_bytes=1024**3,
    )
    db.add(volume)
    await db.flush()
    request = normalize_launch_request(
        {
            "name": f"server-{marker}",
            "plan_id": str(plan.id),
            "environment_id": str(template.id),
            "volume_mounts": [
                {
                    "volume_id": str(volume.id),
                    "mount_path": f"/home/{owner.username}",
                    "mode": "read_write",
                    "max_size_bytes": 1024**3,
                }
            ],
        },
        username=owner.username,
    )
    server = Server(
        name=request.name,
        user_id=owner.id,
        plan_id=plan.id,
        environment_id=template.id,
        status=server_status,
        container_id=previous_container_id if server_status == "stopping" else None,
        allocated_cpu=1.0,
        allocated_memory="1g",
        allocated_disk="2g",
        allocated_gpu=0,
        volume_id=volume.id,
        volume_mode="read_write",
    )
    db.add(server)
    await db.flush()
    volume.labels = {"initialize_for_server": str(server.id)}
    mount = {
        "volume_id": str(volume.id),
        "volume_name": volume.name,
        "mount_path": f"/home/{owner.username}",
        "mode": "read_write",
        "is_primary": True,
        "max_size_bytes": 1024**3,
        "auto_created": False,
    }
    db.add(
        ServerVolume(
            server_id=server.id,
            volume_id=volume.id,
            mount_path=mount["mount_path"],
            mode=mount["mode"],
            is_primary=True,
        )
    )
    operation_id = server.id if action == "create" else uuid.uuid4()
    guard = VolumeOperation(
        operation_id=operation_id,
        volume_id=volume.id,
        owner_id=owner.id,
        kind="mount",
        state="reserved",
        fencing_token=uuid.uuid4(),
    )
    db.add(guard)
    if with_gpu:
        db.add(GpuAllocation(server_id=server.id, device=f"nvidia.com/gpu={marker}"))
    executor_id = uuid.uuid4()
    operation = ServerLaunchOperation(
        id=operation_id,
        server_id=server.id,
        owner_id=owner.id,
        action=action,
        state="executing",
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        heartbeat_at=operation_heartbeat_at or utc_now(),
        revision_id=revision.id,
        request_payload=request.model_dump(mode="json"),
        mounts=[mount],
        gpu_devices=[],
        username=owner.username,
        environment_slug=template.slug,
        resources={"cpu": 1.0, "memory": "1g", "disk": "2g", "gpu": 0},
        generation=1,
        previous_container_id=previous_container_id,
        previous_status="running" if previous_container_id else None,
    )
    db.add(operation)
    queue = None
    if action == "create" and with_queue:
        claim_token = uuid.uuid4()
        queue = ServerQueue(
            user_id=owner.id,
            environment_id=template.id,
            plan_id=plan.id,
            status="starting",
            server_name=request.name,
            request_payload=request.model_dump(mode="json"),
            request_version=1,
            plan_snapshot={},
            revision_id=revision.id,
            priority=0,
            server_id=server.id,
            claim_token=claim_token,
            requested_at=utc_now(),
        )
        db.add(queue)
        await db.flush()
        db.add(
            ServerLaunchIntent(
                server_id=server.id,
                owner_id=owner.id,
                revision_id=revision.id,
                request_payload=request.model_dump(mode="json"),
                mounts=[mount],
                gpu_devices=[],
                environment_slug=template.slug,
                username=owner.username,
                queue_id=queue.id,
                claim_token=claim_token,
            )
        )
    await add_worker(
        db,
        executor_id,
        state=executor_state,
        heartbeat_at=worker_heartbeat_at,
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return LaunchFixture(
        server_id=server.id,
        operation_id=operation.id,
        revision_id=revision.id,
        template_id=template.id,
        plan_id=plan.id,
        volume_id=volume.id,
        queue_id=queue.id if queue is not None else None,
        queue_claim_token=queue.claim_token if queue is not None else None,
        username=owner.username,
    )


@dataclass
class BackupFixture:
    backup_id: uuid.UUID
    volume_id: uuid.UUID
    fencing_token: uuid.UUID


async def add_backup(db, owner, *, executor_state="running", reserved_bytes=1000):
    marker = uuid.uuid4().hex
    volume = Volume(
        name=f"backup-source-{marker}",
        display_name="Source",
        owner_id=owner.id,
        visibility="private",
        status="active",
        size_bytes=0,
        max_size_bytes=1024**3,
    )
    db.add(volume)
    await db.flush()
    executor_id = uuid.uuid4()
    backup = VolumeBackup(
        volume_name=volume.name,
        source_volume_id=volume.id,
        source_display_name=volume.display_name,
        user_id=owner.id,
        status="in_progress",
        format_version="nukelab.volume/v1",
        sha256="d" * 64,
        logical_bytes=4,
        member_count=1,
        max_logical_bytes=1024,
        reserved_bytes=reserved_bytes,
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        heartbeat_at=utc_now(),
    )
    db.add(backup)
    await db.flush()
    db.add(
        VolumeOperation(
            operation_id=backup.id,
            volume_id=volume.id,
            owner_id=owner.id,
            kind="backup",
            state="running",
            fencing_token=backup.fencing_token,
        )
    )
    await add_worker(db, executor_id, state=executor_state)
    await db.commit()
    return BackupFixture(backup.id, volume.id, backup.fencing_token)


@dataclass
class RestoreFixture:
    restore_id: uuid.UUID
    destination_volume_id: uuid.UUID
    fencing_token: uuid.UUID


async def add_restore(
    db,
    owner,
    *,
    destination_status="restoring",
    destination_size=0,
    executor_state="running",
    reserved_bytes=1000,
):
    marker = uuid.uuid4().hex
    source = Volume(
        name=f"restore-source-{marker}",
        display_name="Source",
        owner_id=owner.id,
        visibility="private",
        status="active",
        size_bytes=0,
        max_size_bytes=1024**3,
    )
    destination = Volume(
        name=f"restore-destination-{marker}",
        display_name="Restored",
        owner_id=owner.id,
        visibility="private",
        status=destination_status,
        size_bytes=destination_size,
        max_size_bytes=1024**3,
    )
    db.add_all([source, destination])
    await db.flush()
    backup = VolumeBackup(
        volume_name=source.name,
        source_volume_id=source.id,
        source_display_name=source.display_name,
        user_id=owner.id,
        status="completed",
        format_version="nukelab.volume/v1",
        sha256="d" * 64,
        size_bytes=10,
        logical_bytes=4,
        member_count=1,
        max_logical_bytes=1024,
        reserved_bytes=0,
        fencing_token=uuid.uuid4(),
        completed_at=utc_now(),
    )
    db.add(backup)
    await db.flush()
    executor_id = uuid.uuid4()
    restore = VolumeRestore(
        backup_id=backup.id,
        user_id=owner.id,
        destination_volume_id=destination.id,
        destination_name=destination.name,
        display_name="Restored",
        max_size_bytes=1024,
        reserved_bytes=reserved_bytes,
        status="in_progress",
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        heartbeat_at=utc_now(),
    )
    db.add(restore)
    await db.flush()
    db.add(
        VolumeOperation(
            operation_id=restore.id,
            volume_id=destination.id,
            owner_id=owner.id,
            kind="restore",
            state="running",
            fencing_token=restore.fencing_token,
        )
    )
    await add_worker(db, executor_id, state=executor_state)
    await db.commit()
    return RestoreFixture(restore.id, destination.id, restore.fencing_token)


async def inspect(db, driver, kind, operation_id, artifacts=None):
    return await ReconciliationService(db, driver, artifact_inspector=artifacts).inspect(
        kind, operation_id
    )


@pytest.mark.asyncio
async def test_success_applies_once_and_terminal_row_is_immutable(db_session, test_user):
    fixture = await add_launch(db_session, test_user)
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
    )
    decision = await inspect(db_session, driver, "launch", fixture.operation_id)
    assert decision.terminal_state is TerminalState.SUCCEEDED
    finalizer = OperationFinalizer(db_session, driver)

    assert await finalizer.finalize(decision) is True

    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    queue = await db_session.get(ServerQueue, fixture.queue_id, populate_existing=True)
    volume = await db_session.get(Volume, fixture.volume_id, populate_existing=True)
    record = await db_session.scalar(
        select(ServerLaunchRecord).where(ServerLaunchRecord.server_id == fixture.server_id)
    )
    assert operation.state == "succeeded"
    assert operation.reason_code is None
    assert operation.finished_at is not None
    assert server.status == "running"
    assert server.container_id == container_id
    assert server.image == LOCAL_ID
    assert server.started_at is not None
    assert server.status_reason is None
    assert queue.status == "started"
    assert queue.started_at == server.started_at
    assert queue.reason_code is None
    assert "initialize_for_server" not in (volume.labels or {})
    assert record is not None
    assert record.revision_id == fixture.revision_id
    assert record.actual_runtime_identity["local_id"] == LOCAL_ID
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 1

    before = {
        "operation": (
            operation.state,
            operation.reason_code,
            operation.finished_at,
        ),
        "server": (server.status, server.container_id, server.started_at),
        "queue": (queue.status, queue.started_at, queue.reason_code),
    }
    assert await finalizer.finalize(decision) is False
    await db_session.refresh(operation)
    await db_session.refresh(server)
    await db_session.refresh(queue)
    assert before == {
        "operation": (
            operation.state,
            operation.reason_code,
            operation.finished_at,
        ),
        "server": (server.status, server.container_id, server.started_at),
        "queue": (queue.status, queue.started_at, queue.reason_code),
    }
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 1
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_success_requires_container_and_public_readiness(db_session, test_user):
    fixture = await add_launch(db_session, test_user)
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
    )
    decision = await inspect(db_session, driver, "launch", fixture.operation_id)
    assert decision.terminal_state is TerminalState.SUCCEEDED

    driver.ready = False
    assert await OperationFinalizer(db_session, driver).finalize(decision) is False

    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    assert operation.state == "executing"
    assert server.status == "starting"
    assert driver.readiness_probes
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_fence_mismatch_and_terminal_rows_are_noops(db_session, test_user):
    fixture = await add_launch(db_session, test_user)
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
    )
    decision = await inspect(db_session, driver, "launch", fixture.operation_id)
    finalizer = OperationFinalizer(db_session, driver)

    assert await finalizer.finalize(decision, expected_fence=uuid.uuid4()) is False
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    assert operation.state == "executing"
    assert server.status == "starting"
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 0

    operation.state = "succeeded"
    await db_session.commit()
    assert await finalizer.finalize(decision) is False
    await db_session.refresh(operation)
    await db_session.refresh(server)
    assert operation.state == "succeeded"
    assert server.status == "starting"
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 0

    missing = ReconcileDecision(
        kind=OperationKind.LAUNCH,
        operation_id=uuid.uuid4(),
        liveness=Liveness.STOPPED,
        proof_source="graceful_marker",
        runtime_state=RuntimeState.ABSENT,
        terminal_state=TerminalState.SUCCEEDED,
        reason_code="runtime_verified",
    )
    assert await finalizer.finalize(missing) is False
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 0


@pytest.mark.asyncio
async def test_live_executor_and_missing_terminal_state_never_fail(db_session, test_user):
    fixture = await add_launch(db_session, test_user)
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
        health="starting",
    )
    decision = await inspect(db_session, driver, "launch", fixture.operation_id)
    assert decision.liveness is Liveness.ALIVE
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    finalizer = OperationFinalizer(db_session, driver)

    assert await finalizer.finalize(decision) is False
    forced_failure = ReconcileDecision(
        kind=OperationKind.LAUNCH,
        operation_id=fixture.operation_id,
        liveness=Liveness.ALIVE,
        proof_source="runtime_inspection",
        runtime_state=RuntimeState.ABSENT,
        terminal_state=TerminalState.FAILED,
        reason_code="runtime_absent",
    )
    assert await finalizer.finalize(forced_failure) is False
    deferred = ReconcileDecision(
        kind=OperationKind.LAUNCH,
        operation_id=fixture.operation_id,
        liveness=Liveness.ALIVE,
        proof_source="worker_heartbeat",
        runtime_state=RuntimeState.ABSENT,
        terminal_state=None,
        reason_code="runtime_absent",
    )
    assert await finalizer.finalize(deferred) is False

    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    assert operation.state == "executing"
    assert operation.reason_code is None
    assert server.status == "starting"
    assert server.status_reason is None
    assert await db_session.scalar(select(func.count()).select_from(GpuAllocation)) == 1
    guard = await db_session.scalar(
        select(VolumeOperation).where(
            VolumeOperation.operation_id == fixture.operation_id,
        )
    )
    assert guard.state == "reserved"
    assert driver.mutations == []


@pytest.mark.asyncio
async def test_stale_operation_heartbeat_is_not_takeover_permission(db_session, test_user):
    old = utc_now().replace(year=2020)
    fixture = await add_launch(
        db_session,
        test_user,
        operation_heartbeat_at=old,
    )
    driver = FakeDriver()
    decision = await inspect(db_session, driver, "launch", fixture.operation_id)
    assert decision.liveness is Liveness.ALIVE
    assert decision.terminal_state is None

    assert await OperationFinalizer(db_session, driver).finalize(decision) is False
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    assert operation.state == "executing"
    assert await db_session.scalar(select(func.count()).select_from(GpuAllocation)) == 1


@pytest.mark.asyncio
async def test_launch_failure_releases_only_proof_safe_reservations(db_session, test_user):
    fixture = await add_launch(db_session, test_user, executor_state="stopped")
    driver = FakeDriver()
    decision = await inspect(db_session, driver, "launch", fixture.operation_id)
    assert decision.terminal_state is TerminalState.FAILED
    assert decision.liveness is Liveness.STOPPED
    assert decision.runtime_state is RuntimeState.ABSENT
    finalizer = OperationFinalizer(db_session, driver)

    assert await finalizer.finalize(decision) is True

    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    queue = await db_session.get(ServerQueue, fixture.queue_id, populate_existing=True)
    guard = await db_session.scalar(
        select(VolumeOperation).where(
            VolumeOperation.operation_id == fixture.operation_id,
        )
    )
    assert operation.state == "failed"
    assert operation.reason_code == "runtime_absent"
    assert operation.finished_at is not None
    assert server.status == "error"
    assert server.container_id is None
    assert server.status_reason == "runtime_absent"
    assert queue.status == "failed"
    assert queue.reason_code == "runtime_absent"
    assert queue.failed_at is not None
    assert guard.state == "succeeded"
    assert await db_session.scalar(select(func.count()).select_from(GpuAllocation)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Volume)) == 1
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 0
    assert driver.mutations == []
    assert await finalizer.finalize(decision) is False


@pytest.mark.asyncio
async def test_ambiguous_launch_marks_recovery_required_without_release(db_session, test_user):
    fixture = await add_launch(db_session, test_user, executor_state="stopped")
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    for _ in range(2):
        container_id = f"container-{uuid.uuid4().hex}"
        driver.containers[container_id] = container_info(
            container_id,
            server_id=fixture.server_id,
            launch_id=fixture.operation_id,
        )
    decision = await inspect(db_session, driver, "launch", fixture.operation_id)
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.runtime_state is RuntimeState.AMBIGUOUS
    finalizer = OperationFinalizer(db_session, driver)

    assert await finalizer.finalize(decision) is True

    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    queue = await db_session.get(ServerQueue, fixture.queue_id, populate_existing=True)
    guard = await db_session.scalar(
        select(VolumeOperation).where(
            VolumeOperation.operation_id == fixture.operation_id,
        )
    )
    assert operation.state == "uncertain"
    assert operation.reason_code == "multiple_runtime_containers"
    assert server.status == "starting"
    assert server.status_reason == "recovery_required"
    assert queue.status == "starting"
    assert queue.reason_code == "recovery_required"
    assert guard.state == "reserved"
    assert await db_session.scalar(select(func.count()).select_from(GpuAllocation)) == 1
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 0
    assert driver.mutations == []
    assert await finalizer.finalize(decision) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["stop", "delete"])
async def test_proof_backed_termination_finishes_without_runtime_mutation(
    db_session, test_user, action
):
    predecessor = f"container-{uuid.uuid4().hex}"
    fixture = await add_launch(
        db_session,
        test_user,
        action=action,
        executor_state="stopped",
        previous_container_id=predecessor,
        server_status="stopping",
    )
    driver = FakeDriver()
    decision = await inspect(db_session, driver, "launch", fixture.operation_id)
    assert decision.terminal_state is TerminalState.SUCCEEDED
    assert decision.runtime_state is RuntimeState.ABSENT

    assert await OperationFinalizer(db_session, driver).finalize(decision) is True

    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == fixture.operation_id)
    )
    assert guard.state == "succeeded"
    assert await db_session.scalar(select(func.count()).select_from(GpuAllocation)) == 0
    assert driver.mutations == []
    if action == "stop":
        server = await db_session.get(Server, fixture.server_id, populate_existing=True)
        operation = await db_session.get(
            ServerLaunchOperation, fixture.operation_id, populate_existing=True
        )
        assert server.status == "stopped"
        assert server.container_id is None
        assert operation.state == "succeeded"
    else:
        assert await db_session.get(Server, fixture.server_id, populate_existing=True) is None


@pytest.mark.asyncio
async def test_backup_failure_releases_storage_only_with_proof(db_session, test_user):
    fixture = await add_backup(db_session, test_user, executor_state="stopped")
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=None)
    decision = await inspect(db_session, driver, "backup", fixture.backup_id, artifacts)
    assert decision.terminal_state is TerminalState.FAILED
    finalizer = OperationFinalizer(db_session, driver)

    assert await finalizer.finalize(decision) is True

    backup = await db_session.get(VolumeBackup, fixture.backup_id, populate_existing=True)
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == fixture.backup_id)
    )
    assert backup.status == "failed"
    assert backup.reason_code == "helper_absent"
    assert backup.reserved_bytes == 0
    assert backup.completed_at is not None
    assert guard.state == "failed"
    assert await db_session.scalar(select(func.count()).select_from(Volume)) >= 1
    assert driver.mutations == []
    assert await finalizer.finalize(decision) is False


@pytest.mark.asyncio
async def test_backup_recovery_required_retains_reserved_bytes(db_session, test_user):
    fixture = await add_backup(db_session, test_user, reserved_bytes=2048)
    backup = await db_session.get(VolumeBackup, fixture.backup_id)
    await db_session.delete(await db_session.get(WorkerHeartbeat, backup.executor_id))
    await db_session.commit()
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=None)
    decision = await inspect(db_session, driver, "backup", fixture.backup_id, artifacts)
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    finalizer = OperationFinalizer(db_session, driver)

    assert await finalizer.finalize(decision) is True

    backup = await db_session.get(VolumeBackup, fixture.backup_id, populate_existing=True)
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == fixture.backup_id)
    )
    assert backup.status == "recovery_required"
    assert backup.reserved_bytes == 2048
    assert guard.state == "recovery_required"
    assert await finalizer.finalize(decision) is False


@pytest.mark.asyncio
async def test_backup_success_uses_volume_hook_only_with_artifact_proof(db_session, test_user):
    owner_id = test_user.id
    fixture = await add_backup(db_session, test_user)
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=completion_metadata())
    decision = await inspect(db_session, driver, "backup", fixture.backup_id, artifacts)
    assert decision.terminal_state is TerminalState.SUCCEEDED
    hooks = RecordingVolumeHooks(db_session, complete_backup=True)
    finalizer = OperationFinalizer(db_session, driver, volume_hooks=hooks)

    assert await finalizer.finalize(decision) is True
    backup = await db_session.get(VolumeBackup, fixture.backup_id, populate_existing=True)
    assert backup.status == "completed"
    assert backup.reserved_bytes == 0
    assert hooks.calls == [
        ("backup", fixture.backup_id, fixture.fencing_token, TerminalState.SUCCEEDED)
    ]
    assert await finalizer.finalize(decision) is False
    assert len(hooks.calls) == 1
    assert driver.mutations == []

    owner = await db_session.get(User, owner_id, populate_existing=True)
    unproven = await add_backup(db_session, owner)
    unproven_artifacts = FakeArtifactInspector(metadata=None)
    unproven_decision = await inspect(
        db_session, driver, "backup", unproven.backup_id, unproven_artifacts
    )
    assert unproven_decision.terminal_state is None
    hooks = RecordingVolumeHooks(db_session, complete_backup=True)
    assert (
        await OperationFinalizer(db_session, driver, volume_hooks=hooks).finalize(unproven_decision)
        is False
    )
    assert hooks.calls == []
    deferred = await db_session.get(VolumeBackup, unproven.backup_id, populate_existing=True)
    assert deferred.status == "in_progress"
    assert deferred.reserved_bytes == 1000


@pytest.mark.asyncio
async def test_backup_success_without_hook_defers(db_session, test_user):
    fixture = await add_backup(db_session, test_user)
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=completion_metadata())
    decision = await inspect(db_session, driver, "backup", fixture.backup_id, artifacts)
    assert decision.terminal_state is TerminalState.SUCCEEDED

    assert await OperationFinalizer(db_session, driver).finalize(decision) is False
    backup = await db_session.get(VolumeBackup, fixture.backup_id, populate_existing=True)
    assert backup.status == "in_progress"
    assert backup.reserved_bytes == 1000


@pytest.mark.asyncio
async def test_restore_missing_artifact_stays_recovery_required(db_session, test_user):
    fixture = await add_restore(db_session, test_user, executor_state="stopped")
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=None)
    decision = await inspect(db_session, driver, "restore", fixture.restore_id, artifacts)
    assert decision.terminal_state is TerminalState.FAILED
    finalizer = OperationFinalizer(db_session, driver)

    assert await finalizer.finalize(decision) is True

    restore = await db_session.get(VolumeRestore, fixture.restore_id, populate_existing=True)
    destination = await db_session.get(
        Volume, fixture.destination_volume_id, populate_existing=True
    )
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == fixture.restore_id)
    )
    assert restore.status == "recovery_required"
    assert restore.status != "failed"
    assert restore.reserved_bytes == 1000
    assert destination.status == "restoring"
    assert destination.size_bytes == 0
    assert guard.state == "recovery_required"
    assert driver.mutations == []
    assert await finalizer.finalize(decision) is False


@pytest.mark.asyncio
async def test_restore_success_uses_hook_without_attaching_destination(db_session, test_user):
    fixture = await add_restore(
        db_session,
        test_user,
        destination_status="active",
        destination_size=4,
    )
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=completion_metadata())
    decision = await inspect(db_session, driver, "restore", fixture.restore_id, artifacts)
    assert decision.terminal_state is TerminalState.SUCCEEDED
    hooks = RecordingVolumeHooks(db_session, complete_restore=True)
    finalizer = OperationFinalizer(db_session, driver, volume_hooks=hooks)

    assert await finalizer.finalize(decision) is True
    restore = await db_session.get(VolumeRestore, fixture.restore_id, populate_existing=True)
    destination = await db_session.get(
        Volume, fixture.destination_volume_id, populate_existing=True
    )
    assert restore.status == "completed"
    assert restore.reserved_bytes == 0
    assert destination.status == "active"
    assert destination.size_bytes == 4
    assert hooks.calls == [
        ("restore", fixture.restore_id, fixture.fencing_token, TerminalState.SUCCEEDED)
    ]
    assert await finalizer.finalize(decision) is False
    assert len(hooks.calls) == 1
    assert driver.mutations == []


async def _cleanup_committed_launch(fixture: LaunchFixture, owner_id):
    async with AsyncSession(test_engine) as cleanup, cleanup.begin():
        await cleanup.execute(
            delete(ServerLaunchRecord).where(ServerLaunchRecord.server_id == fixture.server_id)
        )
        await cleanup.execute(
            delete(ServerLaunchOperation).where(
                ServerLaunchOperation.server_id == fixture.server_id
            )
        )
        await cleanup.execute(
            delete(ServerLaunchIntent).where(ServerLaunchIntent.server_id == fixture.server_id)
        )
        if fixture.queue_id is not None:
            await cleanup.execute(delete(ServerQueue).where(ServerQueue.id == fixture.queue_id))
        await cleanup.execute(
            delete(ServerVolume).where(ServerVolume.server_id == fixture.server_id)
        )
        await cleanup.execute(
            delete(VolumeOperation).where(VolumeOperation.operation_id == fixture.operation_id)
        )
        await cleanup.execute(
            delete(GpuAllocation).where(GpuAllocation.server_id == fixture.server_id)
        )
        await cleanup.execute(delete(Server).where(Server.id == fixture.server_id))
        await cleanup.execute(delete(Volume).where(Volume.id == fixture.volume_id))
        await cleanup.execute(
            delete(EnvironmentRevision).where(EnvironmentRevision.id == fixture.revision_id)
        )
        await cleanup.execute(
            delete(EnvironmentTemplate).where(EnvironmentTemplate.id == fixture.template_id)
        )
        await cleanup.execute(delete(ServerPlan).where(ServerPlan.id == fixture.plan_id))
        await cleanup.execute(delete(User).where(User.id == owner_id))


@pytest.mark.asyncio
async def test_concurrent_finalize_produces_exactly_one_transition():
    marker = uuid.uuid4().hex
    owner_id = uuid.uuid4()
    async with AsyncSession(test_engine, expire_on_commit=False) as setup:
        setup.add(
            User(
                id=owner_id,
                username=f"finalizer_{marker}",
                email=f"{marker}@example.test",
                role="user",
                is_active=True,
                nuke_balance=100,
            )
        )
        await setup.flush()
        owner = await setup.get(User, owner_id)
        fixture = await add_launch(setup, owner)
    container_id = f"container-{marker}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
    )
    try:
        async with AsyncSession(test_engine, expire_on_commit=False) as inspect_db:
            decision = await ReconciliationService(inspect_db, driver).inspect(
                "launch", fixture.operation_id
            )
        assert decision.terminal_state is TerminalState.SUCCEEDED

        async def attempt():
            async with AsyncSession(test_engine, expire_on_commit=False) as db:
                return await OperationFinalizer(db, driver).finalize(decision)

        results = await asyncio.wait_for(asyncio.gather(attempt(), attempt()), timeout=10)
        assert sorted(results) == [False, True]

        async with AsyncSession(test_engine, expire_on_commit=False) as verify:
            operation = await verify.get(
                ServerLaunchOperation, fixture.operation_id, populate_existing=True
            )
            server = await verify.get(Server, fixture.server_id, populate_existing=True)
            records = await verify.scalar(
                select(func.count())
                .select_from(ServerLaunchRecord)
                .where(ServerLaunchRecord.server_id == fixture.server_id)
            )
            assert operation.state == "succeeded"
            assert server.status == "running"
            assert records == 1
    finally:
        await _cleanup_committed_launch(fixture, owner_id)
