# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded, deduplicated reminders for long-standing recovery rows."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from app import tasks
from app.core.time_utils import utc_now
from app.models.notification import Notification
from app.models.server_launch_operation import ServerLaunchOperation
from app.services.recovery_notifications import (
    RECOVERY_REMINDER_AFTER,
    RECOVERY_REMINDER_BATCH_LIMIT,
    RecoveryReminderReport,
    send_recovery_reminders,
)
from app.worker import celery_app
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


@pytest.mark.asyncio
async def test_sweep_finds_only_stale_unresolved_rows(db_session, test_user):
    now = utc_now()
    stale_launch = await add_minimal_launch(
        db_session,
        test_user,
        state="uncertain",
        created_at=now - RECOVERY_REMINDER_AFTER - timedelta(minutes=5),
    )
    stale_backup = await add_backup_row(
        db_session,
        test_user,
        status="recovery_required",
        created_at=now - RECOVERY_REMINDER_AFTER - timedelta(hours=2),
    )
    await add_minimal_launch(
        db_session,
        test_user,
        state="uncertain",
        created_at=now - timedelta(hours=2),
    )
    await add_minimal_launch(
        db_session,
        test_user,
        state="failed",
        created_at=now - RECOVERY_REMINDER_AFTER - timedelta(hours=2),
    )
    await add_backup_row(
        db_session,
        test_user,
        status="completed",
        created_at=now - RECOVERY_REMINDER_AFTER - timedelta(hours=2),
    )

    report = await send_recovery_reminders(db_session, now=now)

    assert report == RecoveryReminderReport(scanned=2, sent=2, skipped=0)
    notifications = await _notifications(db_session)
    assert len(notifications) == 2
    assert {item.extra_data["operation_id"] for item in notifications} == {
        str(stale_launch.operation.id),
        str(stale_backup.id),
    }
    assert {item.extra_data["recovery_event"] for item in notifications} == {"reminder"}
    assert {item.extra_data["operation_kind"] for item in notifications} == {
        "launch",
        "backup",
    }
    assert all(item.user_id == test_user.id for item in notifications)
    assert all("still" in item.title.lower() for item in notifications)


@pytest.mark.asyncio
async def test_sweep_dedupes_within_the_24_hour_window(db_session, test_user):
    now = utc_now()
    fixture = await add_minimal_launch(
        db_session,
        test_user,
        state="uncertain",
        created_at=now - RECOVERY_REMINDER_AFTER - timedelta(hours=1),
    )

    first = await send_recovery_reminders(db_session, now=now)
    second = await send_recovery_reminders(db_session, now=now + timedelta(hours=1))

    assert first.sent == 1
    assert second.scanned == 1
    assert second.sent == 0
    assert second.skipped == 1
    assert len(await _notifications(db_session)) == 1

    later = await send_recovery_reminders(
        db_session, now=now + RECOVERY_REMINDER_AFTER + timedelta(hours=1)
    )

    assert later.sent == 1
    assert len(await _notifications(db_session)) == 2
    assert {item.extra_data["operation_id"] for item in await _notifications(db_session)} == {
        str(fixture.operation.id)
    }


@pytest.mark.asyncio
async def test_sweep_caps_the_batch_and_counts_skips(db_session, test_user):
    now = utc_now()
    rows = [
        await add_minimal_launch(
            db_session,
            test_user,
            state="uncertain",
            created_at=now - RECOVERY_REMINDER_AFTER - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]

    report = await send_recovery_reminders(db_session, limit=2, now=now)

    assert report == RecoveryReminderReport(scanned=2, sent=2, skipped=0)
    notifications = await _notifications(db_session)
    assert len(notifications) == 2
    selected = {item.extra_data["operation_id"] for item in notifications}
    assert selected == {str(rows[1].operation.id), str(rows[2].operation.id)}

    empty = await send_recovery_reminders(db_session, limit=0, now=now)
    assert empty == RecoveryReminderReport()


@pytest.mark.asyncio
async def test_sweep_rejects_a_non_integer_limit(db_session):
    with pytest.raises(ValueError):
        await send_recovery_reminders(db_session, limit=True)
    with pytest.raises(ValueError):
        await send_recovery_reminders(db_session, limit="10")


def test_reminder_task_and_beat_entry_are_registered():
    assert "app.tasks.remind_recovery_required_operations" in celery_app.tasks
    entry = celery_app.conf.beat_schedule["remind-recovery-required-operations"]
    assert entry["task"] == "app.tasks.remind_recovery_required_operations"
    assert entry["schedule"].hour == {8}
    assert entry["schedule"].minute == {0}


@pytest.mark.asyncio
async def test_task_runs_a_bounded_sweep(monkeypatch):
    report = RecoveryReminderReport(scanned=4, sent=1, skipped=3)
    sweep = AsyncMock(return_value=report)
    monkeypatch.setattr(tasks, "send_recovery_reminders", sweep)

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: _Session())

    output = tasks.remind_recovery_required_operations.run()

    assert output == "Recovery reminders: scanned=4, sent=1, skipped=3"
    sweep.assert_awaited_once()
    assert sweep.await_args.kwargs["limit"] == RECOVERY_REMINDER_BATCH_LIMIT


@pytest.mark.asyncio
async def test_task_defers_on_database_failure_without_echoing_details(monkeypatch):
    monkeypatch.setattr(
        tasks,
        "send_recovery_reminders",
        AsyncMock(side_effect=RuntimeError("secret database detail")),
    )

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(tasks, "AsyncSessionLocal", lambda: _Session())
    warning = Mock()
    monkeypatch.setattr(tasks.logger, "warning", warning)

    output = tasks.remind_recovery_required_operations.run()

    assert output == "Recovery reminder sweep deferred"
    warning.assert_called_once()
    assert warning.call_args.kwargs["extra"]["error_class"] == "RuntimeError"
    assert "secret database detail" not in str(warning.call_args)


@pytest.mark.asyncio
async def test_sweep_notification_failure_leaves_rows_for_the_next_run(
    db_session, test_user, monkeypatch
):
    fixture = await add_minimal_launch(
        db_session,
        test_user,
        state="uncertain",
        created_at=utc_now() - RECOVERY_REMINDER_AFTER - timedelta(hours=1),
    )
    monkeypatch.setattr(
        "app.services.notification_service.NotificationService.create",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    )

    async with session_factory(db_session)() as reminder_db:
        report = await send_recovery_reminders(reminder_db)

    assert report.scanned == 1
    assert report.sent == 0
    assert report.skipped == 1
    assert await _notifications(db_session) == []
    state = await db_session.scalar(
        select(ServerLaunchOperation.state).where(ServerLaunchOperation.id == fixture.operation.id)
    )
    assert state == "uncertain"
