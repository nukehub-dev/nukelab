# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Fenced operation heartbeat for crash-safe recovery.

The heartbeat runs independently of the operation's runtime/helper I/O. Each
tick opens a fresh short-lived session and performs one guarded update: the
operation must still be active and its fencing token must still match. Zero
affected rows means the operation completed, was cancelled, or changed
executors, so the task stops without mutating anything.

A heartbeat failure is logged without the exception message and retried on the
next tick. Heartbeats never fail the operation they observe.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import Table, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.batch_job import BatchJob
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore

logger = get_logger(__name__)

SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True)
class _OperationTarget:
    table: Table
    state_column: str
    active_states: tuple[str, ...]


_JOB_HEARTBEAT_STATES = ("starting", "running", "cancelling")

_TARGETS: dict[str, _OperationTarget] = {
    "launch": _OperationTarget(
        table=ServerLaunchOperation.__table__,
        state_column="state",
        active_states=("executing",),
    ),
    "backup": _OperationTarget(
        table=VolumeBackup.__table__,
        state_column="status",
        active_states=("in_progress",),
    ),
    "restore": _OperationTarget(
        table=VolumeRestore.__table__,
        state_column="status",
        active_states=("in_progress",),
    ),
    "job": _OperationTarget(
        table=BatchJob.__table__,
        state_column="state",
        active_states=_JOB_HEARTBEAT_STATES,
    ),
}


def _target(kind: str) -> _OperationTarget:
    try:
        return _TARGETS[kind]
    except KeyError:
        raise ValueError(f"Unsupported operation heartbeat kind: {kind}") from None


def _application_session_factory() -> SessionFactory:
    """Resolve the process-wide session factory lazily for test seams."""
    from app.db.session import AsyncSessionLocal

    return AsyncSessionLocal


def _log_write_failure(exc: BaseException, *, kind: str, operation_id: uuid.UUID) -> None:
    logger.warning(
        "Operation heartbeat write failed (%s); will retry on the next tick",
        type(exc).__name__,
        extra={"kind": kind, "operation_id": str(operation_id)},
    )


async def _update_heartbeat(
    session_factory: SessionFactory,
    target: _OperationTarget,
    operation_id: uuid.UUID,
    fencing_token: uuid.UUID,
    executor_id: uuid.UUID | None,
) -> bool:
    """Refresh one active fenced row; return False when it no longer matches."""
    values: dict[str, object] = {"heartbeat_at": utc_now()}
    if executor_id is not None:
        values["executor_id"] = executor_id
    statement = (
        update(target.table)
        .where(
            target.table.c.id == operation_id,
            target.table.c.fencing_token == fencing_token,
            target.table.c[target.state_column].in_(target.active_states),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(statement)
        return bool(result.rowcount)


async def _run_heartbeat(
    session_factory: SessionFactory,
    target: _OperationTarget,
    *,
    kind: str,
    operation_id: uuid.UUID,
    fencing_token: uuid.UUID,
    executor_id: uuid.UUID | None,
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    """Wait for the next interval, then beat until the row stops matching."""
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
        else:
            return
        try:
            active = await _update_heartbeat(
                session_factory,
                target,
                operation_id,
                fencing_token,
                executor_id,
            )
        except Exception as exc:
            _log_write_failure(exc, kind=kind, operation_id=operation_id)
            continue
        if not active:
            return


@asynccontextmanager
async def operation_heartbeat(
    session_factory: SessionFactory | None = None,
    *,
    kind: str,
    operation_id: uuid.UUID,
    fencing_token: uuid.UUID,
    executor_id: uuid.UUID | None,
    interval: float | None = None,
):
    """Refresh ``heartbeat_at`` while the fenced operation row stays active.

    ``kind`` selects the journal table and its active states. The caller passes
    the process executor identity from :func:`current_executor_id`; ``None``
    leaves any recorded executor unchanged and is used by tests or legacy
    paths without a registered worker heartbeat.

    The first beat runs before the context body, so a slow operation starts
    with a fresh heartbeat. A terminal row or a changed fence stops the task
    quietly. Database failures are logged by exception class only and retried
    on the next tick; they never propagate to the operation.
    """
    target = _target(kind)
    interval_seconds = (
        float(settings.operation_heartbeat_interval_seconds)
        if interval is None
        else float(interval)
    )
    if interval_seconds <= 0:
        raise ValueError("Operation heartbeat interval must be positive.")

    factory = session_factory or _application_session_factory()
    try:
        active = await _update_heartbeat(
            factory,
            target,
            operation_id,
            fencing_token,
            executor_id,
        )
    except Exception as exc:
        _log_write_failure(exc, kind=kind, operation_id=operation_id)
        active = True

    if not active:
        # The operation already finished or another executor owns the fence.
        yield
        return

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _run_heartbeat(
            factory,
            target,
            kind=kind,
            operation_id=operation_id,
            fencing_token=fencing_token,
            executor_id=executor_id,
            interval_seconds=interval_seconds,
            stop_event=stop_event,
        )
    )
    try:
        yield
    finally:
        stop_event.set()
        with contextlib.suppress(asyncio.CancelledError):
            await task
