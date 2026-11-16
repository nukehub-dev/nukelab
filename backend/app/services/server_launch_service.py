# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Shared durable launch orchestration, with database admission before runtime I/O.

This service owns its session's transaction boundaries. Callers must supply a clean
session and keep API authorization/scopes at the transport boundary. Runtime-unknown
outcomes retain starting reservations and mount intents for explicit reconciliation.
"""

import logging
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.container.driver import ContainerDriver
from app.container.spawner import ServerSpawner
from app.core.permissions import Permission
from app.core.security import has_permission
from app.core.time_utils import utc_now
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_launch_intent import ServerLaunchIntent
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.server_volume import ServerVolume
from app.models.user import User
from app.models.volume import Volume
from app.schemas.environment_manifest import ImageIdentity, ManifestResources, VolumeRequirement
from app.schemas.server_launch import NormalizedLaunchRequest
from app.schemas.server_queue import QueuedServerResponse
from app.services.admission_service import acquire_admission_lock
from app.services.environment_revision_service import (
    EnvironmentRevisionService,
    fingerprint,
    template_configuration,
)
from app.services.environment_service import EnvironmentService
from app.services.gpu_allocator import GpuAllocatorService
from app.services.plan_service import PlanService
from app.services.quota_service import QuotaService
from app.services.resource_pool_service import ResourcePoolService
from app.services.server_launch_validation import validate_launch_volumes
from app.services.server_provenance_service import ServerProvenanceService, build_manifest
from app.services.server_queue_service import QueueError, ServerQueueService
from app.services.volume_operation_service import acquire_volume_operations

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


def plan_snapshot(plan: ServerPlan) -> dict:
    return {
        "cpu": plan.cpu_limit,
        "memory": plan.memory_limit,
        "disk": plan.disk_limit,
        "gpu_count": plan.gpu_limit or 0,
        "cost_per_hour": plan.cost_per_hour,
    }


class ServerLaunchService:
    def __init__(self, db: AsyncSession, driver: ContainerDriver):
        self.db = db
        self.driver = driver
        self.spawner = ServerSpawner(driver=driver)

    async def _clear_read_transaction(self):
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Launch service requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

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

    async def resolve_revision(self, owner_id: uuid.UUID, request: NormalizedLaunchRequest):
        """Resolve approved references without holding admission/database locks."""
        await self._clear_read_transaction()
        async with self.db.begin():
            _, _, environment = await self._policy(owner_id, request)
            configuration = template_configuration(environment)
        # Only approved references escape the transaction. Never import image choices.
        identities = []
        for reference in (configuration["image"], configuration["tool_image"]):
            if not reference:
                identities.append(None)
                continue
            if not await self.driver.image_exists(reference):
                if reference.startswith("sha256:"):
                    raise LaunchError("artifact_missing", 409)
                await self.driver.pull_image(reference)
            identities.append(
                ImageIdentity.model_validate(await self.driver.resolve_image(reference))
            )
        if identities[1] is not None:
            self.driver.immutable_toolchain_cache_name(
                identities[1].model_dump(mode="json"), configuration["tool_mounts"] or ["/opt/nuke"]
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
            quota = QuotaService(self.db)
            if not (
                await quota.check_spawn_allowed(
                    str(owner_id), str(plan.id), commit=False, include_gpu_pool=False
                )
            )["allowed"]:
                raise LaunchError("quota_exceeded", 429)
            if settings.credits_enabled and (owner.nuke_balance or 0) < (plan.cost_per_hour or 0):
                raise LaunchError("insufficient_credits", 402)
            mounts = await validate_launch_volumes(self.db, owner, request, plan)
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
                volume.last_mounted_at = utc_now()
                if mount.mount_path == f"/home/{owner.username}":
                    volume.labels = {**(volume.labels or {}), "was_home_volume": True}
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
            )

    async def _stored_reservation(self, server_id, owner_id) -> LaunchReservation:
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
        try:
            async with self.db.begin():
                reservation = await self._stored_reservation(
                    reservation.server_id, reservation.owner_id
                )
                previous = await self.db.get(Server, reservation.server_id, populate_existing=True)
                record = await self.db.get(ServerLaunchRecord, reservation.server_id)
                if previous is not None and previous.status == "running" and record is not None:
                    if (
                        previous.user_id != reservation.owner_id
                        or record.revision_id != reservation.revision_id
                    ):
                        raise LaunchError("launch_in_progress")
                    return previous
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
                if server is None or server.status != "starting" or server.container_id:
                    raise LaunchError("launch_in_progress")
                resources = {
                    "cpu": server.allocated_cpu,
                    "memory": server.allocated_memory,
                    "disk": server.allocated_disk,
                    "gpu": server.allocated_gpu,
                }
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
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                server = await self.db.scalar(
                    select(Server)
                    .where(Server.id == reservation.server_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if server is None or server.status != "starting":
                    raise LaunchError("launch_in_progress")
                for key in ("container_id", "image", "external_url", "health_status"):
                    setattr(server, key, getattr(spawned, key))
                server.status = "running"
                server.status_reason = None
                server.started_at = server.last_activity = server.last_billed_at = utc_now()
                owner = await self.db.get(User, reservation.owner_id)
                prefs = owner.preferences or {}
                if prefs.get("max_server_runtime_enabled", True):
                    try:
                        duration = (
                            int(prefs["max_server_runtime"]) * 60
                            if prefs.get("max_server_runtime") is not None
                            else settings.server_max_runtime
                        )
                    except (ValueError, TypeError):
                        duration = settings.server_max_runtime
                    server.expires_at = (
                        utc_now() + timedelta(seconds=duration) if duration > 0 else None
                    )
                revision = await self._revisions(reservation.owner_id).require_available(
                    reservation.revision_id
                )
                manifest = build_manifest(
                    revision,
                    template_label=reservation.environment_slug,
                    resources=ManifestResources(
                        cpu=server.allocated_cpu,
                        memory_mib=ResourcePoolService._parse_memory(server.allocated_memory),
                        disk_mib=ResourcePoolService._parse_memory(server.allocated_disk),
                        gpu_count=server.allocated_gpu,
                    ),
                    volumes=[
                        VolumeRequirement(
                            purpose="home" if m["is_primary"] else "data",
                            mount_path=m["mount_path"],
                            mode=m["mode"],
                        )
                        for m in reservation.mounts
                    ],
                )
                await ServerProvenanceService(
                    self.db, self._revisions(reservation.owner_id)
                ).record_launch(
                    operation_id=reservation.server_id,
                    server_id=server.id,
                    owner_id=reservation.owner_id,
                    generation=1,
                    manifest=manifest,
                    actual_runtime=actual_runtime,
                    actual_toolchain=actual_toolchain,
                )
                if reservation.queue_id:
                    queue = await self.db.get(
                        ServerQueue,
                        reservation.queue_id,
                        populate_existing=True,
                        with_for_update=True,
                    )
                    if queue.status != "starting" or queue.claim_token != reservation.claim_token:
                        raise LaunchError("launch_in_progress")
                    queue.status = "started"
                    queue.started_at = server.started_at
                    queue.reason_code = None
                return server
        except BaseException as exc:
            await self.db.rollback()
            # A failed waiter is not evidence that its container/helper terminated.
            async with self.db.begin():
                server = await self.db.get(Server, reservation.server_id)
                if server is not None and server.status == "starting":
                    server.status_reason = "recovery_required"
                if reservation.queue_id:
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

    async def submit(self, owner_id: uuid.UUID, request: NormalizedLaunchRequest):
        revision_id = await self.resolve_revision(owner_id, request)
        reservation = await self.reserve(owner_id, request, revision_id)
        if isinstance(reservation, QueuedServerResponse):
            return reservation
        return await self.provision(reservation)
