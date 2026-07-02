# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""
Structured logging configuration.

Supports two formats:
  - json: machine-readable structured logs for production
  - text: human-readable logs for development

Wires up existing config.py settings: LOG_LEVEL, LOG_FORMAT, LOG_FILE,
LOG_MAX_BYTES, LOG_BACKUP_COUNT.
"""

import json
import logging
import logging.handlers
import os
import sys
from typing import Any

from app.config import settings
from app.core.context import correlation_id


class JSONFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Inject correlation ID from contextvar
        cid = correlation_id.get("")
        if cid:
            log_data["correlation_id"] = cid

        # Extra fields from record
        for key in ("path", "method", "user_id", "duration_ms", "status_code"):
            if hasattr(record, key):
                value = getattr(record, key)
                if value is not None:
                    log_data[key] = value

        # Exception info (record.exc_info may be True when captured automatically)
        if record.exc_info:
            exc_info = record.exc_info
            if exc_info is True:
                import sys

                exc_info = sys.exc_info()
            if exc_info[0] is not None:
                log_data["traceback"] = self.formatException(exc_info)

        return json.dumps(log_data, default=str)


class CorrelationIdFilter(logging.Filter):
    """Ensure correlation_id is available on every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        cid = correlation_id.get("")
        record.correlation_id = cid  # type: ignore[attr-defined]
        return True


class TextFormatter(logging.Formatter):
    """Human-readable format with correlation ID."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(correlation_id)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # Ensure correlation_id attr exists (set by filter)
        if not hasattr(record, "correlation_id"):
            record.correlation_id = ""  # type: ignore[attr-defined]
        return super().format(record)


def configure_logging(
    level: str | None = None,
    log_format: str | None = None,
    log_file: str | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> None:
    """
    Configure root logger with structured or text formatting.

    Called once during application startup (main.py lifespan).
    """
    resolved_level = (level or settings.log_level).upper()
    resolved_format = (log_format or settings.log_format).lower()
    resolved_file = log_file or settings.log_file
    resolved_max_bytes = max_bytes or settings.log_max_bytes
    resolved_backup_count = backup_count or settings.log_backup_count

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, resolved_level, logging.INFO))

    # Remove existing handlers to avoid duplicates on reconfiguration
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Shared filter
    cid_filter = CorrelationIdFilter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.addFilter(cid_filter)

    if resolved_format == "json":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(TextFormatter())

    root_logger.addHandler(console_handler)

    # File handler (optional)
    if resolved_file:
        # Ensure directory exists
        log_dir = os.path.dirname(resolved_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            resolved_file,
            maxBytes=resolved_max_bytes,
            backupCount=resolved_backup_count,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.addFilter(cid_filter)

        if resolved_format == "json":
            file_handler.setFormatter(JSONFormatter())
        else:
            file_handler.setFormatter(TextFormatter())

        root_logger.addHandler(file_handler)

    # Suppress overly verbose third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("aioredis").setLevel(logging.WARNING)

    root_logger.info(
        "Logging configured",
        extra={
            "level": resolved_level,
            "format": resolved_format,
            "file": resolved_file,
        },
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger with correlation ID support pre-configured."""
    logger = logging.getLogger(name)
    return logger
