"""Tests for Audit Middleware."""

import pytest
import uuid
from unittest.mock import patch, AsyncMock, Mock

from app.middleware.audit import AuditMiddleware
from app.models.activity_log import ActivityLog
from app.models.user import User


class TestAuditMiddleware:
    """Audit middleware behavior tests."""

    @pytest.fixture
    def middleware(self):
        """Create audit middleware instance."""
        return AuditMiddleware(app=None)

    @pytest.fixture
    def mock_request(self):
        """Create a mock request."""

        class MockRequest:
            def __init__(self):
                self.state = type("obj", (object,), {"user": None})()
                self.client = type("obj", (object,), {"host": "127.0.0.1"})()
                self.headers = {}
                self.method = "POST"
                self.url = type(
                    "obj", (object,), {"path": "/api/users/123e4567-e89b-12d3-a456-426614174000"}
                )()

        return MockRequest()

    @pytest.fixture
    def mock_response(self):
        """Create a mock response."""

        class MockResponse:
            status_code = 200

        return MockResponse()

    @pytest.mark.asyncio
    async def test_log_activity_without_auth(self, middleware, mock_request, mock_response):
        """Should log with actor_id=None when no auth header present."""
        mock_request.headers = {}

        with patch.object(middleware, "_get_user_from_token", return_value=None):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                # Check that ActivityLog was created with actor_id=None
                call_args = mock_db.add.call_args[0][0]
                assert isinstance(call_args, ActivityLog)
                assert call_args.actor_id is None

    @pytest.mark.asyncio
    async def test_log_activity_with_valid_token(
        self, middleware, mock_request, mock_response, test_user
    ):
        """Should log with correct actor_id when valid JWT is provided."""

        with patch.object(middleware, "_get_user_from_token", return_value=test_user):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                call_args = mock_db.add.call_args[0][0]
                assert isinstance(call_args, ActivityLog)
                assert call_args.actor_id == test_user.id

    @pytest.mark.asyncio
    async def test_log_activity_with_invalid_token(self, middleware, mock_request, mock_response):
        """Should log with actor_id=None when invalid JWT is provided."""
        mock_request.headers = {"authorization": "Bearer invalid_token"}

        with patch.object(middleware, "_get_user_from_token", return_value=None):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                call_args = mock_db.add.call_args[0][0]
                assert isinstance(call_args, ActivityLog)
                assert call_args.actor_id is None

    @pytest.mark.asyncio
    async def test_log_activity_with_non_bearer_auth(self, middleware, mock_request, mock_response):
        """Should log with actor_id=None when auth header is not Bearer."""
        mock_request.headers = {"authorization": "Basic dXNlcjpwYXNz"}

        with patch.object(middleware, "_get_user_from_token", return_value=None):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                call_args = mock_db.add.call_args[0][0]
                assert isinstance(call_args, ActivityLog)
                assert call_args.actor_id is None

    @pytest.mark.asyncio
    async def test_log_activity_captures_ip_and_user_agent(
        self, middleware, mock_request, mock_response
    ):
        """Should capture IP address and user agent."""
        mock_request.headers = {}
        mock_request.client.host = "192.168.1.100"

        with patch.object(middleware, "_get_user_from_token", return_value=None):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                call_args = mock_db.add.call_args[0][0]
                assert call_args.ip_address == "192.168.1.100"

    def test_skip_methods(self, middleware):
        """Should skip GET, HEAD, OPTIONS methods."""
        assert "GET" in middleware.SKIP_METHODS
        assert "HEAD" in middleware.SKIP_METHODS
        assert "OPTIONS" in middleware.SKIP_METHODS
        assert "POST" not in middleware.SKIP_METHODS
        assert "PUT" not in middleware.SKIP_METHODS
        assert "DELETE" not in middleware.SKIP_METHODS

    def test_skip_paths(self, middleware):
        """Should skip health, docs, and metrics paths."""
        assert "/api/health" in middleware.SKIP_PATHS
        assert "/api/docs" in middleware.SKIP_PATHS
        assert "/api/metrics" in middleware.SKIP_PATHS
        assert "/api/users" not in middleware.SKIP_PATHS

    @pytest.mark.asyncio
    async def test_capture_before_state_for_put(self, middleware):
        """Should capture before state for PUT requests."""
        from unittest.mock import MagicMock

        request = MagicMock()
        request.url.path = "/api/users/123e4567-e89b-12d3-a456-426614174000"
        request.method = "PUT"

        with patch.object(middleware, "_fetch_record", return_value={"username": "old_name"}):
            state = await middleware._capture_before_state(request)
            assert state == {"username": "old_name"}

    @pytest.mark.asyncio
    async def test_action_naming_post(self, middleware, mock_request, mock_response):
        """Should name POST actions as 'create_<target>'."""
        mock_request.headers = {}
        mock_request.url.path = "/api/servers"

        with patch.object(middleware, "_get_user_from_token", return_value=None):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                call_args = mock_db.add.call_args[0][0]
                assert call_args.action == "create_servers"

    @pytest.mark.asyncio
    async def test_action_naming_post_with_subaction(self, middleware, mock_request, mock_response):
        """Should name POST sub-actions like 'bulk-action_users'."""
        mock_request.headers = {}
        mock_request.url.path = "/api/users/bulk-action"
        mock_request.method = "POST"

        with patch.object(middleware, "_get_user_from_token", return_value=None):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                call_args = mock_db.add.call_args[0][0]
                assert call_args.action == "bulk-action_users"

    @pytest.mark.asyncio
    async def test_action_naming_put(self, middleware, mock_request, mock_response):
        """Should name PUT actions as 'update_<target>'."""
        mock_request.headers = {}
        mock_request.url.path = "/api/users/123e4567-e89b-12d3-a456-426614174000"
        mock_request.method = "PUT"

        with patch.object(middleware, "_get_user_from_token", return_value=None):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                call_args = mock_db.add.call_args[0][0]
                assert call_args.action == "update_users"

    @pytest.mark.asyncio
    async def test_action_naming_delete(self, middleware, mock_request, mock_response):
        """Should name DELETE actions as 'delete_<target>'."""
        mock_request.headers = {}
        mock_request.url.path = "/api/servers/123e4567-e89b-12d3-a456-426614174000"
        mock_request.method = "DELETE"

        with patch.object(middleware, "_get_user_from_token", return_value=None):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                call_args = mock_db.add.call_args[0][0]
                assert call_args.action == "delete_servers"

    @pytest.mark.asyncio
    async def test_log_includes_actor_info_in_details(
        self, middleware, mock_request, mock_response, test_user
    ):
        """Should include actor username, role, and email in details."""
        test_user.role = "admin"
        test_user.email = "admin@example.com"

        with patch.object(middleware, "_get_user_from_token", return_value=test_user):
            with patch("app.middleware.audit.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db
                mock_db.add = Mock()
                mock_db.commit = AsyncMock()

                await middleware._log_activity(mock_request, mock_response, {})

                call_args = mock_db.add.call_args[0][0]
                assert call_args.details["actor_username"] == test_user.username
                assert call_args.details["actor_role"] == "admin"
                assert call_args.details["actor_email"] == "admin@example.com"
