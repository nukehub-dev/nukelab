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


class TestScheduleServiceExecute:
    """Tests for execute_schedule."""

    @pytest.mark.asyncio
    async def test_execute_schedule_server_not_found(self, db_session, test_user):
        """Should mark schedule inactive when server missing."""
        from unittest.mock import patch

        server = Server(name="tmp", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)

        # Mock the server query to return None
        async def mock_execute(stmt):
            class MockResult:
                def scalar_one_or_none(self):
                    return None

            return MockResult()

        with patch.object(db_session, "execute", side_effect=mock_execute):
            result = await service.execute_schedule(sched)

        assert result["success"] is False
        assert "Server not found" in result["error"]
        assert sched.is_active is False

    @pytest.mark.asyncio
    async def test_execute_schedule_start_no_container(self, db_session, test_user):
        """Start action with no container_id should report missing."""
        server = Server(name="srv", user_id=test_user.id, status="stopped", container_id=None)
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        result = await service.execute_schedule(sched)
        assert result["success"] is False
        assert (
            "container missing" in result["message"].lower()
            or "cannot auto-start" in result["message"]
        )

    @pytest.mark.asyncio
    async def test_execute_schedule_start_stopped_container(self, db_session, test_user):
        """Start action with stopped container should start it."""
        server = Server(name="srv", user_id=test_user.id, status="stopped", container_id="cid-123")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        mock_spawner = Mock()
        mock_spawner.get_status = AsyncMock(return_value="stopped")
        mock_spawner.start = AsyncMock()

        with (
            patch("app.container.spawner.spawner", mock_spawner),
            patch(
                "app.services.schedule_service.broadcast_server_status_change",
                new_callable=AsyncMock,
            ),
        ):
            result = await service.execute_schedule(sched)

        assert result["success"] is True
        assert "started" in result["message"].lower()
        mock_spawner.start.assert_awaited_once_with("cid-123")
        assert server.status == "running"

    @pytest.mark.asyncio
    async def test_execute_schedule_start_already_running(self, db_session, test_user):
        """Start action with already running container does nothing."""
        server = Server(name="srv", user_id=test_user.id, status="running", container_id="cid-123")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="start",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        mock_spawner = Mock()
        mock_spawner.get_status = AsyncMock(return_value="running")

        with patch("app.container.spawner.spawner", mock_spawner):
            result = await service.execute_schedule(sched)

        assert result["success"] is False
        mock_spawner.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_schedule_stop(self, db_session, test_user):
        """Stop action should stop running server."""
        server = Server(name="srv", user_id=test_user.id, status="running", container_id="cid-123")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="stop",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        mock_spawner = Mock()
        mock_spawner.delete = AsyncMock()

        with (
            patch("app.container.spawner.spawner", mock_spawner),
            patch(
                "app.services.schedule_service.broadcast_server_status_change",
                new_callable=AsyncMock,
            ),
            patch("app.services.quota_service.QuotaService") as mock_quota_cls,
        ):
            mock_quota = Mock()
            mock_quota.decrement_usage = AsyncMock()
            mock_quota_cls.return_value = mock_quota
            result = await service.execute_schedule(sched)

        assert result["success"] is True
        assert "stopped" in result["message"].lower()
        mock_spawner.delete.assert_awaited_once_with("cid-123")
        assert server.status == "stopped"

    @pytest.mark.asyncio
    async def test_execute_schedule_stop_with_plan_billing(self, db_session, test_user):
        """Stop action should reconcile billing when plan exists."""
        from app.models.server_plan import ServerPlan

        server = Server(
            name="srv",
            user_id=test_user.id,
            status="running",
            container_id="cid-123",
            plan_id=uuid_mod.uuid4(),
        )
        db_session.add(server)
        await db_session.flush()

        plan = ServerPlan(
            id=server.plan_id,
            name="test",
            slug="test",
            cpu_limit=1.0,
            memory_limit="512m",
            disk_limit="10g",
            cost_per_hour=1,
        )
        db_session.add(plan)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="stop",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        mock_spawner = Mock()
        mock_spawner.delete = AsyncMock()
        mock_credit = Mock()
        mock_credit.reconcile_server_billing = AsyncMock()

        with (
            patch("app.container.spawner.spawner", mock_spawner),
            patch(
                "app.services.schedule_service.broadcast_server_status_change",
                new_callable=AsyncMock,
            ),
            patch("app.services.credit_service.CreditService", return_value=mock_credit),
            patch("app.services.quota_service.QuotaService") as mock_quota_cls,
        ):
            mock_quota = Mock()
            mock_quota.decrement_usage = AsyncMock()
            mock_quota_cls.return_value = mock_quota
            result = await service.execute_schedule(sched)

        assert result["success"] is True
        mock_credit.reconcile_server_billing.assert_awaited_once()
        mock_quota.decrement_usage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_schedule_restart(self, db_session, test_user):
        """Restart action should stop then start container."""
        server = Server(name="srv", user_id=test_user.id, status="running", container_id="cid-123")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="restart",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        mock_spawner = Mock()
        mock_spawner.stop = AsyncMock()
        mock_spawner.start = AsyncMock()

        with (
            patch("app.container.spawner.spawner", mock_spawner),
            patch(
                "app.services.schedule_service.broadcast_server_status_change",
                new_callable=AsyncMock,
            ),
        ):
            result = await service.execute_schedule(sched)

        assert result["success"] is True
        assert "restarted" in result["message"].lower()
        mock_spawner.stop.assert_awaited_once_with("cid-123")
        mock_spawner.start.assert_awaited_once_with("cid-123")

    @pytest.mark.asyncio
    async def test_execute_schedule_exception(self, db_session, test_user):
        """Exception during execution should rollback and return error."""
        server = Server(name="srv", user_id=test_user.id, status="running", container_id="cid-123")
        db_session.add(server)
        await db_session.flush()

        sched = ServerSchedule(
            server_id=server.id,
            user_id=test_user.id,
            action="restart",
            cron_expression="0 9 * * *",
            next_run_at=datetime.now(UTC).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(sched)
        await db_session.commit()

        service = ScheduleService(db_session)
        mock_spawner = Mock()
        mock_spawner.stop = AsyncMock(side_effect=Exception("docker error"))

        with patch("app.container.spawner.spawner", mock_spawner):
            result = await service.execute_schedule(sched)

        assert result["success"] is False
        assert "docker error" in result["error"]
