"""Tests for structured logging configuration."""

import json
import logging

from app.core.context import correlation_id
from app.core.logging import (
    CorrelationIdFilter,
    JSONFormatter,
    TextFormatter,
    configure_logging,
    get_logger,
)


class TestJSONFormatter:
    """JSON log line formatting."""

    def test_basic_json_output(self):
        """Should produce valid JSON with core fields."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert data["message"] == "hello"
        assert "timestamp" in data

    def test_correlation_id_injection(self):
        """Should include correlation_id when contextvar is set."""
        token = correlation_id.set("test-cid-123")
        try:
            formatter = JSONFormatter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="hello",
                args=(),
                exc_info=None,
            )
            output = formatter.format(record)
            data = json.loads(output)
            assert data["correlation_id"] == "test-cid-123"
        finally:
            correlation_id.reset(token)

    def test_extra_fields(self):
        """Should include extra record attributes."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        record.path = "/api/test"
        record.method = "GET"
        record.status_code = 200
        record.duration_ms = 42.5

        output = formatter.format(record)
        data = json.loads(output)
        assert data["path"] == "/api/test"
        assert data["method"] == "GET"
        assert data["status_code"] == 200
        assert data["duration_ms"] == 42.5

    def test_exception_traceback(self):
        """Should include traceback when exc_info is present."""
        formatter = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="failed",
                args=(),
                exc_info=True,
            )
            output = formatter.format(record)

        data = json.loads(output)
        assert "traceback" in data
        assert "ValueError" in data["traceback"]


class TestCorrelationIdFilter:
    """Correlation ID filter behavior."""

    def test_sets_attribute_on_record(self):
        """Should set correlation_id attribute on every record."""
        filt = CorrelationIdFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        result = filt.filter(record)
        assert result is True
        assert hasattr(record, "correlation_id")

    def test_reads_contextvar(self):
        """Should read current correlation_id from contextvar."""
        token = correlation_id.set("ctx-456")
        try:
            filt = CorrelationIdFilter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="hello",
                args=(),
                exc_info=None,
            )
            filt.filter(record)
            assert record.correlation_id == "ctx-456"
        finally:
            correlation_id.reset(token)


class TestTextFormatter:
    """Human-readable text formatter."""

    def test_includes_correlation_id(self):
        """Should render correlation_id in output."""
        formatter = TextFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        record.correlation_id = "txt-789"  # type: ignore[attr-defined]
        output = formatter.format(record)
        assert "txt-789" in output


class TestConfigureLogging:
    """Logging configuration setup."""

    def test_creates_handlers(self):
        """Should attach handlers to root logger."""
        root_logger = logging.getLogger()
        # Remove existing handlers temporarily
        original_handlers = root_logger.handlers[:]
        for h in original_handlers:
            root_logger.removeHandler(h)

        try:
            configure_logging(level="DEBUG", log_format="json")
            assert len(root_logger.handlers) >= 1
            handler_types = [type(h).__name__ for h in root_logger.handlers]
            assert "StreamHandler" in handler_types
        finally:
            # Restore original handlers
            for h in root_logger.handlers[:]:
                root_logger.removeHandler(h)
            for h in original_handlers:
                root_logger.addHandler(h)

    def test_respects_level(self):
        """Should set root logger level."""
        root_logger = logging.getLogger()
        original_level = root_logger.level
        try:
            configure_logging(level="WARNING", log_format="text")
            assert root_logger.level == logging.WARNING
        finally:
            root_logger.setLevel(original_level)


class TestGetLogger:
    """Logger factory."""

    def test_returns_logger(self):
        """Should return a logging.Logger instance."""
        logger = get_logger("my.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "my.module"
