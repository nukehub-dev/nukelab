# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Headless batch-job create/start checkpoints and observed launch state.

The runtime rehydrates only the admitted job journal: the frozen revision
snapshot supplies the command environment and toolchain layout, while the
runtime identity supplies the exact image. It never re-resolves a mutable image
tag or re-authorizes a revoked revision. Every external call is preceded by a
durable checkpoint, and an ambiguous response never authorizes another create
or start.
"""

from __future__ import annotations

import copy
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import (
    ContainerDriver,
    ContainerDriverError,
    ImmutableToolchainCacheError,
)
from app.core.logging import get_logger
from app.core.time_utils import utc_now
from app.models.batch_job import TERMINAL_JOB_STATES, BatchJob
from app.models.volume import Volume
from app.services.admission_service import acquire_admission_lock
from app.services.batch_job_admission_service import (
    BatchJobAdmissionService,
)
from app.services.batch_job_finalizer import BatchJobFinalizer
from app.services.operation_heartbeat import operation_heartbeat
from app.services.worker_heartbeat import current_executor_id

logger = get_logger(__name__)

ACTIVE_RUNTIME_STATES = ("starting", "running", "cancelling")
_ACTIVE_STATES = frozenset(ACTIVE_RUNTIME_STATES)
_TERMINAL_STATES = frozenset(TERMINAL_JOB_STATES)
_FIXED_ENV_KEYS = frozenset({"HOME", "TMPDIR", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED"})
_PLATFORM_ENV_PREFIXES = (
    "NUKELAB_AUTH_",
    "NUKELAB_SERVER_",
    "JWT_",
    "DATABASE_",
    "REDIS_",
    "CELERY_",
    "SMTP_",
)
_ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ENV_REFERENCE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_LOG_TAIL_LINES = 5000
_PROOF_RUNTIME = "runtime"
_PROOF_CONTROL = "control_plane"
_PROOF_ARTIFACT = "artifact"


@dataclass(frozen=True, slots=True)
class JobStateSnapshot:
    """Plain fields rehydrated from the admitted job row."""

    job_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    state: str
    reason_code: str | None
    argv: tuple[str, ...]
    max_runtime_seconds: int
    revision_snapshot: dict
    plan_snapshot: dict
    volume_snapshot: dict
    volume_name: str | None
    runtime_identity: dict
    reserved_cpu: float | None
    reserved_memory_mib: int | None
    reserved_disk_mib: int | None
    container_id: str | None
    container_name: str | None
    fencing_token: uuid.UUID
    volume_fencing_token: uuid.UUID | None
    volume_operation_id: uuid.UUID | None
    volume_id: uuid.UUID | None
    reservation_active: bool
    create_requested_at: datetime | None
    start_requested_at: datetime | None
    start_observed_at: datetime | None
    started_at: datetime | None
    deadline_at: datetime | None
    stop_requested_at: datetime | None
    heartbeat_at: datetime | None
    executor_id: uuid.UUID | None
    finished_at: datetime | None
    exit_code: int | None
    cleanup_state: str
    cleanup_attempts: int
    log_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class RuntimeStartResult:
    job_id: uuid.UUID
    action: str
    container_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ContainerLookup:
    status: str
    container_id: str | None = None
    info: dict | None = None


@dataclass(frozen=True, slots=True)
class LogCapture:
    state: str
    text: str | None
    truncated: bool
    size_bytes: int
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class _Prepared:
    mounts: list[dict]
    env: dict[str, str]
    limits: dict


@dataclass(frozen=True, slots=True)
class _Checkpoint:
    action: str
    snapshot: JobStateSnapshot | None = None


def _status(error: BaseException) -> int | None:
    value = getattr(error, "status", None)
    return value if isinstance(value, int) else None


def _error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    message = str(error)
    return message if message else type(error).__name__


def _is_validation_error(error: BaseException) -> bool:
    return isinstance(error, ContainerDriverError) and str(error).startswith(
        "Invalid batch job request:"
    )


def _runtime_time(value: object) -> datetime | None:
    """Parse Docker's RFC3339 timestamps, rejecting its zero value."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    if parsed.year <= 1:
        return None
    return parsed


def _labels(info: dict) -> dict:
    config = info.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    return labels if isinstance(labels, dict) else {}


def _state(info: dict) -> dict:
    value = info.get("State")
    return value if isinstance(value, dict) else {}


def container_status(info: dict) -> str:
    """Return created, running, exited/dead, or an unexpected state name."""
    state = _state(info)
    raw = str(state.get("Status") or "").lower()
    if state.get("Running") is True or raw == "running":
        return "running"
    if bool(state.get("FinishedAt")) and _runtime_time(state.get("FinishedAt")) is not None:
        return "exited"
    if raw in ("exited", "dead"):
        return "exited"
    if raw == "created":
        return "created"
    if raw:
        return raw
    return "unknown"


def validate_job_container(job: JobStateSnapshot, info: dict) -> str | None:
    """Validate the deterministic ownership labels and admitted image identity."""
    labels = _labels(info)
    if labels.get("nukelab.job.id") != str(job.job_id):
        return "identity_mismatch"
    if labels.get("nukelab.job.fence") != str(job.fencing_token):
        return "identity_mismatch"
    if labels.get("nukelab.workload") != "job":
        return "identity_mismatch"
    expected_image = job.runtime_identity.get("local_id")
    if isinstance(expected_image, str) and info.get("Image") != expected_image:
        return "identity_mismatch"
    expected_name = job.container_name
    actual_name = info.get("Name")
    if (
        isinstance(expected_name, str)
        and isinstance(actual_name, str)
        and actual_name.lstrip("/") != expected_name
    ):
        return "identity_mismatch"
    return None


def sanitize_environment(configuration: dict) -> dict[str, str]:
    """Keep approved template variables but never platform auth/server secrets."""
    raw = configuration.get("environment_variables")
    if not isinstance(raw, dict):
        return {}
    environment: dict[str, str] = {}
    for key, value in raw.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not _ENV_KEY_RE.fullmatch(key)
            or key in _FIXED_ENV_KEYS
            or key.startswith(_PLATFORM_ENV_PREFIXES)
            or len(value) > 8192
            or "\x00" in value
        ):
            continue
        environment[key] = value
    return environment


def _expand_env_vars(value: str, environment: dict[str, str]) -> str:
    def replace_reference(match: re.Match[str]) -> str:
        return environment.get(match.group(1), "")

    return _ENV_REFERENCE_RE.sub(replace_reference, value)


def _cpu_count(cpu: float | None) -> int:
    try:
        value = int(cpu or 1)
    except (TypeError, ValueError):
        value = 1
    return max(1, value)


def _bounded_limits(snapshot: JobStateSnapshot) -> dict:
    memory_mib = int(snapshot.reserved_memory_mib or 0)
    if memory_mib <= 0:
        memory_mib = 512
    return {
        "cpu": max(0.1, float(snapshot.reserved_cpu or 1.0)),
        "memory_bytes": memory_mib * 1024**2,
        "pids_limit": settings.batch_jobs_pids_limit,
        "tmpfs_bytes": settings.batch_jobs_tmpfs_bytes,
    }


def capture_tail(logs: str, *, now: datetime | None = None) -> LogCapture:
    """Encode before truncation so malformed output cannot raise or overrun."""
    raw = logs if isinstance(logs, str) else str(logs)
    encoded = raw.encode("utf-8", errors="replace")
    size_bytes = len(encoded)
    limit = settings.batch_jobs_log_tail_bytes
    truncated = size_bytes > limit
    if truncated:
        text = encoded[-limit:].decode("utf-8", errors="ignore")
    else:
        text = raw.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    expires_at = (now or utc_now()) + timedelta(seconds=settings.batch_jobs_log_retention_seconds)
    return LogCapture(
        state="truncated" if truncated else "available",
        text=text,
        truncated=truncated,
        size_bytes=size_bytes,
        expires_at=expires_at,
    )


class BatchJobRuntimeService:
    """Create and start exactly one admitted headless job container."""

    def __init__(
        self,
        db: AsyncSession,
        driver: ContainerDriver,
        *,
        admission: BatchJobAdmissionService | None = None,
        finalizer: BatchJobFinalizer | None = None,
    ):
        self.db = db
        self.driver = driver
        self.admission = admission or BatchJobAdmissionService(db, driver)
        self.finalizer = finalizer or BatchJobFinalizer(db, driver, admission=self.admission)

    async def _clean_session(self) -> None:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Batch job runtime requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    @asynccontextmanager
    async def _heartbeat(self, snapshot: JobStateSnapshot):
        """Refresh only active fenced job rows during long runtime I/O."""
        async with operation_heartbeat(
            kind="job",
            operation_id=snapshot.job_id,
            fencing_token=snapshot.fencing_token,
            executor_id=current_executor_id(),
        ):
            yield

    async def load(self, job_id: uuid.UUID) -> JobStateSnapshot | None:
        """Read the journal and the immutable volume identity in one snapshot."""
        await self._clean_session()
        async with self.db.begin():
            job = await self.db.scalar(
                select(BatchJob)
                .where(BatchJob.id == job_id)
                .execution_options(populate_existing=True)
            )
            if job is None:
                return None
            volume_name = (
                await self.db.scalar(select(Volume.name).where(Volume.id == job.volume_id))
                if job.volume_id is not None
                else None
            )
            return _snapshot(job, volume_name=volume_name)

    async def start(self, job_id: uuid.UUID) -> RuntimeStartResult:
        """Resume the admitted job without ever re-creating or re-starting it."""
        snapshot = await self.load(job_id)
        if snapshot is None:
            return RuntimeStartResult(job_id=job_id, action="noop", detail="job_not_found")
        if snapshot.state not in _ACTIVE_STATES or not snapshot.reservation_active:
            return RuntimeStartResult(job_id=job_id, action="noop", detail="not_active")
        if snapshot.state == "cancelling" or snapshot.stop_requested_at is not None:
            return await self.cancel_before_start(snapshot)
        if snapshot.state != "starting":
            return RuntimeStartResult(job_id=job_id, action="noop", detail="not_starting")
        if snapshot.container_id is not None or snapshot.create_requested_at is not None:
            # A prior executor may have claimed preparation or created a
            # runtime. Never prepare or create again; inspect the deterministic
            # identity and let the monitor start only a container with no start
            # checkpoint.
            return await self._observe_existing(snapshot)

        # Claim the preparation itself before any toolchain/volume helper I/O.
        # A duplicate task or monitor that sees this claim must only inspect.
        checkpoint = await self._checkpoint_create(snapshot)
        if checkpoint.action == "cancelled":
            return await self.cancel_before_start(checkpoint.snapshot or snapshot)
        if checkpoint.action == "existing":
            return await self._observe_existing(checkpoint.snapshot or snapshot)
        if checkpoint.action != "create" or checkpoint.snapshot is None:
            return RuntimeStartResult(job_id=job_id, action="noop", detail=checkpoint.action)

        claimed = checkpoint.snapshot
        prepared = None
        async with self._heartbeat(claimed):
            prepared = await self._prepare(claimed)
        if isinstance(prepared, RuntimeStartResult):
            return prepared
        if prepared is None:
            return RuntimeStartResult(job_id=job_id, action="noop", detail="preparation_deferred")

        # Re-read before the actual create. Cancellation that landed during
        # preparation is safe to settle because this executor owns the claim
        # and no create has been issued yet.
        before_create = await self._checkpoint_pre_create(claimed)
        if before_create.action == "cancelled":
            return await self._cancel_claimed_before_create(before_create.snapshot or claimed)
        if before_create.action == "existing":
            return await self._observe_existing(before_create.snapshot or claimed)
        if before_create.action != "create" or before_create.snapshot is None:
            return RuntimeStartResult(job_id=job_id, action="noop", detail=before_create.action)
        return await self._create_and_start(before_create.snapshot, prepared)

    async def start_created(self, job_id: uuid.UUID, container_id: str) -> RuntimeStartResult:
        """Start a container that was created before its start checkpoint."""
        snapshot = await self.load(job_id)
        if snapshot is None:
            return RuntimeStartResult(job_id=job_id, action="noop", detail="job_not_found")
        if (
            snapshot.state != "starting"
            or not snapshot.reservation_active
            or snapshot.start_requested_at is not None
        ):
            return RuntimeStartResult(job_id=job_id, action="noop", detail="not_startable")
        if snapshot.state == "cancelling" or snapshot.stop_requested_at is not None:
            return await self.cancel_before_start(snapshot)
        lookup = await self.lookup_container(snapshot)
        if lookup.status != "found" or lookup.container_id != container_id:
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        checkpoint = await self._checkpoint_start(snapshot)
        if checkpoint.action == "cancelled":
            return await self.cancel_before_start(checkpoint.snapshot or snapshot)
        if checkpoint.action == "existing":
            return await self._observe_after_start(checkpoint.snapshot or snapshot)
        if checkpoint.action != "start" or checkpoint.snapshot is None:
            return RuntimeStartResult(job_id=job_id, action="noop", detail=checkpoint.action)
        return await self._start_container(checkpoint.snapshot, container_id)

    async def _prepare(self, snapshot: JobStateSnapshot) -> _Prepared | RuntimeStartResult | None:
        image = _runtime_image(snapshot)
        if image is None:
            return await self._fail_terminal(snapshot, "runtime_unverifiable", _PROOF_CONTROL)
        volume_name = snapshot.volume_name
        if not isinstance(volume_name, str) or not volume_name:
            return await self._fail_terminal(snapshot, "volume_unavailable", _PROOF_CONTROL)
        try:
            volume = await self.driver.get_volume(volume_name)
        except Exception as exc:
            logger.warning(
                "Batch job volume inspection deferred",
                extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
            )
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        if volume is None:
            return await self._fail_terminal(snapshot, "volume_unavailable", _PROOF_CONTROL)

        mounts = [
            {
                "Type": "volume",
                "Source": volume_name,
                "Target": "/work",
                "ReadOnly": False,
            }
        ]
        configuration = (
            copy.deepcopy(snapshot.revision_snapshot.get("configuration"))
            if isinstance(snapshot.revision_snapshot.get("configuration"), dict)
            else {}
        )
        environment = sanitize_environment(configuration)
        cpu_count = _cpu_count(snapshot.reserved_cpu)
        environment["NUKELAB_JOB_ID"] = str(snapshot.job_id)
        environment["NUKELAB_JOB_NAME"] = snapshot.name
        environment["NUKELAB_USER_ID"] = str(snapshot.owner_id)
        environment["NUKELAB_CPU_COUNT"] = str(cpu_count)
        environment["OMP_NUM_THREADS"] = str(cpu_count)

        toolchain_identity = snapshot.revision_snapshot.get("toolchain_identity")
        if toolchain_identity is not None:
            prepared = await self._prepare_toolchain(
                snapshot, toolchain_identity, configuration, environment
            )
            if isinstance(prepared, RuntimeStartResult):
                return prepared
            if prepared is None:
                return None
            mount, manifest, toolchain_image = prepared
            mounts.append(mount)
            await self._apply_toolchain_environment(
                snapshot, toolchain_image, manifest, environment
            )

        try:
            await self.driver.prepare_batch_volume(
                name=f"nukelab-job-prep-{snapshot.job_id}",
                image=image,
                volume=volume_name,
                labels={
                    "nukelab.managed": "true",
                    "nukelab.batch.prep": str(snapshot.job_id),
                },
                timeout_seconds=settings.batch_jobs_stop_timeout_seconds,
            )
        except ContainerDriverError as exc:
            code = _error_code(exc)
            if code == "batch_volume_prepare_unknown":
                return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
            if code == "batch_volume_prepare_failed":
                return await self._fail_terminal(snapshot, "volume_unavailable", _PROOF_CONTROL)
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        except Exception as exc:
            logger.warning(
                "Batch job volume preparation deferred",
                extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
            )
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")

        return _Prepared(mounts=mounts, env=environment, limits=_bounded_limits(snapshot))

    async def _prepare_toolchain(
        self,
        snapshot: JobStateSnapshot,
        identity: object,
        configuration: dict,
        environment: dict[str, str],
    ) -> tuple[dict, dict, str] | RuntimeStartResult | None:
        if not isinstance(identity, dict):
            return await self._fail_terminal(snapshot, "artifact_missing", _PROOF_ARTIFACT)
        image = identity.get("image") or identity.get("spawn_reference")
        if not isinstance(image, str):
            return await self._fail_terminal(snapshot, "artifact_missing", _PROOF_ARTIFACT)
        mounts = snapshot.revision_snapshot.get("toolchain_mounts")
        if not isinstance(mounts, list) or not mounts:
            configured = configuration.get("tool_mounts")
            mounts = configured if isinstance(configured, list) and configured else ["/opt/nuke"]
        if any(not isinstance(path, str) for path in mounts):
            return await self._fail_terminal(snapshot, "artifact_missing", _PROOF_ARTIFACT)
        try:
            cache_name = self.driver.immutable_toolchain_cache_name(identity, mounts)
        except ImmutableToolchainCacheError:
            return await self._fail_terminal(snapshot, "artifact_missing", _PROOF_ARTIFACT)
        try:
            manifest = await self.driver.prepare_immutable_toolchain_volume(
                image, cache_name, mounts
            )
        except ImmutableToolchainCacheError as exc:
            if exc.outcome_unknown:
                return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
            return await self._fail_terminal(snapshot, "artifact_missing", _PROOF_ARTIFACT)
        except Exception as exc:
            logger.warning(
                "Batch job toolchain preparation deferred",
                extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
            )
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        manifest_mounts = manifest.get("mounts") if isinstance(manifest, dict) else None
        if isinstance(manifest_mounts, list) and manifest_mounts != mounts:
            return await self._fail_terminal(snapshot, "artifact_missing", _PROOF_ARTIFACT)
        target = mounts[0]
        return (
            {
                "Type": "volume",
                "Source": cache_name,
                "Target": target,
                "ReadOnly": True,
            },
            manifest if isinstance(manifest, dict) else {},
            image,
        )

    async def _apply_toolchain_environment(
        self,
        snapshot: JobStateSnapshot,
        toolchain_image: str,
        manifest: dict,
        environment: dict[str, str],
    ) -> None:
        try:
            image_env = await self.driver.get_image_env(toolchain_image)
            if not isinstance(image_env, dict):
                image_env = {}
        except Exception:
            image_env = {}
        prepend = manifest.get("env_prepend")
        if isinstance(prepend, dict):
            for key, value in prepend.items():
                if (
                    not isinstance(key, str)
                    or not _ENV_KEY_RE.fullmatch(key)
                    or key in _FIXED_ENV_KEYS
                    or key.startswith(_PLATFORM_ENV_PREFIXES)
                ):
                    continue
                if not isinstance(value, str):
                    continue
                existing = environment.get(key) or image_env.get(key)
                environment[key] = f"{value}:{existing}" if existing else value
        values = manifest.get("env")
        if isinstance(values, dict):
            for key, value in values.items():
                if (
                    not isinstance(key, str)
                    or not _ENV_KEY_RE.fullmatch(key)
                    or key in _FIXED_ENV_KEYS
                    or key.startswith(_PLATFORM_ENV_PREFIXES)
                ):
                    continue
                if not isinstance(value, str):
                    continue
                expanded = _expand_env_vars(value, {**image_env, **environment})
                environment.setdefault(key, expanded)

    async def _checkpoint_create(self, snapshot: JobStateSnapshot) -> _Checkpoint:
        now = utc_now()
        executor_id = current_executor_id()
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(snapshot.job_id)
            if job is None or job.fencing_token != snapshot.fencing_token:
                return _Checkpoint("noop")
            if job.state not in _ACTIVE_STATES or not job.reservation_active:
                return _Checkpoint("noop")
            if job.state == "cancelling" or job.stop_requested_at is not None:
                return _Checkpoint("cancelled", _snapshot(job, volume_name=snapshot.volume_name))
            if job.container_id is not None or job.create_requested_at is not None:
                return _Checkpoint("existing", _snapshot(job, volume_name=snapshot.volume_name))
            job.create_requested_at = now
            job.executor_id = executor_id or job.executor_id
            job.heartbeat_at = now
            job.updated_at = now
            return _Checkpoint("create", _snapshot(job, volume_name=snapshot.volume_name))

    async def _checkpoint_pre_create(self, snapshot: JobStateSnapshot) -> _Checkpoint:
        """Revalidate the create claim immediately before the create call."""
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(snapshot.job_id)
            if job is None or job.fencing_token != snapshot.fencing_token:
                return _Checkpoint("noop")
            if job.state not in _ACTIVE_STATES or not job.reservation_active:
                return _Checkpoint("noop")
            if job.state == "cancelling" or job.stop_requested_at is not None:
                return _Checkpoint("cancelled", _snapshot(job, volume_name=snapshot.volume_name))
            if job.container_id is not None:
                return _Checkpoint("existing", _snapshot(job, volume_name=snapshot.volume_name))
            if job.create_requested_at is None:
                return _Checkpoint("noop")
            return _Checkpoint("create", _snapshot(job, volume_name=snapshot.volume_name))

    async def _cancel_claimed_before_create(self, snapshot: JobStateSnapshot) -> RuntimeStartResult:
        """Settle a cancellation while this executor still owns the create claim."""
        async with self._heartbeat(snapshot):
            lookup = await self.lookup_container(snapshot)
        if lookup.status == "missing":
            # No create was issued by this executor after the claim, so a
            # control-plane cancellation is safe and releases the guard.
            return await self._finalize_cancelled(snapshot)
        if lookup.status in ("unavailable", "mismatch"):
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        return await self.cancel_before_start(snapshot)

    async def _checkpoint_start(self, snapshot: JobStateSnapshot) -> _Checkpoint:
        now = utc_now()
        executor_id = current_executor_id()
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(snapshot.job_id)
            if job is None or job.fencing_token != snapshot.fencing_token:
                return _Checkpoint("noop")
            if job.state not in _ACTIVE_STATES or not job.reservation_active:
                return _Checkpoint("noop")
            if job.state == "cancelling" or job.stop_requested_at is not None:
                return _Checkpoint("cancelled", _snapshot(job, volume_name=snapshot.volume_name))
            if job.start_requested_at is not None:
                return _Checkpoint("existing", _snapshot(job, volume_name=snapshot.volume_name))
            job.start_requested_at = now
            job.executor_id = executor_id or job.executor_id
            job.heartbeat_at = now
            job.updated_at = now
            return _Checkpoint("start", _snapshot(job, volume_name=snapshot.volume_name))

    async def _create_and_start(
        self, snapshot: JobStateSnapshot, prepared: _Prepared
    ) -> RuntimeStartResult:
        image = _runtime_image(snapshot)
        if image is None:
            return await self._fail_terminal(snapshot, "runtime_unverifiable", _PROOF_CONTROL)
        try:
            async with self._heartbeat(snapshot):
                container_id = await self.driver.create_batch_container(
                    name=snapshot.container_name or f"nukelab-job-{snapshot.job_id}",
                    image=image,
                    argv=list(snapshot.argv),
                    mounts=prepared.mounts,
                    labels={
                        "nukelab.managed": "true",
                        "nukelab.workload": "job",
                        "nukelab.job.id": str(snapshot.job_id),
                        "nukelab.job.fence": str(snapshot.fencing_token),
                    },
                    limits=prepared.limits,
                    env=prepared.env,
                    workdir="/work",
                    timeout_seconds=snapshot.max_runtime_seconds,
                )
        except TimeoutError:
            return await self._resolve_uncertain_create(snapshot)
        except ContainerDriverError as exc:
            return await self._handle_create_error(snapshot, exc)
        except Exception as exc:
            logger.warning(
                "Batch job create outcome deferred",
                extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
            )
            return await self._resolve_uncertain_create(snapshot)

        if not isinstance(container_id, str) or not container_id:
            return await self._resolve_uncertain_create(snapshot)
        try:
            persisted = await self.persist_container_id(snapshot, container_id)
        except Exception as exc:
            logger.warning(
                "Batch job container identity was not recorded",
                extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
            )
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        if persisted is None:
            return RuntimeStartResult(job_id=snapshot.job_id, action="noop", detail="fenced_out")
        if persisted.state == "cancelling" or persisted.stop_requested_at is not None:
            return await self.cancel_before_start(persisted)
        checkpoint = await self._checkpoint_start(persisted)
        if checkpoint.action == "cancelled":
            return await self.cancel_before_start(checkpoint.snapshot or persisted)
        if checkpoint.action == "existing":
            return await self._observe_after_start(checkpoint.snapshot or persisted)
        if checkpoint.action != "start" or checkpoint.snapshot is None:
            return RuntimeStartResult(
                job_id=snapshot.job_id, action="noop", detail=checkpoint.action
            )
        return await self._start_container(checkpoint.snapshot, container_id)

    async def _handle_create_error(
        self, snapshot: JobStateSnapshot, error: ContainerDriverError
    ) -> RuntimeStartResult:
        status = _status(error)
        if status == 409:
            return await self._resolve_uncertain_create(snapshot)
        if _is_validation_error(error) or (status is not None and 400 <= status < 500):
            return await self._fail_terminal(snapshot, "runtime_unverifiable", _PROOF_CONTROL)
        return await self._resolve_uncertain_create(snapshot)

    async def _resolve_uncertain_create(self, snapshot: JobStateSnapshot) -> RuntimeStartResult:
        lookup = await self.lookup_container(snapshot)
        if lookup.status == "found" and lookup.container_id is not None:
            persisted = await self.persist_container_id(snapshot, lookup.container_id)
            if persisted is None:
                return RuntimeStartResult(
                    job_id=snapshot.job_id, action="noop", detail="fenced_out"
                )
            if persisted.state == "cancelling" or persisted.stop_requested_at is not None:
                return await self.cancel_before_start(persisted)
            checkpoint = await self._checkpoint_start(persisted)
            if checkpoint.action == "cancelled":
                return await self.cancel_before_start(checkpoint.snapshot or persisted)
            if checkpoint.action == "existing":
                return await self._observe_after_start(checkpoint.snapshot or persisted)
            if checkpoint.action == "start" and checkpoint.snapshot is not None:
                return await self._start_container(checkpoint.snapshot, lookup.container_id)
        return await self.mark_recovery(snapshot, reason="runtime_unverifiable")

    async def persist_container_id(
        self,
        snapshot: JobStateSnapshot,
        container_id: str,
        *,
        touch_heartbeat: bool = True,
        replace_existing: bool = False,
    ) -> JobStateSnapshot | None:
        now = utc_now()
        executor_id = current_executor_id()
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(snapshot.job_id)
            if job is None or job.fencing_token != snapshot.fencing_token:
                return None
            if job.state in _TERMINAL_STATES:
                return None
            if (
                job.container_id is not None
                and job.container_id != container_id
                and not replace_existing
            ):
                return None
            job.container_id = container_id
            if touch_heartbeat:
                job.executor_id = executor_id or job.executor_id
                job.heartbeat_at = now
            job.updated_at = now
            return _snapshot(job, volume_name=snapshot.volume_name)

    async def _start_container(
        self, snapshot: JobStateSnapshot, container_id: str
    ) -> RuntimeStartResult:
        try:
            async with self._heartbeat(snapshot):
                await self.driver.start_container(container_id)
        except TimeoutError:
            return await self._resolve_uncertain_start(snapshot)
        except ContainerDriverError as exc:
            status = _status(exc)
            if status in (304, 409):
                return await self._resolve_uncertain_start(snapshot)
            if (
                status == 404
                or _is_validation_error(exc)
                or (status is not None and 400 <= status < 500)
            ):
                return await self._fail_terminal(snapshot, "runtime_unverifiable", _PROOF_CONTROL)
            return await self._resolve_uncertain_start(snapshot)
        except Exception as exc:
            logger.warning(
                "Batch job start outcome deferred",
                extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
            )
            return await self._resolve_uncertain_start(snapshot)
        return await self._observe_after_start(snapshot)

    async def _resolve_uncertain_start(self, snapshot: JobStateSnapshot) -> RuntimeStartResult:
        lookup = await self.lookup_container(snapshot)
        if lookup.status != "found" or lookup.info is None:
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        status = container_status(lookup.info)
        if status == "running":
            return await self.persist_running(snapshot, lookup.info)
        if status == "exited":
            return await self.finalize_exit(snapshot, lookup.info)
        return await self.mark_recovery(snapshot, reason="runtime_unverifiable")

    async def _observe_after_start(self, snapshot: JobStateSnapshot) -> RuntimeStartResult:
        lookup = await self.lookup_container(snapshot)
        if lookup.status == "missing":
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        if lookup.status != "found" or lookup.info is None:
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        status = container_status(lookup.info)
        if status == "running":
            return await self.persist_running(snapshot, lookup.info)
        if status == "exited":
            return await self.finalize_exit(snapshot, lookup.info)
        return await self.mark_recovery(snapshot, reason="runtime_unverifiable")

    async def _observe_existing(self, snapshot: JobStateSnapshot) -> RuntimeStartResult:
        from app.services.batch_job_monitor import BatchJobMonitorService

        monitor = BatchJobMonitorService(
            self.db,
            self.driver,
            admission=self.admission,
            finalizer=self.finalizer,
        )
        observation = await monitor.observe_job(snapshot.job_id)
        return RuntimeStartResult(
            job_id=snapshot.job_id,
            action=observation.action,
            container_id=observation.container_id,
            detail=observation.detail,
        )

    async def cancel_before_start(self, snapshot: JobStateSnapshot) -> RuntimeStartResult:
        """Settle a cancellation without issuing a create or start."""
        async with self._heartbeat(snapshot):
            return await self._cancel_before_start(snapshot)

    async def _cancel_before_start(self, snapshot: JobStateSnapshot) -> RuntimeStartResult:
        lookup = await self.lookup_container(snapshot)
        if lookup.status == "unavailable":
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        if lookup.status == "mismatch":
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        if lookup.status == "missing":
            if snapshot.create_requested_at is not None:
                # A create may have reached the daemon even though its response
                # was lost; require reconciliation instead of releasing alone.
                return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
            return await self._finalize_cancelled(snapshot)
        if lookup.info is None or lookup.container_id is None:
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        status = container_status(lookup.info)
        if status == "running":
            return await self.stop_and_finalize(snapshot, lookup.container_id, forced="cancel")
        if status == "exited":
            return await self.finalize_exit(snapshot, lookup.info, forced="cancel")
        if status != "created":
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        try:
            await self.driver.delete_container(lookup.container_id, force=False)
        except ContainerDriverError as exc:
            if _status(exc) != 404:
                logger.warning(
                    "Batch job created-container cleanup retained",
                    extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
                )
        except Exception as exc:
            logger.warning(
                "Batch job created-container cleanup retained",
                extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
            )
        return await self._finalize_cancelled(snapshot)

    async def stop_and_finalize(
        self, snapshot: JobStateSnapshot, container_id: str, *, forced: str
    ) -> RuntimeStartResult:
        try:
            async with self._heartbeat(snapshot):
                await self.driver.stop_container(
                    container_id, timeout=settings.batch_jobs_stop_timeout_seconds
                )
        except ContainerDriverError as exc:
            status = _status(exc)
            if status == 404:
                return await self._finalize_without_runtime(snapshot, forced=forced)
            if status != 304:
                return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        except Exception as exc:
            logger.warning(
                "Batch job stop deferred",
                extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
            )
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        lookup = await self.lookup_container(snapshot)
        if lookup.status != "found" or lookup.info is None:
            if lookup.status == "missing":
                return await self._finalize_without_runtime(snapshot, forced=forced)
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        if container_status(lookup.info) == "running":
            return await self.mark_recovery(snapshot, reason="runtime_unverifiable")
        return await self.finalize_exit(snapshot, lookup.info, forced=forced)

    async def _finalize_cancelled(self, snapshot: JobStateSnapshot) -> RuntimeStartResult:
        now = utc_now()
        result = await self.finalizer.finalize(
            snapshot.job_id,
            fencing_token=snapshot.fencing_token,
            state="cancelled",
            outcome_code="cancelled",
            reason_code="request_cancelled",
            proof_class=_PROOF_CONTROL,
            executor_terminated=True,
            started_at=snapshot.started_at,
            finished_at=now,
            log_state="unavailable",
        )
        return _finalized_result(snapshot, "cancelled", result)

    async def _finalize_without_runtime(
        self, snapshot: JobStateSnapshot, *, forced: str
    ) -> RuntimeStartResult:
        now = utc_now()
        if forced == "deadline":
            state, outcome, reason = "timed_out", "timed_out", "job_deadline_exceeded"
        else:
            state, outcome, reason = "cancelled", "cancelled", "request_cancelled"
        result = await self.finalizer.finalize(
            snapshot.job_id,
            fencing_token=snapshot.fencing_token,
            state=state,
            outcome_code=outcome,
            reason_code=reason,
            proof_class=_PROOF_RUNTIME,
            executor_terminated=True,
            started_at=snapshot.started_at,
            finished_at=now,
            log_state="unavailable",
        )
        return _finalized_result(snapshot, outcome, result)

    async def finalize_exit(
        self,
        snapshot: JobStateSnapshot,
        info: dict,
        *,
        forced: str | None = None,
    ) -> RuntimeStartResult:
        container_id = snapshot.container_id
        if container_id is None:
            container_id = await self._container_id_from_info(snapshot, info)
        logs = await self._capture_logs(container_id)
        state, outcome, reason, exit_code, started_at, finished_at = _classify_exit(
            snapshot, info, forced=forced
        )
        result = await self.finalizer.finalize(
            snapshot.job_id,
            fencing_token=snapshot.fencing_token,
            state=state,
            outcome_code=outcome,
            reason_code=reason,
            proof_class=_PROOF_RUNTIME,
            exit_code=exit_code,
            executor_terminated=True,
            started_at=started_at,
            finished_at=finished_at,
            log_state=logs.state,
            log_text=logs.text,
            log_truncated=logs.truncated,
            log_size_bytes=logs.size_bytes,
            log_expires_at=logs.expires_at,
        )
        return _finalized_result(snapshot, outcome, result)

    async def _container_id_from_info(self, snapshot: JobStateSnapshot, info: dict) -> str | None:
        identifier = info.get("Id")
        if isinstance(identifier, str) and identifier:
            return identifier
        return snapshot.container_id

    async def _capture_logs(self, container_id: str | None) -> LogCapture:
        if not container_id:
            return LogCapture("unavailable", None, False, 0, None)
        try:
            logs = await self.driver.get_container_logs(container_id, tail=_LOG_TAIL_LINES)
        except Exception as exc:
            logger.warning(
                "Batch job log capture unavailable",
                extra={"error_class": type(exc).__name__},
            )
            return LogCapture("unavailable", None, False, 0, None)
        return capture_tail(logs)

    async def persist_running(self, snapshot: JobStateSnapshot, info: dict) -> RuntimeStartResult:
        observed_at = utc_now()
        state = _state(info)
        observed_started = _runtime_time(state.get("StartedAt")) or snapshot.started_at
        started_at = snapshot.started_at or observed_started or observed_at
        deadline_at = snapshot.deadline_at or (
            started_at + timedelta(seconds=int(snapshot.max_runtime_seconds))
        )
        executor_id = current_executor_id()
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(snapshot.job_id)
            if job is None or job.fencing_token != snapshot.fencing_token:
                return RuntimeStartResult(job_id=snapshot.job_id, action="noop")
            if job.state not in _ACTIVE_STATES:
                return RuntimeStartResult(job_id=snapshot.job_id, action="noop")
            if job.state == "starting":
                job.state = "running"
            job.start_observed_at = job.start_observed_at or observed_at
            job.started_at = job.started_at or started_at
            job.deadline_at = job.deadline_at or deadline_at
            job.heartbeat_at = observed_at
            job.executor_id = executor_id or job.executor_id
            job.updated_at = observed_at
            updated = _snapshot(job, volume_name=snapshot.volume_name)
        if updated.stop_requested_at is not None or updated.state == "cancelling":
            if updated.container_id:
                return await self.stop_and_finalize(updated, updated.container_id, forced="cancel")
            return await self.mark_recovery(updated, reason="runtime_unverifiable")
        return RuntimeStartResult(
            job_id=snapshot.job_id,
            action="running",
            container_id=updated.container_id,
        )

    async def lookup_container(self, snapshot: JobStateSnapshot) -> ContainerLookup:
        info: dict | None = None
        container_id = snapshot.container_id
        if container_id is not None:
            try:
                info = await self.driver.get_container_info(container_id)
            except ContainerDriverError as exc:
                if _status(exc) != 404:
                    return ContainerLookup("unavailable")
            except Exception:
                return ContainerLookup("unavailable")
        if info is None and snapshot.container_name:
            try:
                found = await self.driver.get_container_by_name(snapshot.container_name)
            except Exception:
                return ContainerLookup("unavailable")
            if found:
                container_id = found
                try:
                    info = await self.driver.get_container_info(found)
                except Exception:
                    return ContainerLookup("unavailable")
        if info is None:
            return ContainerLookup("missing")
        if validate_job_container(snapshot, info) is not None:
            return ContainerLookup("mismatch", container_id=container_id, info=info)
        identifier = info.get("Id")
        resolved = identifier if isinstance(identifier, str) and identifier else container_id
        return ContainerLookup("found", container_id=resolved, info=info)

    async def mark_recovery(self, snapshot: JobStateSnapshot, *, reason: str) -> RuntimeStartResult:
        try:
            await self.admission.mark_recovery_required(
                snapshot.job_id,
                fencing_token=snapshot.fencing_token,
                executor_id=current_executor_id(),
                reason_code=reason,
            )
        except Exception as exc:
            logger.warning(
                "Batch job recovery handoff deferred",
                extra={"job_id": str(snapshot.job_id), "error_class": type(exc).__name__},
            )
        return RuntimeStartResult(
            job_id=snapshot.job_id,
            action="recovery_required",
            container_id=snapshot.container_id,
            detail=reason,
        )

    async def _fail_terminal(
        self, snapshot: JobStateSnapshot, reason: str, proof_class: str
    ) -> RuntimeStartResult:
        now = utc_now()
        result = await self.finalizer.finalize(
            snapshot.job_id,
            fencing_token=snapshot.fencing_token,
            state="failed",
            outcome_code="failed",
            reason_code=reason,
            proof_class=proof_class,
            executor_terminated=True,
            started_at=snapshot.started_at,
            finished_at=now,
            log_state="unavailable",
        )
        return _finalized_result(snapshot, "failed", result)

    async def _locked_job(self, job_id: uuid.UUID) -> BatchJob | None:
        return await self.db.scalar(
            select(BatchJob)
            .where(BatchJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )


def _runtime_image(snapshot: JobStateSnapshot) -> str | None:
    for key in ("image", "spawn_reference"):
        value = snapshot.runtime_identity.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _snapshot(job: BatchJob, *, volume_name: str | None) -> JobStateSnapshot:
    return JobStateSnapshot(
        job_id=job.id,
        owner_id=job.user_id,
        name=job.name,
        state=job.state,
        reason_code=job.reason_code,
        argv=tuple(str(value) for value in (job.argv or [])),
        max_runtime_seconds=int(job.max_runtime_seconds),
        revision_snapshot=copy.deepcopy(job.revision_snapshot)
        if isinstance(job.revision_snapshot, dict)
        else {},
        plan_snapshot=copy.deepcopy(job.plan_snapshot)
        if isinstance(job.plan_snapshot, dict)
        else {},
        volume_snapshot=copy.deepcopy(job.volume_snapshot)
        if isinstance(job.volume_snapshot, dict)
        else {},
        volume_name=volume_name,
        runtime_identity=copy.deepcopy(job.runtime_identity)
        if isinstance(job.runtime_identity, dict)
        else {},
        reserved_cpu=job.reserved_cpu,
        reserved_memory_mib=job.reserved_memory_mib,
        reserved_disk_mib=job.reserved_disk_mib,
        container_id=job.container_id,
        container_name=job.container_name,
        fencing_token=job.fencing_token,
        volume_fencing_token=job.volume_fencing_token,
        volume_operation_id=job.volume_operation_id,
        volume_id=job.volume_id,
        reservation_active=bool(job.reservation_active),
        create_requested_at=job.create_requested_at,
        start_requested_at=job.start_requested_at,
        start_observed_at=job.start_observed_at,
        started_at=job.started_at,
        deadline_at=job.deadline_at,
        stop_requested_at=job.stop_requested_at,
        heartbeat_at=job.heartbeat_at,
        executor_id=job.executor_id,
        finished_at=job.finished_at,
        exit_code=job.exit_code,
        cleanup_state=job.cleanup_state,
        cleanup_attempts=int(job.cleanup_attempts or 0),
        log_expires_at=job.log_expires_at,
    )


def _classify_exit(
    snapshot: JobStateSnapshot,
    info: dict,
    *,
    forced: str | None,
) -> tuple[str, str, str | None, int | None, datetime | None, datetime]:
    state = _state(info)
    now = utc_now()
    exit_code = state.get("ExitCode")
    if type(exit_code) is not int:
        exit_code = None
    oom_killed = bool(state.get("OOMKilled"))
    started_at = _runtime_time(state.get("StartedAt")) or snapshot.started_at
    finished_at = _runtime_time(state.get("FinishedAt")) or now

    if oom_killed:
        return "failed", "failed", "oom_killed", exit_code, started_at, finished_at

    if forced is not None:
        cutoff = snapshot.deadline_at if forced == "deadline" else snapshot.stop_requested_at
        natural = cutoff is not None and finished_at <= cutoff
        if not natural:
            if forced == "deadline":
                return (
                    "timed_out",
                    "timed_out",
                    "job_deadline_exceeded",
                    exit_code,
                    started_at,
                    finished_at,
                )
            return (
                "cancelled",
                "cancelled",
                "request_cancelled",
                exit_code,
                started_at,
                finished_at,
            )

    deadline = snapshot.deadline_at
    if (
        deadline is not None
        and exit_code in (124, 137)
        and (finished_at >= deadline or now >= deadline)
    ):
        return (
            "timed_out",
            "timed_out",
            "job_deadline_exceeded",
            exit_code,
            started_at,
            finished_at,
        )
    if exit_code == 0:
        return "succeeded", "succeeded", None, exit_code, started_at, finished_at
    if exit_code is not None:
        return "failed", "failed", "nonzero_exit", exit_code, started_at, finished_at
    return "failed", "runtime_unverifiable", "runtime_unverifiable", None, started_at, finished_at


def _finalized_result(snapshot: JobStateSnapshot, outcome: str, result) -> RuntimeStartResult:
    if result.executor_unconfirmed:
        return RuntimeStartResult(
            job_id=snapshot.job_id,
            action="recovery_required",
            container_id=snapshot.container_id,
            detail="executor_unconfirmed",
        )
    if result.error is not None:
        return RuntimeStartResult(
            job_id=snapshot.job_id,
            action="noop",
            container_id=snapshot.container_id,
            detail=result.error,
        )
    return RuntimeStartResult(
        job_id=snapshot.job_id,
        action=outcome,
        container_id=snapshot.container_id,
    )


__all__ = [
    "BatchJobRuntimeService",
    "ContainerLookup",
    "JobStateSnapshot",
    "LogCapture",
    "RuntimeStartResult",
    "capture_tail",
    "container_status",
    "sanitize_environment",
    "validate_job_container",
]
