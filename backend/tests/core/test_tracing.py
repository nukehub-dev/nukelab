"""Tests for OpenTelemetry tracing initialization and helpers."""

import os

import pytest
from unittest import mock

from app.core import tracing
from app.core.context import correlation_id


class TestInitTracing:
    """Unit tests for init_tracing() configuration."""

    def test_disabled_returns_false(self):
        with mock.patch.object(tracing.settings, "otel_traces_enabled", False):
            # Reset initialization guard so the function actually runs.
            tracing._tracing_initialized = False
            result = tracing.init_tracing()
            assert result is False

    def test_disabled_does_not_set_provider(self):
        with mock.patch.object(tracing.settings, "otel_traces_enabled", False):
            with mock.patch("app.core.tracing.trace.set_tracer_provider") as mock_set:
                tracing._tracing_initialized = False
                tracing.init_tracing()
                mock_set.assert_not_called()

    def test_enabled_sets_tracer_provider(self):
        with mock.patch.object(tracing.settings, "otel_traces_enabled", True):
            with mock.patch.object(
                tracing.settings, "otel_exporter_otlp_endpoint", "http://otel-collector:4317"
            ):
                with mock.patch("app.core.tracing.trace.set_tracer_provider") as mock_set:
                    with mock.patch("app.core.tracing.BatchSpanProcessor") as mock_processor:
                        with mock.patch("app.core.tracing.GRPCExporter") as mock_exporter:
                            tracing._tracing_initialized = False
                            tracing.init_tracing()
                            mock_set.assert_called_once()
                            mock_exporter.assert_called_once_with(
                                endpoint="http://otel-collector:4317", timeout=10000
                            )
                            mock_processor.assert_called_once_with(
                                mock_exporter.return_value,
                                max_queue_size=2048,
                                max_export_batch_size=512,
                                schedule_delay_millis=5000,
                            )

    def test_uses_http_exporter_when_configured(self):
        with mock.patch.object(tracing.settings, "otel_traces_enabled", True):
            with mock.patch.object(
                tracing.settings, "otel_exporter_otlp_endpoint", "http://otel-collector:4318"
            ):
                with mock.patch.object(tracing.settings, "otel_exporter_otlp_protocol", "http"):
                    with mock.patch.dict(os.environ, {}, clear=False):
                        os.environ.pop("OTEL_EXPORTER_OTLP_PROTOCOL", None)
                        with mock.patch("app.core.tracing.trace.set_tracer_provider"):
                            with mock.patch("app.core.tracing.BatchSpanProcessor"):
                                with mock.patch("app.core.tracing.HTTPExporter") as mock_http:
                                    with mock.patch("app.core.tracing.GRPCExporter") as mock_grpc:
                                        tracing._tracing_initialized = False
                                        tracing.init_tracing()
                                        mock_http.assert_called_once()
                                        mock_grpc.assert_not_called()

    def test_env_endpoint_overrides_settings(self):
        with mock.patch.object(tracing.settings, "otel_traces_enabled", True):
            with mock.patch.object(
                tracing.settings, "otel_exporter_otlp_endpoint", "http://settings:4317"
            ):
                with mock.patch.object(tracing.settings, "otel_exporter_otlp_protocol", "grpc"):
                    with mock.patch.dict(
                        os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://env:4318"}
                    ):
                        with mock.patch("app.core.tracing.trace.set_tracer_provider"):
                            with mock.patch("app.core.tracing.BatchSpanProcessor"):
                                with mock.patch("app.core.tracing.GRPCExporter") as mock_grpc:
                                    tracing._tracing_initialized = False
                                    tracing.init_tracing()
                                    mock_grpc.assert_called_once_with(
                                        endpoint="http://env:4318", timeout=10000
                                    )

    def test_idempotent(self):
        with mock.patch.object(tracing.settings, "otel_traces_enabled", True):
            with mock.patch.object(
                tracing.settings, "otel_exporter_otlp_endpoint", "http://otel-collector:4317"
            ):
                with mock.patch("app.core.tracing.trace.set_tracer_provider") as mock_set:
                    tracing._tracing_initialized = False
                    tracing.init_tracing()
                    tracing.init_tracing()
                    tracing.init_tracing()
                    mock_set.assert_called_once()


class TestTraceHelpers:
    """Unit tests for tracing helper functions."""

    def test_get_current_trace_id_without_span(self):
        assert tracing.get_current_trace_id() == ""

    def test_get_current_trace_id_with_span(self):
        trace_id = 12345678901234567890123456789012
        span_context = mock.Mock()
        span_context.trace_id = trace_id
        span_context.is_valid = True
        span = mock.Mock()
        span.get_span_context.return_value = span_context

        with mock.patch("app.core.tracing.trace.get_current_span", return_value=span):
            assert tracing.get_current_trace_id() == format(trace_id, "032x")

    def test_set_correlation_from_trace_preserves_existing(self):
        correlation_id.set("existing-correlation-id")
        with mock.patch("app.core.tracing.get_current_trace_id", return_value="abc123"):
            tracing.set_correlation_from_trace()
            assert correlation_id.get() == "existing-correlation-id"
        correlation_id.set("")

    def test_set_correlation_from_trace_sets_trace_id(self):
        correlation_id.set("")
        with mock.patch("app.core.tracing.get_current_trace_id", return_value="abc123"):
            tracing.set_correlation_from_trace()
            assert correlation_id.get() == "abc123"
        correlation_id.set("")

    def test_set_correlation_from_trace_disabled(self):
        correlation_id.set("")
        with mock.patch.object(tracing.settings, "otel_log_correlation", False):
            with mock.patch("app.core.tracing.get_current_trace_id", return_value="abc123"):
                tracing.set_correlation_from_trace()
                assert correlation_id.get() == ""
