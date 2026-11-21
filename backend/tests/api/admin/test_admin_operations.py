# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Sanitized admin operation listing, detail, and proof-only reconciliation."""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select

from app.api import admin_operations
from app.core.time_utils import utc_now
from app.models.activity_log import ActivityLog
from app.models.gpu_allocation import GpuAllocation
from app.models.notification import Notification
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_queue import ServerQueue
from app.models.volume_operation import VolumeOperation
from app.models.worker_heartbeat import WorkerHeartbeat
from app.services.operation_reconciliation import ReconciliationService
from tests.services.test_operation_finalizer import (
    LOCAL_ID,
    FakeArtifactInspector,
    FakeDriver,
    add_launch,
    container_info,
    local_identity,
)
from tests.services.test_operation_reconciler import add_backup_row, add_minimal_launch

pytestmark = pytest.mark.asyncio


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def fake_runtime(monkeypatch):
    driver = FakeDriver()

    async def _get_driver():
        return driver

    monkeypatch.setattr(admin_operations, "get_driver", _get_driver)
    return driver


async def _minimal_launch(db, user, *, state="executing", created_at=None, action="create"):
    fixture = await add_minimal_launch(
        db,
        user,
        state=state,
        action=action,
        created_at=created_at,
    )
    await db.commit()
    return fixture


async def _backup(db, user, *, status="in_progress", created_at=None):
    row = await add_backup_row(db, user, status=status, created_at=created_at)
    await db.commit()
    return row


async def _activity(db, operation_id):
    return (
        await db.scalars(
            select(ActivityLog)
            .where(ActivityLog.target_id == operation_id)
            .order_by(ActivityLog.created_at, ActivityLog.id)
        )
    ).all()


async def _notifications(db, user_id=None):
    statement = select(Notification).order_by(Notification.created_at, Notification.id)
    if user_id is not None:
        statement = statement.where(Notification.user_id == user_id)
    return list((await db.scalars(statement)).all())


async def test_list_filters_pagination_and_sanitization(client, admin_token, db_session, test_user):
    fixture = await add_launch(db_session, test_user)
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    mount = operation.mounts[0]
    recent_id = fixture.operation_id
    old = await _minimal_launch(
        db_session,
        test_user,
        state="uncertain",
        action="start",
        created_at=utc_now() - timedelta(days=5),
    )
    backup = await _backup(
        db_session,
        test_user,
        status="recovery_required",
        created_at=utc_now() - timedelta(days=3),
    )
    headers = auth(admin_token)

    listed = await client.get("/api/admin/operations", headers=headers)
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["pagination"] == {
        "limit": 50,
        "offset": 0,
        "total": 3,
        "has_more": False,
    }
    assert {item["kind"] for item in payload["items"]} == {"launch", "backup"}
    assert {str(item["id"]) for item in payload["items"]} == {
        str(recent_id),
        str(old.operation.id),
        str(backup.id),
    }
    recent = next(item for item in payload["items"] if item["id"] == str(recent_id))
    assert recent["state"] == "executing"
    assert recent["action"] == "create"
    assert recent["owner_id"] == str(test_user.id)
    assert recent["recovery_required"] is False
    assert recent["heartbeat_age_seconds"] is not None
    assert recent["liveness"] is None

    text = json.dumps(payload)
    for forbidden in (
        "request_payload",
        "mounts",
        "resources",
        "fencing_token",
        "executor_id",
        "container_id",
        "environment_slug",
        "volume_name",
        "backup_path",
        "source_metadata",
        "source_display_name",
        mount["volume_name"],
        mount["mount_path"],
        str(fixture.volume_id),
        operation.username,
        test_user.username,
    ):
        assert forbidden not in text

    by_kind = await client.get("/api/admin/operations?kind=launch", headers=headers)
    assert by_kind.json()["pagination"]["total"] == 2
    assert {item["kind"] for item in by_kind.json()["items"]} == {"launch"}

    by_state = await client.get("/api/admin/operations?state=uncertain", headers=headers)
    assert [item["id"] for item in by_state.json()["items"]] == [str(old.operation.id)]

    by_owner = await client.get(f"/api/admin/operations?owner_id={test_user.id}", headers=headers)
    assert by_owner.json()["pagination"]["total"] == 3
    foreign_owner = await client.get(
        f"/api/admin/operations?owner_id={uuid.uuid4()}", headers=headers
    )
    assert foreign_owner.json()["pagination"]["total"] == 0

    aged = await client.get("/api/admin/operations?age_days=2", headers=headers)
    assert {str(item["id"]) for item in aged.json()["items"]} == {
        str(old.operation.id),
        str(backup.id),
    }
    older = await client.get(
        "/api/admin/operations",
        params={"older_than": (utc_now() - timedelta(days=4)).isoformat()},
        headers=headers,
    )
    assert [item["id"] for item in older.json()["items"]] == [str(old.operation.id)]

    recovery = await client.get("/api/admin/operations?recovery_required=true", headers=headers)
    assert {str(item["id"]) for item in recovery.json()["items"]} == {
        str(old.operation.id),
        str(backup.id),
    }
    healthy = await client.get("/api/admin/operations?recovery_required=false", headers=headers)
    assert [item["id"] for item in healthy.json()["items"]] == [str(recent_id)]

    first_page = await client.get("/api/admin/operations?limit=2&offset=0", headers=headers)
    second_page = await client.get("/api/admin/operations?limit=2&offset=2", headers=headers)
    repeat_page = await client.get("/api/admin/operations?limit=2&offset=0", headers=headers)
    assert [item["id"] for item in first_page.json()["items"]] == [
        item["id"] for item in repeat_page.json()["items"]
    ]
    assert first_page.json()["pagination"]["has_more"] is True
    assert len(second_page.json()["items"]) == 1
    assert second_page.json()["pagination"]["has_more"] is False

    assert (await client.get("/api/admin/operations?limit=0", headers=headers)).status_code == 422
    assert (await client.get("/api/admin/operations?limit=101", headers=headers)).status_code == 422
    assert (
        await client.get("/api/admin/operations?offset=1001", headers=headers)
    ).status_code == 422
    assert (await client.get("/api/admin/operations?state=Bad", headers=headers)).status_code == 422


async def test_detail_inspects_active_rows_without_leaking_payloads(
    client, admin_token, db_session, test_user
):
    fixture = await add_launch(db_session, test_user)
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    mount = operation.mounts[0]

    response = await client.get(
        f"/api/admin/operations/launch/{fixture.operation_id}",
        headers=auth(admin_token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "launch"
    assert data["id"] == str(fixture.operation_id)
    assert data["state"] == "executing"
    assert data["action"] == "create"
    assert data["owner_id"] == str(test_user.id)
    assert data["recovery_required"] is False
    assert data["liveness"] == "alive"
    assert data["proof_source"] == "worker_heartbeat"
    assert data["runtime_state"] == "absent"
    assert data["evidence_reason_code"] == "runtime_absent"
    assert data["heartbeat_age_seconds"] is not None
    assert data["counters"] == {}

    text = response.text
    for forbidden in (
        "request_payload",
        "mounts",
        "fencing_token",
        "executor_id",
        "container_id",
        "environment_slug",
        "volume_name",
        mount["volume_name"],
        mount["mount_path"],
        str(fixture.volume_id),
        operation.username,
        test_user.username,
    ):
        assert forbidden not in text


async def test_detail_terminal_foreign_and_missing_rows(client, admin_token, db_session, test_user):
    terminal = await _minimal_launch(db_session, test_user, state="succeeded")
    headers = auth(admin_token)

    detail = await client.get(
        f"/api/admin/operations/launch/{terminal.operation.id}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["state"] == "succeeded"
    assert detail.json()["liveness"] is None
    assert detail.json()["proof_source"] is None

    foreign = await client.get(
        f"/api/admin/operations/backup/{terminal.operation.id}", headers=headers
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == {"code": "operation_not_found"}

    missing = await client.get(f"/api/admin/operations/restore/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404

    invalid = await client.get(f"/api/admin/operations/unknown/{uuid.uuid4()}", headers=headers)
    assert invalid.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"reason": ""},
        {"reason": "   "},
        {"reason": "\n"},
        {"reason": "x" * 256},
        {"reason": "valid reason", "force": True},
        {"reason": "valid reason", "unknown": "field"},
    ],
)
async def test_reconcile_rejects_invalid_bodies(client, admin_token, test_user, body):
    response = await client.post(
        f"/api/admin/operations/launch/{uuid.uuid4()}/reconcile",
        headers=auth(admin_token),
        json=body,
    )
    assert response.status_code == 422


async def test_ambiguous_proof_returns_conflict_without_mutation_or_release(
    client, admin_token, admin_user, db_session, test_user
):
    fixture = await add_launch(db_session, test_user)
    actor_id = admin_user.id
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    await db_session.execute(
        delete(WorkerHeartbeat).where(WorkerHeartbeat.executor_id == operation.executor_id)
    )
    await db_session.commit()

    response = await client.post(
        f"/api/admin/operations/launch/{fixture.operation_id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "operator observed an absent runtime"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "recovery_required"
    assert detail["recovery_required"] is True
    assert detail["applied"] is False
    assert detail["state"] == "executing"
    assert detail["reason_code"] == "runtime_absent"
    assert "container_id" not in json.dumps(detail)

    await db_session.refresh(operation)
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    queue = await db_session.get(ServerQueue, fixture.queue_id, populate_existing=True)
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == fixture.operation_id)
    )
    assert operation.state == "executing"
    assert server.status == "starting"
    assert queue.status == "starting"
    assert guard.state == "reserved"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == fixture.server_id)
        )
        == 1
    )

    logs = await _activity(db_session, fixture.operation_id)
    assert len(logs) == 1
    assert logs[0].action == "operations.reconcile"
    assert logs[0].actor_id == actor_id
    assert logs[0].details["reason"] == "operator observed an absent runtime"
    assert logs[0].details["outcome"] == "recovery_required"
    assert logs[0].details["liveness"] == "ambiguous"
    assert logs[0].details["proof_source"] == "worker_heartbeat_missing"
    assert logs[0].details["runtime_state"] == "absent"


async def test_proof_backed_failure_applies_once_and_repeat_is_noop(
    client, admin_token, admin_user, db_session, test_user
):
    fixture = await add_launch(db_session, test_user, executor_state="stopped")
    actor_id = admin_user.id

    response = await client.post(
        f"/api/admin/operations/launch/{fixture.operation_id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "executor recorded a graceful shutdown"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["applied"] is True
    assert data["previous_state"] == "executing"
    assert data["state"] == "failed"
    assert data["terminal_state"] == "failed"
    assert data["liveness"] == "stopped"
    assert data["proof_source"] == "graceful_marker"
    assert data["runtime_state"] == "absent"
    assert data["evidence_reason_code"] == "runtime_absent"

    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    queue = await db_session.get(ServerQueue, fixture.queue_id, populate_existing=True)
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == fixture.operation_id)
    )
    assert operation.state == "failed"
    assert operation.reason_code == "runtime_absent"
    assert server.status == "error"
    assert queue.status == "failed"
    assert guard.state == "succeeded"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(GpuAllocation)
            .where(GpuAllocation.server_id == fixture.server_id)
        )
        == 0
    )
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 0

    logs = await _activity(db_session, fixture.operation_id)
    transition_logs = [log for log in logs if log.action == "operations.reconcile_applied"]
    assert len(transition_logs) == 1
    details = transition_logs[0].details
    assert transition_logs[0].actor_id == actor_id
    assert details["reason"] == "executor recorded a graceful shutdown"
    assert details["previous_state"] == "executing"
    assert details["new_state"] == "failed"
    assert details["terminal_state"] == "failed"
    assert details["proof_source"] == "graceful_marker"
    assert details["liveness"] == "stopped"
    assert details["runtime_state"] == "absent"

    repeated = await client.post(
        f"/api/admin/operations/launch/{fixture.operation_id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "confirm the terminal row stays closed"},
    )
    assert repeated.status_code == 200
    repeated_data = repeated.json()
    assert repeated_data["applied"] is False
    assert repeated_data["state"] == "failed"
    assert repeated_data["previous_state"] == "failed"
    assert repeated_data["terminal_state"] is None

    await db_session.refresh(operation)
    assert operation.state == "failed"
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 0
    logs = await _activity(db_session, fixture.operation_id)
    assert len([log for log in logs if log.action == "operations.reconcile_applied"]) == 1
    assert len([log for log in logs if log.action == "operations.reconcile"]) == 1


async def test_proof_backed_volume_failure_releases_once(
    client, admin_token, db_session, test_user, monkeypatch
):
    executor_id = uuid.uuid4()
    backup = await add_backup_row(
        db_session,
        test_user,
        status="in_progress",
        executor_id=executor_id,
        reserved_bytes=4096,
        volume_guard=True,
    )
    db_session.add(
        WorkerHeartbeat(
            executor_id=executor_id,
            hostname="worker-host",
            container_id="worker-container",
            container_started_at="2026-11-21T09:00:00.000000000Z",
            pid=1234,
            process_start_time="100",
            single_process_container=True,
            schema_version="nukelab-journal/v1",
            state="stopped",
            heartbeat_at=utc_now(),
        )
    )
    await db_session.commit()
    monkeypatch.setattr(
        admin_operations,
        "_reconciliation_service",
        lambda db, driver: ReconciliationService(
            db, driver, artifact_inspector=FakeArtifactInspector(metadata=None)
        ),
    )

    response = await client.post(
        f"/api/admin/operations/backup/{backup.id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "executor stopped without a completion artifact"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["applied"] is True
    assert data["previous_state"] == "in_progress"
    assert data["state"] == "failed"
    assert data["terminal_state"] == "failed"
    assert data["liveness"] == "stopped"
    assert data["proof_source"] == "runtime_inspection"
    assert data["runtime_state"] == "absent"
    assert data["evidence_reason_code"] == "helper_absent"

    await db_session.refresh(backup)
    guard = await db_session.scalar(
        select(VolumeOperation).where(VolumeOperation.operation_id == backup.id)
    )
    assert backup.status == "failed"
    assert backup.reason_code == "helper_absent"
    assert backup.reserved_bytes == 0
    assert guard.state == "failed"

    repeated = await client.post(
        f"/api/admin/operations/backup/{backup.id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "confirm the volume failure is not replayed"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["applied"] is False
    assert repeated.json()["state"] == "failed"
    logs = await _activity(db_session, backup.id)
    assert len([log for log in logs if log.action == "operations.reconcile_applied"]) == 1


async def test_proof_backed_success_applies_once(
    client, admin_token, db_session, test_user, fake_runtime
):
    fixture = await add_launch(db_session, test_user)
    container_id = f"container-{uuid.uuid4().hex}"
    fake_runtime.images[LOCAL_ID] = local_identity()
    fake_runtime.containers[container_id] = container_info(
        container_id,
        server_id=fixture.server_id,
        launch_id=fixture.operation_id,
    )

    response = await client.post(
        f"/api/admin/operations/launch/{fixture.operation_id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "verified labels, image, readiness, and health"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["applied"] is True
    assert data["previous_state"] == "executing"
    assert data["state"] == "succeeded"
    assert data["terminal_state"] == "succeeded"
    assert data["liveness"] == "alive"
    assert data["proof_source"] == "launch_runtime"
    assert data["runtime_state"] == "present"
    assert data["diagnostics"].get("action") == "create"

    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    server = await db_session.get(Server, fixture.server_id, populate_existing=True)
    queue = await db_session.get(ServerQueue, fixture.queue_id, populate_existing=True)
    assert operation.state == "succeeded"
    assert server.status == "running"
    assert server.container_id == container_id
    assert queue.status == "started"
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 1
    assert fake_runtime.mutations == []

    repeated = await client.post(
        f"/api/admin/operations/launch/{fixture.operation_id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "confirm repeated reconciliation is a no-op"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["applied"] is False
    assert repeated.json()["state"] == "succeeded"
    assert await db_session.scalar(select(func.count()).select_from(ServerLaunchRecord)) == 1

    logs = await _activity(db_session, fixture.operation_id)
    assert len([log for log in logs if log.action == "operations.reconcile_applied"]) == 1


async def test_terminal_volume_rows_are_not_reopened(
    client, admin_token, db_session, test_user, monkeypatch
):
    backup = await _backup(db_session, test_user, status="failed")
    monkeypatch.setattr(
        admin_operations,
        "_reconciliation_service",
        lambda db, driver: ReconciliationService(
            db, driver, artifact_inspector=FakeArtifactInspector(metadata=None)
        ),
    )
    response = await client.post(
        f"/api/admin/operations/backup/{backup.id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "attempt to reopen a terminal backup"},
    )
    assert response.status_code == 200
    assert response.json()["applied"] is False
    assert response.json()["state"] == "failed"
    await db_session.refresh(backup)
    assert backup.status == "failed"
    logs = await _activity(db_session, backup.id)
    assert len(logs) == 1
    assert logs[0].action == "operations.reconcile"


async def test_applied_reconciliation_notifies_the_owner_once(
    client, admin_token, admin_user, db_session, test_user
):
    fixture = await add_launch(db_session, test_user, executor_state="stopped")
    admin_id = admin_user.id

    response = await client.post(
        f"/api/admin/operations/launch/{fixture.operation_id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "executor recorded a graceful shutdown"},
    )

    assert response.status_code == 200
    assert response.json()["applied"] is True
    notifications = await _notifications(db_session)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.user_id == test_user.id
    assert notification.user_id != admin_id
    assert notification.type == "server"
    assert notification.extra_data["operation_kind"] == "launch"
    assert notification.extra_data["operation_id"] == str(fixture.operation_id)
    assert notification.extra_data["terminal_state"] == "failed"
    assert notification.extra_data["server_id"] == str(fixture.server_id)

    repeated = await client.post(
        f"/api/admin/operations/launch/{fixture.operation_id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "confirm the terminal row stays closed"},
    )

    assert repeated.status_code == 200
    assert repeated.json()["applied"] is False
    assert len(await _notifications(db_session)) == 1


async def test_notification_failure_does_not_fail_applied_reconciliation(
    client, admin_token, db_session, test_user, monkeypatch
):
    fixture = await add_launch(db_session, test_user, executor_state="stopped")

    class BrokenNotifier:
        def __init__(self, db):
            self.db = db

        async def notify_applied(self, decision, *, applied_state=None):
            raise RuntimeError("notification channel unavailable")

    monkeypatch.setattr(admin_operations, "RecoveryNotifier", BrokenNotifier)

    response = await client.post(
        f"/api/admin/operations/launch/{fixture.operation_id}/reconcile",
        headers=auth(admin_token),
        json={"reason": "executor recorded a graceful shutdown"},
    )

    assert response.status_code == 200
    assert response.json()["applied"] is True
    assert response.json()["state"] == "failed"
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    assert operation.state == "failed"
    assert await _notifications(db_session) == []
