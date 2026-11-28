# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""One bounded owner completion notification per batch-job terminal event."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.services.batch_job_finalizer import BatchJobFinalizer
from app.services.batch_job_notifications import (
    EVENT_KEY,
    BatchJobNotifier,
    notification_dedupe_key,
)
from tests.conftest import test_engine
from tests.services.test_batch_job_runtime import (
    committed_admitted_job as committed_admitted_job,
)
from tests.services.test_batch_job_runtime import (
    load_job,
    set_job,
    volume_operation,
)


async def _notifications(db, user_id) -> list[Notification]:
    return list(
        (
            await db.scalars(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at, Notification.id)
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_success_creates_one_bounded_notification(db_session, test_user):
    job_id = uuid.uuid4()
    created = await BatchJobNotifier(db_session).notify_terminal(
        job_id=job_id,
        owner_id=test_user.id,
        job_name="  safe\n job  ",
        state="succeeded",
    )

    assert created is True
    notifications = await _notifications(db_session, test_user.id)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.user_id == test_user.id
    assert notification.type == "job"
    assert notification.severity == "success"
    assert notification.action_url == f"/jobs/{job_id}"
    assert notification.extra_data["dedupe_key"] == notification_dedupe_key(job_id)
    assert notification.extra_data["job_id"] == str(job_id)
    assert notification.extra_data["terminal_state"] == "succeeded"
    assert notification.extra_data["event_key"] == EVENT_KEY
    assert "safe job" in notification.message
    assert str(job_id) in notification.message
    assert "succeeded" in notification.message


@pytest.mark.asyncio
async def test_failure_state_is_reported_without_extra_payload(db_session, test_user):
    job_id = uuid.uuid4()
    created = await BatchJobNotifier(db_session).notify_terminal(
        job_id=job_id,
        owner_id=test_user.id,
        job_name="nightly check",
        state="failed",
    )

    assert created is True
    notification = (await _notifications(db_session, test_user.id))[0]
    assert notification.severity == "error"
    assert "failed" in notification.title.lower()
    assert "failed" in notification.message
    assert set(notification.extra_data) == {
        "dedupe_key",
        "event_key",
        "job_id",
        "terminal_state",
    }


@pytest.mark.asyncio
async def test_repeated_notification_creates_one_row(db_session, test_user):
    job_id = uuid.uuid4()
    notifier = BatchJobNotifier(db_session)

    first = await notifier.notify_terminal(
        job_id=job_id,
        owner_id=test_user.id,
        job_name="repeat",
        state="succeeded",
    )
    second = await notifier.notify_terminal(
        job_id=job_id,
        owner_id=test_user.id,
        job_name="repeat",
        state="succeeded",
    )

    assert first is True
    assert second is False
    assert len(await _notifications(db_session, test_user.id)) == 1


@pytest.mark.asyncio
async def test_suppressed_primary_event_falls_back_to_in_app(db_session, test_user):
    test_user.preferences = {
        "notifications": {
            "events": [
                {
                    "event": EVENT_KEY,
                    "channels": {"email": False, "webhook": False, "in_app": False, "push": False},
                }
            ]
        }
    }
    await db_session.commit()

    created = await BatchJobNotifier(db_session).notify_terminal(
        job_id=uuid.uuid4(),
        owner_id=test_user.id,
        job_name="fallback",
        state="succeeded",
    )

    assert created is True
    notifications = await _notifications(db_session, test_user.id)
    assert len(notifications) == 1
    assert notifications[0].extra_data["event_key"] == EVENT_KEY


@pytest.mark.asyncio
async def test_delivery_failure_is_swallowed(db_session, test_user):
    with patch(
        "app.services.notification_service.NotificationService.create",
        side_effect=RuntimeError("notification store unavailable"),
    ):
        created = await BatchJobNotifier(db_session).notify_terminal(
            job_id=uuid.uuid4(),
            owner_id=test_user.id,
            job_name="failure",
            state="succeeded",
        )

    assert created is False
    assert await _notifications(db_session, test_user.id) == []


@pytest.mark.asyncio
async def test_finalize_creates_one_notification_and_never_leaks_payload(
    committed_admitted_job,
):
    fixture = committed_admitted_job
    await set_job(
        fixture.job_id,
        argv=["python", "-c", "print('ARGV_SECRET')"],
        name="safe job",
    )
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        finalizer = BatchJobFinalizer(db, fixture.driver)
        first = await finalizer.finalize(
            fixture.job_id,
            fencing_token=fixture.admission.fencing_token,
            state="succeeded",
            outcome_code="succeeded",
            proof_class="runtime",
            exit_code=0,
            executor_terminated=True,
            log_state="available",
            log_text="LOG_SECRET",
        )
        second = await finalizer.finalize(
            fixture.job_id,
            fencing_token=fixture.admission.fencing_token,
            state="succeeded",
            outcome_code="succeeded",
            proof_class="runtime",
            exit_code=0,
            executor_terminated=True,
        )

    assert first.applied is True
    assert second.already_terminal is True
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        notifications = await _notifications(db, fixture.owner_id)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.action_url == f"/jobs/{fixture.job_id}"
    assert "safe job" in notification.message
    rendered = f"{notification.title} {notification.message} {notification.extra_data}"
    assert "ARGV_SECRET" not in rendered
    assert "LOG_SECRET" not in rendered
    assert fixture.volume_name not in rendered
    assert "nukelab-job-" not in rendered


class _FailingNotifier:
    async def notify_terminal(self, **kwargs):
        raise RuntimeError("notification store unavailable")


@pytest.mark.asyncio
async def test_notification_failure_keeps_terminal_result_and_release(
    committed_admitted_job,
):
    fixture = committed_admitted_job
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        finalizer = BatchJobFinalizer(db, fixture.driver, notifier=_FailingNotifier())
        result = await finalizer.finalize(
            fixture.job_id,
            fencing_token=fixture.admission.fencing_token,
            state="failed",
            outcome_code="failed",
            reason_code="nonzero_exit",
            proof_class="runtime",
            exit_code=1,
            executor_terminated=True,
        )

    assert result.applied is True
    job = await load_job(fixture.job_id)
    assert job.state == "failed"
    assert job.outcome_code == "failed"
    assert job.exit_code == 1
    assert job.result_recorded_at is not None
    assert job.reservation_active is False
    assert (await volume_operation(fixture.job_id)).state == "failed"
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        assert await _notifications(db, fixture.owner_id) == []
