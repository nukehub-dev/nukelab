# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Celery worker correlation ID propagation."""

from unittest import mock


class MockContextVar:
    """Simple mock for contextvars.ContextVar."""

    def __init__(self, default=""):
        self._value = default

    def get(self, default=""):
        return self._value if self._value != "" else default

    def set(self, value):
        self._value = value


def _mock_cid():
    """Return a mock context var for correlation_id."""
    return MockContextVar()


class TestGetCidFromHeaders:
    """Tests for _get_cid_from_headers."""

    def test_returns_empty_for_none(self):
        from app.worker import _get_cid_from_headers

        assert _get_cid_from_headers(None) == ""

    def test_returns_empty_for_empty_dict(self):
        from app.worker import _get_cid_from_headers

        assert _get_cid_from_headers({}) == ""

    def test_extracts_nested_correlation_id(self):
        from app.worker import _get_cid_from_headers

        headers = {"headers": {"correlation_id": "abc-123"}}
        assert _get_cid_from_headers(headers) == "abc-123"

    def test_returns_empty_when_nested_headers_missing(self):
        from app.worker import _get_cid_from_headers

        assert _get_cid_from_headers({"other": "value"}) == ""


class TestInjectCorrelationId:
    """Tests for inject_correlation_id signal handler."""

    def test_injects_when_headers_present(self):
        from app.worker import inject_correlation_id

        headers = {"headers": {}}
        mock_cid = _mock_cid()
        mock_cid.set("cid-123")
        with mock.patch("app.worker.correlation_id", mock_cid):
            inject_correlation_id(headers=headers)
        assert headers["headers"]["correlation_id"] == "cid-123"

    def test_skips_when_headers_none(self):
        from app.worker import inject_correlation_id

        # Should not raise
        inject_correlation_id(headers=None)


class TestSetCorrelationId:
    """Tests for set_correlation_id signal handler."""

    def test_sets_cid_when_present(self):
        from app.worker import set_correlation_id

        task = mock.Mock()
        task.request.headers = {"correlation_id": "task-cid"}
        mock_cid = _mock_cid()
        with mock.patch("app.worker.correlation_id", mock_cid):
            set_correlation_id(task=task, task_id="t1")
            assert mock_cid.get() == "task-cid"

    def test_skips_when_task_none(self):
        from app.worker import set_correlation_id

        # Should not raise
        set_correlation_id(task=None, task_id="t1")

    def test_skips_when_no_cid(self):
        from app.worker import set_correlation_id

        task = mock.Mock()
        task.request.headers = {}
        mock_cid = _mock_cid()
        with mock.patch("app.worker.correlation_id", mock_cid):
            set_correlation_id(task=task, task_id="t1")
            assert mock_cid.get() == ""

    def test_skips_when_headers_none(self):
        from app.worker import set_correlation_id

        task = mock.Mock()
        task.request.headers = None
        mock_cid = _mock_cid()
        with mock.patch("app.worker.correlation_id", mock_cid):
            set_correlation_id(task=task, task_id="t1")
            assert mock_cid.get() == ""


class TestClearCorrelationId:
    """Tests for clear_correlation_id signal handler."""

    def test_clears_cid(self):
        from app.worker import clear_correlation_id

        mock_cid = _mock_cid()
        mock_cid.set("old-cid")
        with mock.patch("app.worker.correlation_id", mock_cid):
            clear_correlation_id(task_id="t1")
            assert mock_cid.get() == ""


class TestContextTask:
    """Tests for ContextTask custom base class."""

    def test_delay_delegates_to_apply_async(self):
        from app.worker import ContextTask

        with mock.patch.object(ContextTask, "apply_async", return_value=mock.Mock()) as mock_apply:
            task = ContextTask()
            task.delay(1, 2)
            mock_apply.assert_called_once()


class TestCeleryApp:
    """Tests for celery_app configuration."""

    def test_celery_app_exists(self):
        from app.worker import celery_app

        assert celery_app is not None
        assert celery_app.main == "nukelab"

    def test_beat_schedule_has_tasks(self):
        from app.worker import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "collect-container-metrics" in schedule
        assert "collect-system-metrics" in schedule
        assert "check-container-health" in schedule
        assert "cleanup-expired-data" in schedule
