# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Security regression tests for WebSocket / real-time channels (Phase 9).

These tests verify that unauthenticated connections are rejected, users cannot
subscribe to unauthorized channels, and malformed messages do not crash the
WebSocket handler. Tests use the same mocking style as the existing websocket
unit tests to avoid event-loop conflicts with TestClient.
"""

from unittest import mock

import pytest

from app.websocket.metrics_socket import MetricsWebSocketManager


class TestWebSocketAuthentication:
    """Verify WebSocket authentication and authorization."""

    @pytest.mark.asyncio
    async def test_unauthenticated_websocket_connection_is_rejected(self):
        """Connection without a token should be closed with 4001."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {}
        ws.receive_text = mock.AsyncMock(side_effect=TimeoutError())
        await manager.handle_connection(ws)

        calls = [call.args[0] for call in ws.send_json.call_args_list]
        assert any(c.get("event") == "auth:error" for c in calls)
        ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_token_websocket_connection_is_rejected(self):
        """Connection with a tampered token should be rejected."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "invalid-token"}
        ws.receive_text = mock.AsyncMock(side_effect=TimeoutError())
        await manager.handle_connection(ws)

        calls = [call.args[0] for call in ws.send_json.call_args_list]
        assert any(c.get("event") == "auth:error" for c in calls)

    @pytest.mark.asyncio
    async def test_valid_token_websocket_connection_succeeds(self, test_user):
        """Connection with a valid JWT should receive auth:success."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "valid-token"}
        ws.receive_text = mock.AsyncMock(side_effect=Exception("disconnect"))

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        calls = [call.args[0] for call in ws.send_json.call_args_list]
        assert any(c.get("event") == "auth:success" for c in calls)


class TestWebSocketAuthorization:
    """Verify channel subscription authorization."""

    @pytest.mark.asyncio
    async def test_user_cannot_subscribe_to_global_metrics(self, test_user):
        """Non-admin users should be denied global metric subscription."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "valid-token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                '{"type": "subscribe", "scope": "global"}',
                Exception("disconnect"),
            ]
        )

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        calls = [call.args[0] for call in ws.send_json.call_args_list]
        error_calls = [c for c in calls if c.get("event") == "error"]
        assert error_calls
        assert any("admin" in c.get("message", "").lower() for c in error_calls)

    @pytest.mark.asyncio
    async def test_user_cannot_subscribe_to_other_user_channel(self, test_user):
        """Users cannot subscribe to another user's channel."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "valid-token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                '{"type": "subscribe", "scope": "user", "target_id": "00000000-0000-0000-0000-000000000000"}',
                Exception("disconnect"),
            ]
        )

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        calls = [call.args[0] for call in ws.send_json.call_args_list]
        error_calls = [c for c in calls if c.get("event") == "error"]
        assert error_calls
        assert any("access denied" in c.get("message", "").lower() for c in error_calls)

    @pytest.mark.asyncio
    async def test_admin_can_subscribe_to_global_metrics(self, admin_user):
        """Admins should be allowed global metric subscription."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "valid-token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                '{"type": "subscribe", "scope": "global"}',
                Exception("disconnect"),
            ]
        )

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=admin_user,
        ):
            await manager.handle_connection(ws)

        calls = [call.args[0] for call in ws.send_json.call_args_list]
        assert any(c.get("event") == "subscribed" for c in calls)


class TestWebSocketInputValidation:
    """Verify malformed WebSocket messages are handled safely."""

    @pytest.mark.asyncio
    async def test_invalid_json_message_returns_error(self, test_user):
        """Non-JSON text should not crash the handler."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "valid-token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                "not valid json",
                Exception("disconnect"),
            ]
        )

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        calls = [call.args[0] for call in ws.send_json.call_args_list]
        error_calls = [c for c in calls if c.get("event") == "error"]
        assert error_calls
        assert any("invalid json" in c.get("message", "").lower() for c in error_calls)

    @pytest.mark.asyncio
    async def test_unknown_scope_returns_error(self, test_user):
        """Unknown subscription scope should be rejected gracefully."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "valid-token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                '{"type": "subscribe", "scope": "unknown_scope"}',
                Exception("disconnect"),
            ]
        )

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        calls = [call.args[0] for call in ws.send_json.call_args_list]
        error_calls = [c for c in calls if c.get("event") == "error"]
        assert error_calls
        assert any("unknown scope" in c.get("message", "").lower() for c in error_calls)

    @pytest.mark.asyncio
    async def test_subscribe_logs_without_server_id_returns_error(self, test_user):
        """subscribe_logs without server_id should be rejected."""
        manager = MetricsWebSocketManager()
        ws = mock.AsyncMock()
        ws.query_params = {"token": "valid-token"}
        ws.receive_text = mock.AsyncMock(
            side_effect=[
                '{"type": "subscribe_logs"}',
                Exception("disconnect"),
            ]
        )

        with mock.patch(
            "app.websocket.metrics_socket.validate_token",
            new_callable=mock.AsyncMock,
            return_value=test_user,
        ):
            await manager.handle_connection(ws)

        calls = [call.args[0] for call in ws.send_json.call_args_list]
        error_calls = [c for c in calls if c.get("event") == "error"]
        assert error_calls
