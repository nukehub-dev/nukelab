# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

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

    def test_parse_duration_seconds(self):
        """Seconds unit should parse correctly."""
        from app.core.time_utils import parse_duration

        assert parse_duration("30s") == 30
        assert parse_duration("0s") == 0

    def test_parse_duration_weeks(self):
        """Weeks unit should parse correctly."""
        from app.core.time_utils import parse_duration

        assert parse_duration("1w") == 604800
        assert parse_duration("2w") == 1209600

    def test_parse_duration_decimal(self):
        """Decimal values should parse correctly."""
        from app.core.time_utils import parse_duration

        assert parse_duration("1.5h") == 5400
        assert parse_duration("0.5d") == 43200

    def test_parse_duration_invalid_format(self):
        """Invalid formats should raise ValueError."""
        from app.core.time_utils import parse_duration

        with pytest.raises(ValueError):
            parse_duration("abc")
        with pytest.raises(ValueError):
            parse_duration("1x")
        with pytest.raises(ValueError):
            parse_duration("h")

    def test_format_duration_seconds_edge(self):
        """Format duration for seconds edge cases."""
        from app.core.time_utils import format_duration

        assert format_duration(0) == "0s"
        assert format_duration(59) == "59s"
        assert format_duration(1) == "1s"

    def test_format_duration_minutes(self):
        """Format duration for minutes range."""
        from app.core.time_utils import format_duration

        assert format_duration(60) == "1m"
        assert format_duration(61) == "1m"
        assert format_duration(3599) == "59m"

    def test_format_duration_hours(self):
        """Format duration for hours range."""
        from app.core.time_utils import format_duration

        assert format_duration(3600) == "1h"
        assert format_duration(7200) == "2h"
        assert format_duration(86399) == "23h"

    def test_format_duration_days(self):
        """Format duration for days range."""
        from app.core.time_utils import format_duration

        assert format_duration(86400) == "1d"
        assert format_duration(172800) == "2d"
        assert format_duration(604799) == "6d"

    def test_format_duration_weeks(self):
        """Format duration for weeks range."""
        from app.core.time_utils import format_duration

        assert format_duration(604800) == "1w"
        assert format_duration(1209600) == "2w"
