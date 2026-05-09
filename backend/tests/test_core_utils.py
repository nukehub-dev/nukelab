"""Tests for core utility functions."""

import pytest


class TestTimeUtils:
    """Time duration parsing and formatting tests."""

    def test_parse_duration(self):
        """Duration strings should parse to seconds."""
        from app.core.time_utils import parse_duration

        assert parse_duration("30m") == 1800
        assert parse_duration("1h") == 3600
        assert parse_duration("24h") == 86400
        assert parse_duration("1d") == 86400

    def test_parse_duration_plain_int(self):
        """Plain integers should parse as seconds."""
        from app.core.time_utils import parse_duration

        assert parse_duration("3600") == 3600

    def test_format_duration(self):
        """Seconds should format to human-readable durations."""
        from app.core.time_utils import format_duration

        assert format_duration(3600) == "1h"
        assert format_duration(1800) == "30m"
        assert format_duration(86400) == "1d"
