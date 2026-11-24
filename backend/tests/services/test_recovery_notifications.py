# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Owner notifications for applied recovery transitions stay bounded and safe."""

import json
import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select, update

from app.models.notification import Notification
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.volume_backup import VolumeBackup
from app.services import recovery_notifications
from app.services.operation_reconciler import OperationReconciler
from app.services.operation_reconciliation import (
    Liveness,
    OperationKind,
    ReconcileDecision,
    RuntimeState,
    TerminalState,
)
from app.services.recovery_notifications import RecoveryNotifier
from tests.services.test_operation_finalizer import (
    FakeArtifactInspector,
    FakeDriver,
    add_launch,
    add_worker,
)
from tests.services.test_operation_reconciler import (
    add_backup_row,
    add_minimal_launch,
    session_factory,
)


async def _notifications(db) -> list[Notification]:
    return list(
        (
            await db.scalars(
                select(Notification).order_by(Notification.created_at, Notification.id)
            )
        ).all()
    )


def decision(
    kind: OperationKind,
    operation_id: uuid.UUID,
    terminal: TerminalState,
    *,
    reason: str = "runtime_absent",
) -> ReconcileDecision:
    return ReconcileDecision(
        kind=kind,
        operation_id=operation_id,
        liveness=Liveness.STOPPED,
        proof_source="graceful_marker",
        runtime_state=RuntimeState.ABSENT,
        terminal_state=terminal,
        reason_code=reason,
    )


@pytest.mark.asyncio
async def test_applied_launch_failure_notifies_the_owner_once(db_session, test_user):
    fixture = await add_launch(db_session, test_user, executor_state="stopped")

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.finalized == 1
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    assert operation.state == "failed"
    notifications = await _notifications(db_session)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.user_id == test_user.id
    assert notification.type == "server"
    assert "failed" in notification.title.lower()
    assert notification.extra_data["recovery_event"] == "attention"
    assert notification.extra_data["operation_kind"] == "launch"
    assert notification.extra_data["operation_id"] == str(fixture.operation_id)
    assert notification.extra_data["terminal_state"] == "failed"
    assert notification.extra_data["server_id"] == str(fixture.server_id)
    assert notification.extra_data["reason_code"] == "runtime_absent"

    repeated = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert repeated.scanned == 0
    assert len(await _notifications(db_session)) == 1


@pytest.mark.asyncio
async def test_applied_launch_recovery_required_notifies_once(db_session, test_user):
    fixture = await add_minimal_launch(db_session, test_user, state="executing")

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.recovery_required == 1
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation.id, populate_existing=True
    )
    assert operation.state == "uncertain"
    notifications = await _notifications(db_session)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.extra_data["terminal_state"] == "uncertain"
    assert notification.extra_data["server_id"] == str(fixture.server.id)
    assert "attention" in notification.title.lower()

    repeated = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert repeated.scanned == 1
    assert len(await _notifications(db_session)) == 1


@pytest.mark.asyncio
async def test_applied_volume_failure_notifies_the_owner(db_session, test_user):
    executor_id = uuid.uuid4()
    backup = await add_backup_row(
        db_session,
        test_user,
        status="in_progress",
        executor_id=executor_id,
        volume_guard=True,
    )
    await add_worker(db_session, executor_id, state="stopped")

    report = await OperationReconciler(
        session_factory(db_session),
        FakeDriver(),
        artifact_inspector=FakeArtifactInspector(metadata=None),
    ).scan()

    assert report.finalized == 1
    await db_session.refresh(backup)
    assert backup.status == "failed"
    notifications = await _notifications(db_session)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.user_id == test_user.id
    assert notification.type == "volume"
    assert notification.action_url == "/volumes"
    assert notification.extra_data["operation_kind"] == "backup"
    assert notification.extra_data["operation_id"] == str(backup.id)
    assert notification.extra_data["backup_id"] == str(backup.id)
    assert notification.extra_data["terminal_state"] == "failed"


@pytest.mark.asyncio
async def test_volume_recovery_then_completion_sends_one_distinct_notification_each(
    db_session, test_user
):
    backup = await add_backup_row(db_session, test_user, status="recovery_required")
    backup.reason_code = "helper_absent"
    await db_session.commit()
    notifier = RecoveryNotifier(db_session)

    recovery = decision(
        OperationKind.BACKUP,
        backup.id,
        TerminalState.RECOVERY_REQUIRED,
        reason="helper_absent",
    )
    assert await notifier.notify_applied(recovery, applied_state="recovery_required") is True
    assert await notifier.notify_applied(recovery, applied_state="recovery_required") is False

    backup.status = "completed"
    await db_session.commit()
    completed = decision(OperationKind.BACKUP, backup.id, TerminalState.SUCCEEDED)
    assert await notifier.notify_applied(completed, applied_state="completed") is True
    assert await notifier.notify_applied(completed, applied_state="completed") is False

    notifications = await _notifications(db_session)
    assert len(notifications) == 2
    assert [item.extra_data["recovery_event"] for item in notifications] == [
        "attention",
        "completed",
    ]
    assert notifications[0].extra_data["event_key"] == "volume_recovery_failed"
    assert notifications[0].extra_data["reason_code"] == "helper_absent"
    assert notifications[1].extra_data["event_key"] == "volume_recovery_completed"
    assert "reason_code" not in notifications[1].extra_data
    assert "helper_absent" not in notifications[1].message
    assert notifications[1].severity == "success"


@pytest.mark.asyncio
async def test_applied_notification_uses_the_committed_row_state(db_session, test_user):
    backup = await add_backup_row(db_session, test_user, status="recovery_required")
    notifier = RecoveryNotifier(db_session)

    # A failure decision can be degraded to recovery_required under the lock.
    stale_decision = decision(OperationKind.BACKUP, backup.id, TerminalState.FAILED)
    assert await notifier.notify_applied(stale_decision, applied_state="failed") is True

    notification = (await _notifications(db_session))[0]
    assert notification.extra_data["terminal_state"] == "recovery_required"
    assert "attention" in notification.title.lower()


@pytest.mark.asyncio
async def test_notifier_ignores_invalid_inputs_and_disabled_in_app(db_session, test_user):
    notifier = RecoveryNotifier(db_session)
    assert await notifier.notify_applied(object()) is False
    assert await notifier.notify_reminder("launch", uuid.uuid4()) is False

    fixture = await add_minimal_launch(db_session, test_user, state="failed")
    fixture.operation.reason_code = "Bad Reason!"
    test_user.preferences = {
        "notifications": {
            "events": [
                {
                    "event": "server_failed",
                    "channels": {
                        "in_app": False,
                        "email": False,
                        "webhook": False,
                        "push": False,
                    },
                }
            ]
        }
    }
    await db_session.commit()

    failed = decision(OperationKind.LAUNCH, fixture.operation.id, TerminalState.FAILED)
    assert await notifier.notify_applied(failed, applied_state="failed") is False
    assert await _notifications(db_session) == []


@pytest.mark.asyncio
async def test_no_notification_for_ambiguous_noop_or_routine_terminal_rows(db_session, test_user):
    fixture = await add_minimal_launch(db_session, test_user, state="executing")
    notifier = RecoveryNotifier(db_session)

    deferred = ReconcileDecision(
        kind=OperationKind.LAUNCH,
        operation_id=fixture.operation.id,
        liveness=Liveness.ALIVE,
        proof_source="worker_heartbeat",
        runtime_state=RuntimeState.ABSENT,
        terminal_state=None,
        reason_code="runtime_absent",
    )
    assert await notifier.notify_applied(deferred) is False
    assert await notifier.notify_applied(deferred, applied_state="executing") is False

    fixture.operation.state = "succeeded"
    fixture.operation.reason_code = None
    await db_session.commit()
    routine = decision(OperationKind.LAUNCH, fixture.operation.id, TerminalState.SUCCEEDED)
    assert await notifier.notify_applied(routine, applied_state="succeeded") is False

    assert await _notifications(db_session) == []


@pytest.mark.asyncio
async def test_notification_never_contains_payloads_mounts_paths_or_identity(db_session, test_user):
    fixture = await add_launch(db_session, test_user, executor_state="stopped")
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    mount = operation.mounts[0]
    await db_session.execute(
        update(ServerLaunchOperation)
        .where(ServerLaunchOperation.id == fixture.operation_id)
        .values(
            request_payload={
                "token": "secret-token-value",
                "mounts": [{"mount_path": "/secret/host/path"}],
            }
        )
    )
    await db_session.commit()

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.finalized == 1
    notifications = await _notifications(db_session)
    assert len(notifications) == 1
    notification = notifications[0]
    text = json.dumps(
        {
            "title": notification.title,
            "message": notification.message,
            "extra_data": notification.extra_data,
        }
    )
    for forbidden in (
        "request_payload",
        "secret-token-value",
        "/secret/host/path",
        "mounts",
        "resources",
        "fencing_token",
        "executor_id",
        "container_id",
        "environment_slug",
        mount["volume_name"],
        mount["mount_path"],
        str(fixture.volume_id),
        operation.username,
        test_user.username,
    ):
        assert forbidden not in text


@pytest.mark.asyncio
async def test_volume_notification_omits_archive_paths_and_error_text(db_session, test_user):
    backup = await add_backup_row(db_session, test_user, status="in_progress")
    await db_session.execute(
        update(VolumeBackup)
        .where(VolumeBackup.id == backup.id)
        .values(
            status="failed",
            backup_path="/secret/archive/path",
            error_message="secret raw exception",
            source_metadata={"token": "secret-metadata-value"},
        )
    )
    await db_session.commit()

    notifier = RecoveryNotifier(db_session)
    failed = decision(
        OperationKind.BACKUP,
        backup.id,
        TerminalState.FAILED,
        reason="helper_absent",
    )
    assert await notifier.notify_applied(failed, applied_state="failed") is True

    notification = (await _notifications(db_session))[0]
    text = json.dumps(
        {
            "title": notification.title,
            "message": notification.message,
            "extra_data": notification.extra_data,
        }
    )
    for forbidden in (
        "/secret/archive/path",
        "secret raw exception",
        "secret-metadata-value",
        "backup_path",
        "error_message",
    ):
        assert forbidden not in text


@pytest.mark.asyncio
async def test_notification_delivery_failure_is_logged_by_class_and_ignored(
    db_session, test_user, monkeypatch
):
    fixture = await add_launch(db_session, test_user, executor_state="stopped")
    monkeypatch.setattr(
        "app.services.notification_service.NotificationService.create",
        AsyncMock(side_effect=RuntimeError("channel secret detail")),
    )
    warning = Mock()
    monkeypatch.setattr(recovery_notifications.logger, "warning", warning)

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.finalized == 1
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    assert operation.state == "failed"
    assert await _notifications(db_session) == []
    warning.assert_called_once()
    assert warning.call_args.kwargs["extra"]["error_class"] == "RuntimeError"
    assert "channel secret detail" not in json.dumps(warning.call_args.kwargs)


@pytest.mark.asyncio
async def test_notifier_exception_does_not_change_scan_counts(db_session, test_user, monkeypatch):
    fixture = await add_launch(db_session, test_user, executor_state="stopped")

    async def _broken(self, decision, *, applied_state=None):
        raise RuntimeError("notification backend unavailable")

    monkeypatch.setattr(RecoveryNotifier, "notify_applied", _broken)
    warning = Mock()
    monkeypatch.setattr(
        "app.services.operation_reconciler.logger.warning",
        warning,
    )

    report = await OperationReconciler(session_factory(db_session), FakeDriver()).scan()

    assert report.scanned == 1
    assert report.finalized == 1
    assert report.errors == 0
    operation = await db_session.get(
        ServerLaunchOperation, fixture.operation_id, populate_existing=True
    )
    assert operation.state == "failed"
    warning.assert_called_once()
    assert warning.call_args.kwargs["extra"]["error_class"] == "RuntimeError"


def test_recovery_notification_labels_titles_and_aliases():
    assert (
        recovery_notifications._normalized_state(OperationKind.LAUNCH, "recovery_required")
        == "uncertain"
    )
    assert (
        recovery_notifications._normalized_state(OperationKind.LAUNCH, "completed") == "succeeded"
    )
    assert recovery_notifications._normalized_state(OperationKind.LAUNCH, None) is None
    assert recovery_notifications._normalized_state(OperationKind.BACKUP, " FAILED ") == "failed"

    assert (
        recovery_notifications._decision_state(
            decision(OperationKind.LAUNCH, uuid.uuid4(), TerminalState.RECOVERY_REQUIRED)
        )
        == "uncertain"
    )
    assert (
        recovery_notifications._decision_state(
            decision(OperationKind.BACKUP, uuid.uuid4(), TerminalState.SUCCEEDED)
        )
        == "completed"
    )
    assert (
        recovery_notifications._decision_state(
            decision(OperationKind.RESTORE, uuid.uuid4(), TerminalState.FAILED)
        )
        == "failed"
    )

    assert (
        recovery_notifications._event_key(OperationKind.LAUNCH, "completed")
        == recovery_notifications._LAUNCH_COMPLETED_EVENT_KEY
    )
    assert (
        recovery_notifications._event_key(OperationKind.BACKUP, "completed")
        == recovery_notifications._VOLUME_COMPLETED_EVENT_KEY
    )
    assert recovery_notifications._label(OperationKind.LAUNCH) == "server operation"
    assert recovery_notifications._label(OperationKind.BACKUP) == "volume backup"
    assert recovery_notifications._label(OperationKind.RESTORE) == "volume restore"
    assert (
        recovery_notifications._title(OperationKind.LAUNCH, "completed", "succeeded")
        == "Server operation recovered"
    )
    assert (
        recovery_notifications._title(OperationKind.LAUNCH, "reminder", "uncertain")
        == "Server operation still needs attention"
    )
    assert (
        recovery_notifications._title(OperationKind.LAUNCH, "attention", "failed")
        == "Server launch failed"
    )


@pytest.mark.asyncio
async def test_notifier_ignores_missing_targets_and_invalid_ids(db_session):
    notifier = RecoveryNotifier(db_session)

    assert (
        await notifier.notify_applied(
            decision(OperationKind.LAUNCH, uuid.uuid4(), TerminalState.FAILED)
        )
        is False
    )
    assert (
        await notifier.notify_applied(
            decision(OperationKind.BACKUP, uuid.uuid4(), TerminalState.SUCCEEDED)
        )
        is False
    )
    assert (
        await notifier.notify_applied(
            decision(OperationKind.RESTORE, uuid.uuid4(), TerminalState.FAILED)
        )
        is False
    )
    assert await notifier.notify_reminder(OperationKind.LAUNCH, uuid.uuid4()) is False
    assert await notifier.notify_reminder(OperationKind.BACKUP, uuid.uuid4()) is False
    assert (
        await notifier.notify_applied(Mock(kind=OperationKind.LAUNCH, operation_id="not-a-uuid"))
        is False
    )


@pytest.mark.asyncio
async def test_safe_rollback_swallows_database_failures():
    notifier = RecoveryNotifier(Mock())
    notifier.db.rollback = AsyncMock(side_effect=RuntimeError("connection lost"))

    await notifier._safe_rollback()

    notifier.db.rollback.assert_awaited_once()
