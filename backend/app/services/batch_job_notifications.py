# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""One deduplicated owner notification after a new batch-job terminal result.

Delivery is best-effort: a notification failure never changes the committed
result, reopens the job, releases a reservation, or fails the calling task.
Deduplication uses a PostgreSQL transaction advisory lock plus a bounded query
over existing notification rows, so no schema change is required.

Notifications carry only the job id, its already-validated bounded name, the
terminal state, and a ``/jobs/<id>`` link. Command arguments, logs, environment
values, volume names/paths, image/runtime identity, and secrets never appear.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.batch_job import TERMINAL_JOB_STATES
from app.models.notification import Notification

logger = get_logger(__name__)

EVENT_KEY = "batch_job_completed"
TERMINAL_EVENT = "completed"
DEDUPE_NAMESPACE = "nukelab:batch-job-notification"
NOTIFICATION_TYPE = "job"
MAX_NAME_LENGTH = 120

_TERMINAL_STATES = frozenset(TERMINAL_JOB_STATES)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]+")

_LOCK_SQL = text("SELECT pg_advisory_xact_lock(:key)")


def notification_lock_key(job_id: uuid.UUID, terminal_event: str = TERMINAL_EVENT) -> int:
    """Derive a stable signed 64-bit transaction advisory-lock key."""
    material = f"{DEDUPE_NAMESPACE}:{job_id}:{terminal_event}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)


def notification_dedupe_key(job_id: uuid.UUID, terminal_event: str = TERMINAL_EVENT) -> str:
    """Return the deterministic per-job terminal-event dedupe key."""
    return f"batch_job:{job_id}:{terminal_event}"


def _bounded_name(value: object) -> str | None:
    """Defensive bound for the already-validated submission name."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(_CONTROL_CHAR_RE.sub(" ", value).split()).strip()
    if not cleaned:
        return None
    return cleaned[:MAX_NAME_LENGTH]


def _severity(state: str) -> str:
    if state == "succeeded":
        return "success"
    if state in ("failed", "timed_out"):
        return "error"
    return "warning"


def _title(state: str) -> str:
    return {
        "succeeded": "Batch job completed",
        "failed": "Batch job failed",
        "cancelled": "Batch job cancelled",
        "timed_out": "Batch job timed out",
        "expired": "Batch job expired",
    }.get(state, "Batch job finished")


def _message(job_id: uuid.UUID, name: str | None, state: str) -> str:
    if name:
        subject = f"Your batch job '{name}' ({job_id})"
    else:
        subject = f"Your batch job ({job_id})"
    return f"{subject} finished with state '{state}'."


class BatchJobNotifier:
    """Best-effort, owner-scoped completion notification."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def notify_terminal(
        self,
        *,
        job_id: uuid.UUID,
        owner_id: uuid.UUID,
        job_name: object = None,
        state: str,
    ) -> bool:
        """Create at most one in-app notification for this terminal event.

        Returns ``True`` only when a notification row was written. Every
        failure is swallowed and logged without exception content.
        """
        if (
            not isinstance(job_id, uuid.UUID)
            or not isinstance(owner_id, uuid.UUID)
            or state not in _TERMINAL_STATES
        ):
            return False
        dedupe_key = notification_dedupe_key(job_id)
        lock_key = notification_lock_key(job_id)
        name = _bounded_name(job_name)
        try:
            # The transaction-scoped lock covers the existence check and the
            # NotificationService.create commit. A concurrent finalizer waits,
            # then observes the committed row and skips delivery.
            await self.db.execute(_LOCK_SQL, {"key": lock_key})
            existing = await self.db.scalar(
                select(Notification.id)
                .where(
                    Notification.user_id == owner_id,
                    Notification.extra_data["dedupe_key"].as_string() == dedupe_key,
                )
                .limit(1)
            )
            if existing is not None:
                await self._safe_rollback()
                return False

            notification = await self._create(
                owner_id=owner_id,
                job_id=job_id,
                name=name,
                state=state,
                dedupe_key=dedupe_key,
                event_key=EVENT_KEY,
            )
            if notification is None:
                # A preference entry for this new event key could suppress
                # in-app delivery. Fall back to the default in-app-only channel
                # (event_key=None) without forcing email, webhook, or push.
                notification = await self._create(
                    owner_id=owner_id,
                    job_id=job_id,
                    name=name,
                    state=state,
                    dedupe_key=dedupe_key,
                    event_key=None,
                )
            if notification is None:
                await self._safe_rollback()
                return False
            logger.info(
                "Batch job completion notification created",
                extra={
                    "job_id": str(job_id),
                    "terminal_state": state,
                },
            )
            return True
        except Exception as exc:
            await self._safe_rollback()
            logger.warning(
                "Batch job completion notification deferred",
                extra={
                    "job_id": str(job_id),
                    "terminal_state": state,
                    "error_class": type(exc).__name__,
                },
            )
            return False

    async def _create(
        self,
        *,
        owner_id: uuid.UUID,
        job_id: uuid.UUID,
        name: str | None,
        state: str,
        dedupe_key: str,
        event_key: str | None,
    ) -> Notification | None:
        # Imported lazily because notification_service imports Celery tasks.
        from app.services.notification_service import NotificationService

        extra_data: dict[str, object] = {
            "dedupe_key": dedupe_key,
            "job_id": str(job_id),
            "terminal_state": state,
        }
        if event_key is None:
            # Keep the stored audit key meaningful while the preference lookup
            # uses the default in-app-only event.
            extra_data["event_key"] = EVENT_KEY
        return await NotificationService(self.db).create(
            user_id=owner_id,
            title=_title(state),
            message=_message(job_id, name, state),
            type=NOTIFICATION_TYPE,
            severity=_severity(state),
            action_url=f"/jobs/{job_id}",
            extra_data=extra_data,
            event_key=event_key,
        )

    async def _safe_rollback(self) -> None:
        try:
            await self.db.rollback()
        except Exception:
            pass


__all__ = [
    "BatchJobNotifier",
    "EVENT_KEY",
    "TERMINAL_EVENT",
    "notification_dedupe_key",
    "notification_lock_key",
]
