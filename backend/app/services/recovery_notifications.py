# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Owner notifications for proof-backed recovery transitions.

The operation journal stays authoritative: notifications are a best-effort
side effect that never changes a state, releases a reservation, or fails a
reconciliation scan. Deliveries carry only bounded identifiers, a safe reason
code, and a destination reference -- never request payloads, mounts,
environment values, container identities, tokens, or raw paths/exceptions.

Deduplication is persisted in the existing notification rows:

- one attention notification per operation and terminal state;
- one completion notification per operation, only after an attention event;
- at most one reminder per operation per ``RECOVERY_REMINDER_AFTER`` window.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utc_now
from app.models.notification import Notification
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.services.operation_reconciliation import OperationKind, ReconcileDecision

logger = logging.getLogger(__name__)

RECOVERY_EVENT_ATTENTION = "attention"
RECOVERY_EVENT_REMINDER = "reminder"
RECOVERY_EVENT_COMPLETED = "completed"

RECOVERY_REMINDER_AFTER = timedelta(hours=24)
RECOVERY_REMINDER_BATCH_LIMIT = 100

# Existing user-preference keys are reused so recovery mail/webhook/push
# delivery follows the same opt-in rules as ordinary server/volume events.
_LAUNCH_ATTENTION_EVENT_KEY = "server_failed"
_LAUNCH_COMPLETED_EVENT_KEY = "server_ready"
_VOLUME_ATTENTION_EVENT_KEY = "volume_recovery_failed"
_VOLUME_COMPLETED_EVENT_KEY = "volume_recovery_completed"

_SAFE_REASON_RE = re.compile(r"[a-z][a-z0-9_]{0,99}\Z")

_ATTENTION_STATES = {
    OperationKind.LAUNCH: frozenset({"failed", "uncertain"}),
    OperationKind.BACKUP: frozenset({"failed", "recovery_required"}),
    OperationKind.RESTORE: frozenset({"failed", "recovery_required"}),
}
_COMPLETED_STATES = {
    OperationKind.LAUNCH: "succeeded",
    OperationKind.BACKUP: "completed",
    OperationKind.RESTORE: "completed",
}
_REMINDER_STATES = {
    OperationKind.LAUNCH: "uncertain",
    OperationKind.BACKUP: "recovery_required",
    OperationKind.RESTORE: "recovery_required",
}


@dataclass(frozen=True, slots=True)
class RecoveryReminderReport:
    """Bounded counters for one reminder sweep; never row payloads."""

    scanned: int = 0
    sent: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "sent": self.sent,
            "skipped": self.skipped,
        }


@dataclass(frozen=True, slots=True)
class _Target:
    user_id: UUID
    state: str
    notification_type: str
    action_url: str
    destination: dict[str, str]
    reason_code: str | None


def _safe_reason_code(value) -> str | None:
    if isinstance(value, str) and _SAFE_REASON_RE.fullmatch(value):
        return value
    return None


def _normalized_state(kind: OperationKind, value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    state = value.strip().lower()
    if kind is OperationKind.LAUNCH:
        # Persisted launch recovery state is ``uncertain``; accept the
        # contract wording as an alias so a retried notification keeps one key.
        if state == "recovery_required":
            return "uncertain"
        if state == "completed":
            return "succeeded"
    return state or None


def _decision_state(decision: ReconcileDecision) -> str | None:
    terminal = decision.terminal_state
    if terminal is None:
        return None
    if decision.kind is OperationKind.LAUNCH and terminal.value == "recovery_required":
        return "uncertain"
    if decision.kind is not OperationKind.LAUNCH and terminal.value == "succeeded":
        return "completed"
    return terminal.value


def _event_key(kind: OperationKind, event: str) -> str:
    if event == RECOVERY_EVENT_COMPLETED:
        if kind is OperationKind.LAUNCH:
            return _LAUNCH_COMPLETED_EVENT_KEY
        return _VOLUME_COMPLETED_EVENT_KEY
    if kind is OperationKind.LAUNCH:
        return _LAUNCH_ATTENTION_EVENT_KEY
    return _VOLUME_ATTENTION_EVENT_KEY


def _label(kind: OperationKind) -> str:
    if kind is OperationKind.LAUNCH:
        return "server operation"
    if kind is OperationKind.BACKUP:
        return "volume backup"
    return "volume restore"


def _title(kind: OperationKind, event: str, state: str) -> str:
    if kind is OperationKind.LAUNCH:
        if event == RECOVERY_EVENT_COMPLETED:
            return "Server operation recovered"
        if event == RECOVERY_EVENT_REMINDER:
            return "Server operation still needs attention"
        if state == "failed":
            return "Server launch failed"
        return "Server operation needs attention"
    prefix = "Volume backup" if kind is OperationKind.BACKUP else "Volume restore"
    if event == RECOVERY_EVENT_COMPLETED:
        return f"{prefix} recovered"
    if event == RECOVERY_EVENT_REMINDER:
        return f"{prefix} still needs attention"
    if state == "failed":
        return f"{prefix} failed"
    return f"{prefix} needs attention"


def _message(kind: OperationKind, event: str, state: str, reason: str | None) -> str:
    label = _label(kind)
    if event == RECOVERY_EVENT_COMPLETED:
        base = f"Your {label} completed successfully after recovery review."
    elif event == RECOVERY_EVENT_REMINDER:
        base = f"Your {label} is still waiting for recovery review."
    elif state == "failed":
        base = f"Your {label} failed. Review recovery history for details."
    else:
        base = (
            f"Your {label} could not be verified automatically. "
            "Review its recovery status for details."
        )
    if reason:
        return f"{base} Reason code: {reason}."
    return base


class RecoveryNotifier:
    """Best-effort owner notifications for applied recovery transitions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def notify_applied(
        self,
        decision: ReconcileDecision,
        *,
        applied_state: str | None = None,
    ) -> bool:
        """Notify the owner when ``decision`` applied a terminal transition.

        Returns ``True`` only when a notification row was written. Every
        failure is swallowed and logged without the exception message.
        """
        kind = getattr(decision, "kind", None)
        operation_id = getattr(decision, "operation_id", None)
        try:
            if not isinstance(kind, OperationKind):
                return False
            if not isinstance(operation_id, UUID):
                return False
            state = _normalized_state(kind, applied_state or _decision_state(decision))
            if state is None:
                return False
            target = await self._load_target(kind, operation_id)
            if target is None:
                return False
            # The committed journal row is authoritative: a volume failure can
            # be degraded to ``recovery_required`` by the finalizer even when
            # the inspection decision said ``failed``.
            state = _normalized_state(kind, target.state) or state
            if state in _ATTENTION_STATES[kind]:
                event = RECOVERY_EVENT_ATTENTION
            elif state == _COMPLETED_STATES[kind]:
                if not await self._exists(
                    user_id=target.user_id,
                    kind=kind,
                    operation_id=operation_id,
                    event=RECOVERY_EVENT_ATTENTION,
                ):
                    # Routine successes are not recovery events.
                    return False
                event = RECOVERY_EVENT_COMPLETED
            else:
                return False
            if await self._exists(
                user_id=target.user_id,
                kind=kind,
                operation_id=operation_id,
                event=event,
                terminal_state=state,
                dedupe_completed=event == RECOVERY_EVENT_COMPLETED,
            ):
                return False
            return await self._deliver(target, kind, operation_id, event, state)
        except Exception as exc:
            await self._safe_rollback()
            logger.warning(
                "Recovery notification failed",
                extra={
                    "kind": str(getattr(kind, "value", kind)),
                    "operation_id": str(operation_id),
                    "error_class": type(exc).__name__,
                },
            )
            return False

    async def notify_reminder(
        self,
        kind: OperationKind,
        operation_id: UUID,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Send one bounded reminder for a still-unresolved recovery row."""
        try:
            if not isinstance(kind, OperationKind) or not isinstance(operation_id, UUID):
                return False
            state = _REMINDER_STATES[kind]
            current = now or utc_now()
            target = await self._load_target(kind, operation_id)
            if target is None or _normalized_state(kind, target.state) != state:
                return False
            if await self._exists(
                user_id=target.user_id,
                kind=kind,
                operation_id=operation_id,
                event=RECOVERY_EVENT_REMINDER,
                since=current - RECOVERY_REMINDER_AFTER,
            ):
                return False
            return await self._deliver(
                target,
                kind,
                operation_id,
                RECOVERY_EVENT_REMINDER,
                state,
            )
        except Exception as exc:
            await self._safe_rollback()
            logger.warning(
                "Recovery reminder notification failed",
                extra={
                    "kind": str(getattr(kind, "value", kind)),
                    "operation_id": str(operation_id),
                    "error_class": type(exc).__name__,
                },
            )
            return False

    async def _exists(
        self,
        *,
        user_id: UUID,
        kind: OperationKind,
        operation_id: UUID,
        event: str,
        terminal_state: str | None = None,
        since: datetime | None = None,
        dedupe_completed: bool = False,
    ) -> bool:
        conditions = [
            Notification.user_id == user_id,
            Notification.extra_data["operation_id"].as_string() == str(operation_id),
            Notification.extra_data["operation_kind"].as_string() == kind.value,
            Notification.extra_data["recovery_event"].as_string() == event,
        ]
        if terminal_state is not None and not dedupe_completed:
            conditions.append(
                Notification.extra_data["terminal_state"].as_string() == terminal_state
            )
        if since is not None:
            conditions.append(Notification.created_at >= since)
        found = await self.db.scalar(select(Notification.id).where(*conditions).limit(1))
        return found is not None

    async def _load_target(
        self,
        kind: OperationKind,
        operation_id: UUID,
    ) -> _Target | None:
        if kind is OperationKind.LAUNCH:
            row = await self.db.get(ServerLaunchOperation, operation_id, populate_existing=True)
            if row is None or row.owner_id is None:
                return None
            return _Target(
                user_id=row.owner_id,
                state=row.state,
                notification_type="server",
                action_url=f"/servers/{row.server_id}",
                destination={"server_id": str(row.server_id)},
                reason_code=_safe_reason_code(row.reason_code),
            )
        model = VolumeBackup if kind is OperationKind.BACKUP else VolumeRestore
        row = await self.db.get(model, operation_id, populate_existing=True)
        if row is None or row.user_id is None:
            return None
        destination = (
            {"backup_id": str(row.id)}
            if kind is OperationKind.BACKUP
            else {"restore_id": str(row.id)}
        )
        return _Target(
            user_id=row.user_id,
            state=row.status,
            notification_type="volume",
            action_url="/volumes",
            destination=destination,
            reason_code=_safe_reason_code(row.reason_code),
        )

    async def _deliver(
        self,
        target: _Target,
        kind: OperationKind,
        operation_id: UUID,
        event: str,
        state: str,
    ) -> bool:
        # Imported lazily: notification_service imports the Celery task module
        # at import time, which already imports the reconciler.
        from app.services.notification_service import NotificationService

        reason = target.reason_code if event != RECOVERY_EVENT_COMPLETED else None
        extra_data: dict[str, object] = {
            "recovery_event": event,
            "operation_kind": kind.value,
            "operation_id": str(operation_id),
            "terminal_state": state,
            **target.destination,
        }
        if reason is not None:
            extra_data["reason_code"] = reason
        notification = await NotificationService(self.db).create(
            user_id=target.user_id,
            title=_title(kind, event, state),
            message=_message(kind, event, state, reason),
            type=target.notification_type,
            severity="success" if event == RECOVERY_EVENT_COMPLETED else "warning",
            action_url=target.action_url,
            extra_data=extra_data,
            event_key=_event_key(kind, event),
        )
        if notification is None:
            return False
        logger.info(
            "Recovery notification created",
            extra={
                "kind": kind.value,
                "operation_id": str(operation_id),
                "event": event,
                "terminal_state": state,
            },
        )
        return True

    async def _safe_rollback(self) -> None:
        try:
            await self.db.rollback()
        except Exception:
            pass


async def send_recovery_reminders(
    db: AsyncSession,
    *,
    limit: int = RECOVERY_REMINDER_BATCH_LIMIT,
    now: datetime | None = None,
) -> RecoveryReminderReport:
    """Send bounded reminders for recovery rows older than 24 hours.

    A selection query failure propagates to the caller so the next scheduled
    run can retry untouched rows. Individual notification failures are
    contained by ``RecoveryNotifier``.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if limit < 1:
        return RecoveryReminderReport()

    current = now or utc_now()
    cutoff = current - RECOVERY_REMINDER_AFTER
    candidates: list[tuple[datetime | None, OperationKind, uuid.UUID, str]] = []

    for kind, model, state in (
        (OperationKind.LAUNCH, ServerLaunchOperation, "uncertain"),
        (OperationKind.BACKUP, VolumeBackup, "recovery_required"),
        (OperationKind.RESTORE, VolumeRestore, "recovery_required"),
    ):
        state_column = model.state if kind is OperationKind.LAUNCH else model.status
        rows = (
            await db.execute(
                select(model.id, model.created_at)
                .where(state_column == state, model.created_at <= cutoff)
                .order_by(model.created_at.asc(), model.id.asc())
                .limit(limit)
            )
        ).all()
        candidates.extend((row[1], kind, row[0], state) for row in rows)

    candidates.sort(key=lambda item: (item[0] or datetime.min, str(item[2])))
    selected = candidates[:limit]

    notifier = RecoveryNotifier(db)
    sent = 0
    skipped = 0
    for _, kind, operation_id, _state in selected:
        if await notifier.notify_reminder(kind, operation_id, now=current):
            sent += 1
        else:
            skipped += 1

    report = RecoveryReminderReport(
        scanned=len(selected),
        sent=sent,
        skipped=skipped,
    )
    logger.info("Recovery reminder sweep complete", extra=report.as_dict())
    return report
