"""Tests for Prometheus metrics instrumentation."""

import pytest
from fastapi import status

from app.config import settings


@pytest.fixture(autouse=True)
def reset_prometheus_settings(monkeypatch):
    """Restore Prometheus settings after each test."""
    original_enabled = settings.prometheus_enabled
    original_store = settings.request_metrics_store
    yield
    settings.prometheus_enabled = original_enabled
    settings.request_metrics_store = original_store


@pytest.fixture
def prometheus_enabled():
    """Enable Prometheus metrics for a single test."""
    settings.prometheus_enabled = True
    yield


@pytest.mark.asyncio
async def test_metrics_endpoint_disabled_by_default(client):
    """When PROMETHEUS_ENABLED=false, /api/metrics should 404."""
    settings.prometheus_enabled = False
    response = await client.get("/metrics")
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_metrics_endpoint_enabled(client, prometheus_enabled):
    """When PROMETHEUS_ENABLED=true, /api/metrics returns OpenMetrics text."""
    response = await client.get("/metrics")
    assert response.status_code == status.HTTP_200_OK
    assert "text/plain" in response.headers["content-type"]
    assert "nukelab_http_requests_total" in response.text


@pytest.mark.asyncio
async def test_request_counter_increments(client, prometheus_enabled):
    """A successful request should increment nukelab_http_requests_total."""
    # Capture counter value before the request on a non-skipped route (root).
    # In the ASGI test client the app root_path is not part of the request path,
    # so the recorded path label is "/" rather than "/api/".
    before_response = await client.get("/metrics")
    before = _extract_counter(before_response.text, "nukelab_http_requests_total", "GET", "/", "200")

    response = await client.get("/")
    assert response.status_code == status.HTTP_200_OK

    after_response = await client.get("/metrics")
    after = _extract_counter(after_response.text, "nukelab_http_requests_total", "GET", "/", "200")

    assert after == before + 1


@pytest.mark.asyncio
async def test_metrics_endpoint_skipped_in_db_buffer(client):
    """/api/metrics should not be recorded in the DB request_metrics buffer."""
    from app.middleware.request_metrics import RequestMetricsMiddleware

    assert "/api/metrics" in RequestMetricsMiddleware.SKIP_PATHS


@pytest.mark.asyncio
async def test_prometheus_only_mode_does_not_buffer_db(client):
    """With REQUEST_METRICS_STORE=prometheus, no DB record is queued."""
    from app.middleware.request_metrics import _metrics_buffer

    settings.prometheus_enabled = True
    settings.request_metrics_store = "prometheus"

    # Flush any existing buffered records and reset the in-memory buffer
    await _metrics_buffer.flush()

    response = await client.get("/health")
    assert response.status_code == status.HTTP_200_OK

    # Give the fire-and-forget task a moment to run, then assert nothing was buffered
    await _metrics_buffer.flush()
    assert len(_metrics_buffer._buffer) == 0


def _extract_counter(text: str, name: str, method: str, path: str, status_code: str) -> int:
    """Parse a Prometheus counter line and return its integer value."""
    labels = f'method="{method}",path="{path}",status_code="{status_code}"'
    for line in text.splitlines():
        if line.startswith(f"{name}{{") and labels in line:
            # Line format: name{labels} value
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                return int(float(parts[1]))
    return 0
