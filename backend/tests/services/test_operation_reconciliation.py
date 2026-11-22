# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Read-only reconciliation decisions built from real rows and fake runtimes."""

import copy
import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriverError
from app.core.time_utils import utc_now
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.models.worker_heartbeat import WorkerHeartbeat
from app.services.operation_reconciliation import (
    PROOF_RECOVERY_ARTIFACT,
    Liveness,
    OperationKind,
    ReconciliationService,
    RuntimeState,
    TerminalState,
)

LOCAL_ID = "sha256:" + "a" * 64
OTHER_ID = "sha256:" + "b" * 64
MANIFEST_DIGEST = "sha256:" + "c" * 64
VERIFIED_REFERENCE = "registry.example.test/nukelab/runtime@" + MANIFEST_DIGEST
HEARTBEAT_STARTED_AT = "2026-11-21T09:00:00.000000000Z"
OTHER_STARTED_AT = "2026-11-21T09:05:00.000000000Z"


class FakeDriver:
    def __init__(self):
        self.containers: dict[str, dict] = {}
        self.images: dict[str, dict] = {}
        self.named: dict[str, str] = {}
        self.mutations: list[str] = []
        self.unavailable = False

    async def get_container_info(self, identifier):
        self._fail_if_unavailable()
        info = self.containers.get(identifier)
        if info is None:
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
            raise ContainerDriverError("image missing", status=404)
        return copy.deepcopy(identity)

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


def local_identity(*, local_id=LOCAL_ID, os_name="linux", architecture="amd64"):
    return {
        "requested_reference": "approved:latest",
        "local_id": local_id,
        "repository_digests": [],
        "os": os_name,
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
    started_at=HEARTBEAT_STARTED_AT,
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
            "StartedAt": started_at,
            "Health": {"Status": health},
        },
    }


@dataclass
class LaunchRows:
    server: Server
    operation: ServerLaunchOperation
    revision: EnvironmentRevision
    identity: dict


@dataclass
class BackupRows:
    backup: VolumeBackup
    operation_id: uuid.UUID
    fencing_token: uuid.UUID


async def add_worker(
    db: AsyncSession,
    executor_id,
    *,
    heartbeat_at=None,
    state="running",
    container_id="worker-container",
    container_started_at=HEARTBEAT_STARTED_AT,
    single_process_container=False,
):
    db.add(
        WorkerHeartbeat(
            executor_id=executor_id,
            hostname="worker-host",
            container_id=container_id,
            container_started_at=container_started_at,
            pid=1234,
            process_start_time="100",
            single_process_container=single_process_container,
            schema_version="nukelab-journal/v1",
            state=state,
            heartbeat_at=heartbeat_at or utc_now(),
        )
    )
    await db.flush()


async def add_launch(
    db: AsyncSession,
    user: User,
    *,
    action="create",
    state="executing",
    generation=1,
    executor_id=None,
    heartbeat_at=None,
    worker_state="running",
    single_process_container=False,
    previous_container_id=None,
    identity=None,
):
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
    resolved_identity = identity or local_identity()
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint="a" * 64,
        template_fingerprint="b" * 64,
        configuration={},
        runtime_identity=resolved_identity,
    )
    db.add(revision)
    await db.flush()
    server = Server(
        name=f"server-{marker}",
        user_id=user.id,
        status="starting",
        container_id=previous_container_id,
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
        request_payload={},
        mounts=[],
        gpu_devices=[],
        username=user.username,
        resources={},
        generation=generation,
        previous_container_id=previous_container_id,
    )
    db.add(operation)
    await db.flush()
    if executor_id is not None:
        await add_worker(
            db,
            executor_id,
            heartbeat_at=heartbeat_at,
            state=worker_state,
            single_process_container=single_process_container,
        )
    return LaunchRows(server, operation, revision, resolved_identity)


async def add_backup(
    db: AsyncSession,
    user: User,
    *,
    status="in_progress",
    executor_id=None,
    heartbeat_at=None,
    worker_state="running",
    single_process_container=False,
    sha256="d" * 64,
):
    marker = uuid.uuid4().hex
    backup = VolumeBackup(
        volume_name=f"volume-{marker}",
        user_id=user.id,
        source_display_name="source",
        format_version="nukelab.volume/v1",
        sha256=sha256,
        logical_bytes=4,
        member_count=1,
        max_logical_bytes=1024,
        reserved_bytes=0,
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        heartbeat_at=heartbeat_at,
        status=status,
    )
    db.add(backup)
    await db.flush()
    if executor_id is not None:
        await add_worker(
            db,
            executor_id,
            heartbeat_at=heartbeat_at,
            state=worker_state,
            single_process_container=single_process_container,
        )
    return BackupRows(backup, backup.id, backup.fencing_token)


async def add_restore(
    db: AsyncSession,
    user: User,
    backup: VolumeBackup,
    *,
    destination_status="restoring",
    status="in_progress",
    executor_id=None,
    heartbeat_at=None,
    worker_state="running",
    single_process_container=False,
):
    marker = uuid.uuid4().hex
    volume = Volume(
        name=f"restored-{marker}",
        display_name="Restored",
        owner_id=user.id,
        status=destination_status,
        size_bytes=4 if destination_status == "active" else 0,
    )
    db.add(volume)
    await db.flush()
    restore = VolumeRestore(
        backup_id=backup.id,
        user_id=user.id,
        destination_volume_id=volume.id,
        destination_name=volume.name,
        display_name="Restored",
        max_size_bytes=1024,
        reserved_bytes=0,
        status=status,
        fencing_token=uuid.uuid4(),
        executor_id=executor_id,
        heartbeat_at=heartbeat_at,
    )
    db.add(restore)
    await db.flush()
    if executor_id is not None:
        await add_worker(
            db,
            executor_id,
            heartbeat_at=heartbeat_at,
            state=worker_state,
            single_process_container=single_process_container,
        )
    return restore, volume


def add_helper(
    driver: FakeDriver,
    *,
    operation_id,
    fencing_token,
    backup_id,
    running=True,
    exit_code=0,
):
    helper_id = f"helper-{uuid.uuid4().hex}"
    driver.named[f"nukelab-recovery-{operation_id}"] = helper_id
    driver.containers[helper_id] = {
        "Id": helper_id,
        "Config": {
            "Labels": {
                "nukelab.recovery.operation": str(operation_id),
                "nukelab.recovery.fence": str(fencing_token),
                "nukelab.recovery.backup": str(backup_id),
            }
        },
        "State": {
            "Running": running,
            "Status": "running" if running else "exited",
            "ExitCode": exit_code,
        },
    }
    return helper_id


def completion_metadata(*, sha256="d" * 64):
    return {
        "sha256": sha256,
        "compressed_bytes": 10,
        "logical_bytes": 4,
        "member_count": 1,
    }


@pytest.mark.asyncio
async def test_fresh_worker_heartbeat_is_alive(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_launch(db_session, test_user, executor_id=executor_id)
    driver = FakeDriver()

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.ALIVE
    assert decision.proof_source == "worker_heartbeat"
    assert decision.terminal_state is None
    assert decision.reason_code == "runtime_absent"


@pytest.mark.asyncio
async def test_graceful_marker_proves_stopped(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
        worker_state="stopped",
    )
    driver = FakeDriver()

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.STOPPED
    assert decision.proof_source == "graceful_marker"
    assert decision.terminal_state is TerminalState.FAILED
    assert decision.reason_code == "runtime_absent"


@pytest.mark.asyncio
async def test_legacy_executor_requires_drain_confirmation(db_session, test_user, monkeypatch):
    monkeypatch.setattr(settings, "recovery_legacy_drain_confirmed", False)
    rows = await add_launch(db_session, test_user, executor_id=None)
    driver = FakeDriver()

    ambiguous = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert ambiguous.liveness is Liveness.AMBIGUOUS
    assert ambiguous.proof_source == "legacy_executor"
    assert ambiguous.terminal_state is TerminalState.RECOVERY_REQUIRED

    monkeypatch.setattr(settings, "recovery_legacy_drain_confirmed", True)
    stopped = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert stopped.liveness is Liveness.STOPPED
    assert stopped.proof_source == "legacy_drain"
    assert stopped.terminal_state is TerminalState.FAILED


@pytest.mark.asyncio
async def test_stale_api_executor_in_live_container_is_ambiguous(db_session, test_user):
    executor_id = uuid.uuid4()
    stale = utc_now() - timedelta(seconds=60)
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
        heartbeat_at=stale,
    )
    driver = FakeDriver()
    driver.containers["worker-container"] = {
        "Id": "worker-container",
        "Config": {"Labels": {}},
        "State": {"Running": True, "StartedAt": HEARTBEAT_STARTED_AT},
    }

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.AMBIGUOUS
    assert decision.proof_source == "api_executor_ambiguous"
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED


@pytest.mark.asyncio
async def test_replaced_single_process_executor_is_stopped(db_session, test_user):
    executor_id, replacement_id = uuid.uuid4(), uuid.uuid4()
    stale = utc_now() - timedelta(seconds=60)
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
        heartbeat_at=stale,
        single_process_container=True,
    )
    await add_worker(
        db_session,
        replacement_id,
        heartbeat_at=utc_now(),
        single_process_container=True,
    )
    driver = FakeDriver()
    driver.containers["worker-container"] = {
        "Id": "worker-container",
        "Config": {"Labels": {}},
        "State": {"Running": True, "StartedAt": HEARTBEAT_STARTED_AT},
    }

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.STOPPED
    assert decision.proof_source == "executor_replaced"


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["gone", "restarted"])
async def test_container_incarnation_change_is_stopped(db_session, test_user, scenario):
    executor_id = uuid.uuid4()
    stale = utc_now() - timedelta(seconds=60)
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
        heartbeat_at=stale,
    )
    driver = FakeDriver()
    if scenario == "restarted":
        driver.containers["worker-container"] = {
            "Id": "worker-container",
            "Config": {"Labels": {}},
            "State": {"Running": True, "StartedAt": OTHER_STARTED_AT},
        }

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.STOPPED
    assert decision.proof_source == "container_incarnation"


@pytest.mark.asyncio
async def test_container_identity_lookup_failure_is_ambiguous(db_session, test_user):
    executor_id = uuid.uuid4()
    stale = utc_now() - timedelta(seconds=60)
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
        heartbeat_at=stale,
    )
    driver = FakeDriver()
    driver.unavailable = True

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.AMBIGUOUS
    assert decision.proof_source == "runtime_inspection"


@pytest.mark.asyncio
async def test_launch_exactly_one_healthy_container_is_succeeded(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
    )
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=rows.server.id,
        launch_id=rows.operation.id,
    )

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.ALIVE
    assert decision.runtime_state is RuntimeState.PRESENT
    assert decision.terminal_state is TerminalState.SUCCEEDED
    assert decision.proof_source == "launch_runtime"
    assert decision.reason_code == "runtime_verified"


@pytest.mark.asyncio
async def test_registry_verified_launch_requires_exact_local_digest(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
        identity=verified_identity(),
    )
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = verified_identity()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=rows.server.id,
        launch_id=rows.operation.id,
    )

    verified = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)
    assert verified.terminal_state is TerminalState.SUCCEEDED

    driver.images[LOCAL_ID] = {**verified_identity(), "repository_digests": []}
    untrusted = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)
    assert untrusted.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert untrusted.reason_code == "runtime_image_unverified"


@pytest.mark.asyncio
async def test_zero_containers_uses_executor_evidence(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
        worker_state="stopped",
    )
    driver = FakeDriver()

    stopped = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)
    assert stopped.runtime_state is RuntimeState.ABSENT
    assert stopped.terminal_state is TerminalState.FAILED
    assert stopped.reason_code == "runtime_absent"

    legacy = await add_launch(db_session, test_user, executor_id=None)
    ambiguous = await ReconciliationService(db_session, driver).inspect(
        "launch", legacy.operation.id
    )
    assert ambiguous.terminal_state is TerminalState.RECOVERY_REQUIRED


@pytest.mark.asyncio
async def test_multiple_launch_containers_are_ambiguous(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_launch(db_session, test_user, executor_id=executor_id)
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    for _ in range(2):
        container_id = f"container-{uuid.uuid4().hex}"
        driver.containers[container_id] = container_info(
            container_id,
            server_id=rows.server.id,
            launch_id=rows.operation.id,
        )

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.runtime_state is RuntimeState.AMBIGUOUS
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "multiple_runtime_containers"


@pytest.mark.asyncio
async def test_running_predecessor_blocks_restart_finalization(db_session, test_user):
    executor_id = uuid.uuid4()
    predecessor_id = f"container-{uuid.uuid4().hex}"
    rows = await add_launch(
        db_session,
        test_user,
        action="restart",
        executor_id=executor_id,
        previous_container_id=predecessor_id,
    )
    driver = FakeDriver()
    driver.containers[predecessor_id] = container_info(
        predecessor_id,
        server_id=rows.server.id,
        launch_id=uuid.uuid4(),
        started_at=OTHER_STARTED_AT,
    )

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.runtime_state is RuntimeState.PRESENT
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "predecessor_running"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["server", "image", "platform", "generation", "health"])
async def test_incomplete_launch_proof_is_recovery_required(db_session, test_user, failure):
    executor_id = uuid.uuid4()
    rows = await add_launch(db_session, test_user, executor_id=executor_id)
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.images[LOCAL_ID] = local_identity()
    info = container_info(
        container_id,
        server_id=rows.server.id if failure != "server" else uuid.uuid4(),
        launch_id=rows.operation.id,
    )
    if failure == "image":
        info["Image"] = OTHER_ID
        driver.images[OTHER_ID] = local_identity(local_id=OTHER_ID)
    if failure == "platform":
        driver.images[LOCAL_ID] = local_identity(architecture="arm64")
    if failure == "health":
        info["State"]["Health"] = {"Status": "starting"}
    driver.containers[container_id] = info
    if failure == "generation":
        db_session.add(
            ServerLaunchRecord(
                server_id=rows.server.id,
                user_id=test_user.id,
                revision_id=rows.revision.id,
                generation=5,
                manifest={},
                actual_runtime_identity=rows.identity,
            )
        )
        await db_session.flush()

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.terminal_state is not TerminalState.SUCCEEDED
    assert (
        decision.reason_code
        == {
            "server": "runtime_server_mismatch",
            "image": "runtime_image_mismatch",
            "platform": "runtime_platform_mismatch",
            "generation": "generation_mismatch",
            "health": "runtime_unhealthy",
        }[failure]
    )


@pytest.mark.asyncio
async def test_stop_with_absent_runtime_and_stopped_executor_succeeds(db_session, test_user):
    executor_id = uuid.uuid4()
    predecessor_id = f"container-{uuid.uuid4().hex}"
    rows = await add_launch(
        db_session,
        test_user,
        action="stop",
        executor_id=executor_id,
        worker_state="stopped",
        previous_container_id=predecessor_id,
    )
    driver = FakeDriver()

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.runtime_state is RuntimeState.ABSENT
    assert decision.terminal_state is TerminalState.SUCCEEDED
    assert decision.reason_code == "runtime_absent"


@pytest.mark.asyncio
async def test_helper_running_defers_backup_and_restore(db_session, test_user):
    backup_executor = uuid.uuid4()
    backup_rows = await add_backup(db_session, test_user, executor_id=backup_executor)
    driver = FakeDriver()
    add_helper(
        driver,
        operation_id=backup_rows.backup.id,
        fencing_token=backup_rows.fencing_token,
        backup_id=backup_rows.backup.id,
        running=True,
    )

    backup = await ReconciliationService(db_session, driver).inspect(
        "backup", backup_rows.backup.id
    )
    assert backup.runtime_state is RuntimeState.PRESENT
    assert backup.terminal_state is None
    assert backup.reason_code == "helper_running"

    restore_executor = uuid.uuid4()
    restore, _ = await add_restore(
        db_session,
        test_user,
        backup_rows.backup,
        executor_id=restore_executor,
    )
    add_helper(
        driver,
        operation_id=restore.id,
        fencing_token=restore.fencing_token,
        backup_id=backup_rows.backup.id,
        running=True,
    )
    restored = await ReconciliationService(db_session, driver).inspect("restore", restore.id)
    assert restored.terminal_state is None
    assert restored.reason_code == "helper_running"


@pytest.mark.asyncio
async def test_absent_helper_and_stopped_executor_fails_backup(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_backup(
        db_session,
        test_user,
        executor_id=executor_id,
        worker_state="stopped",
    )
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=None)

    decision = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("backup", rows.backup.id)

    assert decision.runtime_state is RuntimeState.ABSENT
    assert decision.terminal_state is TerminalState.FAILED
    assert decision.reason_code == "helper_absent"


@pytest.mark.asyncio
async def test_absent_helper_and_ambiguous_executor_requires_recovery(db_session, test_user):
    rows = await add_backup(db_session, test_user, executor_id=None)
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=None)

    decision = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("backup", rows.backup.id)

    assert decision.liveness is Liveness.AMBIGUOUS
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED


@pytest.mark.asyncio
async def test_valid_backup_artifact_is_success_evidence(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_backup(db_session, test_user, executor_id=executor_id)
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=completion_metadata())

    decision = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("backup", rows.backup.id)

    assert decision.runtime_state is RuntimeState.PRESENT
    assert decision.terminal_state is TerminalState.SUCCEEDED
    assert decision.proof_source == "recovery_artifact"
    assert decision.reason_code == "artifact_verified"


@pytest.mark.asyncio
async def test_invalid_backup_artifact_is_not_success(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_backup(db_session, test_user, executor_id=executor_id)
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=completion_metadata(), archive_matches=False)

    decision = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("backup", rows.backup.id)

    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "artifact_invalid"


@pytest.mark.asyncio
async def test_restore_destination_state_gates_success(db_session, test_user):
    backup_executor = uuid.uuid4()
    restore_executor = uuid.uuid4()
    backup_rows = await add_backup(db_session, test_user, executor_id=backup_executor)
    restore, volume = await add_restore(
        db_session,
        test_user,
        backup_rows.backup,
        destination_status="restoring",
        executor_id=restore_executor,
    )
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=completion_metadata())

    restoring = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("restore", restore.id)

    # A helper can finish immediately before its executor dies. Verified
    # completion metadata lets the completion hook activate this destination.
    assert restoring.terminal_state is TerminalState.SUCCEEDED
    assert restoring.proof_source == PROOF_RECOVERY_ARTIFACT

    volume.status = "restore_failed"
    await db_session.flush()
    failed = await ReconciliationService(db_session, driver, artifact_inspector=artifacts).inspect(
        "restore", restore.id
    )

    assert failed.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert failed.reason_code == "destination_not_complete"

    volume.status = "active"
    volume.size_bytes = 4
    await db_session.flush()
    complete = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("restore", restore.id)

    assert complete.terminal_state is TerminalState.SUCCEEDED
    assert complete.runtime_state is RuntimeState.PRESENT


@pytest.mark.asyncio
async def test_inspector_does_not_mutate_rows_or_call_mutating_driver_methods(
    db_session, test_user
):
    executor_id = uuid.uuid4()
    stale = utc_now() - timedelta(seconds=60)
    rows = await add_launch(
        db_session,
        test_user,
        action="stop",
        executor_id=executor_id,
        heartbeat_at=stale,
        previous_container_id=f"container-{uuid.uuid4().hex}",
    )
    driver = FakeDriver()
    before_operation = {
        key: getattr(rows.operation, key)
        for key in ("state", "reason_code", "finished_at", "executor_id", "heartbeat_at")
    }
    before_server = {
        key: getattr(rows.server, key) for key in ("status", "container_id", "status_reason")
    }

    await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert driver.mutations == []
    assert not db_session.dirty
    assert not db_session.new
    assert not db_session.deleted
    assert before_operation == {
        key: getattr(rows.operation, key)
        for key in ("state", "reason_code", "finished_at", "executor_id", "heartbeat_at")
    }
    assert before_server == {
        key: getattr(rows.server, key) for key in ("status", "container_id", "status_reason")
    }


@pytest.mark.asyncio
async def test_missing_operation_is_bounded_and_ambiguous(db_session, test_user):
    driver = FakeDriver()

    decision = await ReconciliationService(db_session, driver).inspect("backup", uuid.uuid4())

    assert decision.kind is OperationKind.BACKUP
    assert decision.liveness is Liveness.AMBIGUOUS
    assert decision.runtime_state is RuntimeState.AMBIGUOUS
    assert decision.terminal_state is None
    assert decision.reason_code == "operation_not_found"


@pytest.mark.asyncio
async def test_terminal_operation_never_recommends_another_transition(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_launch(
        db_session,
        test_user,
        state="succeeded",
        executor_id=executor_id,
    )
    driver = FakeDriver()

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.terminal_state is None
    assert decision.reason_code == "operation_terminal"


@pytest.mark.asyncio
async def test_missing_worker_row_is_ambiguous(db_session, test_user):
    rows = await add_launch(db_session, test_user, executor_id=None)
    rows.operation.executor_id = uuid.uuid4()
    await db_session.flush()
    driver = FakeDriver()

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.AMBIGUOUS
    assert decision.proof_source == "worker_heartbeat_missing"


@pytest.mark.asyncio
async def test_missing_container_identity_on_worker_row_is_ambiguous(db_session, test_user):
    executor_id = uuid.uuid4()
    stale = utc_now() - timedelta(seconds=60)
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
        heartbeat_at=stale,
    )
    heartbeat = await db_session.get(WorkerHeartbeat, executor_id)
    heartbeat.container_id = None
    heartbeat.container_started_at = None
    await db_session.flush()
    driver = FakeDriver()

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.AMBIGUOUS
    assert decision.proof_source == "container_identity_missing"


@pytest.mark.asyncio
async def test_uninspectable_worker_container_state_is_ambiguous(db_session, test_user):
    executor_id = uuid.uuid4()
    stale = utc_now() - timedelta(seconds=60)
    rows = await add_launch(
        db_session,
        test_user,
        executor_id=executor_id,
        heartbeat_at=stale,
    )
    driver = FakeDriver()
    driver.containers["worker-container"] = {
        "Id": "worker-container",
        "Config": {"Labels": {}},
        "State": "unknown",
    }

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.liveness is Liveness.AMBIGUOUS
    assert decision.proof_source == "runtime_inspection"


@pytest.mark.asyncio
async def test_termination_with_unexpected_launch_container_requires_recovery(
    db_session, test_user
):
    executor_id = uuid.uuid4()
    rows = await add_launch(
        db_session,
        test_user,
        action="delete",
        executor_id=executor_id,
    )
    container_id = f"container-{uuid.uuid4().hex}"
    driver = FakeDriver()
    driver.containers[container_id] = container_info(
        container_id,
        server_id=rows.server.id,
        launch_id=rows.operation.id,
    )

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.runtime_state is RuntimeState.PRESENT
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "runtime_unexpected"


@pytest.mark.asyncio
async def test_termination_with_live_executor_and_absent_runtime_defers(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_launch(
        db_session,
        test_user,
        action="stop",
        executor_id=executor_id,
    )
    driver = FakeDriver()

    decision = await ReconciliationService(db_session, driver).inspect("launch", rows.operation.id)

    assert decision.runtime_state is RuntimeState.ABSENT
    assert decision.terminal_state is None
    assert decision.reason_code == "runtime_absent"


@pytest.mark.asyncio
async def test_helper_identity_mismatch_is_recovery_required(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_backup(db_session, test_user, executor_id=executor_id)
    driver = FakeDriver()
    helper_id = f"helper-{uuid.uuid4().hex}"
    driver.named[f"nukelab-recovery-{rows.backup.id}"] = helper_id
    driver.containers[helper_id] = {
        "Id": helper_id,
        "Config": {
            "Labels": {
                "nukelab.recovery.operation": str(rows.backup.id),
                "nukelab.recovery.fence": str(uuid.uuid4()),
                "nukelab.recovery.backup": str(rows.backup.id),
            }
        },
        "State": {"Running": True, "Status": "running", "ExitCode": 0},
    }

    decision = await ReconciliationService(db_session, driver).inspect("backup", rows.backup.id)

    assert decision.runtime_state is RuntimeState.AMBIGUOUS
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "helper_identity_mismatch"


@pytest.mark.asyncio
async def test_failed_helper_without_artifact_fails_only_when_executor_is_stopped(
    db_session, test_user
):
    executor_id = uuid.uuid4()
    rows = await add_backup(
        db_session,
        test_user,
        executor_id=executor_id,
        worker_state="stopped",
    )
    driver = FakeDriver()
    add_helper(
        driver,
        operation_id=rows.backup.id,
        fencing_token=rows.fencing_token,
        backup_id=rows.backup.id,
        running=False,
        exit_code=1,
    )
    artifacts = FakeArtifactInspector(metadata=None)

    decision = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("backup", rows.backup.id)

    assert decision.terminal_state is TerminalState.FAILED
    assert decision.reason_code == "helper_failed"


@pytest.mark.asyncio
async def test_failed_helper_with_artifact_requires_recovery(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_backup(db_session, test_user, executor_id=executor_id)
    driver = FakeDriver()
    add_helper(
        driver,
        operation_id=rows.backup.id,
        fencing_token=rows.fencing_token,
        backup_id=rows.backup.id,
        running=False,
        exit_code=1,
    )
    artifacts = FakeArtifactInspector(metadata=completion_metadata())

    decision = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("backup", rows.backup.id)

    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "helper_failed"


@pytest.mark.asyncio
async def test_live_executor_with_missing_helper_defers(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_backup(db_session, test_user, executor_id=executor_id)
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=None)

    decision = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("backup", rows.backup.id)

    assert decision.runtime_state is RuntimeState.ABSENT
    assert decision.terminal_state is None
    assert decision.reason_code == "helper_absent"


@pytest.mark.asyncio
async def test_restore_checksum_mismatch_and_missing_destination_require_recovery(
    db_session, test_user
):
    backup_executor = uuid.uuid4()
    backup_rows = await add_backup(db_session, test_user, executor_id=backup_executor)
    restore_executor = uuid.uuid4()
    restore, volume = await add_restore(
        db_session,
        test_user,
        backup_rows.backup,
        destination_status="active",
        executor_id=restore_executor,
    )
    driver = FakeDriver()
    mismatched = FakeArtifactInspector(metadata=completion_metadata(sha256="e" * 64))

    checksum = await ReconciliationService(
        db_session, driver, artifact_inspector=mismatched
    ).inspect("restore", restore.id)
    assert checksum.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert checksum.reason_code == "artifact_invalid"

    restore.destination_volume_id = None
    await db_session.flush()
    matching = FakeArtifactInspector(metadata=completion_metadata())
    destination = await ReconciliationService(
        db_session, driver, artifact_inspector=matching
    ).inspect("restore", restore.id)
    assert destination.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert destination.reason_code == "destination_missing"
    assert volume.status == "active"


@pytest.mark.asyncio
async def test_restore_destination_size_mismatch_requires_recovery(db_session, test_user):
    backup_executor = uuid.uuid4()
    backup_rows = await add_backup(db_session, test_user, executor_id=backup_executor)
    restore_executor = uuid.uuid4()
    restore, volume = await add_restore(
        db_session,
        test_user,
        backup_rows.backup,
        destination_status="active",
        executor_id=restore_executor,
    )
    volume.size_bytes = 999
    await db_session.flush()
    driver = FakeDriver()
    artifacts = FakeArtifactInspector(metadata=completion_metadata())

    decision = await ReconciliationService(
        db_session, driver, artifact_inspector=artifacts
    ).inspect("restore", restore.id)

    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "destination_size_mismatch"


@pytest.mark.asyncio
async def test_unknown_kind_and_invalid_operation_id_are_rejected(db_session):
    driver = FakeDriver()
    service = ReconciliationService(db_session, driver)
    with pytest.raises(ValueError, match="Unsupported operation kind"):
        await service.inspect("checkpoint", uuid.uuid4())
    with pytest.raises(ValueError, match="Invalid operation id"):
        await service.inspect("launch", "not-a-uuid")


@pytest.mark.asyncio
async def test_volume_operation_without_fence_requires_recovery(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_backup(db_session, test_user, executor_id=executor_id)
    rows.backup.fencing_token = None
    await db_session.flush()
    driver = FakeDriver()

    decision = await ReconciliationService(db_session, driver).inspect("backup", rows.backup.id)

    assert decision.runtime_state is RuntimeState.AMBIGUOUS
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "operation_identity_missing"


@pytest.mark.asyncio
async def test_unreadable_artifact_with_stopped_executor_requires_recovery(db_session, test_user):
    from app.services.operation_reconciliation import ArtifactInspectionUnavailable

    executor_id = uuid.uuid4()
    rows = await add_backup(
        db_session,
        test_user,
        executor_id=executor_id,
        worker_state="stopped",
    )
    driver = FakeDriver()

    class UnreadableArtifacts:
        def read_completion(self, **kwargs):
            raise ArtifactInspectionUnavailable("storage unavailable")

        def backup_archive_matches(self, *, backup_id, metadata):
            raise ArtifactInspectionUnavailable("storage unavailable")

    decision = await ReconciliationService(
        db_session, driver, artifact_inspector=UnreadableArtifacts()
    ).inspect("backup", rows.backup.id)

    assert decision.runtime_state is RuntimeState.AMBIGUOUS
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "artifact_inspection_unavailable"


@pytest.mark.asyncio
async def test_uninspectable_helper_with_stopped_executor_requires_recovery(db_session, test_user):
    executor_id = uuid.uuid4()
    rows = await add_backup(
        db_session,
        test_user,
        executor_id=executor_id,
        worker_state="stopped",
    )
    driver = FakeDriver()
    driver.unavailable = True

    decision = await ReconciliationService(db_session, driver).inspect("backup", rows.backup.id)

    assert decision.runtime_state is RuntimeState.AMBIGUOUS
    assert decision.terminal_state is TerminalState.RECOVERY_REQUIRED
    assert decision.reason_code == "runtime_inspection_unavailable"


@pytest.mark.asyncio
async def test_inspector_does_not_mutate_volume_rows(db_session, test_user):
    backup_executor = uuid.uuid4()
    backup_rows = await add_backup(db_session, test_user, executor_id=backup_executor)
    restore_executor = uuid.uuid4()
    restore, volume = await add_restore(
        db_session,
        test_user,
        backup_rows.backup,
        destination_status="restoring",
        executor_id=restore_executor,
    )
    driver = FakeDriver()
    add_helper(
        driver,
        operation_id=backup_rows.backup.id,
        fencing_token=backup_rows.fencing_token,
        backup_id=backup_rows.backup.id,
        running=True,
    )
    add_helper(
        driver,
        operation_id=restore.id,
        fencing_token=restore.fencing_token,
        backup_id=backup_rows.backup.id,
        running=True,
    )
    before_backup = {
        key: getattr(backup_rows.backup, key)
        for key in (
            "status",
            "sha256",
            "reserved_bytes",
            "helper_identity",
            "reason_code",
            "executor_id",
            "heartbeat_at",
            "completed_at",
        )
    }
    before_restore = {
        key: getattr(restore, key)
        for key in (
            "status",
            "reserved_bytes",
            "helper_identity",
            "reason_code",
            "executor_id",
            "heartbeat_at",
            "completed_at",
            "destination_volume_id",
        )
    }
    before_volume = {"status": volume.status, "size_bytes": volume.size_bytes}
    service = ReconciliationService(db_session, driver)

    await service.inspect("backup", backup_rows.backup.id)
    await service.inspect("restore", restore.id)

    assert driver.mutations == []
    assert not db_session.dirty
    assert before_backup == {key: getattr(backup_rows.backup, key) for key in before_backup}
    assert before_restore == {key: getattr(restore, key) for key in before_restore}
    assert before_volume == {"status": volume.status, "size_bytes": volume.size_bytes}


def test_runtime_artifact_inspector_requires_storage(monkeypatch):
    from app.services import operation_reconciliation as module

    monkeypatch.setattr(settings, "volume_backup_storage_path", None)
    inspector = module._RuntimeArtifactInspector(FakeDriver())
    with pytest.raises(module.ArtifactInspectionUnavailable):
        inspector.read_completion(
            kind=OperationKind.BACKUP,
            operation_id=uuid.uuid4(),
            backup_id=uuid.uuid4(),
            fencing_token=uuid.uuid4(),
            maximum=1024,
        )
    with pytest.raises(module.ArtifactInspectionUnavailable):
        inspector.backup_archive_matches(backup_id=uuid.uuid4(), metadata=completion_metadata())


def test_runtime_artifact_inspector_delegates_completion_reads(monkeypatch, tmp_path):
    from app.services import operation_reconciliation as module

    operation_id, backup_id, fencing_token = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(settings, "volume_backup_storage_path", str(tmp_path))

    def limits(maximum):
        return maximum

    captured = {}

    def metadata(work, operation, fence, backup, action, limits):
        captured.update(
            {
                "work": work,
                "operation": operation,
                "fence": fence,
                "backup": backup,
                "action": action,
                "limits": limits,
            }
        )
        return completion_metadata()

    monkeypatch.setattr(module.VolumeRecoveryRuntime, "_limits", lambda self, value: limits(value))
    monkeypatch.setattr(
        module.VolumeRecoveryRuntime, "_metadata", lambda self, *args: metadata(*args)
    )
    monkeypatch.setattr(module.VolumeRecoveryRuntime, "_storage", lambda self: tmp_path)

    inspector = module._RuntimeArtifactInspector(FakeDriver())
    result = inspector.read_completion(
        kind=OperationKind.RESTORE,
        operation_id=operation_id,
        backup_id=backup_id,
        fencing_token=fencing_token,
        maximum=2048,
    )

    assert result == completion_metadata()
    assert captured == {
        "work": tmp_path / "backups" / str(backup_id) / "operations" / str(operation_id),
        "operation": str(operation_id),
        "fence": str(fencing_token),
        "backup": str(backup_id),
        "action": "restore",
        "limits": 2048,
    }


def test_runtime_artifact_inspector_verifies_archive_checksum(monkeypatch, tmp_path):
    import hashlib
    import os

    from app.services import operation_reconciliation as module

    backup_id = uuid.uuid4()
    archive_directory = tmp_path / "backups" / str(backup_id)
    archive_directory.mkdir(parents=True)
    payload = b"compressed-artifact"
    archive = archive_directory / "archive.tar.gz"
    archive.write_bytes(payload)
    monkeypatch.setattr(settings, "volume_backup_storage_path", str(tmp_path))
    monkeypatch.setattr(module, "_TRUSTED_ARTIFACT_UID", os.getuid())
    monkeypatch.setattr(module.VolumeRecoveryRuntime, "_storage", lambda self: tmp_path)
    inspector = module._RuntimeArtifactInspector(FakeDriver())

    metadata = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "compressed_bytes": len(payload),
    }
    assert inspector.backup_archive_matches(backup_id=backup_id, metadata=metadata) is True
    assert (
        inspector.backup_archive_matches(
            backup_id=backup_id, metadata={**metadata, "sha256": "0" * 64}
        )
        is False
    )
    archive.unlink()
    assert inspector.backup_archive_matches(backup_id=backup_id, metadata=metadata) is False
