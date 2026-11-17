# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for ScheduleService business logic."""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.models.server import Server
from app.models.server_schedule import ServerSchedule
from app.services.schedule_service import ScheduleService, _get_next_run, _validate_cron


class TestCronHelpers:
    """Tests for cron helper functions."""

    def test_validate_cron_valid(self):
        """Should not raise for valid cron."""
        _validate_cron("0 9 * * *")

    def test_validate_cron_invalid(self):
        """Should raise ValueError for invalid cron."""
        with pytest.raises(ValueError):
            _validate_cron("not-a-cron")

    def test_get_next_run(self):
        """Should return a future datetime."""
        next_run = _get_next_run("0 9 * * *")
        assert isinstance(next_run, datetime)
        assert next_run > datetime.now(UTC).replace(tzinfo=None)


class TestScheduleServiceGet:
    """Tests for get_schedules_for_server."""

    @pytest.mark.asyncio
    async def test_get_schedules_empty(self, db_session):
        """Should return empty list for server with no schedules."""
        service = ScheduleService(db_session)
        result = await service.get_schedules_for_server(str(uuid_mod.uuid4()))
        assert result == []

    @pytest.mark.asyncio
    async def test_get_schedules_for_server(self, db_session, test_user):
        """Should return schedules for server."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        result = await service.get_schedules_for_server(str(server.id))
        assert len(result) == 1
        assert result[0]["action"] == "start"

    @pytest.mark.asyncio
    async def test_get_schedules_filtered_by_user(self, db_session, test_user, admin_user):
        """Should filter schedules by user_id."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        result = await service.get_schedules_for_server(str(server.id), user_id=str(admin_user.id))
        assert result == []


class TestScheduleServiceCreate:
    """Tests for create_schedule."""

    @pytest.mark.asyncio
    async def test_create_schedule_success(self, db_session, test_user):
        """Should create a schedule."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()

        service = ScheduleService(db_session)
        schedule = await service.create_schedule(
            str(server.id), str(test_user.id), action="start", cron_expression="0 9 * * *"
        )
        assert schedule.action == "start"
        assert schedule.cron_expression == "0 9 * * *"
        assert schedule.next_run_at is not None

    @pytest.mark.asyncio
    async def test_create_schedule_invalid_action(self, db_session, test_user):
        """Should reject invalid action."""
        service = ScheduleService(db_session)
        with pytest.raises(ValueError) as exc_info:
            await service.create_schedule(
                str(uuid_mod.uuid4()),
                str(test_user.id),
                action="delete",
                cron_expression="0 9 * * *",
            )
        assert "Invalid action" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_schedule_invalid_cron(self, db_session, test_user):
        """Should reject invalid cron."""
        service = ScheduleService(db_session)
        with pytest.raises(ValueError):
            await service.create_schedule(
                str(uuid_mod.uuid4()), str(test_user.id), action="start", cron_expression="invalid"
            )


class TestScheduleServiceUpdate:
    """Tests for update_schedule."""

    @pytest.mark.asyncio
    async def test_update_schedule_action(self, db_session, test_user):
        """Should update schedule action."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        updated = await service.update_schedule(str(sched.id), str(test_user.id), action="stop")
        assert updated.action == "stop"

    @pytest.mark.asyncio
    async def test_update_schedule_cron(self, db_session, test_user):
        """Should update cron and recalculate next_run."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        updated = await service.update_schedule(
            str(sched.id), str(test_user.id), cron_expression="0 18 * * *"
        )
        assert updated.cron_expression == "0 18 * * *"
        assert updated.next_run_at is not None

    @pytest.mark.asyncio
    async def test_update_schedule_not_found(self, db_session, test_user):
        """Should raise when schedule not found."""
        service = ScheduleService(db_session)
        with pytest.raises(ValueError) as exc_info:
            await service.update_schedule(str(uuid_mod.uuid4()), str(test_user.id), action="stop")
        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_schedule_invalid_action(self, db_session, test_user):
        """Should reject invalid action."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        with pytest.raises(ValueError):
            await service.update_schedule(str(sched.id), str(test_user.id), action="invalid")

    @pytest.mark.asyncio
    async def test_update_schedule_toggle_active(self, db_session, test_user):
        """Should toggle is_active."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        updated = await service.update_schedule(str(sched.id), str(test_user.id), is_active=False)
        assert updated.is_active is False


class TestScheduleServiceDelete:
    """Tests for delete_schedule."""

    @pytest.mark.asyncio
    async def test_delete_schedule_success(self, db_session, test_user):
        """Should delete schedule."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        result = await service.delete_schedule(str(sched.id), str(test_user.id))
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_schedule_not_found(self, db_session, test_user):
        """Should return False when schedule not found."""
        service = ScheduleService(db_session)
        result = await service.delete_schedule(str(uuid_mod.uuid4()), str(test_user.id))
        assert result is False


class TestScheduleServiceDue:
    """Tests for get_due_schedules."""

    @pytest.mark.asyncio
    async def test_get_due_schedules_empty(self, db_session):
        """Should return empty when no schedules are due."""
        service = ScheduleService(db_session)
        result = await service.get_due_schedules()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_due_schedules_returns_due(self, db_session, test_user):
        """Should return schedules that are due."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        result = await service.get_due_schedules()
        assert len(result) == 1
        assert result[0].action == "start"

    @pytest.mark.asyncio
    async def test_get_due_schedules_skips_future(self, db_session, test_user):
        """Should not return future schedules."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        result = await service.get_due_schedules()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_due_schedules_skips_inactive(self, db_session, test_user):
        """Should not return inactive schedules."""
        server = Server(name="srv", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5),
            is_active=False,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        result = await service.get_due_schedules()
        assert result == []


@pytest.fixture
def schedule_inputs(db_session, test_user):
    owner_id = test_user.id

    async def create(action="start", status="stopped", container_id="old-container", plan_id=None):
        server = Server(
            name=f"scheduled-{uuid_mod.uuid4().hex}",
            user_id=owner_id,
            status=status,
            container_id=container_id,
            plan_id=plan_id,
        )
        db_session.add(server)
        await db_session.flush()
        schedule = ServerSchedule(
            server_id=server.id,
            user_id=owner_id,
            action=action,
            cron_expression="0 9 * * *",
            timezone="UTC",
            next_run_at=datetime.now(UTC).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(schedule)
        await db_session.commit()
        return server.id, schedule.id, owner_id, schedule

    return create


class TestScheduleServiceExecute:
    @pytest.mark.asyncio
    async def test_missing_server_disables_schedule(self, db_session, schedule_inputs):
        _, schedule_id, _, schedule = await schedule_inputs()
        result = Mock()
        result.scalar_one_or_none.return_value = None
        with patch.object(db_session, "execute", AsyncMock(return_value=result)):
            outcome = await ScheduleService(db_session).execute_schedule(schedule)
        assert outcome == {"success": False, "error": "Server not found"}
        stored = await db_session.get(ServerSchedule, schedule_id, populate_existing=True)
        assert not stored.is_active

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action,initial,expected",
        [
            ("start", "stopped", "running"),
            ("stop", "running", "stopped"),
            ("restart", "running", "running"),
        ],
    )
    async def test_actions_use_guarded_boundary_and_close_driver(
        self, db_session, schedule_inputs, action, initial, expected
    ):
        from types import SimpleNamespace

        from sqlalchemy import select

        from app.models.notification import Notification

        server_id, schedule_id, owner_id, schedule = await schedule_inputs(action, initial)
        runtime = SimpleNamespace(close=AsyncMock())

        async def perform(id_, owner_id=None):
            assert id_ == server_id
            # Shared lifecycle expires all read-only identities before admission.
            await db_session.rollback()
            server = await db_session.get(Server, id_, populate_existing=True)
            server.status = expected
            server.container_id = None if expected == "stopped" else "new-container"
            await db_session.commit()
            return server

        lifecycle = Mock(
            start=AsyncMock(side_effect=perform), restart=AsyncMock(side_effect=perform)
        )
        termination = Mock(stop=AsyncMock(side_effect=perform))
        with (
            patch(
                "app.services.schedule_service.get_fresh_driver", AsyncMock(return_value=runtime)
            ),
            patch("app.services.schedule_service.ServerLifecycleService", return_value=lifecycle),
            patch(
                "app.services.schedule_service.ServerTerminationService", return_value=termination
            ),
            patch("app.services.schedule_service.broadcast_server_status_change", AsyncMock()),
        ):
            outcome = await ScheduleService(db_session).execute_schedule(schedule)
        assert outcome["success"] is True
        boundary = termination.stop if action == "stop" else getattr(lifecycle, action)
        if action == "stop":
            boundary.assert_awaited_once_with(server_id, owner_id)
        else:
            boundary.assert_awaited_once_with(server_id, owner_id=owner_id)
        stored = await db_session.get(ServerSchedule, schedule_id, populate_existing=True)
        assert stored.run_count == 1 and stored.last_run_at is not None
        assert stored.next_run_at > stored.last_run_at
        notifications = (
            await db_session.scalars(select(Notification).where(Notification.user_id == owner_id))
        ).all()
        assert len(notifications) == 1
        runtime.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_without_container_still_uses_shared_recreation_policy(
        self, db_session, schedule_inputs
    ):
        from types import SimpleNamespace

        server_id, _, owner_id, schedule = await schedule_inputs(container_id=None)
        runtime = SimpleNamespace(close=AsyncMock())
        launched = SimpleNamespace(container_id="recreated-runtime")
        lifecycle = Mock(start=AsyncMock(return_value=launched))
        with (
            patch(
                "app.services.schedule_service.get_fresh_driver", AsyncMock(return_value=runtime)
            ),
            patch("app.services.schedule_service.ServerLifecycleService", return_value=lifecycle),
            patch("app.services.schedule_service.broadcast_server_status_change", AsyncMock()),
        ):
            outcome = await ScheduleService(db_session).execute_schedule(schedule)
        assert outcome["success"]
        lifecycle.start.assert_awaited_once_with(server_id, owner_id=owner_id)
        runtime.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_running_start_is_noop(self, db_session, schedule_inputs):
        _, schedule_id, _, schedule = await schedule_inputs(status="running")
        with patch("app.services.schedule_service.get_fresh_driver", AsyncMock()) as factory:
            outcome = await ScheduleService(db_session).execute_schedule(schedule)
        assert outcome["success"] is False
        factory.assert_not_awaited()
        stored = await db_session.get(ServerSchedule, schedule_id, populate_existing=True)
        assert stored.run_count == 1

    @pytest.mark.asyncio
    async def test_runtime_failure_is_sanitized_and_driver_closed(
        self, db_session, schedule_inputs
    ):
        from types import SimpleNamespace

        from app.services.server_launch_service import LaunchError

        _, schedule_id, _, schedule = await schedule_inputs()
        runtime = SimpleNamespace(close=AsyncMock())
        lifecycle = Mock(start=AsyncMock(side_effect=LaunchError("launch_in_progress", 409)))
        with (
            patch(
                "app.services.schedule_service.get_fresh_driver", AsyncMock(return_value=runtime)
            ),
            patch("app.services.schedule_service.ServerLifecycleService", return_value=lifecycle),
        ):
            outcome = await ScheduleService(db_session).execute_schedule(schedule)
        assert outcome == {"success": False, "error": "launch_in_progress"}
        runtime.close.assert_awaited_once()
        stored = await db_session.get(ServerSchedule, schedule_id, populate_existing=True)
        assert stored.run_count == 0

    @pytest.mark.asyncio
    async def test_stop_reconciles_billing_after_guarded_termination(
        self, db_session, schedule_inputs
    ):
        from types import SimpleNamespace

        from app.models.server_plan import ServerPlan

        plan = ServerPlan(
            name="schedule-billing",
            slug="schedule-billing",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="1g",
            cost_per_hour=1,
        )
        db_session.add(plan)
        await db_session.commit()
        plan_id = plan.id
        server_id, _, _, schedule = await schedule_inputs(
            action="stop", status="running", plan_id=plan_id
        )
        server = await db_session.get(Server, server_id)
        runtime = SimpleNamespace(close=AsyncMock())
        termination = Mock(stop=AsyncMock(return_value=server))
        credit = Mock(reconcile_server_billing=AsyncMock())
        with (
            patch(
                "app.services.schedule_service.get_fresh_driver", AsyncMock(return_value=runtime)
            ),
            patch(
                "app.services.schedule_service.ServerTerminationService", return_value=termination
            ),
            patch("app.services.credit_service.CreditService", return_value=credit),
            patch("app.services.schedule_service.broadcast_server_status_change", AsyncMock()),
        ):
            outcome = await ScheduleService(db_session).execute_schedule(schedule)
        assert outcome["success"]
        credit.reconcile_server_billing.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_due_schedules_survive_session_expiration(
        self, db_session, schedule_inputs
    ):
        from types import SimpleNamespace

        first_id, _, _, _ = await schedule_inputs()
        second_id, _, _, _ = await schedule_inputs()
        service = ScheduleService(db_session)
        schedules = await service.get_due_schedules()
        runtime = SimpleNamespace(close=AsyncMock())
        seen = []

        async def launch(server_id, owner_id=None):
            seen.append(server_id)
            await db_session.rollback()
            server = await db_session.get(Server, server_id, populate_existing=True)
            server.status = "running"
            await db_session.commit()
            return server

        lifecycle = Mock(start=AsyncMock(side_effect=launch))
        with (
            patch(
                "app.services.schedule_service.get_fresh_driver", AsyncMock(return_value=runtime)
            ),
            patch("app.services.schedule_service.ServerLifecycleService", return_value=lifecycle),
            patch("app.services.schedule_service.broadcast_server_status_change", AsyncMock()),
        ):
            for schedule in schedules:
                assert (await service.execute_schedule(schedule))["success"]
        assert set(seen) == {first_id, second_id}
        assert runtime.close.await_count == 2

    @pytest.mark.asyncio
    async def test_cancellation_propagates_and_closes_action_driver(
        self, db_session, schedule_inputs
    ):
        import asyncio
        from types import SimpleNamespace

        _, _, _, schedule = await schedule_inputs()
        runtime = SimpleNamespace(close=AsyncMock())
        lifecycle = Mock(start=AsyncMock(side_effect=asyncio.CancelledError()))
        with (
            patch(
                "app.services.schedule_service.get_fresh_driver", AsyncMock(return_value=runtime)
            ),
            patch("app.services.schedule_service.ServerLifecycleService", return_value=lifecycle),
        ):
            with pytest.raises(asyncio.CancelledError):
                await ScheduleService(db_session).execute_schedule(schedule)
        runtime.close.assert_awaited_once()
