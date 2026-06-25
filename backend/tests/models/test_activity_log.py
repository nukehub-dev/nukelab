"""Tests for Activity Log model."""

import pytest


class TestActivityLogModel:
    """Activity log model field tests."""

    def test_activity_log_has_state_fields(self):
        """Activity log should have before_state, after_state, and request_id fields."""
        from app.models.activity_log import ActivityLog

        log = ActivityLog()
        assert hasattr(log, "before_state")
        assert hasattr(log, "after_state")
        assert hasattr(log, "request_id")
