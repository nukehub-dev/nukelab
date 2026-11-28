# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Shared durable launch orchestration, with database admission before runtime I/O.

This service owns its session's transaction boundaries. Callers must supply a clean
session and keep API authorization/scopes at the transport boundary. Runtime-unknown
outcomes retain starting reservations and mount intents for explicit reconciliation.
"""

import logging
import uuid
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver, ContainerDriverError
from app.container.spawner import ServerSpawner
from app.core.permissions import Permission
from app.core.security import has_permission
from app.core.time_utils import utc_now
from app.models.environment_template import EnvironmentTemplate
from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server
from app.models.server_launch_intent import ServerLaunchIntent
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.server_volume import ServerVolume
from app.models.user import User
from app.models.volume import Volume
from app.models.volume_operation import VolumeOperation
from app.schemas.environment_manifest import (
    ImageIdentity,
    ManifestResources,
    VolumeRequirement,
)
from app.schemas.server_launch import NormalizedLaunchRequest
from app.schemas.server_queue import QueuedServerResponse
from app.services.admission_service import acquire_admission_lock
from app.services.credit_hold_service import CreditHoldService
from app.services.environment_revision_service import (
    EnvironmentRevisionService,
    fingerprint,
    template_configuration,
)
from app.services.environment_service import EnvironmentService
from app.services.gpu_allocator import GpuAllocatorService
from app.services.operation_heartbeat import SessionFactory, operation_heartbeat
from app.services.plan_service import PlanService
from app.services.quota_service import QuotaService
from app.services.registry_artifact_service import RegistryArtifactService
from app.services.registry_client import RegistryError, VerifiedImage
from app.services.registry_image_service import RegistryImageService
from app.services.resource_pool_service import ResourcePoolService
from app.services.server_launch_validation import validate_launch_volumes
from app.services.server_operation_service import (
    claim_operation,
    create_operation,
    finish_operation,
)
from app.services.server_provenance_service import (
    ServerProvenanceService,
    build_manifest,
)
from app.services.server_queue_service import QueueError, ServerQueueService
from app.services.volume_operation_service import (
    ACTIVE_STATES as ACTIVE_VOLUME_STATES,
)
from app.services.volume_operation_service import (
    acquire_volume_operations,
    transition_volume_operation,
)
from app.services.worker_heartbeat import current_executor_id

logger = logging.getLogger(__name__)


class LaunchError(ValueError):
    def __init__(self, code: str, status_code: int = 409):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class LaunchReservation:
    server_id: uuid.UUID
    owner_id: uuid.UUID
    revision_id: uuid.UUID
    request: NormalizedLaunchRequest
    username: str
    environment_slug: str
    gpu_devices: list[str]
    mounts: list[dict]
    queue_id: uuid.UUID | None = None
    claim_token: uuid.UUID | None = None
    operation_id: uuid.UUID | None = None
    generation: int = 1
    previous_container_id: str | None = None


def plan_snapshot(plan: ServerPlan) -> dict:
    return {
        "cpu": plan.cpu_limit,
        "memory": plan.memory_limit,
        "disk": plan.disk_limit,
        "gpu_count": plan.gpu_limit or 0,
        "cost_per_hour": plan.cost_per_hour,
    }


@dataclass(frozen=True)
class LaunchSuccessOutcome:
    """The exact, already-observed result of one successful launch attempt."""

    server_id: uuid.UUID
    owner_id: uuid.UUID
    operation_id: uuid.UUID | None
    revision_id: uuid.UUID
    generation: int
    request: NormalizedLaunchRequest
    mounts: list[dict]
    environment_slug: str
    actual_runtime: ImageIdentity
    actual_toolchain: ImageIdentity | None
    container_id: str
    image: str
    external_url: str | None
    health_status: str
    resources: dict
    queue_id: uuid.UUID | None = None
    claim_token: uuid.UUID | None = None
    fencing_token: uuid.UUID | None = None


async def finalize_launch_success(
    db: AsyncSession,
    outcome: LaunchSuccessOutcome,
    *,
    revisions: EnvironmentRevisionService,
) -> Server:
    """Apply one verified launch result under admission and row locks.

    Both the live provisioner and crash reconciliation call this function. A
    repeated call for the same terminal operation returns the existing server
    without creating a second provenance row or touching the runtime.
    """
    await acquire_admission_lock(db)
    server = await db.scalar(
        select(Server)
        .where(Server.id == outcome.server_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if server is None:
        raise LaunchError("launch_in_progress")

    operation = None
    if outcome.operation_id is not None:
        operation = await db.get(
            ServerLaunchOperation,
            outcome.operation_id,
            with_for_update=True,
            populate_existing=True,
        )
        if operation is None or operation.fencing_token != outcome.fencing_token:
            raise LaunchError("launch_in_progress")
        if operation.state == "succeeded":
            record = await db.get(ServerLaunchRecord, operation.id, populate_existing=True)
            if (
                server.status == "running"
                and record is not None
                and record.server_id == server.id
                and record.user_id == outcome.owner_id
                and record.revision_id == outcome.revision_id
                and record.generation == outcome.generation
            ):
                return server
            raise LaunchError("launch_in_progress")
        if operation.state not in ("executing", "uncertain"):
            raise LaunchError("launch_in_progress")

    if server.status != "starting":
        raise LaunchError("launch_in_progress")

    for key in ("container_id", "image", "external_url", "health_status"):
        setattr(server, key, getattr(outcome, key))
    for key in ("cpu", "memory", "disk", "gpu"):
        setattr(server, "allocated_" + key, outcome.resources[key])
    server.plan_id = outcome.request.plan_id
    server.environment_id = outcome.request.environment_id
    # A metadata-only volume is initialized once, by its owning launch.
    for mount in outcome.mounts:
        volume = await db.get(Volume, uuid.UUID(mount["volume_id"]))
        if volume is not None and (volume.labels or {}).get("initialize_for_server") == str(
            server.id
        ):
            volume.labels = {
                key: value for key, value in volume.labels.items() if key != "initialize_for_server"
            }
    server.status = "running"
    server.status_reason = None
    server.started_at = server.last_activity = server.last_billed_at = utc_now()
    owner = await db.get(User, outcome.owner_id)
    prefs = (owner.preferences or {}) if owner is not None else {}
    if prefs.get("max_server_runtime_enabled", True):
        try:
            duration = (
                int(prefs["max_server_runtime"]) * 60
                if prefs.get("max_server_runtime") is not None
                else settings.server_max_runtime
            )
        except (ValueError, TypeError):
            duration = settings.server_max_runtime
        server.expires_at = utc_now() + timedelta(seconds=duration) if duration > 0 else None

    revision = await revisions.require_available(outcome.revision_id)
    manifest = build_manifest(
        revision,
        template_label=outcome.environment_slug,
        resources=ManifestResources(
            cpu=server.allocated_cpu,
            memory_mib=ResourcePoolService._parse_memory(server.allocated_memory),
            disk_mib=ResourcePoolService._parse_memory(server.allocated_disk),
            gpu_count=server.allocated_gpu,
        ),
        volumes=[
            VolumeRequirement(
                purpose="home" if mount["is_primary"] else "data",
                mount_path=mount["mount_path"],
                mode=mount["mode"],
            )
            for mount in outcome.mounts
        ],
    )
    await ServerProvenanceService(db, revisions).record_launch(
        operation_id=outcome.operation_id or outcome.server_id,
        server_id=server.id,
        owner_id=outcome.owner_id,
        generation=outcome.generation,
        manifest=manifest,
        actual_runtime=outcome.actual_runtime,
        actual_toolchain=outcome.actual_toolchain,
    )
    if outcome.queue_id:
        queue = await db.get(
            ServerQueue,
            outcome.queue_id,
            populate_existing=True,
            with_for_update=True,
        )
        if queue.status != "starting" or queue.claim_token != outcome.claim_token:
            raise LaunchError("launch_in_progress")
        queue.status = "started"
        queue.started_at = server.started_at
        queue.reason_code = None
    if outcome.operation_id is not None:
        finished = await finish_operation(
            db,
            outcome.operation_id,
            outcome.fencing_token,
            "succeeded",
            runtime_verified=True,
        )
        if finished is None:
            raise LaunchError("launch_in_progress")
    return server


class ServerLaunchService:
    def __init__(
        self,
        db: AsyncSession,
        driver: ContainerDriver,
        *,
        registry: RegistryImageService | None = None,
        artifacts: RegistryArtifactService | None = None,
        heartbeat_session_factory: SessionFactory | None = None,
    ):
        self.db = db
        self.driver = driver
        self.registry = registry or RegistryImageService.from_settings()
        self.artifacts = artifacts or RegistryArtifactService.from_settings(driver)
        self.heartbeat_session_factory = heartbeat_session_factory
        self.spawner = ServerSpawner(driver=driver)

    async def _clear_read_transaction(self):
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Launch service requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    @staticmethod
    def _remember_volume_use(volume, mount_path, username, *, mounted=True):
        if mounted:
            volume.last_mounted_at = utc_now()
        if mount_path == f"/home/{username}":
            volume.labels = {**(volume.labels or {}), "was_home_volume": True}

    async def _policy(self, owner_id, request):
        owner = await self.db.scalar(
            select(User).where(User.id == owner_id).execution_options(populate_existing=True)
        )
        if owner is None or not has_permission(owner, Permission.SERVERS_WRITE_OWN):
            raise LaunchError("permission_revoked", 403)
        plan = await self.db.scalar(
            select(ServerPlan)
            .where(ServerPlan.id == request.plan_id)
            .execution_options(populate_existing=True)
        )
        if plan is None or not plan.is_active:
            raise LaunchError("configuration_changed")
        if not plan.allow_servers:
            raise LaunchError("configuration_changed")
        if not await PlanService(self.db).can_user_use_plan(
            str(plan.id), owner.role, str(owner.id)
        ):
            raise LaunchError("permission_revoked", 403)
        environment = await self.db.scalar(
            select(EnvironmentTemplate)
            .where(EnvironmentTemplate.id == request.environment_id)
            .execution_options(populate_existing=True)
        )
        if environment is None or not await EnvironmentService(self.db).can_user_use_env(
            str(request.environment_id), owner.role
        ):
            raise LaunchError("permission_revoked", 403)
        if (plan.gpu_limit or 0) > 0 and not settings.gpu_enabled:
            raise LaunchError("gpu_unavailable", 400)
        return owner, plan, environment

    def _revisions(self, owner_id):
        async def authorize(template):
            owner = await self.db.scalar(
                select(User).where(User.id == owner_id).execution_options(populate_existing=True)
            )
            if owner is None or not has_permission(owner, Permission.SERVERS_WRITE_OWN):
                raise LaunchError("permission_revoked", 403)
            if not await EnvironmentService(self.db).can_user_use_env(str(template.id), owner.role):
                raise LaunchError("permission_revoked", 403)

        return EnvironmentRevisionService(self.db, authorize)

    @staticmethod
    def _verified_from_identity(identity: ImageIdentity) -> VerifiedImage | None:
        """Rebuild the registry identity stored on an approved revision."""
        if not identity.registry_verified:
            return None
        if (
            identity.verified_reference is None
            or identity.manifest_digest is None
            or identity.descriptor_media_type is None
        ):
            raise LaunchError("revision_unavailable")
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

    @staticmethod
    def _raise_registry_error(error: RegistryError):
        status = 503 if error.code in {"registry_unreachable", "registry_auth_failed"} else 409
        raise LaunchError(error.code, status) from None

    async def _resolve_reference_identity(self, reference: str) -> ImageIdentity:
        """Resolve one approved reference under the registry verification policy."""
        if reference.startswith("sha256:"):
            if not await self.driver.image_exists(reference):
                raise LaunchError("artifact_missing")
            return ImageIdentity.model_validate(await self.driver.resolve_image(reference))

        try:
            resolution = await self.registry.resolve(reference)
        except RegistryError as error:
            self._raise_registry_error(error)

        if resolution.state == "verified":
            if resolution.verified is None:
                raise LaunchError("artifact_mismatch")
            try:
                return await self.artifacts.ensure_local(resolution.verified)
            except RegistryError as error:
                self._raise_registry_error(error)

        if resolution.state == "fallback":
            logger.warning(
                "Registry verification unavailable; recording a local-only artifact",
                extra={"code": resolution.fallback_reason},
            )

        # Policy off, or a truthful prefer fallback with no verified revision yet.
        if not await self.driver.image_exists(reference):
            if reference.startswith("sha256:"):
                raise LaunchError("artifact_missing")
            await self.driver.pull_image(reference)
        return ImageIdentity.model_validate(await self.driver.resolve_image(reference))

    async def _verify_approved_identity(self, approved: ImageIdentity) -> None:
        """Prove an approved identity is locally usable without a tag fallback."""
        verified = self._verified_from_identity(approved)
        if verified is not None:
            try:
                local = await self.artifacts.ensure_local(verified)
            except RegistryError as error:
                self._raise_registry_error(error)
            if (local.local_id, local.os, local.architecture) != (
                approved.local_id,
                approved.os,
                approved.architecture,
            ):
                raise LaunchError("artifact_mismatch")
            return

        if not await self.driver.image_exists(approved.local_id):
            raise LaunchError("artifact_missing")
        actual = ImageIdentity.model_validate(await self.driver.resolve_image(approved.local_id))
        if (actual.local_id, actual.os, actual.architecture) != (
            approved.local_id,
            approved.os,
            approved.architecture,
        ):
            raise LaunchError("revision_unavailable")

    async def resolve_revision(self, owner_id: uuid.UUID, request: NormalizedLaunchRequest):
        """Resolve approved references without holding admission/database locks."""
        await self._clear_read_transaction()
        existing_revision_id = None
        async with self.db.begin():
            _, _, environment = await self._policy(owner_id, request)
            configuration = template_configuration(environment)
            existing = await self._revisions(owner_id).find_active_revision(
                request.environment_id, fingerprint(configuration)
            )
            if existing is not None:
                existing_revision_id = existing.id

        if existing_revision_id is not None:
            # Recheck the template, permission, and approval after the read
            # transaction. A concurrent configuration edit must not reuse a stale
            # approved revision.
            async with self.db.begin():
                _, _, environment = await self._policy(owner_id, request)
                current_fingerprint = fingerprint(template_configuration(environment))
                revision = await self._revisions(owner_id).require_available(existing_revision_id)
                if (
                    revision.template_id != request.environment_id
                    or revision.template_fingerprint != current_fingerprint
                ):
                    raise LaunchError("configuration_changed")
                try:
                    runtime_identity = ImageIdentity.model_validate(revision.runtime_identity)
                    toolchain_identity = (
                        ImageIdentity.model_validate(revision.toolchain_identity)
                        if revision.toolchain_identity
                        else None
                    )
                except ValueError:
                    raise LaunchError("revision_unavailable") from None
            for identity in (runtime_identity, toolchain_identity):
                if identity is not None:
                    await self._verify_approved_identity(identity)
            return existing_revision_id

        # Only approved references escape the transaction. Never import image choices.
        identities = []
        for reference in (configuration["image"], configuration["tool_image"]):
            identities.append(
                await self._resolve_reference_identity(reference) if reference else None
            )
        if identities[1] is not None:
            self.driver.immutable_toolchain_cache_name(
                identities[1].model_dump(mode="json"),
                configuration["tool_mounts"] or ["/opt/nuke"],
            )
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            revision = await self._revisions(owner_id).capture(
                request.environment_id,
                expected_template_fingerprint=fingerprint(configuration),
                runtime=identities[0],
                toolchain=identities[1],
            )
            revision_id = revision.id
        return revision_id

    async def reserve(
        self,
        owner_id: uuid.UUID,
        request: NormalizedLaunchRequest,
        revision_id: uuid.UUID,
        *,
        queue_id: uuid.UUID | None = None,
    ) -> LaunchReservation | QueuedServerResponse | None:
        """Commit a complete reservation or waiting request; never call the runtime."""
        await self._clear_read_transaction()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            owner, plan, environment = await self._policy(owner_id, request)
            revision = await self._revisions(owner_id).require_available(revision_id)
            if revision.template_id != request.environment_id:
                raise LaunchError("revision_unavailable")
            queue = None
            if queue_id is not None:
                queue = await self.db.scalar(
                    select(ServerQueue)
                    .where(ServerQueue.id == queue_id, ServerQueue.user_id == owner_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if queue is None or queue.status != "pending":
                    raise LaunchError("launch_in_progress")
                if queue.plan_snapshot != plan_snapshot(plan):
                    raise LaunchError("configuration_changed")
                if queue.revision_id != revision_id or queue.request_payload != request.model_dump(
                    mode="json"
                ):
                    raise LaunchError("configuration_changed")
            if await self.db.scalar(
                select(Server.id).where(Server.user_id == owner_id, Server.name == request.name)
            ):
                raise LaunchError("request_already_exists")
            other_request = await self.db.scalar(
                select(ServerQueue.id).where(
                    ServerQueue.user_id == owner_id,
                    ServerQueue.server_name == request.name,
                    ServerQueue.status.in_(["pending", "starting"]),
                    ServerQueue.id != queue_id if queue_id else True,
                )
            )
            if other_request is not None:
                raise QueueError("request_already_exists", 409, other_request)
            active_name = await self.db.scalar(
                select(ServerLaunchOperation.id).where(
                    ServerLaunchOperation.owner_id == owner_id,
                    ServerLaunchOperation.state.in_(["prepared", "executing", "uncertain"]),
                    ServerLaunchOperation.request_payload["name"].astext == request.name,
                )
            )
            if active_name is not None:
                raise LaunchError("request_already_exists")
            quota = QuotaService(self.db)
            if not (
                await quota.check_spawn_allowed(
                    str(owner_id), str(plan.id), commit=False, include_gpu_pool=False
                )
            )["allowed"]:
                raise LaunchError("quota_exceeded", 429)
            if settings.credits_enabled and await CreditHoldService.spendable_balance(
                self.db, owner.id
            ) < (plan.cost_per_hour or 0):
                raise LaunchError("insufficient_credits", 402)
            mounts = await validate_launch_volumes(
                self.db,
                owner,
                request,
                plan,
                protected_mount_paths=(revision.configuration.get("tool_mounts") or ["/opt/nuke"])
                if revision.toolchain_identity
                else (),
            )
            request = request.model_copy(update={"volume_mounts": mounts})
            pool = ResourcePoolService(self.db)
            gpu_allocator = GpuAllocatorService(self.db)
            wait_reason = None
            if not await pool.can_fit(str(plan.id)):
                wait_reason = "capacity_wait"
            elif gpu_allocator.enabled() and len(await gpu_allocator.available()) < (
                plan.gpu_limit or 0
            ):
                wait_reason = "gpu_wait"
            if wait_reason:
                if queue_id is not None:
                    queue.reason_code = wait_reason
                    return None
                entry = await ServerQueueService(self.db).enqueue(
                    owner_id=owner_id,
                    name=request.name,
                    plan_id=plan.id,
                    environment_id=request.environment_id,
                    request_payload=request.model_dump(mode="json"),
                    plan_snapshot=plan_snapshot(plan),
                    revision_id=revision_id,
                    reason_code=wait_reason,
                    priority=plan.priority or 0,
                    timeout_seconds=settings.queue_timeout_seconds,
                    max_per_owner=settings.queue_max_pending_per_owner,
                    max_total=settings.queue_max_pending_total,
                )
                description = await ServerQueueService(self.db).describe(entry)
                return QueuedServerResponse(
                    queue_id=entry.id,
                    queue_position=description.position,
                    message=description.message,
                    request=description.request,
                )
            server_id = uuid.uuid4()
            stored_mounts = []
            for mount in mounts:
                auto_created = mount.volume_id == ""
                if auto_created:
                    volume = Volume(
                        id=uuid.uuid4(),
                        name=f"nukelab-volume-{uuid.uuid4().hex}",
                        display_name=f"{request.name} Data",
                        owner_id=owner_id,
                        visibility="private",
                        max_size_bytes=mount.max_size_bytes,
                        status="active",
                        size_bytes=0,
                        labels={"launch_id": str(server_id)},
                    )
                    self.db.add(volume)
                    await self.db.flush()
                else:
                    volume = await self.db.get(Volume, mount.volume_id)
                    if volume is None:
                        raise LaunchError("volume_unavailable")
                    # A newly created empty volume has a root-owned Docker
                    # volume root. Mark it for one-time mount-root permission
                    # setup so the hardened runtime can write to it. Never
                    # touch volumes that already hold data or are attached.
                    if (
                        mount.mode == "read_write"
                        and (volume.size_bytes or 0) == 0
                        and await self.db.scalar(
                            select(ServerVolume.server_id)
                            .where(ServerVolume.volume_id == volume.id)
                            .limit(1)
                        )
                        is None
                    ):
                        volume.labels = {
                            **(volume.labels or {}),
                            "initialize_for_server": str(server_id),
                        }
                        # The spawner uses this persisted flag for its one-time
                        # mount-root setup, including after a queue claim or
                        # recoverable redelivery.
                        auto_created = True
                self._remember_volume_use(volume, mount.mount_path, owner.username)
                stored_mounts.append(
                    {
                        **mount.model_dump(mode="json"),
                        "volume_id": str(volume.id),
                        "volume_name": volume.name,
                        "auto_created": auto_created,
                    }
                )
            primary_id = uuid.UUID(stored_mounts[0]["volume_id"])
            server = Server(
                id=server_id,
                name=request.name,
                user_id=owner_id,
                plan_id=plan.id,
                environment_id=request.environment_id,
                status="starting",
                image=revision.runtime_identity["local_id"],
                allocated_cpu=plan.cpu_limit,
                allocated_memory=plan.memory_limit,
                allocated_disk=plan.disk_limit,
                allocated_gpu=plan.gpu_limit or 0,
                volume_id=primary_id,
                volume_mode=mounts[0].mode,
            )
            self.db.add(server)
            await self.db.flush()
            for mount in stored_mounts:
                self.db.add(
                    ServerVolume(
                        server_id=server_id,
                        volume_id=uuid.UUID(mount["volume_id"]),
                        mount_path=mount["mount_path"],
                        mode=mount["mode"],
                        is_primary=mount["is_primary"],
                    )
                )
            await acquire_volume_operations(
                self.db,
                volume_ids=[uuid.UUID(m["volume_id"]) for m in stored_mounts],
                owner_id=owner_id,
                operation_id=server_id,
                kind="mount",
            )
            devices = await gpu_allocator.allocate(
                str(server_id), plan.gpu_limit or 0, commit=False
            )
            if devices is None:
                raise LaunchError("gpu_wait", 409)
            claim_token = None
            if queue_id is not None:
                claim_token = uuid.uuid4()
                claimed = await ServerQueueService(self.db).claim(
                    queue_id, server_id=server_id, claim_token=claim_token
                )
                if claimed is None:
                    raise LaunchError("launch_in_progress")
            self.db.add(
                ServerLaunchIntent(
                    server_id=server_id,
                    owner_id=owner_id,
                    revision_id=revision_id,
                    request_payload=request.model_dump(mode="json"),
                    mounts=deepcopy(stored_mounts),
                    gpu_devices=list(devices),
                    environment_slug=environment.slug,
                    username=owner.username,
                    queue_id=queue_id,
                    claim_token=claim_token,
                )
            )
            await create_operation(
                self.db,
                server_id=server_id,
                owner_id=owner_id,
                action="create",
                operation_id=server_id,
                revision_id=revision_id,
                request_payload=request.model_dump(mode="json"),
                mounts=stored_mounts,
                gpu_devices=devices,
                username=owner.username,
                environment_slug=environment.slug,
                resources={
                    "cpu": plan.cpu_limit,
                    "memory": plan.memory_limit,
                    "disk": plan.disk_limit,
                    "gpu": plan.gpu_limit or 0,
                },
                generation=1,
            )
            await quota.increment_usage(str(owner_id), str(plan.id), commit=False)
            return LaunchReservation(
                server_id,
                owner_id,
                revision_id,
                request,
                owner.username,
                environment.slug,
                devices,
                stored_mounts,
                queue_id,
                claim_token,
                server_id,
            )

    async def _stored_reservation(self, server_id, owner_id) -> LaunchReservation:
        operation = await self.db.get(ServerLaunchOperation, server_id, populate_existing=True)
        if operation is not None:
            return await self._operation_reservation(operation.id, owner_id)
        intent = await self.db.scalar(
            select(ServerLaunchIntent)
            .where(
                ServerLaunchIntent.server_id == server_id,
                ServerLaunchIntent.owner_id == owner_id,
            )
            .execution_options(populate_existing=True)
        )
        owner = await self.db.scalar(
            select(User).where(User.id == owner_id).execution_options(populate_existing=True)
        )
        if intent is None or owner is None:
            raise LaunchError("launch_intent_unavailable")
        return LaunchReservation(
            server_id,
            owner_id,
            intent.revision_id,
            NormalizedLaunchRequest.model_validate(deepcopy(intent.request_payload)),
            intent.username,
            intent.environment_slug,
            list(intent.gpu_devices),
            deepcopy(intent.mounts),
            intent.queue_id,
            intent.claim_token,
        )

    async def _operation_reservation(self, operation_id, owner_id) -> LaunchReservation:
        operation = await self.db.get(ServerLaunchOperation, operation_id, populate_existing=True)
        if (
            operation is None
            or operation.owner_id != owner_id
            or operation.action not in ("create", "start", "restart", "update")
            or operation.revision_id is None
            or operation.request_payload is None
            or operation.generation is None
        ):
            raise LaunchError("launch_intent_unavailable")
        initial = await self.db.get(ServerLaunchIntent, operation.server_id)
        return LaunchReservation(
            operation.server_id,
            operation.owner_id,
            operation.revision_id,
            NormalizedLaunchRequest.model_validate(deepcopy(operation.request_payload)),
            operation.username,
            operation.environment_slug or "",
            list(operation.gpu_devices),
            deepcopy(operation.mounts),
            initial.queue_id if initial and operation.action == "create" else None,
            initial.claim_token if initial and operation.action == "create" else None,
            operation.id,
            operation.generation,
            operation.previous_container_id,
        )

    async def load_operation_reservation(
        self, operation_id: uuid.UUID, owner_id: uuid.UUID
    ) -> LaunchReservation:
        """Load exact journal intent without authorizing a second executor."""
        await self._clear_read_transaction()
        async with self.db.begin():
            return await self._operation_reservation(operation_id, owner_id)

    async def _remove_previous_runtime(self, reservation: LaunchReservation):
        """Remove only this operation's verified, stopped predecessor by exact ID."""
        container_id = reservation.previous_container_id
        if not container_id:
            return

        async def inspect_previous():
            try:
                info = await self.driver.get_container_info(container_id)
            except ContainerDriverError as exc:
                if exc.status == 404:
                    return None
                raise LaunchError("runtime_inspection_unavailable", 503) from exc
            labels = info.get("Config", {}).get("Labels") or {}
            if labels.get("nukelab.server.id") != str(reservation.server_id) or labels.get(
                "nukelab.user.id"
            ) != str(reservation.owner_id):
                raise LaunchError("runtime_identity_mismatch", 503)
            if not isinstance(info.get("State", {}).get("Running"), bool):
                raise LaunchError("runtime_inspection_unavailable", 503)
            return info

        previous = await inspect_previous()
        if previous is None:
            return
        if previous["State"]["Running"]:
            try:
                await self.driver.stop_container(container_id)
            except ContainerDriverError as exc:
                if exc.status == 404:
                    return
                if exc.status != 304:
                    raise
            previous = await inspect_previous()
            if previous is None:
                return
            if previous["State"]["Running"]:
                raise LaunchError("runtime_still_running", 503)
        try:
            await self.driver.delete_container(container_id, force=False)
        except ContainerDriverError as exc:
            if exc.status != 404:
                raise

    async def _checkpoint_previous_runtime_gone(self, reservation, fencing_token):
        """Move accounting/membership only after verified predecessor termination."""
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            operation = await self.db.get(
                ServerLaunchOperation,
                reservation.operation_id,
                populate_existing=True,
                with_for_update=True,
            )
            if (
                operation is None
                or operation.fencing_token != fencing_token
                or operation.state != "executing"
            ):
                raise LaunchError("launch_in_progress")
            server = await self.db.get(
                Server,
                reservation.server_id,
                populate_existing=True,
                with_for_update=True,
            )
            if (
                server is None
                or server.status != "starting"
                or server.user_id != reservation.owner_id
            ):
                raise LaunchError("launch_in_progress")
            desired = {uuid.UUID(mount["volume_id"]) for mount in operation.mounts}
            prior_ids = set(
                (
                    await self.db.scalars(
                        select(ServerLaunchOperation.id).where(
                            ServerLaunchOperation.server_id == server.id
                        )
                    )
                ).all()
            ) | {server.id}
            guards = (
                await self.db.scalars(
                    select(VolumeOperation)
                    .where(
                        VolumeOperation.operation_id.in_(prior_ids),
                        VolumeOperation.kind == "mount",
                        VolumeOperation.state.in_(ACTIVE_VOLUME_STATES),
                    )
                    .order_by(VolumeOperation.volume_id, VolumeOperation.operation_id)
                )
            ).all()
            for guard in guards:
                if guard.operation_id == operation.id and guard.volume_id in desired:
                    continue
                await transition_volume_operation(
                    self.db,
                    operation_id=guard.operation_id,
                    volume_id=guard.volume_id,
                    fencing_token=guard.fencing_token,
                    state="succeeded",
                    executor_terminated=True,
                )
            await self.db.execute(
                delete(GpuAllocation).where(
                    GpuAllocation.server_id == server.id,
                    GpuAllocation.device.not_in(operation.gpu_devices),
                )
            )
            await self.db.execute(delete(ServerVolume).where(ServerVolume.server_id == server.id))
            self.db.add_all(
                [
                    ServerVolume(
                        server_id=server.id,
                        volume_id=uuid.UUID(mount["volume_id"]),
                        mount_path=mount["mount_path"],
                        mode=mount["mode"],
                        is_primary=mount["is_primary"],
                    )
                    for mount in operation.mounts
                ]
            )
            if not operation.mounts:
                raise LaunchError("volume_unavailable")
            primary = next(
                (mount for mount in operation.mounts if mount.get("is_primary")),
                operation.mounts[0],
            )
            server.volume_id = uuid.UUID(primary["volume_id"])
            server.volume_mode = primary["mode"]
            for key in ("cpu", "memory", "disk", "gpu"):
                setattr(server, "allocated_" + key, operation.resources[key])
            server.name = reservation.request.name
            server.plan_id = reservation.request.plan_id
            server.environment_id = reservation.request.environment_id
            server.container_id = None
            await self.db.flush()

    async def _provision_runtime_io(
        self,
        reservation: LaunchReservation,
        fencing_token: uuid.UUID | None,
        runtime: ImageIdentity,
        toolchain: ImageIdentity | None,
        configuration: dict,
        resources: dict,
    ):
        """Perform the slow runtime/helper window under the operation heartbeat."""
        await self._remove_previous_runtime(reservation)
        await self._checkpoint_previous_runtime_gone(reservation, fencing_token)
        from app.services.xfs_quota_service import xfs_quota_service

        for mount in reservation.mounts:
            if mount.get("auto_created"):
                await self.driver.ensure_volume(
                    mount["volume_name"],
                    labels={
                        "nukelab.managed": "true",
                        "nukelab.user.id": str(reservation.owner_id),
                    },
                )
                if mount.get("max_size_bytes"):
                    quota_set = xfs_quota_service.set_quota(
                        mount["volume_name"], mount["max_size_bytes"]
                    )
                    if settings.xfs_quota_enabled and not quota_set:
                        raise LaunchError("volume_quota_unavailable", 503)
        # Spawner receives only service-resolved volume names; no new DB/client loop.
        spawned = await self.spawner.spawn(
            user_id=str(reservation.owner_id),
            username=reservation.username,
            server_name=reservation.request.name,
            environment=reservation.environment_slug,
            environment_id=str(reservation.request.environment_id),
            image=runtime.spawn_reference,
            tool_image=toolchain.spawn_reference if toolchain else None,
            tool_mounts=configuration["tool_mounts"],
            env_vars=configuration["environment_variables"],
            volume_mounts=reservation.mounts,
            server_id=str(reservation.server_id),
            gpu_devices=reservation.gpu_devices,
            resolved_images={
                "runtime": runtime.model_dump(mode="json"),
                "toolchain": toolchain.model_dump(mode="json") if toolchain else None,
            },
            launch_operation_id=str(reservation.operation_id),
            **resources,
        )
        actual = await self.driver.get_container_info(spawned.container_id)
        actual_runtime = ImageIdentity.model_validate(
            await self.driver.resolve_image(actual["Image"])
        )
        actual_toolchain = (
            ImageIdentity.model_validate(spawned._observed_toolchain_identity)
            if toolchain
            else None
        )
        if actual_runtime.local_id != runtime.local_id or spawned.health_status != "healthy":
            raise LaunchError("runtime_verification_failed", 503)
        return spawned, actual_runtime, actual_toolchain

    async def load_reservation(
        self, server_id: uuid.UUID, owner_id: uuid.UUID
    ) -> LaunchReservation:
        """Reconstruct exact intent in a new session; this does not authorize retrying I/O.

        A crashed or unknown executor must be reconciled before starting new work.
        Durable intent supplies identity, never TTL-only takeover permission.
        """
        await self._clear_read_transaction()
        async with self.db.begin():
            return await self._stored_reservation(server_id, owner_id)

    async def provision(self, reservation: LaunchReservation) -> Server:
        """Use pinned images and the reserved identity; preserve protection on errors."""
        claimed = False
        fencing_token = None
        try:
            await self._clear_read_transaction()
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                reservation = (
                    await self._operation_reservation(
                        reservation.operation_id, reservation.owner_id
                    )
                    if reservation.operation_id is not None
                    else await self._stored_reservation(reservation.server_id, reservation.owner_id)
                )
                operation = (
                    await self.db.get(
                        ServerLaunchOperation,
                        reservation.operation_id,
                        populate_existing=True,
                    )
                    if reservation.operation_id
                    else None
                )
                if operation is None:
                    raise LaunchError("launch_intent_unavailable")
                previous = await self.db.get(Server, reservation.server_id, populate_existing=True)
                record = await self.db.get(
                    ServerLaunchRecord,
                    reservation.operation_id or reservation.server_id,
                )
                if operation is not None and operation.state in (
                    "executing",
                    "uncertain",
                    "failed",
                ):
                    raise LaunchError("launch_in_progress")
                if (
                    previous is not None
                    and record is not None
                    and (
                        (operation is not None and operation.state == "succeeded")
                        or (operation is None and previous.status == "running")
                    )
                ):
                    if (
                        previous.user_id != reservation.owner_id
                        or record.server_id != reservation.server_id
                        or record.revision_id != reservation.revision_id
                    ):
                        raise LaunchError("launch_in_progress")
                    return previous
                if operation is not None and operation.state != "prepared":
                    raise LaunchError("launch_in_progress")
                revision = await self._revisions(reservation.owner_id).require_available(
                    reservation.revision_id
                )
                runtime = ImageIdentity.model_validate(revision.runtime_identity)
                toolchain = (
                    ImageIdentity.model_validate(revision.toolchain_identity)
                    if revision.toolchain_identity
                    else None
                )
                configuration = dict(revision.configuration)
                server = await self.db.get(Server, reservation.server_id)
                if (
                    server is None
                    or server.status != "starting"
                    or (
                        server.container_id is not None
                        and server.container_id != reservation.previous_container_id
                    )
                ):
                    raise LaunchError("launch_in_progress")
                resources = (
                    deepcopy(operation.resources)
                    if operation is not None
                    else {
                        "cpu": server.allocated_cpu,
                        "memory": server.allocated_memory,
                        "disk": server.allocated_disk,
                        "gpu": server.allocated_gpu,
                    }
                )
                if operation is not None:
                    fencing_token = operation.fencing_token
                    if (
                        await claim_operation(
                            self.db,
                            operation.id,
                            fencing_token,
                            executor_id=current_executor_id(),
                        )
                        is None
                    ):
                        raise LaunchError("launch_in_progress")
            claimed = True
            heartbeat = (
                operation_heartbeat(
                    self.heartbeat_session_factory,
                    kind="launch",
                    operation_id=reservation.operation_id,
                    fencing_token=fencing_token,
                    executor_id=current_executor_id(),
                )
                if reservation.operation_id is not None and fencing_token is not None
                else nullcontext()
            )
            async with heartbeat:
                spawned, actual_runtime, actual_toolchain = await self._provision_runtime_io(
                    reservation,
                    fencing_token,
                    runtime,
                    toolchain,
                    configuration,
                    resources,
                )
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                outcome = LaunchSuccessOutcome(
                    server_id=reservation.server_id,
                    owner_id=reservation.owner_id,
                    operation_id=reservation.operation_id,
                    revision_id=reservation.revision_id,
                    generation=reservation.generation,
                    request=reservation.request,
                    mounts=reservation.mounts,
                    environment_slug=reservation.environment_slug,
                    actual_runtime=actual_runtime,
                    actual_toolchain=actual_toolchain,
                    container_id=spawned.container_id,
                    image=spawned.image,
                    external_url=spawned.external_url,
                    health_status=spawned.health_status,
                    resources=resources,
                    queue_id=reservation.queue_id,
                    claim_token=reservation.claim_token,
                    fencing_token=fencing_token,
                )
                return await finalize_launch_success(
                    self.db,
                    outcome,
                    revisions=self._revisions(reservation.owner_id),
                )
        except BaseException as exc:
            await self.db.rollback()
            if not claimed:
                raise
            # A failed waiter is not evidence that its container/helper terminated.
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                if reservation.operation_id is not None:
                    recovered = await finish_operation(
                        self.db,
                        reservation.operation_id,
                        fencing_token,
                        "uncertain",
                        reason_code="recovery_required",
                    )
                else:
                    recovered = None
                server = await self.db.get(Server, reservation.server_id)
                if (
                    recovered is not None
                    and recovered.state == "uncertain"
                    and server is not None
                    and server.status == "starting"
                ):
                    server.status_reason = "recovery_required"
                if (
                    reservation.queue_id
                    and recovered is not None
                    and recovered.state == "uncertain"
                ):
                    queue = await self.db.get(ServerQueue, reservation.queue_id)
                    if (
                        queue is not None
                        and queue.status == "starting"
                        and queue.claim_token == reservation.claim_token
                    ):
                        queue.reason_code = "recovery_required"
            logger.exception(
                "Launch requires runtime reconciliation",
                extra={"server_id": str(reservation.server_id)},
            )
            if not isinstance(exc, Exception):
                raise
            raise LaunchError("recovery_required", 503) from exc

    async def submit_pinned(
        self,
        owner_id: uuid.UUID,
        request: NormalizedLaunchRequest,
        revision_id: uuid.UUID,
    ):
        """Recreate an approved selection without resolving or substituting a mutable tag."""
        await self._clear_read_transaction()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            owner, plan, _ = await self._policy(owner_id, request)
            revision = await self._revisions(owner_id).require_available(revision_id)
            if revision.template_id != request.environment_id:
                raise LaunchError("revision_unavailable")
            if settings.credits_enabled and await CreditHoldService.spendable_balance(
                self.db, owner.id
            ) < (plan.cost_per_hour or 0):
                raise LaunchError("insufficient_credits", 402)
            runtime = ImageIdentity.model_validate(revision.runtime_identity)
            toolchain = (
                ImageIdentity.model_validate(revision.toolchain_identity)
                if revision.toolchain_identity
                else None
            )
            roots = (
                (revision.configuration.get("tool_mounts") or ["/opt/nuke"]) if toolchain else []
            )
            await validate_launch_volumes(
                self.db, owner, request, plan, protected_mount_paths=roots
            )
        # Immutable identity is the only lookup key; never pull the original tag.
        for approved in (runtime, toolchain):
            if approved is not None:
                await self._verify_approved_identity(approved)
        if toolchain:
            self.driver.immutable_toolchain_cache_name(toolchain.model_dump(mode="json"), roots)
        reservation = await self.reserve(owner_id, request, revision_id)
        if isinstance(reservation, QueuedServerResponse):
            return reservation
        return await self.provision(reservation)

    async def submit(self, owner_id: uuid.UUID, request: NormalizedLaunchRequest):
        revision_id = await self.resolve_revision(owner_id, request)
        reservation = await self.reserve(owner_id, request, revision_id)
        if isinstance(reservation, QueuedServerResponse):
            return reservation
        return await self.provision(reservation)
