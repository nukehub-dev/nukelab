"""Tests for ActivityService business logic."""

import pytest
import uuid as uuid_mod

from app.services.activity_service import ActivityService
from app.models.activity_log import ActivityLog


class TestActivityServiceLog:
    """Tests for log method."""

    @pytest.mark.asyncio
    async def test_log_basic(self, db_session, test_user):
        """log should create an activity log entry."""
        service = ActivityService(db_session)
        log = await service.log(
            action="server.create",
            target_type="server",
            target_id=str(uuid_mod.uuid4()),
            actor_id=str(test_user.id),
            details={"name": "test-server"},
            ip_address="127.0.0.1",
            user_agent="test-agent",
        )
        assert log.action == "server.create"
        assert log.target_type == "server"
        assert log.actor_id == test_user.id
        assert log.details == {"name": "test-server"}
        assert str(log.ip_address) == "127.0.0.1"
        assert log.user_agent == "test-agent"

    @pytest.mark.asyncio
    async def test_log_without_optional_fields(self, db_session):
        """log should work without optional fields."""
        service = ActivityService(db_session)
        log = await service.log(action="system.startup", target_type="system")
        assert log.action == "system.startup"
        assert log.actor_id is None
        assert log.target_id is None
        assert log.details == {}


class TestActivityServiceGetLogs:
    """Tests for get_logs."""

    @pytest.mark.asyncio
    async def test_get_logs_no_filters(self, db_session, test_user):
        """get_logs should return all logs."""
        service = ActivityService(db_session)
        await service.log(action="test.action", target_type="test", actor_id=str(test_user.id))

        logs = await service.get_logs()
        assert len(logs) >= 1

    @pytest.mark.asyncio
    async def test_get_logs_filter_by_actor(self, db_session, test_user, admin_user):
        """get_logs should filter by actor_id."""
        service = ActivityService(db_session)
        await service.log(action="test", target_type="test", actor_id=str(test_user.id))
        await service.log(action="test", target_type="test", actor_id=str(admin_user.id))

        logs = await service.get_logs(actor_id=str(test_user.id))
        assert all(log.actor_id == test_user.id for log in logs)

    @pytest.mark.asyncio
    async def test_get_logs_filter_by_action(self, db_session, test_user):
        """get_logs should filter by action."""
        service = ActivityService(db_session)
        await service.log(action="server.create", target_type="server", actor_id=str(test_user.id))
        await service.log(action="server.delete", target_type="server", actor_id=str(test_user.id))

        logs = await service.get_logs(action="server.create")
        assert all(log.action == "server.create" for log in logs)

    @pytest.mark.asyncio
    async def test_get_logs_filter_by_target_type(self, db_session, test_user):
        """get_logs should filter by target_type."""
        service = ActivityService(db_session)
        await service.log(action="test", target_type="server", actor_id=str(test_user.id))
        await service.log(action="test", target_type="user", actor_id=str(test_user.id))

        logs = await service.get_logs(target_type="server")
        assert all(log.target_type == "server" for log in logs)

    @pytest.mark.asyncio
    async def test_get_logs_filter_by_target_id(self, db_session, test_user):
        """get_logs should filter by target_id."""
        target_id = str(uuid_mod.uuid4())
        service = ActivityService(db_session)
        await service.log(
            action="test", target_type="server", target_id=target_id, actor_id=str(test_user.id)
        )
        await service.log(
            action="test",
            target_type="server",
            target_id=str(uuid_mod.uuid4()),
            actor_id=str(test_user.id),
        )

        logs = await service.get_logs(target_id=target_id)
        assert all(str(log.target_id) == target_id for log in logs)

    @pytest.mark.asyncio
    async def test_get_logs_pagination(self, db_session, test_user):
        """get_logs should respect limit and offset."""
        service = ActivityService(db_session)
        for i in range(5):
            await service.log(action=f"test.{i}", target_type="test", actor_id=str(test_user.id))

        logs = await service.get_logs(limit=2, offset=0)
        assert len(logs) == 2


class TestActivityServiceUserActivity:
    """Tests for get_user_activity."""

    @pytest.mark.asyncio
    async def test_get_user_activity(self, db_session, test_user, admin_user):
        """get_user_activity should return logs for specific user."""
        service = ActivityService(db_session)
        await service.log(action="test", target_type="test", actor_id=str(test_user.id))
        await service.log(action="test", target_type="test", actor_id=str(admin_user.id))

        logs = await service.get_user_activity(str(test_user.id))
        assert len(logs) >= 1
        assert all(log.actor_id == test_user.id for log in logs)

    @pytest.mark.asyncio
    async def test_get_user_activity_empty(self, db_session):
        """get_user_activity should return empty for user with no activity."""
        service = ActivityService(db_session)
        logs = await service.get_user_activity(str(uuid_mod.uuid4()))
        assert logs == []


class TestActivityServiceWorkspaceActivity:
    """Tests for get_workspace_activity."""

    @pytest.mark.asyncio
    async def test_get_workspace_activity(self, db_session):
        """get_workspace_activity should return workspace logs."""
        ws_id = str(uuid_mod.uuid4())
        service = ActivityService(db_session)
        await service.log(action="test", target_type="workspace", target_id=ws_id)
        await service.log(action="test", target_type="server", target_id=str(uuid_mod.uuid4()))

        logs = await service.get_workspace_activity(ws_id)
        assert len(logs) == 1
        assert logs[0].target_type == "workspace"

    @pytest.mark.asyncio
    async def test_get_workspace_activity_empty(self, db_session):
        """get_workspace_activity should return empty for workspace with no activity."""
        service = ActivityService(db_session)
        logs = await service.get_workspace_activity(str(uuid_mod.uuid4()))
        assert logs == []
