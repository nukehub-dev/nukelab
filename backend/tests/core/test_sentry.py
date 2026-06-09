"""Tests for Sentry error tracking initialization and helpers."""

import pytest
from unittest import mock


class TestInitSentry:
    """Tests for init_sentry()."""

    def test_skips_when_dsn_empty(self):
        """Should not initialize Sentry when DSN is empty."""
        with mock.patch("app.core.sentry.settings") as mock_settings:
            mock_settings.sentry_dsn = ""
            with mock.patch("sentry_sdk.init") as mock_init:
                from app.core.sentry import init_sentry
                init_sentry()
                mock_init.assert_not_called()

    def test_initializes_when_dsn_set(self):
        """Should initialize Sentry when DSN is configured."""
        with mock.patch("app.core.sentry.settings") as mock_settings:
            mock_settings.sentry_dsn = "https://key@o1.ingest.sentry.io/1"
            mock_settings.app_env = "test"
            mock_settings.sentry_release = "nukelab@abc123"
            with mock.patch("sentry_sdk.init") as mock_init:
                from app.core.sentry import init_sentry
                init_sentry()
                mock_init.assert_called_once()
                call_kwargs = mock_init.call_args.kwargs
                assert call_kwargs["dsn"] == "https://key@o1.ingest.sentry.io/1"
                assert call_kwargs["environment"] == "test"
                assert call_kwargs["traces_sample_rate"] == 0.1
                assert call_kwargs["release"] == "nukelab@abc123"
                assert call_kwargs["max_value_length"] == 4096
                assert "_before_send_transaction" in str(call_kwargs["before_send_transaction"])

    def test_uses_default_release_when_not_set(self):
        """Should fall back to default release tag."""
        with mock.patch("app.core.sentry.settings") as mock_settings:
            mock_settings.sentry_dsn = "https://key@o1.ingest.sentry.io/1"
            mock_settings.app_env = "test"
            mock_settings.sentry_release = ""
            with mock.patch("sentry_sdk.init") as mock_init:
                from app.core.sentry import init_sentry
                init_sentry()
                call_kwargs = mock_init.call_args.kwargs
                assert call_kwargs["release"] == "nukelab@dev"


class TestBeforeSend:
    """Tests for event filtering."""

    def test_filters_health_check_events(self):
        """Should drop events from health check paths."""
        from app.core.sentry import _before_send
        event = {"request": {"url": "http://localhost:8080/api/health"}}
        result = _before_send(event, {})
        assert result is None

    def test_allows_regular_events(self):
        """Should allow events from regular API paths."""
        from app.core.sentry import _before_send
        event = {"request": {"url": "http://localhost:8080/api/users"}}
        result = _before_send(event, {})
        assert result is event

    def test_handles_missing_request(self):
        """Should allow events with no request data."""
        from app.core.sentry import _before_send
        event = {"exception": {"values": []}}
        result = _before_send(event, {})
        assert result is event


class TestBeforeSendTransaction:
    """Tests for transaction event filtering."""

    def test_filters_health_check_transactions(self):
        """Should drop transactions from health check paths."""
        from app.core.sentry import _before_send_transaction
        event = {"request": {"url": "http://localhost:8080/api/health"}}
        result = _before_send_transaction(event, {})
        assert result is None

    def test_allows_regular_transactions(self):
        """Should allow transactions from regular API paths."""
        from app.core.sentry import _before_send_transaction
        event = {"request": {"url": "http://localhost:8080/api/users"}}
        result = _before_send_transaction(event, {})
        assert result is event


class TestSetSentryUser:
    """Tests for set_sentry_user()."""

    def test_sets_user_context(self):
        """Should set user context in Sentry scope (no PII like username)."""
        with mock.patch("app.core.sentry.settings") as mock_settings:
            mock_settings.sentry_dsn = "https://key@o1.ingest.sentry.io/1"
            with mock.patch("sentry_sdk.set_user") as mock_set_user:
                from app.core.sentry import set_sentry_user
                set_sentry_user("user-123", "admin")
                mock_set_user.assert_called_once_with({
                    "id": "user-123",
                    "role": "admin",
                })

    def test_skips_when_dsn_empty(self):
        """Should not call set_user when DSN is empty."""
        with mock.patch("app.core.sentry.settings") as mock_settings:
            mock_settings.sentry_dsn = ""
            with mock.patch("sentry_sdk.set_user") as mock_set_user:
                from app.core.sentry import set_sentry_user
                set_sentry_user("user-123")
                mock_set_user.assert_not_called()


class TestScrubSensitiveData:
    """Tests for _scrub_sensitive_data."""

    def test_scrubs_password_in_dict(self):
        """Should redact password values."""
        from app.core.sentry import _scrub_sensitive_data
        data = {"username": "alice", "password": "secret123"}
        result = _scrub_sensitive_data(data)
        assert result["username"] == "alice"
        assert result["password"] == "[REDACTED]"

    def test_scrubs_nested_sensitive_data(self):
        """Should redact sensitive keys in nested structures."""
        from app.core.sentry import _scrub_sensitive_data
        data = {"user": {"id": "1", "token": "abc123"}, "items": [1, 2]}
        result = _scrub_sensitive_data(data)
        assert result["user"]["id"] == "1"
        assert result["user"]["token"] == "[REDACTED]"

    def test_leaves_non_sensitive_data_intact(self):
        """Should not modify non-sensitive data."""
        from app.core.sentry import _scrub_sensitive_data
        data = {"name": "test", "count": 42, "active": True}
        result = _scrub_sensitive_data(data)
        assert result == data


class TestBeforeSendScrubbing:
    """Tests for PII scrubbing in before_send."""

    def test_scrubs_sensitive_request_body(self):
        """Should redact passwords in request body."""
        from app.core.sentry import _before_send
        event = {
            "request": {
                "url": "http://localhost/api/auth/login",
                "data": {"username": "alice", "password": "secret"},
            }
        }
        result = _before_send(event, {})
        assert result is not None
        assert result["request"]["data"]["password"] == "[REDACTED]"
        assert result["request"]["data"]["username"] == "alice"

    def test_scrubs_user_context_pii(self):
        """Should strip username/email from user context."""
        from app.core.sentry import _before_send
        event = {
            "request": {"url": "http://localhost/api/users"},
            "user": {"id": "123", "username": "alice", "email": "a@b.com", "role": "admin"},
        }
        result = _before_send(event, {})
        assert result is not None
        assert result["user"] == {"id": "123", "role": "admin"}

    def test_scrubs_query_string(self):
        """Should redact sensitive query params."""
        from app.core.sentry import _before_send
        event = {
            "request": {
                "url": "http://localhost/api/test",
                "query_string": {"token": "abc", "page": "1"},
            }
        }
        result = _before_send(event, {})
        assert result["request"]["query_string"]["token"] == "[REDACTED]"
        assert result["request"]["query_string"]["page"] == "1"


class TestSetSentryTag:
    """Tests for set_sentry_tag()."""

    def test_sets_tag(self):
        """Should set a tag in Sentry scope."""
        with mock.patch("app.core.sentry.settings") as mock_settings:
            mock_settings.sentry_dsn = "https://key@o1.ingest.sentry.io/1"
            with mock.patch("sentry_sdk.set_tag") as mock_set_tag:
                from app.core.sentry import set_sentry_tag
                set_sentry_tag("feature", "test")
                mock_set_tag.assert_called_once_with("feature", "test")

    def test_skips_when_dsn_empty(self):
        """Should not call set_tag when DSN is empty."""
        with mock.patch("app.core.sentry.settings") as mock_settings:
            mock_settings.sentry_dsn = ""
            with mock.patch("sentry_sdk.set_tag") as mock_set_tag:
                from app.core.sentry import set_sentry_tag
                set_sentry_tag("feature", "test")
                mock_set_tag.assert_not_called()
