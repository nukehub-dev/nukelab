"""OpenTelemetry distributed tracing initialization and helpers.

Provides a single idempotent `init_tracing()` entry point used by both the
FastAPI application and Celery workers. When tracing is disabled (the default)
all helpers are no-ops so existing tests and local development are unaffected.
"""

from __future__ import annotations

import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.sdk.resources import (
    Resource,
    SERVICE_NAME,
    SERVICE_VERSION,
    DEPLOYMENT_ENVIRONMENT,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from app.config import settings
from app.core.context import correlation_id
from app.core.logging import get_logger

logger = get_logger(__name__)

# Internal flag so we don't initialize the provider twice in the same process.
_tracing_initialized = False


def _build_resource() -> Resource:
    """Build the OTel resource describing this service."""
    return Resource.create(
        {
            SERVICE_NAME: settings.otel_service_name,
            SERVICE_VERSION: settings.otel_service_version,
            DEPLOYMENT_ENVIRONMENT: settings.app_env,
        }
    )


def _build_exporter() -> Optional[GRPCExporter | HTTPExporter]:
    """Build an OTLP exporter based on configuration."""
    # Standard OTEL env vars take precedence over application settings.
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or settings.otel_exporter_otlp_endpoint
    if not endpoint:
        logger.warning("OTel endpoint not configured; traces will not be exported")
        return None

    protocol = (
        os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL")
        or settings.otel_exporter_otlp_protocol
        or "grpc"
    ).lower()

    timeout = int(os.environ.get("OTEL_EXPORTER_OTLP_TIMEOUT", "10000"))

    if protocol == "http" or protocol == "http/protobuf":
        return HTTPExporter(endpoint=endpoint, timeout=timeout)
    return GRPCExporter(endpoint=endpoint, timeout=timeout)


def init_tracing(force: bool = False) -> bool:
    """Initialize OpenTelemetry tracing for the current process.

    Idempotent: subsequent calls return immediately unless ``force=True``.
    Returns True when tracing is active, False otherwise.
    """
    global _tracing_initialized

    if _tracing_initialized and not force:
        return settings.otel_traces_enabled

    _tracing_initialized = True

    if not settings.otel_traces_enabled:
        logger.info("OpenTelemetry tracing disabled")
        return False

    # Configure W3C tracecontext + baggage propagation globally.
    set_global_textmap(
        CompositePropagator(
            [
                TraceContextTextMapPropagator(),
                W3CBaggagePropagator(),
            ]
        )
    )

    resource = _build_resource()
    provider = TracerProvider(resource=resource)

    exporter = _build_exporter()
    if exporter is not None:
        processor = BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            max_export_batch_size=512,
            schedule_delay_millis=5000,
        )
        provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

    logger.info(
        "OpenTelemetry tracing initialized",
        extra={
            "service_name": settings.otel_service_name,
            "endpoint": settings.otel_exporter_otlp_endpoint,
            "protocol": settings.otel_exporter_otlp_protocol,
        },
    )
    return True


def is_tracing_enabled() -> bool:
    """Return whether tracing is enabled in configuration."""
    return settings.otel_traces_enabled


def get_current_trace_id() -> str:
    """Return the hex trace ID of the current span, or empty string."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return ""


def set_correlation_from_trace() -> None:
    """Set the legacy correlation_id to the current OTel trace ID.

    This bridges the existing structured-logging correlation ID with OTel traces
    so that logs without an explicit X-Correlation-ID header can still be joined
    to a trace.
    """
    if not settings.otel_log_correlation:
        return

    if correlation_id.get(""):
        return  # Preserve an explicitly provided correlation ID.

    trace_id = get_current_trace_id()
    if trace_id:
        correlation_id.set(trace_id)


def set_span_status_from_http(status_code: int) -> None:
    """Mark the current span OK/ERROR based on an HTTP status code."""
    span = trace.get_current_span()
    if not span or not span.is_recording():
        return

    if 400 <= status_code < 600:
        span.set_status(Status(StatusCode.ERROR, f"HTTP {status_code}"))
    else:
        span.set_status(Status(StatusCode.OK))
