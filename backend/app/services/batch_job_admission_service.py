# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Batch job admission: prove the approved artifact, then reserve once.

The runtime lane must not create containers from this module. Admission proves
the persisted revision identity outside the shared lock, rechecks current policy
and accounting under that lock, writes the durable reservation plus exclusive
volume guard in one transaction, and returns a frozen :class:`JobAdmission`.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver, ContainerDriverError
from app.core.permissions import Permission
from app.core.security import has_permission
from app.core.time_utils import utc_now
from app.models.batch_job import (
    ACTIVE_JOB_STATES,
    TERMINAL_JOB_STATES,
    BatchJob,
    BatchJobLog,
)
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.schemas.environment_manifest import ImageIdentity
from app.services.admission_service import acquire_admission_lock
from app.services.environment_revision_service import (
    EnvironmentRevisionService,
    RevisionUnavailable,
)
from app.services.environment_service import EnvironmentService
from app.services.plan_service import PlanService
from app.services.quota_service import QuotaService
from app.services.registry_artifact_service import RegistryArtifactService
from app.services.registry_client import RegistryError, VerifiedImage
from app.services.resource_pool_service import ResourcePoolService
from app.services.storage_capability_service import StorageCapabilityService
from app.services.volume_operation_service import (
    ACTIVE_STATES as ACTIVE_VOLUME_STATES,
)
from app.services.volume_operation_service import (
    VolumeOperationError,
    acquire_volume_operations,
    transition_volume_operation,
)

_RESERVED_JOB_STATES = tuple(state for state in ACTIVE_JOB_STATES if state != "queued")
_TERMINAL_JOB_STATES = frozenset(TERMINAL_JOB_STATES)
_BUSY_VOLUME_STATUSES = frozenset({"restoring", "restore_failed", "deleting"})
_OUTCOME_STATES = frozenset({"succeeded", "failed", "cancelled", "timed_out", "expired"})
_POLICY_PROOF = "control_plane"
_ARTIFACT_PROOF = "artifact"
_RUNTIME_PROOF = "runtime"


class JobAdmissionError(ValueError):
    """A typed admission/finalization conflict for the runtime lane."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class JobAdmission:
    """One committed reservation and the exact runtime inputs the lane may use."""

    job_id: uuid.UUID
    owner_id: uuid.UUID
    revision_id: uuid.UUID
    plan_id: uuid.UUID
    volume_id: uuid.UUID
    volume_name: str
    container_name: str
    fencing_token: uuid.UUID
    volume_fencing_token: uuid.UUID
    image: str
    runtime_identity: dict
    toolchain_identity: dict | None
    toolchain_mounts: list[str]
    configuration: dict
    cpu: float
    memory_mib: int
    disk_mib: int
    max_runtime_seconds: int


@dataclass(frozen=True, slots=True)
class _ProofInput:
    runtime_identity: ImageIdentity
    toolchain_identity: ImageIdentity | None
    configuration: dict


class _ProofFailure(Exception):
    def __init__(self, reason: str, proof_class: str):
        self.reason = reason
        self.proof_class = proof_class
        super().__init__(reason)


def _parse_identity(value: object) -> ImageIdentity | None:
    if not isinstance(value, dict):
        return None
    try:
        return ImageIdentity.model_validate(value)
    except ValueError:
        return None


def _identity_key(identity: ImageIdentity) -> tuple:
    return (
        identity.local_id,
        identity.os,
        identity.architecture,
        identity.registry_verified,
        identity.verified_reference,
        identity.manifest_digest,
    )


def _identity_payload(identity: ImageIdentity) -> dict:
    payload = identity.model_dump(mode="json")
    payload["image"] = identity.spawn_reference
    payload["spawn_reference"] = identity.spawn_reference
    payload["platform"] = {
        "os": identity.os,
        "architecture": identity.architecture,
        "variant": identity.variant,
    }
    return payload


def _safe_memory_mib(value: object) -> int | None:
    try:
        return int(ResourcePoolService._parse_memory(str(value or "0")))
    except (TypeError, ValueError):
        return None


def _snapshot_plan_values(snapshot: object) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    try:
        cpu = float(snapshot.get("cpu") or 0)
        memory_mib = int(snapshot.get("memory_mib") or 0)
        disk_mib = int(snapshot.get("disk_mib") or 0)
        gpu_count = int(snapshot.get("gpu_count") or 0)
        cost_per_hour = int(snapshot.get("cost_per_hour") or 0)
    except (TypeError, ValueError):
        return None
    return {
        "cpu": cpu,
        "memory_mib": memory_mib,
        "disk_mib": disk_mib,
        "gpu_count": gpu_count,
        "cost_per_hour": cost_per_hour,
    }


def _current_plan_values(plan: ServerPlan) -> dict | None:
    memory_mib = _safe_memory_mib(plan.memory_limit)
    disk_mib = _safe_memory_mib(plan.disk_limit)
    if memory_mib is None or disk_mib is None:
        return None
    try:
        return {
            "cpu": float(plan.cpu_limit or 0),
            "memory_mib": memory_mib,
            "disk_mib": disk_mib,
            "gpu_count": int(plan.gpu_limit or 0),
            "cost_per_hour": int(plan.cost_per_hour or 0),
        }
    except (TypeError, ValueError):
        return None


def _bounded_log_text(value: str) -> tuple[str, bool, int]:
    """Keep the newest UTF-8 bytes within the configured retention cap."""
    encoded = value.encode("utf-8", errors="replace")
    limit = settings.batch_jobs_log_tail_bytes
    if len(encoded) <= limit:
        return value, False, len(encoded)
    return encoded[-limit:].decode("utf-8", errors="ignore"), True, len(encoded)


class BatchJobAdmissionService:
    """Owner-scoped admission into the shared platform reservation model."""

    def __init__(
        self,
        db: AsyncSession,
        driver: ContainerDriver,
        *,
        artifacts: RegistryArtifactService | None = None,
    ):
        self.db = db
        self.driver = driver
        self.artifacts = artifacts or RegistryArtifactService.from_settings(driver)

    async def _clean_session(self) -> None:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Batch job admission requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def _locked_job(self, job_id: uuid.UUID) -> BatchJob | None:
        return await self.db.scalar(
            select(BatchJob)
            .where(BatchJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _load_proof_input(self, job_id: uuid.UUID) -> _ProofInput | None:
        """Read the frozen submission snapshot and immutable revision metadata."""
        await self._clean_session()
        job = await self.db.scalar(
            select(BatchJob).where(BatchJob.id == job_id).execution_options(populate_existing=True)
        )
        if job is None or job.state != "queued":
            await self.db.rollback()
            return None
        snapshot = job.revision_snapshot if isinstance(job.revision_snapshot, dict) else {}
        runtime = _parse_identity(snapshot.get("runtime_identity"))
        configuration = snapshot.get("configuration")
        if runtime is None or not isinstance(configuration, dict):
            await self.db.rollback()
            raise _ProofFailure("revision_unavailable", _POLICY_PROOF)

        revision = await self.db.scalar(
            select(EnvironmentRevision)
            .where(EnvironmentRevision.id == job.revision_id)
            .execution_options(populate_existing=True)
        )
        if revision is None or revision.revoked:
            await self.db.rollback()
            raise _ProofFailure("revision_unavailable", _POLICY_PROOF)
        approved_runtime = _parse_identity(revision.runtime_identity)
        if approved_runtime is None or _identity_key(approved_runtime) != _identity_key(runtime):
            await self.db.rollback()
            raise _ProofFailure("revision_unavailable", _POLICY_PROOF)

        toolchain = None
        if revision.toolchain_identity is not None:
            toolchain = _parse_identity(revision.toolchain_identity)
            if toolchain is None:
                await self.db.rollback()
                raise _ProofFailure("revision_unavailable", _POLICY_PROOF)
        proof = _ProofInput(
            runtime_identity=runtime,
            toolchain_identity=toolchain,
            configuration=copy.deepcopy(configuration),
        )
        # Release the read transaction before any external artifact proof.
        await self.db.rollback()
        return proof

    @staticmethod
    def _verified_image(identity: ImageIdentity) -> VerifiedImage:
        if (
            identity.verified_reference is None
            or identity.manifest_digest is None
            or identity.descriptor_media_type is None
        ):
            raise _ProofFailure("revision_unavailable", _POLICY_PROOF)
        try:
            return VerifiedImage(
                requested_reference=identity.requested_reference,
                verified_reference=identity.verified_reference,
                manifest_digest=identity.manifest_digest,
                index_digest=identity.index_digest,
                descriptor_media_type=identity.descriptor_media_type,
                os=identity.os,
                architecture=identity.architecture,
                variant=identity.variant,
            )
        except ValueError:
            raise _ProofFailure("revision_unavailable", _POLICY_PROOF) from None

    @staticmethod
    def _registry_failure(code: str) -> tuple[str, str]:
        if code == "artifact_missing":
            return "artifact_missing", _ARTIFACT_PROOF
        return "runtime_unverifiable", _RUNTIME_PROOF

    async def _prove_identity(self, approved: ImageIdentity) -> ImageIdentity:
        """Prove the approved artifact without resolving a moved tag."""
        if approved.registry_verified:
            verified = self._verified_image(approved)
            try:
                local = await self.artifacts.ensure_local(verified)
            except RegistryError as exc:
                raise _ProofFailure(*self._registry_failure(exc.code)) from None
            if (local.local_id, local.os, local.architecture) != (
                approved.local_id,
                approved.os,
                approved.architecture,
            ):
                raise _ProofFailure("revision_unavailable", _POLICY_PROOF)
            return local

        if not await self.driver.image_exists(approved.local_id):
            raise _ProofFailure("artifact_missing", _ARTIFACT_PROOF)
        try:
            raw = await self.driver.resolve_image(approved.local_id)
        except ContainerDriverError:
            raise _ProofFailure("artifact_missing", _ARTIFACT_PROOF) from None
        actual = _parse_identity(raw)
        if actual is None or actual.registry_verified:
            raise _ProofFailure("runtime_unverifiable", _RUNTIME_PROOF)
        if (actual.local_id, actual.os, actual.architecture) != (
            approved.local_id,
            approved.os,
            approved.architecture,
        ):
            raise _ProofFailure("revision_unavailable", _POLICY_PROOF)
        return actual

    async def _prove_artifacts(
        self, proof: _ProofInput
    ) -> tuple[ImageIdentity, ImageIdentity | None]:
        runtime = await self._prove_identity(proof.runtime_identity)
        toolchain = (
            await self._prove_identity(proof.toolchain_identity)
            if proof.toolchain_identity is not None
            else None
        )
        return runtime, toolchain

    @staticmethod
    def _fail_job(job: BatchJob, reason: str, proof_class: str, now) -> None:
        job.state = "failed"
        job.outcome_code = "failed"
        job.reason_code = reason
        job.proof_class = proof_class
        job.state_changed_at = now
        job.finished_at = now
        job.result_recorded_at = now
        job.reservation_active = False
        job.updated_at = now

    @staticmethod
    def _expire_job(job: BatchJob, now) -> None:
        job.state = "expired"
        job.outcome_code = "expired"
        job.reason_code = "queue_expired"
        job.proof_class = _POLICY_PROOF
        job.state_changed_at = now
        job.finished_at = now
        job.result_recorded_at = now
        job.reservation_active = False
        job.updated_at = now

    async def _fail_queued(self, job_id: uuid.UUID, reason: str, proof_class: str) -> bool:
        """Finalize a still-queued job without touching its runtime or guard."""
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(job_id)
            if job is None or job.state != "queued":
                return False
            self._fail_job(job, reason, proof_class, utc_now())
            return True

    async def _defer_queued(self, job_id: uuid.UUID, reason: str) -> bool:
        """Leave a queued job waiting without reserving capacity or a guard."""
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(job_id)
            if job is None or job.state != "queued":
                return False
            job.reason_code = reason
            job.updated_at = utc_now()
            return True

    async def admit(
        self, job_id: uuid.UUID, *, executor_id: uuid.UUID | None
    ) -> JobAdmission | None:
        """Prove artifacts, then reserve capacity, quota and the volume writer."""
        # Host probing is read-only and deliberately outside every admission
        # lock. When the operator requires enforcement, a job must never start
        # against a writable limit the storage layer cannot uphold.
        if settings.batch_jobs_require_storage_enforcement:
            storage = StorageCapabilityService.probe()
            if not storage.enforced:
                await self._defer_queued(job_id, "storage_limits_unenforced")
                return None

        try:
            proof = await self._load_proof_input(job_id)
        except _ProofFailure as failure:
            await self._fail_queued(job_id, failure.reason, failure.proof_class)
            return None
        if proof is None:
            return None

        try:
            runtime, toolchain = await self._prove_artifacts(proof)
        except _ProofFailure as failure:
            await self._fail_queued(job_id, failure.reason, failure.proof_class)
            return None

        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(job_id)
            if job is None or job.state != "queued":
                return None

            now = utc_now()
            if job.queue_expires_at is not None and job.queue_expires_at <= now:
                self._expire_job(job, now)
                return None

            user = await self.db.scalar(
                select(User).where(User.id == job.user_id).execution_options(populate_existing=True)
            )
            if (
                user is None
                or not user.is_active
                or not has_permission(user, Permission.JOBS_WRITE_OWN)
            ):
                self._fail_job(job, "permission_revoked", _POLICY_PROOF, now)
                return None
            cohort = settings.batch_jobs_allowed_user_id_set
            if cohort and user.id not in cohort:
                self._fail_job(job, "cohort_not_allowed", _POLICY_PROOF, now)
                return None

            async def authorize_template(template: EnvironmentTemplate) -> None:
                if (
                    user is None
                    or not user.is_active
                    or not has_permission(user, Permission.JOBS_WRITE_OWN)
                    or not await EnvironmentService(self.db).can_user_use_env(
                        str(template.id), user.role
                    )
                ):
                    raise RevisionUnavailable("The approved environment is unavailable")

            try:
                revision = await EnvironmentRevisionService(
                    self.db, authorize_template
                ).require_available(job.revision_id)
            except RevisionUnavailable:
                self._fail_job(job, "revision_unavailable", _POLICY_PROOF, now)
                return None

            template = await self.db.scalar(
                select(EnvironmentTemplate)
                .where(EnvironmentTemplate.id == revision.template_id)
                .execution_options(populate_existing=True)
            )
            snapshot = job.revision_snapshot if isinstance(job.revision_snapshot, dict) else {}
            snapshot_environment_id = snapshot.get("environment_id")
            if (
                template is None
                or not template.is_active
                or str(template.id) != str(snapshot_environment_id)
            ):
                self._fail_job(job, "revision_unavailable", _POLICY_PROOF, now)
                return None

            current_runtime = _parse_identity(revision.runtime_identity)
            current_toolchain = (
                _parse_identity(revision.toolchain_identity)
                if revision.toolchain_identity is not None
                else None
            )
            if (
                current_runtime is None
                or _identity_key(current_runtime) != _identity_key(runtime)
                or (proof.toolchain_identity is not None) != (current_toolchain is not None)
                or (
                    proof.toolchain_identity is not None
                    and current_toolchain is not None
                    and _identity_key(current_toolchain) != _identity_key(proof.toolchain_identity)
                )
            ):
                self._fail_job(job, "revision_unavailable", _POLICY_PROOF, now)
                return None

            plan = await self.db.scalar(
                select(ServerPlan)
                .where(ServerPlan.id == job.plan_id)
                .execution_options(populate_existing=True)
            )
            if plan is None or not plan.is_active:
                self._fail_job(job, "plan_unavailable", _POLICY_PROOF, now)
                return None
            if not await PlanService(self.db).can_user_use_plan(
                str(plan.id), user.role, str(user.id)
            ):
                self._fail_job(job, "plan_unavailable", _POLICY_PROOF, now)
                return None
            if (plan.gpu_limit or 0) != 0:
                self._fail_job(job, "plan_unavailable", _POLICY_PROOF, now)
                return None

            snapshot_values = _snapshot_plan_values(job.plan_snapshot)
            current_values = _current_plan_values(plan)
            if snapshot_values is None or current_values is None:
                self._fail_job(job, "plan_changed", _POLICY_PROOF, now)
                return None
            if snapshot_values["cost_per_hour"] > 0:
                self._fail_job(job, "paid_plan_unsupported", _POLICY_PROOF, now)
                return None
            if snapshot_values != current_values:
                self._fail_job(job, "plan_changed", _POLICY_PROOF, now)
                return None

            volume = await self.db.scalar(
                select(Volume)
                .where(Volume.id == job.volume_id)
                .execution_options(populate_existing=True)
            )
            if volume is None or volume.owner_id != job.user_id or volume.visibility != "private":
                self._fail_job(job, "volume_unavailable", _POLICY_PROOF, now)
                return None
            if volume.status in _BUSY_VOLUME_STATUSES:
                job.reason_code = "volume_busy"
                job.updated_at = now
                return None
            if volume.status != "active":
                self._fail_job(job, "volume_unavailable", _POLICY_PROOF, now)
                return None

            owner_active = int(
                await self.db.scalar(
                    select(func.count())
                    .select_from(BatchJob)
                    .where(
                        BatchJob.user_id == job.user_id,
                        BatchJob.id != job.id,
                        BatchJob.state.in_(_RESERVED_JOB_STATES),
                    )
                )
                or 0
            )
            fleet_active = int(
                await self.db.scalar(
                    select(func.count())
                    .select_from(BatchJob)
                    .where(
                        BatchJob.id != job.id,
                        BatchJob.state.in_(_RESERVED_JOB_STATES),
                    )
                )
                or 0
            )
            fleet_cap = settings.batch_jobs_max_active_fleet
            if owner_active >= settings.batch_jobs_max_active_per_owner or (
                fleet_cap > 0 and fleet_active >= fleet_cap
            ):
                job.reason_code = "waiting_capacity"
                job.updated_at = now
                return None

            pool = ResourcePoolService(self.db)
            if not await pool.can_fit_resources(
                current_values["cpu"],
                f"{current_values['memory_mib']}m",
                f"{current_values['disk_mib']}m",
            ):
                job.reason_code = "waiting_capacity"
                job.updated_at = now
                return None

            quota = await QuotaService(self.db).check_spawn_allowed(
                str(job.user_id),
                str(plan.id),
                commit=False,
                include_gpu_pool=False,
            )
            if not quota["allowed"]:
                self._fail_job(job, "quota_exceeded", _POLICY_PROOF, now)
                return None

            try:
                guards = await acquire_volume_operations(
                    self.db,
                    volume_ids=[volume.id],
                    owner_id=user.id,
                    operation_id=job.id,
                    kind="job_writer",
                )
            except VolumeOperationError as exc:
                if exc.code == "volume_busy":
                    job.reason_code = "volume_busy"
                    job.updated_at = now
                    return None
                if exc.code == "volume_unavailable":
                    self._fail_job(job, "volume_unavailable", _POLICY_PROOF, now)
                    return None
                raise
            if (
                len(guards) != 1
                or guards[0].volume_id != volume.id
                or guards[0].state not in ACTIVE_VOLUME_STATES
            ):
                raise JobAdmissionError("operation_conflict")
            guard = guards[0]

            identity_payload = _identity_payload(runtime)
            toolchain_payload = _identity_payload(toolchain) if toolchain is not None else None
            configuration = copy.deepcopy(proof.configuration)
            toolchain_mounts = [
                str(path)
                for path in (configuration.get("tool_mounts") or [])
                if isinstance(path, str)
            ]
            if toolchain is not None and not toolchain_mounts:
                toolchain_mounts = ["/opt/nuke"]

            existing_snapshot = (
                copy.deepcopy(job.revision_snapshot)
                if isinstance(job.revision_snapshot, dict)
                else {}
            )
            job.revision_snapshot = {
                **existing_snapshot,
                "toolchain_identity": toolchain_payload,
                "toolchain_mounts": toolchain_mounts,
                "admitted_at": now.isoformat(),
            }

            job.state = "starting"
            job.reason_code = None
            job.reserved_at = now
            job.reservation_active = True
            job.reserved_cpu = current_values["cpu"]
            job.reserved_memory_mib = current_values["memory_mib"]
            job.reserved_disk_mib = current_values["disk_mib"]
            job.volume_operation_id = job.id
            job.volume_fencing_token = guard.fencing_token
            job.runtime_identity = identity_payload
            job.container_name = f"nukelab-job-{job.id}"
            job.executor_id = executor_id
            job.heartbeat_at = now
            job.state_changed_at = now
            job.updated_at = now

            admission = JobAdmission(
                job_id=job.id,
                owner_id=user.id,
                revision_id=revision.id,
                plan_id=plan.id,
                volume_id=volume.id,
                volume_name=volume.name,
                container_name=job.container_name,
                fencing_token=job.fencing_token,
                volume_fencing_token=guard.fencing_token,
                image=runtime.spawn_reference,
                runtime_identity=identity_payload,
                toolchain_identity=toolchain_payload,
                toolchain_mounts=toolchain_mounts,
                configuration=configuration,
                cpu=current_values["cpu"],
                memory_mib=current_values["memory_mib"],
                disk_mib=current_values["disk_mib"],
                max_runtime_seconds=job.max_runtime_seconds,
            )
            # The caller-visible reservation, guard and starting state commit once,
            # after all policy/accounting checks and before any runtime I/O.
            await self.db.commit()
            return admission

    async def mark_recovery_required(
        self,
        job_id: uuid.UUID,
        *,
        fencing_token: uuid.UUID,
        executor_id: uuid.UUID | None,
        reason_code: str = "runtime_unverifiable",
    ) -> bool:
        """Retain capacity and the volume guard for an unresolved runtime outcome."""
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(job_id)
            if job is None or job.state not in _RESERVED_JOB_STATES:
                return False
            if job.fencing_token != fencing_token:
                raise JobAdmissionError("operation_conflict")
            now = utc_now()
            job.state = "recovery_required"
            job.reason_code = reason_code
            job.state_changed_at = now
            job.executor_id = executor_id or job.executor_id
            job.heartbeat_at = now
            job.updated_at = now
            return True

    async def _release_volume_guard(self, job: BatchJob, *, succeeded: bool) -> None:
        operation_id = job.volume_operation_id or job.id
        if job.volume_id is None or job.volume_fencing_token is None:
            return
        guard = await self.db.scalar(
            select(VolumeOperation)
            .where(
                VolumeOperation.operation_id == operation_id,
                VolumeOperation.volume_id == job.volume_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if guard is not None and guard.state in ACTIVE_VOLUME_STATES:
            await transition_volume_operation(
                self.db,
                operation_id=operation_id,
                volume_id=job.volume_id,
                fencing_token=job.volume_fencing_token,
                state="succeeded" if succeeded else "failed",
                executor_terminated=True,
            )

    async def _write_terminal_log(
        self,
        job: BatchJob,
        *,
        log_state: str | None,
        log_text: str | None,
        log_truncated: bool,
        log_size_bytes: int | None,
        log_expires_at: datetime | None,
        now: datetime,
    ) -> None:
        log_requested = (
            log_state is not None
            or log_text is not None
            or log_size_bytes is not None
            or log_expires_at is not None
            or log_truncated
        )
        if not log_requested:
            return
        existing = await self.db.get(
            BatchJobLog,
            job.id,
            with_for_update=True,
            populate_existing=True,
        )
        effective_truncated = bool(log_truncated)
        effective_size = (
            max(0, int(log_size_bytes))
            if log_size_bytes is not None
            else int(existing.size_bytes)
            if existing is not None
            else 0
        )
        if log_text is not None:
            text, bounded, original_size = _bounded_log_text(log_text)
            effective_truncated = bool(effective_truncated or bounded)
            if log_size_bytes is None:
                effective_size = original_size
            if existing is None:
                existing = BatchJobLog(
                    job_id=job.id,
                    text=text,
                    encoding="utf-8",
                    truncated=effective_truncated,
                    size_bytes=effective_size,
                    captured_at=now,
                    expires_at=log_expires_at or job.log_expires_at,
                )
                self.db.add(existing)
            else:
                existing.text = text
                existing.encoding = "utf-8"
                existing.truncated = effective_truncated
                existing.size_bytes = effective_size
                existing.captured_at = now
                if log_expires_at is not None:
                    existing.expires_at = log_expires_at

        if log_state is not None:
            job.log_state = log_state
        elif log_text is not None:
            job.log_state = "truncated" if effective_truncated else "available"
        if (
            log_state is not None
            or log_text is not None
            or log_size_bytes is not None
            or log_truncated
        ):
            job.log_truncated = effective_truncated
            job.log_size_bytes = effective_size
        if log_expires_at is not None:
            job.log_expires_at = log_expires_at

    async def release_terminal(
        self,
        job_id: uuid.UUID,
        *,
        fencing_token: uuid.UUID,
        state: str,
        outcome_code: str,
        reason_code: str | None = None,
        proof_class: str | None = None,
        exit_code: int | None = None,
        executor_terminated: bool,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        log_state: str | None = None,
        log_text: str | None = None,
        log_truncated: bool = False,
        log_size_bytes: int | None = None,
        log_expires_at: datetime | None = None,
        observed_runtime_identity: dict | None = None,
    ) -> BatchJob | None:
        """Apply one terminal result and release capacity/guard only with proof.

        A caller without confirmed executor termination receives
        ``executor_unconfirmed`` and the reservation/guard remain untouched.
        The bounded log payload and observed runtime identity commit atomically
        with the terminal state and guard release.
        """
        if state not in _TERMINAL_JOB_STATES or outcome_code not in _OUTCOME_STATES:
            raise JobAdmissionError("invalid_operation")
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            job = await self._locked_job(job_id)
            if job is None:
                return None
            if job.fencing_token != fencing_token:
                raise JobAdmissionError("operation_conflict")
            if job.state in _TERMINAL_JOB_STATES:
                if not job.reservation_active:
                    return job
                if not executor_terminated:
                    raise JobAdmissionError("executor_unconfirmed")
                await self._release_volume_guard(job, succeeded=job.outcome_code == "succeeded")
                job.reservation_active = False
                job.updated_at = utc_now()
                return job
            if job.state not in _RESERVED_JOB_STATES:
                raise JobAdmissionError("job_not_active")
            if not executor_terminated:
                raise JobAdmissionError("executor_unconfirmed")

            await self._release_volume_guard(job, succeeded=state == "succeeded")

            now = utc_now()
            job.state = state
            job.outcome_code = outcome_code
            job.reason_code = reason_code
            job.proof_class = proof_class
            job.exit_code = exit_code
            if started_at is not None:
                job.started_at = started_at
            job.finished_at = finished_at or now
            if observed_runtime_identity is not None:
                job.runtime_identity = copy.deepcopy(observed_runtime_identity)
            job.result_recorded_at = now
            job.state_changed_at = now
            job.reservation_active = False
            job.updated_at = now
            await self._write_terminal_log(
                job,
                log_state=log_state,
                log_text=log_text,
                log_truncated=log_truncated,
                log_size_bytes=log_size_bytes,
                log_expires_at=log_expires_at,
                now=now,
            )
            return job


__all__ = [
    "BatchJobAdmissionService",
    "JobAdmission",
    "JobAdmissionError",
]
