# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Owner-scoped single-run batch job persistence, queue intent and presentation.

This module owns durable submission, listing, cancellation and bounded log reads.
It deliberately has no dispatch, runtime, admission, volume-guard or billing side
effects: those lanes consume the journal fields written here.
"""

import base64
import copy
import hashlib
import re
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.permissions import Permission
from app.core.security import has_permission
from app.core.time_utils import utc_now
from app.models.batch_job import (
    ACTIVE_JOB_STATES,
    TERMINAL_JOB_STATES,
    BatchJob,
    BatchJobLog,
)
from app.models.credit_hold import CreditHold
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.schemas.batch_job import (
    BatchJobDetail,
    BatchJobListResponse,
    BatchJobSubmitRequest,
    BatchJobSummary,
    BillingMode,
    EligibleRevision,
    EligibleRevisionsResponse,
    JobBilling,
    JobCapabilitiesResponse,
    JobEnvironmentSummary,
    JobLimits,
    JobLogsResponse,
    JobLogSummary,
    JobPlanSummary,
    JobResult,
    JobRuntimeLimits,
    JobVolumeSummary,
)
from app.schemas.environment_manifest import canonical_json
from app.services.admission_service import acquire_admission_lock
from app.services.credit_hold_service import (
    HELD,
    RELEASED,
    CreditHoldError,
    CreditHoldService,
)
from app.services.environment_revision_service import (
    EnvironmentRevisionService,
    RevisionUnavailable,
)
from app.services.environment_service import EnvironmentService
from app.services.plan_service import PlanService
from app.services.resource_pool_service import ResourcePoolService
from app.services.storage_capability_service import StorageCapabilityService

_ELIGIBLE_REVISION_LIMIT = 50
_ELIGIBLE_SCAN_LIMIT = 200
_MAX_NAME_LENGTH = 120
_MIN_RUNTIME_SECONDS = 60
_IDEMPOTENCY_KEY_RE = re.compile(r"[\x21-\x7e]{1,128}\Z")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SAFE_IMAGE_REFERENCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*(?:@sha256:[a-f0-9]{64})?\Z")
_ACTIVE_RESOURCE_STATES = tuple(state for state in ACTIVE_JOB_STATES if state != "queued")
_TERMINAL_STATES = frozenset(TERMINAL_JOB_STATES)
_CANCELLABLE_STATES = frozenset({"queued", "starting", "running"})

CANCEL_CANCELLED = "cancelled"
CANCEL_REQUESTED = "cancellation_requested"
CANCEL_ALREADY_CANCELLING = "already_cancelling"
CANCEL_ALREADY_TERMINAL = "already_terminal"
CANCEL_NOT_CANCELLABLE = "not_cancellable"
CANCEL_NOT_FOUND = "job_not_found"


@dataclass(frozen=True)
class CancelTransition:
    """Locked cancellation classification; the caller owns the transaction."""

    job: BatchJob | None
    previous_state: str | None
    outcome: str


_BUSY_VOLUME_STATUSES = frozenset({"restoring", "restore_failed", "deleting"})

_REASON_MESSAGES = {
    "waiting_capacity": "Waiting for capacity.",
    "volume_busy": "The selected volume is busy.",
    "revision_unavailable": "The selected environment revision is unavailable.",
    "plan_unavailable": "The selected plan is unavailable.",
    "plan_changed": "The selected plan changed. Submit a new job.",
    "paid_plan_unsupported": "Paid plans are not supported for batch jobs yet.",
    "cohort_not_allowed": "This account is not in the batch job pilot cohort.",
    "permission_revoked": "This account is no longer permitted to run batch jobs.",
    "quota_exceeded": "The job exceeds the account resource quota.",
    "artifact_missing": "The approved environment artifact is unavailable.",
    "queue_expired": "The queued job expired. Submit a new job.",
    "storage_limits_unenforced": "Writable storage limits are not kernel-enforced on this host.",
    "insufficient_credits": "The account does not have enough credits.",
    "billing_unavailable": "Job credit authorization is unavailable. Submit a new job.",
    "job_deadline_exceeded": "The job exceeded its maximum runtime.",
    "recovery_required": (
        "Job outcome requires operator verification. Contact support before resubmitting."
    ),
    "request_cancelled": "Job cancelled.",
    "cancellation_requested": "Cancellation requested.",
    "runtime_unverifiable": "The runtime outcome could not be verified.",
}


class JobError(Exception):
    """Typed owner-facing error carrying a stable code and HTTP status."""

    def __init__(self, code: str, status_code: int, field: str | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.field = field


def _safe_image_reference(runtime_identity: object) -> str | None:
    """Return only a registry-verified immutable reference, never raw configuration."""
    if not isinstance(runtime_identity, dict):
        return None
    if runtime_identity.get("registry_verified") is not True:
        return None
    verified = runtime_identity.get("verified_reference")
    if (
        isinstance(verified, str)
        and "@sha256:" in verified
        and _SAFE_IMAGE_REFERENCE_RE.fullmatch(verified)
    ):
        return verified
    return None


def _display_label(name: str, approved_at: datetime | None) -> str:
    approved = approved_at.strftime("%Y-%m-%d") if approved_at is not None else "unknown"
    return f"{name} — approved {approved}"


def _safe_memory_mib(value: str | None) -> int:
    try:
        return int(ResourcePoolService._parse_memory(value or "0"))
    except (TypeError, ValueError):
        return 0


def _plan_snapshot(plan: ServerPlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "name": plan.name,
        "cpu": plan.cpu_limit,
        "memory_mib": _safe_memory_mib(plan.memory_limit),
        "disk_mib": _safe_memory_mib(plan.disk_limit),
        "gpu_count": plan.gpu_limit or 0,
        "cost_per_hour": plan.cost_per_hour or 0,
    }


def _revision_snapshot(
    revision: EnvironmentRevision, template: EnvironmentTemplate
) -> dict[str, Any]:
    return {
        "revision_id": str(revision.id),
        "environment_id": str(template.id),
        "environment_name": template.name,
        "display_label": _display_label(template.name, revision.created_at),
        "fingerprint": revision.fingerprint,
        "template_fingerprint": revision.template_fingerprint,
        "portable_fingerprint": revision.portable_fingerprint,
        "image_reference": _safe_image_reference(revision.runtime_identity),
        "configuration": copy.deepcopy(revision.configuration),
        "runtime_identity": copy.deepcopy(revision.runtime_identity),
    }


def _volume_snapshot(volume: Volume) -> dict[str, Any]:
    return {
        "id": str(volume.id),
        "display_name": volume.display_name or volume.name,
        "visibility": volume.visibility,
    }


def _canonical_request_payload(
    *,
    name: str,
    revision_id: uuid.UUID,
    plan_id: uuid.UUID,
    volume_id: uuid.UUID,
    argv: list[str],
    max_runtime_seconds: int,
) -> dict[str, Any]:
    return {
        "name": name,
        "revision_id": str(revision_id),
        "plan_id": str(plan_id),
        "volume_id": str(volume_id),
        "argv": list(argv),
        "max_runtime_seconds": max_runtime_seconds,
    }


def _request_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _authorized_credits(rate_per_hour: int, max_runtime_seconds: int) -> int:
    if rate_per_hour <= 0:
        return 0
    return max(1, _ceil_div(rate_per_hour * max_runtime_seconds, 3600))


def _idempotency_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _encode_cursor(created_at: datetime, job_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{job_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(f"{cursor}{padding}").decode()
        timestamp, separator, job_id = raw.partition("|")
        if not separator:
            raise ValueError("missing separator")
        created_at = datetime.fromisoformat(timestamp)
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(UTC).replace(tzinfo=None)
        return created_at, uuid.UUID(job_id)
    except (ValueError, TypeError) as exc:
        raise JobError("invalid_request", 422, field="cursor") from exc


class BatchJobService:
    """Transactional owner-facing job operations; callers own the session lifetime."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _cohort_allows(user: User) -> bool:
        cohort = settings.batch_jobs_allowed_user_id_set
        return not cohort or user.id in cohort

    # ── Capabilities and eligibility ────────────────────────────────────────

    async def capabilities(self, user: User) -> JobCapabilitiesResponse:
        # Reads remain available to owners while submission is disabled.
        enabled = has_permission(user, Permission.JOBS_READ_OWN)
        submission_enabled = bool(settings.batch_jobs_submission_enabled)
        permitted = has_permission(user, Permission.JOBS_WRITE_OWN)
        cohort_allowed = self._cohort_allows(user)
        storage = StorageCapabilityService.probe()
        can_submit = submission_enabled and permitted and cohort_allowed
        if not submission_enabled:
            reason_code = "feature_disabled"
        elif not permitted:
            reason_code = "permission_denied"
        elif not cohort_allowed:
            reason_code = "cohort_not_allowed"
        elif storage.required and not storage.enforced:
            # Fail closed rather than advertise a writable limit the kernel
            # cannot enforce. Probe failures are sanitized to one reason.
            can_submit = False
            reason_code = "storage_limits_unenforced"
        else:
            reason_code = None
        # Paid plans are advertised only when the operator enables settlement
        # and the credit subsystem itself is enabled.
        billing_mode: BillingMode = (
            "paid"
            if settings.batch_jobs_allow_paid_plans and settings.credits_enabled
            else "zero_cost"
        )
        return JobCapabilitiesResponse(
            enabled=enabled,
            can_submit=can_submit,
            billing_mode=billing_mode,
            secrets_enabled=False,
            storage_limits_enforced=storage.enforced,
            storage_enforcement_required=storage.required,
            reason_code=reason_code,
            limits=JobLimits(
                max_active_jobs=settings.batch_jobs_max_active_per_owner,
                max_queued_jobs=settings.batch_jobs_max_queued_per_owner,
                default_runtime_seconds=settings.batch_jobs_default_runtime_seconds,
                max_runtime_seconds=settings.batch_jobs_max_runtime_seconds,
                queue_ttl_seconds=settings.batch_jobs_queue_ttl_seconds,
                max_argv_items=settings.batch_jobs_max_argv_items,
                max_input_bytes=settings.batch_jobs_max_input_bytes,
                log_tail_bytes=settings.batch_jobs_log_tail_bytes,
                log_retention_seconds=settings.batch_jobs_log_retention_seconds,
            ),
        )

    async def eligible_revisions(self, user: User) -> EligibleRevisionsResponse:
        environment_service = EnvironmentService(self.db)
        authorization_cache: dict[uuid.UUID, bool] = {}
        rows = (
            await self.db.execute(
                select(EnvironmentRevision, EnvironmentTemplate)
                .join(
                    EnvironmentTemplate,
                    EnvironmentTemplate.id == EnvironmentRevision.template_id,
                )
                .where(
                    EnvironmentRevision.revoked.is_(False),
                    EnvironmentTemplate.is_active.is_(True),
                )
                .order_by(
                    EnvironmentRevision.created_at.desc(),
                    EnvironmentRevision.id.desc(),
                )
                .limit(_ELIGIBLE_SCAN_LIMIT)
                .execution_options(populate_existing=True)
            )
        ).all()
        items: list[EligibleRevision] = []
        for revision, template in rows:
            authorized = authorization_cache.get(template.id)
            if authorized is None:
                authorized = await environment_service.can_user_use_env(str(template.id), user.role)
                authorization_cache[template.id] = authorized
            if not authorized:
                continue
            items.append(
                EligibleRevision(
                    revision_id=revision.id,
                    environment_id=template.id,
                    environment_name=template.name,
                    display_label=_display_label(template.name, revision.created_at),
                    fingerprint=revision.fingerprint,
                    portable_fingerprint=revision.portable_fingerprint,
                    image_reference=_safe_image_reference(revision.runtime_identity),
                    supports_jobs=True,
                    reason_code=None,
                )
            )
            if len(items) >= _ELIGIBLE_REVISION_LIMIT:
                break
        return EligibleRevisionsResponse(items=items)

    async def _authorize_template(self, template: EnvironmentTemplate, user: User) -> None:
        if not await EnvironmentService(self.db).can_user_use_env(str(template.id), user.role):
            raise RevisionUnavailable("The approved environment is unavailable")

    def _revision_service(self, user: User) -> EnvironmentRevisionService:
        async def authorize_template(template: EnvironmentTemplate) -> None:
            await self._authorize_template(template, user)

        return EnvironmentRevisionService(self.db, authorize_template)

    # ── Submission ──────────────────────────────────────────────────────────

    async def submit(
        self,
        user: User,
        idempotency_key: str | None,
        request: BatchJobSubmitRequest,
    ) -> BatchJobDetail:
        if not settings.batch_jobs_submission_enabled:
            raise JobError("feature_disabled", 403)
        if not has_permission(user, Permission.JOBS_WRITE_OWN):
            raise JobError("permission_denied", 403)
        if not self._cohort_allows(user):
            raise JobError("cohort_not_allowed", 403)
        key = self._validate_idempotency_key(idempotency_key)
        name = self._validate_name(request.name)
        argv = self._validate_argv(request.argv)
        max_runtime_seconds = self._validate_runtime(request.max_runtime_seconds)
        fingerprint = _request_fingerprint(
            _canonical_request_payload(
                name=name,
                revision_id=request.revision_id,
                plan_id=request.plan_id,
                volume_id=request.volume_id,
                argv=argv,
                max_runtime_seconds=max_runtime_seconds,
            )
        )
        key_hash = _idempotency_key_hash(key)

        existing = await self._find_by_idempotency(user.id, key_hash)
        if existing is not None:
            return await self._replay(existing, fingerprint)

        if settings.batch_jobs_require_storage_enforcement:
            storage = StorageCapabilityService.probe()
            if not storage.enforced:
                raise JobError("storage_limits_unenforced", 503)

        revision = await self._require_revision(user, request.revision_id)
        plan = await self._require_plan(user, request.plan_id)
        volume = await self._require_volume(user, request.volume_id)
        await self._enforce_owner_limits(user.id)

        template = await self.db.get(EnvironmentTemplate, revision.template_id)
        if template is None or not template.is_active:
            raise JobError("revision_unavailable", 422, field="revision_id")

        now = utc_now()
        rate_per_hour = int(plan.cost_per_hour or 0)
        billing_mode: BillingMode = "paid" if rate_per_hour > 0 else "zero_cost"
        authorized_credits = _authorized_credits(rate_per_hour, max_runtime_seconds)
        job = BatchJob(
            user_id=user.id,
            name=name,
            idempotency_key_hash=key_hash,
            request_fingerprint=fingerprint,
            revision_id=revision.id,
            plan_id=plan.id,
            volume_id=volume.id,
            argv=argv,
            max_runtime_seconds=max_runtime_seconds,
            state="queued",
            reason_code="waiting_capacity",
            state_changed_at=now,
            queue_expires_at=now + timedelta(seconds=settings.batch_jobs_queue_ttl_seconds),
            revision_snapshot=_revision_snapshot(revision, template),
            plan_snapshot=_plan_snapshot(plan),
            volume_snapshot=_volume_snapshot(volume),
            reservation_active=False,
            fencing_token=uuid.uuid4(),
            billing_mode=billing_mode,
            charged_credits=0,
            authorized_credits=authorized_credits,
            billing_rate_per_hour=rate_per_hour,
            billing_state=HELD if billing_mode == "paid" else "none",
            log_state="pending",
            log_truncated=False,
            log_size_bytes=0,
            created_at=now,
            updated_at=now,
        )
        if billing_mode == "paid":
            # Serialize paid balance reservation with interactive launch/queue
            # reservation. Lock order is admission -> user -> hold; the job row
            # and hold commit together so a failed hold leaves no job.
            if not self.db.in_transaction():
                await self.db.begin()
            await acquire_admission_lock(self.db)
        self.db.add(job)
        try:
            await self.db.flush()
            if billing_mode == "paid":
                try:
                    await CreditHoldService.create_hold(
                        self.db,
                        user_id=user.id,
                        job_id=job.id,
                        amount=authorized_credits,
                    )
                except CreditHoldError as exc:
                    await self.db.rollback()
                    if exc.code == "insufficient_credits":
                        raise JobError("insufficient_credits", 402) from None
                    raise JobError("billing_unavailable", 409) from None
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            existing = await self._find_by_idempotency(user.id, key_hash)
            if existing is None:
                raise JobError("idempotency_conflict", 409) from exc
            return await self._replay(existing, fingerprint)
        return await self.detail(job, replayed=False)

    async def _replay(self, job: BatchJob, fingerprint: str) -> BatchJobDetail:
        if job.request_fingerprint != fingerprint:
            raise JobError("idempotency_conflict", 409)
        return await self.detail(job, replayed=True)

    def _validate_idempotency_key(self, value: str | None) -> str:
        if not isinstance(value, str) or not _IDEMPOTENCY_KEY_RE.fullmatch(value):
            raise JobError("invalid_request", 422, field="Idempotency-Key")
        return value

    def _validate_name(self, value: str) -> str:
        if not isinstance(value, str):
            raise JobError("invalid_request", 422, field="name")
        name = value.strip()
        if not name or len(name) > _MAX_NAME_LENGTH or _CONTROL_CHAR_RE.search(name):
            raise JobError("invalid_request", 422, field="name")
        return name

    def _validate_argv(self, value: list[str]) -> list[str]:
        if not isinstance(value, list) or not value:
            raise JobError("invalid_request", 422, field="argv")
        if len(value) > settings.batch_jobs_max_argv_items:
            raise JobError("argv_too_large", 422, field="argv")
        total_bytes = 0
        for item in value:
            if not isinstance(item, str) or "\x00" in item:
                raise JobError("invalid_request", 422, field="argv")
            try:
                total_bytes += len(item.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise JobError("invalid_request", 422, field="argv") from exc
        if total_bytes > settings.batch_jobs_max_input_bytes:
            raise JobError("argv_too_large", 422, field="argv")
        return list(value)

    def _validate_runtime(self, value: int | None) -> int:
        if value is None:
            return settings.batch_jobs_default_runtime_seconds
        if isinstance(value, bool) or not isinstance(value, int):
            raise JobError("invalid_request", 422, field="max_runtime_seconds")
        if value < _MIN_RUNTIME_SECONDS or value > settings.batch_jobs_max_runtime_seconds:
            raise JobError("runtime_too_long", 422, field="max_runtime_seconds")
        return value

    async def _require_revision(self, user: User, revision_id: uuid.UUID) -> EnvironmentRevision:
        try:
            revision = await self._revision_service(user).require_available(revision_id)
        except RevisionUnavailable as exc:
            raise JobError("revision_unavailable", 422, field="revision_id") from exc
        template = await self.db.get(EnvironmentTemplate, revision.template_id)
        if template is None or not template.is_active:
            raise JobError("revision_unavailable", 422, field="revision_id")
        return revision

    async def _require_plan(self, user: User, plan_id: uuid.UUID) -> ServerPlan:
        plan_service = PlanService(self.db)
        plan = await plan_service.get_by_id(str(plan_id))
        if plan is None or not plan.is_active:
            raise JobError("plan_unavailable", 422, field="plan_id")
        if not await plan_service.can_user_use_plan(str(plan.id), user.role, str(user.id)):
            raise JobError("plan_unavailable", 422, field="plan_id")
        if not plan.allow_batch_jobs:
            raise JobError("plan_unavailable", 422, field="plan_id")
        if (plan.gpu_limit or 0) != 0:
            raise JobError("plan_unavailable", 422, field="plan_id")
        if (plan.cost_per_hour or 0) > 0 and not (
            settings.batch_jobs_allow_paid_plans and settings.credits_enabled
        ):
            raise JobError("paid_plan_unsupported", 422, field="plan_id")
        return plan

    async def _require_volume(self, user: User, volume_id: uuid.UUID) -> Volume:
        volume = await self.db.get(Volume, volume_id)
        if volume is None or volume.owner_id != user.id:
            raise JobError("volume_unavailable", 422, field="volume_id")
        if volume.visibility != "private":
            raise JobError("volume_unavailable", 422, field="volume_id")
        if volume.status in _BUSY_VOLUME_STATUSES:
            raise JobError("volume_busy", 409, field="volume_id")
        if volume.status != "active":
            raise JobError("volume_unavailable", 422, field="volume_id")
        return volume

    async def _enforce_owner_limits(self, user_id: uuid.UUID) -> None:
        now = utc_now()
        active_count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(BatchJob)
                .where(
                    BatchJob.user_id == user_id,
                    BatchJob.state.in_(_ACTIVE_RESOURCE_STATES),
                )
            )
            or 0
        )
        if active_count >= settings.batch_jobs_max_active_per_owner:
            raise JobError("job_limit_reached", 429)
        queued_count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(BatchJob)
                .where(
                    BatchJob.user_id == user_id,
                    BatchJob.state == "queued",
                    or_(
                        BatchJob.queue_expires_at.is_(None),
                        BatchJob.queue_expires_at > now,
                    ),
                )
            )
            or 0
        )
        if queued_count >= settings.batch_jobs_max_queued_per_owner:
            raise JobError("job_limit_reached", 429)

    async def _find_by_idempotency(self, user_id: uuid.UUID, key_hash: str) -> BatchJob | None:
        return await self.db.scalar(
            select(BatchJob)
            .where(
                BatchJob.user_id == user_id,
                BatchJob.idempotency_key_hash == key_hash,
            )
            .execution_options(populate_existing=True)
        )

    # ── Reads and cancellation ──────────────────────────────────────────────

    async def list(
        self,
        user: User,
        *,
        state_filter: str = "all",
        limit: int = 25,
        cursor: str | None = None,
    ) -> BatchJobListResponse:
        if state_filter not in ("active", "history", "all"):
            raise JobError("invalid_request", 422, field="state")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise JobError("invalid_request", 422, field="limit")
        conditions = [BatchJob.user_id == user.id]
        if state_filter == "active":
            conditions.append(BatchJob.state.in_(ACTIVE_JOB_STATES))
        elif state_filter == "history":
            conditions.append(BatchJob.state.in_(TERMINAL_JOB_STATES))
        if cursor is not None:
            created_at, job_id = _decode_cursor(cursor)
            conditions.append(
                or_(
                    BatchJob.created_at < created_at,
                    and_(
                        BatchJob.created_at == created_at,
                        BatchJob.id < job_id,
                    ),
                )
            )
        rows = (
            await self.db.scalars(
                select(BatchJob)
                .where(*conditions)
                .order_by(BatchJob.created_at.desc(), BatchJob.id.desc())
                .limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
        visible = rows[:limit]
        next_cursor = (
            _encode_cursor(visible[-1].created_at, visible[-1].id) if has_more and visible else None
        )
        return BatchJobListResponse(
            items=[_summary(job) for job in visible],
            next_cursor=next_cursor,
        )

    async def get(self, user: User, job_id: uuid.UUID) -> BatchJobDetail:
        job = await self._get_owned(job_id, user.id)
        return await self.detail(job, replayed=False)

    async def cancel_transition(
        self, job_id: uuid.UUID, *, owner_id: uuid.UUID | None
    ) -> CancelTransition:
        """Lock a job and apply cancellation without committing.

        The caller must own an open transaction. Lock order matches submission
        and admission: shared admission lock, then the job row. A queued job
        releases its full credit hold here; starting/running jobs only record a
        stop request, and every other active state is refused without releasing
        protection.
        """
        if not self.db.in_transaction():
            raise RuntimeError("Cancellation requires a caller-owned transaction")
        await acquire_admission_lock(self.db)
        conditions = [BatchJob.id == job_id]
        if owner_id is not None:
            conditions.append(BatchJob.user_id == owner_id)
        job = await self.db.scalar(
            select(BatchJob)
            .where(*conditions)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            # Foreign and missing ids are deliberately indistinguishable.
            return CancelTransition(job=None, previous_state=None, outcome=CANCEL_NOT_FOUND)

        previous = job.state
        now = utc_now()
        if job.state == "queued":
            job.state = "cancelled"
            job.outcome_code = "cancelled"
            job.reason_code = "request_cancelled"
            job.state_changed_at = now
            job.finished_at = now
            job.result_recorded_at = now
            job.proof_class = "control_plane"
            job.reservation_active = False
            job.updated_at = now
            released = await CreditHoldService.release(self.db, job.id)
            if released or job.billing_state == HELD or job.billing_mode == "paid":
                job.billing_state = RELEASED
                job.charged_credits = 0
            outcome = CANCEL_CANCELLED
        elif job.state in ("starting", "running"):
            job.state = "cancelling"
            job.reason_code = "cancellation_requested"
            job.state_changed_at = now
            job.stop_requested_at = now
            job.updated_at = now
            outcome = CANCEL_REQUESTED
        elif job.state == "cancelling":
            outcome = CANCEL_ALREADY_CANCELLING
        elif job.state in _TERMINAL_STATES:
            outcome = CANCEL_ALREADY_TERMINAL
        else:
            outcome = CANCEL_NOT_CANCELLABLE
        return CancelTransition(job=job, previous_state=previous, outcome=outcome)

    async def cancel(self, user: User, job_id: uuid.UUID) -> BatchJobDetail:
        """Serialize cancellation with admission under the shared lock and row lock."""
        async with AsyncExitStack() as stack:
            if not self.db.in_transaction():
                await stack.enter_async_context(self.db.begin())
            transition = await self.cancel_transition(job_id, owner_id=user.id)
            if transition.outcome == CANCEL_NOT_FOUND:
                raise JobError("job_not_found", 404)
            if transition.outcome == CANCEL_NOT_CANCELLABLE:
                raise JobError("job_not_cancellable", 409)
            await self.db.commit()
        job = transition.job
        if job is None:  # Defensive: the two refusal outcomes above cover all None cases.
            raise JobError("job_not_found", 404)
        return await self.detail(job, replayed=False)

    async def logs(self, user: User, job_id: uuid.UUID) -> JobLogsResponse:
        job = await self._get_owned(job_id, user.id)
        payload = await self.db.get(BatchJobLog, job.id, populate_existing=True)
        return self._logs_response(job, payload)

    async def _get_owned(self, job_id: uuid.UUID, owner_id: uuid.UUID) -> BatchJob:
        job = await self.db.scalar(
            select(BatchJob)
            .where(BatchJob.id == job_id, BatchJob.user_id == owner_id)
            .execution_options(populate_existing=True)
        )
        if job is None:
            # Foreign and missing ids are deliberately indistinguishable.
            raise JobError("job_not_found", 404)
        return job

    # ── Serialization ───────────────────────────────────────────────────────

    async def detail(self, job: BatchJob, *, replayed: bool) -> BatchJobDetail:
        payload = await self.db.get(BatchJobLog, job.id, populate_existing=True)
        volume = await self.db.get(Volume, job.volume_id) if job.volume_id else None
        hold = await self.db.scalar(select(CreditHold).where(CreditHold.job_id == job.id))
        available = bool(
            volume is not None
            and volume.owner_id == job.user_id
            and volume.status == "active"
            and volume.visibility == "private"
        )
        return _detail(
            job,
            payload,
            volume=volume,
            available=available,
            replayed=replayed,
            unpaid=int(hold.unpaid_credits or 0) if hold is not None else 0,
        )

    def _logs_response(self, job: BatchJob, payload: BatchJobLog | None) -> JobLogsResponse:
        state = _effective_log_state(job, payload)
        expires_at = (payload.expires_at if payload is not None else None) or job.log_expires_at
        if payload is None:
            return JobLogsResponse(
                state=state,
                text=None,
                truncated=bool(job.log_truncated),
                size_bytes=job.log_size_bytes or 0,
                expires_at=expires_at,
                encoding=None,
            )
        if state == "expired":
            return JobLogsResponse(
                state="expired",
                text=None,
                truncated=bool(payload.truncated or job.log_truncated),
                size_bytes=payload.size_bytes or 0,
                expires_at=expires_at,
                encoding=None,
            )
        text = payload.text or ""
        encoded = text.encode("utf-8")
        limit = settings.batch_jobs_log_tail_bytes
        truncated = bool(payload.truncated or job.log_truncated)
        if len(encoded) > limit:
            text = encoded[-limit:].decode("utf-8", errors="ignore")
            truncated = True
        return JobLogsResponse(
            state="truncated" if truncated else "available",
            text=text,
            truncated=truncated,
            size_bytes=payload.size_bytes or len(encoded),
            expires_at=expires_at,
            encoding=payload.encoding or "utf-8",
        )


def _summary(job: BatchJob) -> BatchJobSummary:
    snapshot = job.revision_snapshot if isinstance(job.revision_snapshot, dict) else {}
    environment_name = str(snapshot.get("environment_name") or "")
    return BatchJobSummary(
        id=job.id,
        name=job.name,
        state=job.state,
        reason_code=job.reason_code,
        environment_name=environment_name,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        can_cancel=job.state in _CANCELLABLE_STATES,
    )


def _snapshot_uuid(snapshot: dict, key: str, fallback: uuid.UUID | None) -> uuid.UUID:
    value = snapshot.get(key)
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            pass
    return fallback or uuid.UUID(int=0)


def _effective_log_state(job: BatchJob, payload: BatchJobLog | None) -> str:
    now = utc_now()
    expires_at = (payload.expires_at if payload is not None else None) or job.log_expires_at
    if job.log_state == "expired" or (expires_at is not None and expires_at <= now):
        return "expired"
    if payload is not None:
        return "truncated" if (payload.truncated or job.log_truncated) else "available"
    if job.state in _TERMINAL_STATES or job.log_state in (
        "available",
        "truncated",
        "unavailable",
    ):
        return "unavailable"
    return "pending"


def _result(job: BatchJob) -> JobResult | None:
    if job.state not in _TERMINAL_STATES or not job.outcome_code:
        return None
    duration_seconds = None
    if job.started_at is not None and job.finished_at is not None:
        duration_seconds = max(0, int((job.finished_at - job.started_at).total_seconds()))
    return JobResult(
        exit_code=job.exit_code,
        outcome_code=job.outcome_code,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_seconds=duration_seconds,
        proof=job.proof_class,
    )


def _detail(
    job: BatchJob,
    payload: BatchJobLog | None,
    *,
    volume: Volume | None,
    available: bool,
    replayed: bool,
    unpaid: int = 0,
) -> BatchJobDetail:
    revision_snapshot = job.revision_snapshot if isinstance(job.revision_snapshot, dict) else {}
    plan_snapshot = job.plan_snapshot if isinstance(job.plan_snapshot, dict) else {}
    volume_snapshot = job.volume_snapshot if isinstance(job.volume_snapshot, dict) else {}
    environment = JobEnvironmentSummary(
        revision_id=_snapshot_uuid(revision_snapshot, "revision_id", job.revision_id),
        environment_id=_snapshot_uuid(revision_snapshot, "environment_id", None),
        name=str(revision_snapshot.get("environment_name") or ""),
        display_label=str(revision_snapshot.get("display_label") or ""),
        fingerprint=str(revision_snapshot.get("fingerprint") or ""),
        image_reference=revision_snapshot.get("image_reference"),
    )
    plan = JobPlanSummary(
        id=_snapshot_uuid(plan_snapshot, "id", job.plan_id),
        name=str(plan_snapshot.get("name") or ""),
        cpu=float(plan_snapshot.get("cpu") or 0),
        memory_mib=int(plan_snapshot.get("memory_mib") or 0),
        disk_mib=int(plan_snapshot.get("disk_mib") or 0),
        gpu_count=int(plan_snapshot.get("gpu_count") or 0),
        cost_per_hour=int(plan_snapshot.get("cost_per_hour") or 0),
    )
    volume_summary = JobVolumeSummary(
        id=_snapshot_uuid(volume_snapshot, "id", job.volume_id),
        display_name=(
            (volume.display_name or volume.name)
            if volume is not None
            else str(volume_snapshot.get("display_name") or "")
        ),
        available=available,
    )
    billing_mode: BillingMode = job.billing_mode or "zero_cost"
    return BatchJobDetail(
        id=job.id,
        name=job.name,
        state=job.state,
        reason_code=job.reason_code,
        reason_message=_REASON_MESSAGES.get(job.reason_code or ""),
        created_at=job.created_at,
        updated_at=job.updated_at,
        queue_expires_at=job.queue_expires_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        deadline_at=job.deadline_at,
        can_cancel=job.state in _CANCELLABLE_STATES,
        replayed=replayed,
        environment=environment,
        plan=plan,
        volume=volume_summary,
        argv=list(job.argv or []),
        limits=JobRuntimeLimits(max_runtime_seconds=job.max_runtime_seconds),
        result=_result(job),
        logs=JobLogSummary(
            state=_effective_log_state(job, payload),
            truncated=bool(payload.truncated if payload is not None else job.log_truncated),
            size_bytes=int(
                (payload.size_bytes if payload is not None else job.log_size_bytes) or 0
            ),
            expires_at=(
                (payload.expires_at if payload is not None else None) or job.log_expires_at
            ),
        ),
        billing=JobBilling(
            mode=billing_mode,
            charged=int(job.charged_credits or 0),
            authorized=int(job.authorized_credits or 0),
            rate_per_hour=int(job.billing_rate_per_hour or 0),
            state=job.billing_state or "none",
            unpaid=max(0, int(unpaid)),
        ),
    )


__all__ = [
    "ACTIVE_JOB_STATES",
    "BatchJobService",
    "JobError",
    "TERMINAL_JOB_STATES",
]
