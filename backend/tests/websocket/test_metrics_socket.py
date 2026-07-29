# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for WebSocket metrics socket manager."""

import asyncio
import json
from unittest import mock

import pytest

from app.websocket.metrics_socket import (
    _WS_MSG_LIMITS,
    MetricsWebSocketManager,
    _check_ws_message_rate_limit,
    check_server_access,
    connection_users,
    connections,
    has_permission,
    log_streams,
    stream_logs_to_websocket,
    validate_token,
    validate_websocket_token,
)


class TestValidateToken:
    """JWT token validation for WebSocket auth."""

    @pytest.mark.asyncio
    async def test_validate_token_empty(self):
        result = await validate_token("")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_token_none(self):
        result = await validate_token(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_token_invalid_jwt(self):
        result = await validate_token("bad.token.here")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_token_valid_returns_user(self, db_session, test_user):
        from app.api.auth import create_access_token

        token = create_access_token({"sub": test_user.username})
        with mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session:
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=db_session)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            result = await validate_token(token)
        assert result is not None
        assert result.id == test_user.id

    @pytest.mark.asyncio
    async def test_validate_token_user_not_found(self):
        from app.api.auth import create_access_token

        token = create_access_token({"sub": "nonexistent_user_xyz"})
        with mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session:
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute = mock.AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            result = await validate_token(token)
        assert result is None


class TestValidateWebsocketToken:
    """WebSocket query param token validation."""

    @pytest.mark.asyncio
    async def test_validate_websocket_token_from_query(self, db_session, test_user):
        from app.api.auth import create_access_token

        token = create_access_token({"sub": test_user.username})
        ws = mock.Mock()
        ws.query_params = {"token": token}
        with mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session:
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=db_session)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            result = await validate_websocket_token(ws)
        assert result is not None
        assert result.id == test_user.id

    @pytest.mark.asyncio
    async def test_validate_websocket_token_missing(self):
        ws = mock.Mock()
        ws.query_params = {}
        result = await validate_websocket_token(ws)
        assert result is None


class TestHasPermission:
    """Permission checks for WebSocket contexts."""

    def test_has_permission_with_all(self, test_user):
        test_user.role = "super_admin"
        assert has_permission(test_user, "servers:read") is True
        assert has_permission(test_user, "admin:access") is True

    def test_has_permission_without_permission(self, test_user):
        test_user.role = "user"
        assert has_permission(test_user, "admin:access") is False

    def test_has_permission_with_matching_role(self, test_user):
        test_user.role = "admin"
        assert has_permission(test_user, "admin:access") is True


class TestCheckServerAccess:
    """Server access checks for WebSocket contexts."""

    @pytest.mark.asyncio
    async def test_check_server_access_owner(self, db_session, test_user):
        from app.models.server import Server

        server = Server(
            user_id=test_user.id,
            name="ws-test-server",
            status="stopped",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)
        result = await check_server_access(test_user, str(server.id), db_session)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_server_access_admin(self, db_session, admin_user, test_user):
        from app.models.server import Server

        server = Server(
            user_id=test_user.id,
            name="ws-test-server-admin",
            status="stopped",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)
        result = await check_server_access(admin_user, str(server.id), db_session)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_server_access_other_user_denied(self, db_session, test_user):
        from app.models.user import User

        other = User(
            username="other_ws_user", email="other_ws@test.com", password_hash="x", role="user"
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        from app.models.server import Server

        server = Server(
            user_id=other.id,
            name="ws-test-server-other",
            status="stopped",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)
        result = await check_server_access(test_user, str(server.id), db_session)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_server_access_nonexistent(self, db_session, test_user):
        result = await check_server_access(
            test_user, "550e8400-e29b-41d4-a716-446655440000", db_session
        )
        assert result is False


class TestMetricsWebSocketManager:
    """MetricsWebSocketManager unit tests."""

    @pytest.fixture(autouse=True)
    def cleanup_connections(self):
        connections.clear()
        connection_users.clear()
        log_streams.clear()
        yield
        connections.clear()
        connection_users.clear()
        log_streams.clear()

    @pytest.mark.asyncio
    async def test_get_redis_creates_client(self):
        manager = MetricsWebSocketManager()
        with mock.patch("app.websocket.metrics_socket.redis.from_url") as mock_redis:
            mock_client = mock.Mock()
            mock_redis.return_value = mock_client
            client = await manager.get_redis()
            assert client is mock_client
            mock_redis.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_redis_reuses_client(self):
        manager = MetricsWebSocketManager()
        mock_client = mock.Mock()
        manager.redis_client = mock_client
        result = await manager.get_redis()
        assert result is mock_client

    @pytest.mark.asyncio
    async def test_stop_redis_listener(self):
        manager = MetricsWebSocketManager()
        manager._running = True
        await manager.stop_redis_listener()
        assert manager._running is False

    @pytest.mark.asyncio
    async def test_start_redis_listener_already_running(self):
        manager = MetricsWebSocketManager()
        manager._running = True
        await manager.start_redis_listener()

    @pytest.mark.asyncio
    async def test_broadcast_metric_to_server_room(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["server:abc"] = {ws}
        await manager._broadcast_metric({"server_id": "abc", "cpu": 50})
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["event"] == "metrics:server"

    @pytest.mark.asyncio
    async def test_broadcast_metric_to_global(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["global"] = {ws}
        await manager._broadcast_metric({"server_id": "abc", "cpu": 50})
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["event"] == "metrics:all"

    @pytest.mark.asyncio
    async def test_broadcast_metric_disconnects_failed_ws(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.send_json.side_effect = Exception("conn closed")
        connections["global"] = {ws}
        await manager._broadcast_metric({"server_id": "abc", "cpu": 50})
        assert "global" not in connections

    @pytest.mark.asyncio
    async def test_broadcast_user_event(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["user:123"] = {ws}
        await manager._broadcast_user_event({"user_id": "123", "event": "test", "data": {"x": 1}})
        ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_user_event_no_user_id(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["user:123"] = {ws}
        await manager._broadcast_user_event({"event": "test"})
        ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_system_metric(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["global"] = {ws}
        await manager._broadcast_system_metric({"cpu": 10})
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["event"] == "metrics:system"

    @pytest.mark.asyncio
    async def test_authenticate_with_query_token(self, test_user):
        from app.api.auth import create_access_token

        manager = MetricsWebSocketManager()
        token = create_access_token({"sub": test_user.username})
        ws = mock.Mock()
        ws.query_params = {"token": token}
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            result = await manager._authenticate(ws)
        assert result is test_user

    @pytest.mark.asyncio
    async def test_authenticate_with_auth_message(self, test_user):
        from app.api.auth import create_access_token

        manager = MetricsWebSocketManager()
        token = create_access_token({"sub": test_user.username})
        ws = mock.AsyncMock()
        ws.query_params = {}
        ws.receive_text = mock.AsyncMock(return_value=json.dumps({"type": "auth", "token": token}))
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            result = await manager._authenticate(ws)
        assert result is test_user

    @pytest.mark.asyncio
    async def test_authenticate_timeout(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {}
        ws.receive_text = mock.AsyncMock(side_effect=TimeoutError())
        result = await manager._authenticate(ws)
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_invalid_json(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {}
        ws.receive_text = mock.AsyncMock(return_value="not json")
        result = await manager._authenticate(ws)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_connection_auth_failure(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {}
        ws.receive_text = mock.AsyncMock(side_effect=TimeoutError())
        await manager.handle_connection(ws)
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["event"] == "auth:error"
        ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_connection_auth_success(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "global"}),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)
        auth_success_sent = any(
            call.args[0].get("event") == "auth:success" for call in ws.send_json.call_args_list
        )
        assert auth_success_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_global_admin(self, admin_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "global"}),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=admin_user,
        ):
            await manager.handle_connection(ws)
        sub_sent = any(
            call.args[0].get("event") == "subscribed" for call in ws.send_json.call_args_list
        )
        assert sub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_global_denied_for_user(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "global"}),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)
        error_sent = any(
            call.args[0].get("event") == "error"
            and "Admin access" in call.args[0].get("message", "")
            for call in ws.send_json.call_args_list
        )
        assert error_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_user_own_channel(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "user", "target_id": str(test_user.id)}),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)
        sub_sent = any(
            call.args[0].get("event") == "subscribed" for call in ws.send_json.call_args_list
        )
        assert sub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_unsubscribe(self, admin_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "global"}),
                json.dumps({"type": "unsubscribe", "scope": "global"}),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=admin_user,
        ):
            await manager.handle_connection(ws)
        unsub_sent = any(
            call.args[0].get("event") == "unsubscribed" for call in ws.send_json.call_args_list
        )
        assert unsub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_invalid_json(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(side_effect=["bad json", Exception("disconnect")])
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)
        error_sent = any(
            call.args[0].get("event") == "error"
            and "Invalid JSON" in call.args[0].get("message", "")
            for call in ws.send_json.call_args_list
        )
        assert error_sent

    @pytest.mark.asyncio
    async def test_handle_connection_unknown_scope(self, admin_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "invalid_scope"}),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=admin_user,
        ):
            await manager.handle_connection(ws)
        error_sent = any(
            call.args[0].get("event") == "error"
            and "Unknown scope" in call.args[0].get("message", "")
            for call in ws.send_json.call_args_list
        )
        assert error_sent

    @pytest.mark.asyncio
    async def test_handle_connection_cleanup_on_disconnect(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "user", "target_id": str(test_user.id)}),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)
        for room in list(connections.values()):
            assert ws not in room
        assert ws not in connection_users


class TestStreamLogsToWebsocket:
    """Tests for stream_logs_to_websocket."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        connections.clear()
        connection_users.clear()
        log_streams.clear()
        yield
        connections.clear()
        connection_users.clear()
        log_streams.clear()

    @pytest.mark.asyncio
    async def test_stream_logs_success(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        connections["logs:srv-1"] = {ws}

        async def async_iter():
            yield "line1"
            yield "line2"

        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value=async_iter())
        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1", tail=50)

        assert ws.send_json.call_count >= 1

    @pytest.mark.asyncio
    async def test_stream_logs_disconnects_when_not_in_connections(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        # Not in connections

        async def async_iter():
            yield "line1"

        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value=async_iter())
        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1", tail=50)

    @pytest.mark.asyncio
    async def test_stream_logs_error_handling(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        connections["logs:srv-1"] = {ws}

        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(side_effect=Exception("container gone"))

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1", tail=50)


class TestHandleConnectionExtended:
    """Additional handle_connection tests for uncovered branches."""

    @pytest.fixture(autouse=True)
    def cleanup_connections(self):
        connections.clear()
        connection_users.clear()
        log_streams.clear()
        yield
        connections.clear()
        connection_users.clear()
        log_streams.clear()

    @pytest.mark.asyncio
    async def test_handle_connection_rate_limited(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "global"}),
                Exception("disconnect"),
            ]
        )
        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", True),
        ):
            with mock.patch("app.websocket.metrics_socket.redis.from_url") as mock_redis_cls:
                mock_redis = mock.AsyncMock()
                mock_redis.script_load = mock.AsyncMock(return_value="sha1")
                mock_redis.evalsha = mock.AsyncMock(return_value=999999)  # over limit
                mock_redis_cls.return_value = mock_redis
                await manager.handle_connection(ws)

        rate_limited_sent = any(
            call.args[0].get("event") == "rate_limited" for call in ws.send_json.call_args_list
        )
        assert rate_limited_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_server_allowed(self, test_user):
        from app.models.server import Server

        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        Server(user_id=test_user.id, name="srv", status="stopped")
        # Need to mock the db session since we're not using db_session fixture directly here
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps(
                    {
                        "type": "subscribe",
                        "scope": "server",
                        "target_id": "550e8400-e29b-41d4-a716-446655440000",
                    }
                ),
                Exception("disconnect"),
            ]
        )
        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session,
        ):
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_server = mock.Mock()
            mock_server.user_id = test_user.id
            mock_result.scalar_one_or_none.return_value = mock_server
            mock_db.execute = mock.AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            await manager.handle_connection(ws)

        sub_sent = any(
            call.args[0].get("event") == "subscribed" and call.args[0].get("scope") == "server"
            for call in ws.send_json.call_args_list
        )
        assert sub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_server_denied(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps(
                    {
                        "type": "subscribe",
                        "scope": "server",
                        "target_id": "550e8400-e29b-41d4-a716-446655440000",
                    }
                ),
                Exception("disconnect"),
            ]
        )
        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session,
        ):
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_server = mock.Mock()
            mock_server.user_id = "other-user-id"
            mock_result.scalar_one_or_none.return_value = mock_server
            mock_db.execute = mock.AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            await manager.handle_connection(ws)

        error_sent = any(
            call.args[0].get("event") == "error"
            and "Access denied" in call.args[0].get("message", "")
            for call in ws.send_json.call_args_list
        )
        assert error_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_logs_success(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps(
                    {
                        "type": "subscribe_logs",
                        "server_id": "550e8400-e29b-41d4-a716-446655440000",
                        "tail": 50,
                    }
                ),
                Exception("disconnect"),
            ]
        )
        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session,
        ):
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_server = mock.Mock()
            mock_server.user_id = test_user.id
            mock_server.container_id = "cid-123"
            mock_result.scalar_one_or_none.return_value = mock_server
            mock_db.execute = mock.AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            await manager.handle_connection(ws)

        sub_sent = any(
            call.args[0].get("event") == "logs:subscribed" for call in ws.send_json.call_args_list
        )
        assert sub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_logs_no_server_id(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[json.dumps({"type": "subscribe_logs"}), Exception("disconnect")]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        error_sent = any(
            call.args[0].get("event") == "error"
            and "server_id is required" in call.args[0].get("message", "")
            for call in ws.send_json.call_args_list
        )
        assert error_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_logs_no_container(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps(
                    {"type": "subscribe_logs", "server_id": "550e8400-e29b-41d4-a716-446655440000"}
                ),
                Exception("disconnect"),
            ]
        )
        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session,
        ):
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_server = mock.Mock()
            mock_server.user_id = test_user.id
            mock_server.container_id = None
            mock_result.scalar_one_or_none.return_value = mock_server
            mock_db.execute = mock.AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            await manager.handle_connection(ws)

        error_sent = any(
            call.args[0].get("event") == "error"
            and "no container" in call.args[0].get("message", "").lower()
            for call in ws.send_json.call_args_list
        )
        assert error_sent

    @pytest.mark.asyncio
    async def test_handle_connection_unsubscribe_logs(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "unsubscribe_logs", "server_id": "srv-1"}),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        unsub_sent = any(
            call.args[0].get("event") == "logs:unsubscribed" for call in ws.send_json.call_args_list
        )
        assert unsub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_user_admin_can_access_other(
        self, admin_user, test_user
    ):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "user", "target_id": str(test_user.id)}),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=admin_user,
        ):
            await manager.handle_connection(ws)

        sub_sent = any(
            call.args[0].get("event") == "subscribed" and call.args[0].get("scope") == "user"
            for call in ws.send_json.call_args_list
        )
        assert sub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_auth_failure_send_error_exception(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {}
        ws.receive_text = mock.AsyncMock(side_effect=TimeoutError())
        ws.send_json = mock.AsyncMock(side_effect=Exception("send failed"))
        ws.close = mock.AsyncMock(side_effect=Exception("close failed"))
        await manager.handle_connection(ws)


class TestCheckWsMessageRateLimit:
    """WebSocket message rate limiter tests."""

    @pytest.mark.asyncio
    async def test_rate_limit_disabled(self):
        with mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", False):
            result = await _check_ws_message_rate_limit(mock.Mock(), "u1", "user")
            assert result == (False, 0, 0)

    @pytest.mark.asyncio
    async def test_rate_limit_allows_under_limit(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=1)
        with mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", True):
            with mock.patch("app.websocket.metrics_socket.settings.rate_limit_window_seconds", 60):
                result = await _check_ws_message_rate_limit(mock_redis, "u1", "user")
                assert result[0] is False
                assert result[2] > 0

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_over_limit(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=999999)
        with mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", True):
            with mock.patch("app.websocket.metrics_socket.settings.rate_limit_window_seconds", 60):
                result = await _check_ws_message_rate_limit(mock_redis, "u1", "user")
                assert result[0] is True
                assert result[2] == 0

    @pytest.mark.asyncio
    async def test_rate_limit_redis_error_fail_open(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(side_effect=Exception("redis down"))
        with mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", True):
            result = await _check_ws_message_rate_limit(mock_redis, "u1", "user")
            assert result == (False, 0, 0)

    def test_ws_msg_limits_has_common_roles(self):
        assert "guest" in _WS_MSG_LIMITS
        assert "user" in _WS_MSG_LIMITS
        assert "admin" in _WS_MSG_LIMITS
        assert "super_admin" in _WS_MSG_LIMITS


"""Extended coverage tests for metrics_socket uncovered branches."""

import contextlib

import pytest


class TestStreamLogsEdgeCases:
    """Tests for stream_logs_to_websocket uncovered branches."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        connections.clear()
        connection_users.clear()
        log_streams.clear()
        yield
        connections.clear()
        connection_users.clear()
        log_streams.clear()

    @pytest.mark.asyncio
    async def test_stream_logs_break_when_not_in_connection_users(self):
        ws = mock.AsyncMock()
        # Not in connection_users
        connections["logs:srv-1"] = {ws}

        async def async_iter():
            yield "line1"
            yield "line2"

        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value=async_iter())
        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1", tail=50)

    @pytest.mark.asyncio
    async def test_stream_logs_break_when_not_in_room(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        # Room doesn't exist or ws not in it

        async def async_iter():
            yield "line1"

        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value=async_iter())
        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1", tail=50)

    @pytest.mark.asyncio
    async def test_stream_logs_send_exception_breaks(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        connections["logs:srv-1"] = {ws}

        async def async_iter():
            yield "line1"

        ws.send_json = mock.AsyncMock(side_effect=Exception("conn closed"))

        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value=async_iter())
        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1", tail=50)

    @pytest.mark.asyncio
    async def test_stream_logs_cleanup_removes_task(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        connections["logs:srv-1"] = {ws}
        task_key = f"{id(ws)}:srv-1"
        log_streams[task_key] = mock.Mock()

        async def async_iter():
            yield "line1"

        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value=async_iter())
        mock_client = mock.AsyncMock()
        mock_client.client.containers.get = mock.AsyncMock(return_value=mock_container)

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1", tail=50)

        assert task_key not in log_streams


class TestMetricsWebSocketManagerRedisListener:
    """Tests for start_redis_listener branches."""

    @pytest.mark.asyncio
    async def test_redis_listener_system_metric(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["global"] = {ws}

        async def mock_listen(*args, **kwargs):
            yield {
                "type": "message",
                "data": json.dumps({"cpu": 10}),
                "channel": "metrics:system",
            }

        with mock.patch("app.websocket.metrics_socket.redis.from_url") as mock_redis_cls:
            # redis_client.pubsub() is sync; use regular Mock for redis_client
            mock_pubsub = mock.Mock()
            mock_pubsub.subscribe = mock.AsyncMock()
            mock_pubsub.psubscribe = mock.AsyncMock()
            mock_pubsub.listen = mock_listen
            mock_redis = mock.Mock()
            mock_redis.pubsub.return_value = mock_pubsub
            mock_redis_cls.return_value = mock_redis

            # Run briefly then stop
            task = asyncio.create_task(manager.start_redis_listener())
            await asyncio.sleep(0.1)
            manager._running = False
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_listener_event_payload_on_system_channel(self):
        """Payloads carrying their own event name (e.g. health:system) must be
        forwarded as that event, not re-wrapped as metrics:system (which would
        zero every metric field on the frontend)."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["global"] = {ws}

        async def mock_listen(*args, **kwargs):
            yield {
                "type": "message",
                "data": json.dumps(
                    {"event": "health:system", "data": {"refreshed_at": "2026-01-01T00:00:00"}}
                ),
                "channel": "metrics:system",
            }

        with mock.patch("app.websocket.metrics_socket.redis.from_url") as mock_redis_cls:
            mock_pubsub = mock.Mock()
            mock_pubsub.subscribe = mock.AsyncMock()
            mock_pubsub.psubscribe = mock.AsyncMock()
            mock_pubsub.listen = mock_listen
            mock_redis = mock.Mock()
            mock_redis.pubsub.return_value = mock_pubsub
            mock_redis_cls.return_value = mock_redis

            task = asyncio.create_task(manager.start_redis_listener())
            await asyncio.sleep(0.1)
            manager._running = False
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        ws.send_json.assert_called_once_with(
            {"event": "health:system", "data": {"refreshed_at": "2026-01-01T00:00:00"}}
        )

    @pytest.mark.asyncio
    async def test_redis_listener_pmessage(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["server:abc"] = {ws}

        async def mock_listen(*args, **kwargs):
            yield {
                "type": "pmessage",
                "data": json.dumps({"server_id": "abc", "cpu": 50}),
                "channel": "metrics:server:abc",
            }

        with mock.patch("app.websocket.metrics_socket.redis.from_url") as mock_redis_cls:
            mock_pubsub = mock.Mock()
            mock_pubsub.subscribe = mock.AsyncMock()
            mock_pubsub.psubscribe = mock.AsyncMock()
            mock_pubsub.listen = mock_listen
            mock_redis = mock.Mock()
            mock_redis.pubsub.return_value = mock_pubsub
            mock_redis_cls.return_value = mock_redis

            task = asyncio.create_task(manager.start_redis_listener())
            await asyncio.sleep(0.1)
            manager._running = False
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_listener_user_event(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["user:123"] = {ws}

        async def mock_listen(*args, **kwargs):
            yield {
                "type": "message",
                "data": json.dumps({"user_id": "123", "event": "test", "data": {}}),
                "channel": "user:123",
            }

        with mock.patch("app.websocket.metrics_socket.redis.from_url") as mock_redis_cls:
            mock_pubsub = mock.Mock()
            mock_pubsub.subscribe = mock.AsyncMock()
            mock_pubsub.psubscribe = mock.AsyncMock()
            mock_pubsub.listen = mock_listen
            mock_redis = mock.Mock()
            mock_redis.pubsub.return_value = mock_pubsub
            mock_redis_cls.return_value = mock_redis

            task = asyncio.create_task(manager.start_redis_listener())
            await asyncio.sleep(0.1)
            manager._running = False
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_listener_cancelled(self):
        manager = MetricsWebSocketManager()

        async def mock_listen(*args, **kwargs):
            yield {"type": "message", "data": "{}", "channel": "x"}
            await asyncio.sleep(10)

        with mock.patch("app.websocket.metrics_socket.redis.from_url") as mock_redis_cls:
            mock_pubsub = mock.Mock()
            mock_pubsub.subscribe = mock.AsyncMock()
            mock_pubsub.psubscribe = mock.AsyncMock()
            mock_pubsub.listen = mock_listen
            mock_redis = mock.Mock()
            mock_redis.pubsub.return_value = mock_pubsub
            mock_redis_cls.return_value = mock_redis

            task = asyncio.create_task(manager.start_redis_listener())
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


class TestBroadcastMetricEdgeCases:
    """Tests for _broadcast_metric edge cases."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        connections.clear()
        yield
        connections.clear()

    @pytest.mark.asyncio
    async def test_broadcast_metric_no_server_id(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["global"] = {ws}
        await manager._broadcast_metric({"cpu": 10})  # no server_id
        ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_metric_global_disconnect(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.send_json.side_effect = Exception("closed")
        connections["global"] = {ws}
        await manager._broadcast_metric({"cpu": 10})
        assert "global" not in connections


class TestBroadcastUserEventEdgeCases:
    """Tests for _broadcast_user_event edge cases."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        connections.clear()
        yield
        connections.clear()

    @pytest.mark.asyncio
    async def test_broadcast_user_event_disconnect(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.send_json.side_effect = Exception("closed")
        connections["user:123"] = {ws}
        await manager._broadcast_user_event({"user_id": "123", "event": "test", "data": {}})
        assert "user:123" not in connections


class TestBroadcastSystemMetricEdgeCases:
    """Tests for _broadcast_system_metric edge cases."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        connections.clear()
        yield
        connections.clear()

    @pytest.mark.asyncio
    async def test_broadcast_system_metric_disconnect(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.send_json.side_effect = Exception("closed")
        connections["global"] = {ws}
        await manager._broadcast_system_metric({"cpu": 10})
        assert "global" not in connections


class TestHandleConnectionExtended2:
    """Additional handle_connection tests."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        connections.clear()
        connection_users.clear()
        log_streams.clear()
        yield
        connections.clear()
        connection_users.clear()
        log_streams.clear()

    @pytest.mark.asyncio
    async def test_handle_connection_auth_close_exception(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {}
        ws.receive_text = mock.AsyncMock(side_effect=TimeoutError())
        ws.send_json = mock.AsyncMock(side_effect=Exception("send failed"))
        ws.close = mock.AsyncMock(side_effect=Exception("close failed"))
        await manager.handle_connection(ws)

    @pytest.mark.asyncio
    async def test_handle_connection_rate_limit_redis_init_error(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "user", "target_id": str(test_user.id)}),
                Exception("disconnect"),
            ]
        )
        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", True),
            mock.patch(
                "app.websocket.metrics_socket.redis.from_url",
                side_effect=Exception("redis down"),
            ),
        ):
            await manager.handle_connection(ws)

        # Should still subscribe since rate limiter fails open
        sub_sent = any(
            call.args[0].get("event") == "subscribed" for call in ws.send_json.call_args_list
        )
        assert sub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_server_admin(self, admin_user):
        """Admin subscribing to a server they don't own."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps(
                    {
                        "type": "subscribe",
                        "scope": "server",
                        "target_id": "550e8400-e29b-41d4-a716-446655440000",
                    }
                ),
                Exception("disconnect"),
            ]
        )
        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=admin_user,
            ),
            mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session,
        ):
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_server = mock.Mock()
            mock_server.user_id = "other-user-id"
            mock_result.scalar_one_or_none.return_value = mock_server
            mock_db.execute = mock.AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            await manager.handle_connection(ws)

        # Admin has SERVERS_READ_ALL so should be allowed
        sub_sent = any(
            call.args[0].get("event") == "subscribed" and call.args[0].get("scope") == "server"
            for call in ws.send_json.call_args_list
        )
        assert sub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_subscribe_logs_access_denied(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps(
                    {"type": "subscribe_logs", "server_id": "550e8400-e29b-41d4-a716-446655440000"}
                ),
                Exception("disconnect"),
            ]
        )
        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session,
        ):
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_server = mock.Mock()
            mock_server.user_id = "other-user-id"
            mock_server.container_id = "cid-123"
            mock_result.scalar_one_or_none.return_value = mock_server
            mock_db.execute = mock.AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            await manager.handle_connection(ws)

        error_sent = any(
            call.args[0].get("event") == "error"
            and "Access denied" in call.args[0].get("message", "")
            for call in ws.send_json.call_args_list
        )
        assert error_sent

    @pytest.mark.asyncio
    async def test_handle_connection_unsubscribe_server(self, admin_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "server", "target_id": "abc"}),
                json.dumps({"type": "unsubscribe", "scope": "server", "target_id": "abc"}),
                Exception("disconnect"),
            ]
        )
        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=admin_user,
            ),
            mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session,
        ):
            mock_db = mock.AsyncMock()
            mock_result = mock.Mock()
            mock_server = mock.Mock()
            mock_server.user_id = admin_user.id
            mock_result.scalar_one_or_none.return_value = mock_server
            mock_db.execute = mock.AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            await manager.handle_connection(ws)

        unsub_sent = any(
            call.args[0].get("event") == "unsubscribed" and call.args[0].get("scope") == "server"
            for call in ws.send_json.call_args_list
        )
        assert unsub_sent

    @pytest.mark.asyncio
    async def test_handle_connection_unsubscribe_user(self, admin_user, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe", "scope": "user", "target_id": str(test_user.id)}),
                json.dumps(
                    {"type": "unsubscribe", "scope": "user", "target_id": str(test_user.id)}
                ),
                Exception("disconnect"),
            ]
        )
        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=admin_user,
        ):
            await manager.handle_connection(ws)

        unsub_sent = any(
            call.args[0].get("event") == "unsubscribed" and call.args[0].get("scope") == "user"
            for call in ws.send_json.call_args_list
        )
        assert unsub_sent


class TestCloseAllConnections:
    """Graceful shutdown WebSocket drain tests."""

    @pytest.fixture(autouse=True)
    def clear_connections(self):
        connections.clear()
        connection_users.clear()
        log_streams.clear()
        yield
        connections.clear()
        connection_users.clear()
        log_streams.clear()

    @pytest.mark.asyncio
    async def test_close_all_connections_closes_every_ws(self):
        manager = MetricsWebSocketManager()
        ws1 = mock.AsyncMock()
        ws2 = mock.AsyncMock()
        connections["global"] = {ws1, ws2}
        connection_users[ws1] = {"user_id": "1"}
        connection_users[ws2] = {"user_id": "2"}

        await manager.close_all_connections()

        ws1.close.assert_awaited_once_with(code=1001, reason="Server shutting down")
        ws2.close.assert_awaited_once_with(code=1001, reason="Server shutting down")
        assert len(connections) == 0
        assert len(connection_users) == 0

    @pytest.mark.asyncio
    async def test_close_all_connections_gracefully_handles_errors(self):
        manager = MetricsWebSocketManager()
        ws1 = mock.AsyncMock()
        ws1.close.side_effect = Exception("broken")
        ws2 = mock.AsyncMock()
        connections["global"] = {ws1, ws2}
        connection_users[ws1] = {"user_id": "1"}
        connection_users[ws2] = {"user_id": "2"}

        # Should not raise
        await manager.close_all_connections()

        ws1.close.assert_awaited_once()
        ws2.close.assert_awaited_once()
        assert len(connections) == 0

    @pytest.mark.asyncio
    async def test_close_all_clears_log_streams(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["logs:server1"] = {ws}
        log_streams["123:server1"] = mock.Mock()

        await manager.close_all_connections()

        assert len(log_streams) == 0

    @pytest.mark.asyncio
    async def test_stop_redis_listener_closes_client(self):
        manager = MetricsWebSocketManager()
        redis_mock = mock.AsyncMock()
        manager.redis_client = redis_mock
        manager._running = True

        await manager.stop_redis_listener()

        assert manager._running is False
        redis_mock.close.assert_awaited_once()
        assert manager.redis_client is None

    @pytest.mark.asyncio
    async def test_stop_redis_listener_no_client(self):
        manager = MetricsWebSocketManager()
        manager.redis_client = None
        manager._running = True

        # Should not raise
        await manager.stop_redis_listener()
        assert manager._running is False
