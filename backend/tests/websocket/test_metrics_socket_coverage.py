# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage-focused tests for metrics_socket uncovered branches."""

import asyncio
import json
from unittest import mock

import pytest
from fastapi import WebSocketDisconnect

from app.websocket.metrics_socket import (
    MetricsWebSocketManager,
    _check_ws_message_rate_limit,
    check_server_access,
    connection_users,
    connections,
    has_permission,
    log_streams,
    stream_logs_to_websocket,
    validate_token,
)


@pytest.fixture(autouse=True)
def cleanup_state():
    connections.clear()
    connection_users.clear()
    log_streams.clear()
    yield
    connections.clear()
    connection_users.clear()
    log_streams.clear()


class TestValidateTokenBranches:
    """Uncovered branches in validate_token."""

    @pytest.mark.asyncio
    async def test_validate_token_payload_without_sub(self):
        with mock.patch(
            "app.websocket.metrics_socket.token_signing.verify_access_token",
            new_callable=mock.AsyncMock,
            return_value={"exp": 123},
        ):
            result = await validate_token("any-token")
        assert result is None


class TestCheckServerAccessWriteAll:
    """check_server_access via the SERVERS_WRITE_ALL permission path."""

    @pytest.mark.asyncio
    async def test_write_all_permission_grants_access(self, test_user):
        test_user.role = "moderator"  # moderator has servers:write_all
        assert has_permission(test_user, "servers:write_all") is True
        db = mock.AsyncMock()
        result = await check_server_access(test_user, "any-server-id", db)
        assert result is True
        db.execute.assert_not_called()


class TestStreamLogsCoverage:
    """stream_logs_to_websocket loop body and error path."""

    @pytest.mark.asyncio
    async def test_stream_logs_sends_data_lines(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        connections["logs:srv-1"] = {ws}

        async def log_iter():
            yield "line1"
            yield "line2"

        mock_client = mock.AsyncMock()
        mock_client.stream_container_logs = mock.AsyncMock(return_value=log_iter())

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1", tail=25)

        events = [call.args[0].get("event") for call in ws.send_json.call_args_list]
        assert "logs:started" in events
        assert events.count("logs:data") == 2
        mock_client.stream_container_logs.assert_awaited_once_with("cid-1", tail=25)
        # Cleanup: room emptied and removed
        assert "logs:srv-1" not in connections

    @pytest.mark.asyncio
    async def test_stream_logs_breaks_when_removed_from_connection_users(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        connections["logs:srv-1"] = {ws}

        async def log_iter():
            connection_users.pop(ws, None)  # vanish before first line is processed
            yield "line1"
            yield "line2"

        mock_client = mock.AsyncMock()
        mock_client.stream_container_logs = mock.AsyncMock(return_value=log_iter())

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1")

        events = [call.args[0].get("event") for call in ws.send_json.call_args_list]
        assert "logs:data" not in events

    @pytest.mark.asyncio
    async def test_stream_logs_breaks_when_not_in_room(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        # ws is authenticated but not a member of the logs room

        async def log_iter():
            yield "line1"

        mock_client = mock.AsyncMock()
        mock_client.stream_container_logs = mock.AsyncMock(return_value=log_iter())

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1")

        events = [call.args[0].get("event") for call in ws.send_json.call_args_list]
        assert "logs:data" not in events

    @pytest.mark.asyncio
    async def test_stream_logs_send_failure_breaks_loop(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        connections["logs:srv-1"] = {ws}

        async def log_iter():
            yield "line1"
            yield "line2"

        mock_client = mock.AsyncMock()
        mock_client.stream_container_logs = mock.AsyncMock(return_value=log_iter())

        original_send = ws.send_json

        async def flaky_send(payload):
            if payload.get("event") == "logs:data":
                raise ConnectionError("socket closed")
            await original_send(payload)

        ws.send_json = flaky_send

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1")

    @pytest.mark.asyncio
    async def test_stream_logs_client_error_sends_error_event(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        connections["logs:srv-1"] = {ws}

        mock_client = mock.AsyncMock()
        mock_client.stream_container_logs = mock.AsyncMock(
            side_effect=RuntimeError("container gone")
        )

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            await stream_logs_to_websocket(ws, "srv-1", "cid-1")

        error_calls = [
            call.args[0]
            for call in ws.send_json.call_args_list
            if call.args[0].get("event") == "logs:error"
        ]
        assert len(error_calls) == 1
        assert "container gone" in error_calls[0]["error"]
        assert "logs:srv-1" not in connections

    @pytest.mark.asyncio
    async def test_stream_logs_error_send_failure_suppressed(self):
        ws = mock.AsyncMock()
        connection_users[ws] = {"user_id": "u1"}
        connections["logs:srv-1"] = {ws}
        ws.send_json = mock.AsyncMock(side_effect=Exception("send dead"))

        mock_client = mock.AsyncMock()
        mock_client.stream_container_logs = mock.AsyncMock(side_effect=RuntimeError("boom"))

        with mock.patch(
            "app.container.client.get_container_client",
            new_callable=mock.AsyncMock,
            return_value=mock_client,
        ):
            # Must not raise even though both the stream and the error send fail
            await stream_logs_to_websocket(ws, "srv-1", "cid-1")

        assert "logs:srv-1" not in connections


class TestStartRedisListenerBranches:
    """start_redis_listener channel dispatch and error branches."""

    def _make_pubsub(self, messages):
        async def _listen():
            for message in messages:
                yield message
            # Keep the listener alive until cancelled/stopped
            await asyncio.sleep(10)

        pubsub = mock.Mock()
        pubsub.subscribe = mock.AsyncMock()
        pubsub.psubscribe = mock.AsyncMock()
        pubsub.listen = _listen
        return pubsub

    async def _run_listener(self, manager, pubsub):
        mock_redis = mock.Mock()
        mock_redis.pubsub.return_value = pubsub
        manager.redis_client = mock_redis
        task = asyncio.create_task(manager.start_redis_listener())
        await asyncio.sleep(0.1)
        manager._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_listener_decodes_bytes_channel_for_user_event(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["user:42"] = {ws}

        pubsub = self._make_pubsub(
            [
                {
                    "type": "pmessage",
                    "data": json.dumps({"user_id": "42", "event": "ping", "data": {}}),
                    "channel": b"user:42",
                }
            ]
        )
        await self._run_listener(manager, pubsub)

        ws.send_json.assert_called_once()
        assert ws.send_json.call_args[0][0]["event"] == "ping"

    @pytest.mark.asyncio
    async def test_listener_bytes_channel_system_metric(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["global"] = {ws}

        pubsub = self._make_pubsub(
            [
                {
                    "type": "message",
                    "data": json.dumps({"cpu": 5}),
                    "channel": b"metrics:system",
                }
            ]
        )
        await self._run_listener(manager, pubsub)

        ws.send_json.assert_called_once()
        assert ws.send_json.call_args[0][0]["event"] == "metrics:system"

    @pytest.mark.asyncio
    async def test_listener_missing_channel_defaults_to_metric_broadcast(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["server:abc"] = {ws}

        pubsub = self._make_pubsub(
            [{"type": "message", "data": json.dumps({"server_id": "abc"})}]
        )
        await self._run_listener(manager, pubsub)

        ws.send_json.assert_called_once()
        assert ws.send_json.call_args[0][0]["event"] == "metrics:server"

    @pytest.mark.asyncio
    async def test_listener_ignores_non_message_types(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["global"] = {ws}

        pubsub = self._make_pubsub(
            [{"type": "subscribe", "data": 1, "channel": "metrics:system"}]
        )
        await self._run_listener(manager, pubsub)

        ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_listener_swallows_bad_json(self):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        connections["global"] = {ws}

        pubsub = self._make_pubsub(
            [
                {"type": "message", "data": "not-json{", "channel": "metrics:system"},
                {
                    "type": "message",
                    "data": json.dumps({"cpu": 1}),
                    "channel": "metrics:system",
                },
            ]
        )
        await self._run_listener(manager, pubsub)

        # Bad message skipped, good message still delivered
        ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_listener_swallows_subscribe_errors(self):
        manager = MetricsWebSocketManager()
        mock_redis = mock.Mock()
        pubsub = mock.Mock()
        pubsub.subscribe = mock.AsyncMock(side_effect=ConnectionError("redis down"))
        mock_redis.pubsub.return_value = pubsub
        manager.redis_client = mock_redis

        # Must return without raising
        await manager.start_redis_listener()
        assert manager._running is True


class TestCloseAllConnectionsCoverage:
    """close_all_connections early-return and timeout branches."""

    @pytest.mark.asyncio
    async def test_close_all_with_no_connections(self):
        manager = MetricsWebSocketManager()
        connections["global"] = set()
        log_streams["k"] = mock.Mock()

        await manager.close_all_connections()

        assert manager._shutting_down is True
        assert len(connections) == 0
        assert len(log_streams) == 0

    @pytest.mark.asyncio
    async def test_close_all_cancels_pending_close_tasks(self):
        manager = MetricsWebSocketManager()

        hanging_ws = mock.AsyncMock()
        hang_started = asyncio.Event()

        async def hanging_close(*args, **kwargs):
            hang_started.set()
            await asyncio.sleep(60)

        hanging_ws.close = hanging_close
        fast_ws = mock.AsyncMock()
        connections["global"] = {hanging_ws, fast_ws}
        connection_users[hanging_ws] = {"user_id": "1"}
        connection_users[fast_ws] = {"user_id": "2"}

        await manager.close_all_connections(timeout=0.1)

        assert hang_started.is_set()
        fast_ws.close.assert_awaited_once()
        assert len(connections) == 0
        assert len(connection_users) == 0


class TestHandleConnectionShutdownBranches:
    """handle_connection shutdown-rejection and mid-loop shutdown."""

    @pytest.mark.asyncio
    async def test_rejects_connection_when_shutting_down(self, test_user):
        manager = MetricsWebSocketManager()
        manager._shutting_down = True
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        events = [call.args[0].get("event") for call in ws.send_json.call_args_list]
        assert "error" in events
        assert "auth:success" not in events
        ws.close.assert_awaited_once_with(code=1001, reason="Server shutting down")
        assert ws not in connection_users

    @pytest.mark.asyncio
    async def test_shutdown_rejection_send_failure_suppressed(self, test_user):
        manager = MetricsWebSocketManager()
        manager._shutting_down = True
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.send_json = mock.AsyncMock(side_effect=Exception("dead"))
        ws.close = mock.AsyncMock(side_effect=Exception("dead"))

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            # Must not raise
            await manager.handle_connection(ws)

    @pytest.mark.asyncio
    async def test_loop_breaks_when_shutdown_starts(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}

        async def send_and_shutdown(payload):
            if payload.get("event") == "auth:success":
                manager._shutting_down = True

        ws.send_json = mock.AsyncMock(side_effect=send_and_shutdown)

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        # Loop exited via the shutdown break without calling receive_text again
        ws.receive_text.assert_not_called()
        assert ws not in connection_users


class TestHandleConnectionLogTaskCleanup:
    """Finally-block cancellation of active log stream tasks."""

    @pytest.mark.asyncio
    async def test_disconnect_cancels_active_log_stream_task(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                json.dumps({"type": "subscribe_logs", "server_id": "srv-9"}),
                WebSocketDisconnect(),
            ]
        )

        stream_started = asyncio.Event()
        stream_cancelled = asyncio.Event()

        async def yielding_send(payload):
            # Let the event loop run the freshly created stream task
            await asyncio.sleep(0)

        ws.send_json = yielding_send

        async def fake_stream(websocket, server_id, container_id, tail=100):
            stream_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                stream_cancelled.set()
                raise

        mock_db = mock.AsyncMock()
        mock_result = mock.Mock()
        mock_server = mock.Mock()
        mock_server.user_id = test_user.id
        mock_server.container_id = "cid-9"
        mock_result.scalar_one_or_none.return_value = mock_server
        mock_db.execute = mock.AsyncMock(return_value=mock_result)

        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session,
            mock.patch(
                "app.websocket.metrics_socket.stream_logs_to_websocket", side_effect=fake_stream
            ),
        ):
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            await manager.handle_connection(ws)

        assert stream_started.is_set()
        assert stream_cancelled.is_set()
        assert ws not in connection_users

    @pytest.mark.asyncio
    async def test_subscribe_logs_replaces_existing_stream_task(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        subscribe_msg = json.dumps({"type": "subscribe_logs", "server_id": "srv-9"})
        ws.receive_text = mock.AsyncMock(
            side_effect=[subscribe_msg, subscribe_msg, WebSocketDisconnect()]
        )

        started = []
        cancelled = []

        async def yielding_send(payload):
            # Let the event loop run the freshly created stream tasks
            await asyncio.sleep(0)

        ws.send_json = yielding_send

        async def fake_stream(websocket, server_id, container_id, tail=100):
            started.append(1)
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.append(1)
                raise

        mock_db = mock.AsyncMock()
        mock_result = mock.Mock()
        mock_server = mock.Mock()
        mock_server.user_id = test_user.id
        mock_server.container_id = "cid-9"
        mock_result.scalar_one_or_none.return_value = mock_server
        mock_db.execute = mock.AsyncMock(return_value=mock_result)

        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.AsyncSessionLocal") as mock_session,
            mock.patch(
                "app.websocket.metrics_socket.stream_logs_to_websocket", side_effect=fake_stream
            ),
        ):
            mock_session.return_value.__aenter__ = mock.AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = mock.AsyncMock(return_value=False)
            await manager.handle_connection(ws)

        # Both subscriptions started a stream; the resubscribe cancelled the first
        # task and the disconnect cleanup cancelled the second.
        assert len(started) == 2
        assert len(cancelled) == 2

    @pytest.mark.asyncio
    async def test_disconnect_closes_rate_limit_redis_client(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(side_effect=WebSocketDisconnect())

        mock_redis = mock.AsyncMock()

        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", True),
            mock.patch(
                "app.websocket.metrics_socket.redis.from_url", return_value=mock_redis
            ),
        ):
            await manager.handle_connection(ws)

        mock_redis.aclose.assert_awaited_once()
        assert ws not in connection_users

    @pytest.mark.asyncio
    async def test_disconnect_suppresses_redis_close_error(self, test_user):
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "fake_token"}
        ws.receive_text = mock.AsyncMock(side_effect=WebSocketDisconnect())

        mock_redis = mock.AsyncMock()
        mock_redis.aclose = mock.AsyncMock(side_effect=Exception("close failed"))

        with (
            mock.patch(
                "app.websocket.metrics_socket.validate_token",
                new_callable=mock.AsyncMock,
                return_value=test_user,
            ),
            mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", True),
            mock.patch(
                "app.websocket.metrics_socket.redis.from_url", return_value=mock_redis
            ),
        ):
            # Must not raise despite aclose failing
            await manager.handle_connection(ws)


class TestRateLimitRoleFallback:
    """_check_ws_message_rate_limit role normalization and fallback."""

    @pytest.mark.asyncio
    async def test_unknown_role_falls_back_to_user_limit(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=1)
        with (
            mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", True),
            mock.patch("app.websocket.metrics_socket.settings.rate_limit_window_seconds", 60),
        ):
            is_limited, limit, _remaining = await _check_ws_message_rate_limit(
                mock_redis, "u1", "nonexistent_role"
            )
        assert is_limited is False
        assert limit > 0

    @pytest.mark.asyncio
    async def test_role_lookup_is_case_insensitive(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=1)
        with (
            mock.patch("app.websocket.metrics_socket.settings.rate_limit_enabled", True),
            mock.patch("app.websocket.metrics_socket.settings.rate_limit_window_seconds", 60),
        ):
            _, admin_limit, _ = await _check_ws_message_rate_limit(mock_redis, "u1", "ADMIN")
            _, lower_limit, _ = await _check_ws_message_rate_limit(mock_redis, "u1", "admin")
        assert admin_limit == lower_limit
