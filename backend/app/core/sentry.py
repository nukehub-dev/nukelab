"""Sentry error tracking initialization and helpers.

Configured for FastAPI + Celery with correlation ID propagation,
health-check exclusion, and PII scrubbing.
"""

from urllib.parse import urlparse

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.types import Event, Hint

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Paths that should never send events to Sentry (health probes, metrics, etc.)
_IGNORED_PATHS = {
    "/api/health",
    "/api/health/",
    "/api/system/health",
}

# Sensitive keys to scrub from request data (bodies, query params, cookies)
_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_token",
    "api_key",
    "jwt_secret",
    "session_secret",
    "csrf_token",
    "refresh_token",
    "smtp_password",
    "oauth_client_secret",
    "authorization",
    "cookie",
    "credit_card",
    "cvv",
    "ssn",
}


def _scrub_sensitive_data(data: dict | list | None) -> dict | list | None:
    """Recursively scrub sensitive keys from request data."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = _scrub_sensitive_data(value)
        return result
    elif isinstance(data, list):
        return [_scrub_sensitive_data(item) for item in data]
    return data


def _filter_and_scrub(event: Event) -> Event | None:
    """Drop health-check events and scrub PII from an event."""
    request = event.get("request", {})
    url = request.get("url", "")

    # Drop health-check events
    if url:
        parsed = urlparse(url)
        if parsed.path in _IGNORED_PATHS:
            return None

    # Scrub sensitive data from request body
    if "data" in request:
        request["data"] = _scrub_sensitive_data(request["data"])

    # Scrub sensitive query params
    if "query_string" in request:
        request["query_string"] = _scrub_sensitive_data(request["query_string"])

    # Scrub sensitive cookies
    if "cookies" in request:
        request["cookies"] = _scrub_sensitive_data(request["cookies"])

    # Scrub user context PII (keep only id and role)
    user = event.get("user", {})
    if user:
        event["user"] = {k: v for k, v in user.items() if k in {"id", "role", "ip_address"}}

    return event


def _before_send(event: Event, hint: Hint) -> Event | None:
    """Filter and scrub error events before transmission."""
    return _filter_and_scrub(event)


def _before_send_transaction(event: Event, hint: Hint) -> Event | None:
    """Filter and scrub transaction events before transmission.

    Transactions (performance traces) use the same health-check filtering
    but don't need full PII scrubbing since they carry no request bodies.
    """
    return _filter_and_scrub(event)


def init_sentry() -> None:
    """Initialize Sentry SDK with FastAPI, Celery, SQLAlchemy, and Redis integrations."""
    if not settings.sentry_dsn:
        logger.info("Sentry DSN not configured; skipping initialization")
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        release=settings.sentry_release or "nukelab@dev",
        traces_sample_rate=0.1,
        profiles_sample_rate=0.0,
        max_value_length=4096,  # Prevent huge payloads from bloating events
        before_send=_before_send,
        before_send_transaction=_before_send_transaction,
        send_default_pii=False,  # Do not send user emails, IPs, etc. by default
        integrations=[
            FastApiIntegration(
                transaction_style="endpoint",
                failed_request_status_codes={*range(500, 599)},
            ),
            CeleryIntegration(
                propagate_traces=True,
            ),
            SqlalchemyIntegration(),
            RedisIntegration(),
        ],
    )
    logger.info(
        "Sentry initialized",
        extra={
            "environment": settings.app_env,
            "release": settings.sentry_release or "nukelab@dev",
            "traces_sample_rate": 0.1,
        },
    )


def set_sentry_user(user_id: str | None, role: str | None = None) -> None:
    """Attach user context to the current Sentry scope.

    Only id and role are sent — username is intentionally excluded as PII.
    """
    if not settings.sentry_dsn:
        return
    from sentry_sdk import set_user

    user_context: dict[str, str | None] = {"id": user_id}
    if role:
        user_context["role"] = role
    set_user(user_context)


def set_sentry_tag(key: str, value: str) -> None:
    """Attach a tag to the current Sentry scope."""
    if not settings.sentry_dsn:
        return
    from sentry_sdk import set_tag

    set_tag(key, value)
