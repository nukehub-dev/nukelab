# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admission and immutable generations for start/restart/reconfiguration."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.config import settings
from app.container.driver import ContainerDriverError
from app.core.permissions import Permission
from app.core.security import has_permission
from app.core.time_utils import utc_now
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_queue import ServerQueue
from app.models.server_volume import ServerVolume
from app.models.user import User
from app.models.volume import Volume
from app.schemas.server_launch import NormalizedVolumeMount
from app.services.admission_service import acquire_admission_lock
from app.services.gpu_allocator import GpuAllocatorService
from app.services.quota_service import QuotaService
from app.services.resource_pool_service import ResourcePoolService
from app.services.server_launch_service import (
    LaunchError,
    LaunchReservation,
    ServerLaunchService,
)
from app.services.server_launch_validation import (
    LaunchValidationError,
    normalize_launch_request,
    validate_launch_volumes,
)
from app.services.server_operation_service import (
    ACTIVE_STATES,
    claim_operation,
    create_operation,
    finish_operation,
    get_active,
)
from app.services.volume_operation_service import acquire_volume_operations

COMPUTE_STATES = ("running", "starting", "stopping")


class ServerLifecycleService(ServerLaunchService):
    async def _server(self, server_id, owner_id=None, *, lock=False):
        conditions = [Server.id == server_id]
        if owner_id is not None:
            conditions.append(Server.user_id == owner_id)
        query = select(Server).where(*conditions).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        server = await self.db.scalar(query)
        if server is None:
            raise LaunchError("server_not_found", 404)
        return server

    async def _mounts(self, server, username):
        records = (
            await self.db.scalars(
                select(ServerVolume)
                .where(
                    ServerVolume.server_id == server.id,
                )
                .order_by(ServerVolume.is_primary.desc(), ServerVolume.volume_id)
            )
        ).all()
        mounts = [
            {
                "volume_id": str(row.volume_id),
                "mount_path": row.mount_path,
                "mode": row.mode,
                "is_primary": index == 0,
            }
            for index, row in enumerate(records)
        ]
        if not mounts and server.volume_id:
            mounts = [
                {
                    "volume_id": str(server.volume_id),
                    "mount_path": f"/home/{username}",
                    "mode": server.volume_mode or "read_write",
                    "is_primary": True,
                }
            ]
        for mount in mounts:
            volume = await self.db.get(
                Volume, uuid.UUID(mount["volume_id"]), populate_existing=True
            )
            if volume is None:
                raise LaunchError("volume_unavailable")
            mount["volume_name"] = volume.name
            mount["auto_created"] = (volume.labels or {}).get("initialize_for_server") == str(
                server.id
            )
        return mounts

    async def _fits(self, server, cpu, memory, disk):
        available = await ResourcePoolService(self.db).get_available_resources()
        parse = ResourcePoolService._parse_memory
        own = server.status in COMPUTE_STATES
        return (
            cpu
            <= available["cpu"]["total"]
            - available["cpu"]["allocated"]
            + (server.allocated_cpu if own else 0)
            and parse(memory)
            <= available["memory_mb"]["total"]
            - available["memory_mb"]["allocated"]
            + (parse(server.allocated_memory) if own else 0)
            and parse(disk)
            <= available["disk_mb"]["total"]
            - available["disk_mb"]["allocated"]
            + (parse(server.allocated_disk) if own else 0)
        )

    async def _name_available(self, owner_id, server_id, name):
        if (
            await self.db.scalar(
                select(Server.id).where(
                    Server.user_id == owner_id,
                    Server.id != server_id,
                    Server.name == name,
                )
            )
            is not None
            or await self.db.scalar(
                select(ServerQueue.id).where(
                    ServerQueue.user_id == owner_id,
                    ServerQueue.server_name == name,
                    ServerQueue.status.in_(["pending", "starting"]),
                )
            )
            is not None
            or await self.db.scalar(
                select(ServerLaunchOperation.id).where(
                    ServerLaunchOperation.owner_id == owner_id,
                    ServerLaunchOperation.server_id != server_id,
                    ServerLaunchOperation.state.in_(ACTIVE_STATES),
                    ServerLaunchOperation.request_payload["name"].astext == name,
                )
            )
            is not None
        ):
            raise LaunchError("request_already_exists")

    async def reserve_existing(
        self,
        server_id,
        *,
        owner_id=None,
        request=None,
        action="start",
        expected_version=None,
    ):
        if action not in ("start", "restart", "update"):
            raise ValueError("Invalid lifecycle action")
        await self._clear_read_transaction()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            server = await self._server(server_id, owner_id, lock=True)
            if expected_version is not None and server.updated_at != expected_version:
                raise LaunchError("configuration_changed")
            expected_version = server.updated_at
            if server.status in ("starting", "stopping") or await get_active(self.db, server_id):
                raise LaunchError("launch_in_progress")
            owner = await self.db.get(User, server.user_id, populate_existing=True)
            if owner is None or not has_permission(owner, Permission.SERVERS_WRITE_OWN):
                raise LaunchError("permission_revoked", 403)
            if action == "start" and request is None and server.status == "running":
                return server
            if request is None and server.plan_id:
                from app.services.plan_service import PlanService

                if not await PlanService(self.db).can_user_use_plan(
                    str(server.plan_id), owner.role, str(owner.id)
                ):
                    raise LaunchError("permission_revoked", 403)
            owner_uuid = owner.id
            previous = await self._mounts(server, owner.username)
            if request is None and (not server.plan_id or not server.environment_id):
                # A legacy container may be resumed, but no approved configuration
                # can be invented for recreating it.
                if not server.container_id or action != "start":
                    raise LaunchError("revision_unavailable")
                legacy = True
                revision_id = None
            else:
                legacy = False
                if request is None:
                    body = {
                        "name": server.name,
                        "plan_id": str(server.plan_id),
                        "environment_id": str(server.environment_id),
                    }
                    if previous:
                        body["volume_mounts"] = [
                            {k: m[k] for k in ("volume_id", "mount_path", "mode")} for m in previous
                        ]
                    request = normalize_launch_request(body, username=owner.username)
                await self._policy(owner_uuid, request)
                latest = await self.db.scalar(
                    select(ServerLaunchRecord)
                    .where(
                        ServerLaunchRecord.server_id == server_id,
                    )
                    .order_by(ServerLaunchRecord.generation.desc())
                    .limit(1)
                )
                revision_id = (
                    latest.revision_id
                    if latest and request.environment_id == server.environment_id
                    else None
                )
        # Resolving an approved selection may pull; never do that inside admission.
        if not legacy and revision_id is None:
            revision_id = await self.resolve_revision(owner_uuid, request)
        await self._clear_read_transaction()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            server = await self._server(server_id, owner_id, lock=True)
            if server.updated_at != expected_version:
                raise LaunchError("configuration_changed")
            if server.status in ("starting", "stopping") or await get_active(self.db, server_id):
                raise LaunchError("launch_in_progress")
            owner = await self.db.get(User, server.user_id, populate_existing=True)
            if owner is None or not has_permission(owner, Permission.SERVERS_WRITE_OWN):
                raise LaunchError("permission_revoked", 403)
            previous = await self._mounts(server, owner.username)
            operation_id = uuid.uuid4()
            allocator = GpuAllocatorService(self.db)
            if legacy:
                if not server.container_id or (allocator.enabled() and server.allocated_gpu):
                    raise LaunchError("revision_unavailable")
                desired = {
                    "cpu": server.allocated_cpu,
                    "memory": server.allocated_memory,
                    "disk": server.allocated_disk,
                    "gpu": server.allocated_gpu or 0,
                }
                quota = await QuotaService(self.db).recalculate_usage(
                    str(owner.id), str(server.id), commit=False
                )
                parse = ResourcePoolService._parse_memory
                if (
                    quota.usage_cpu + desired["cpu"] > quota.max_cpu_total
                    or quota.usage_memory_mb + parse(desired["memory"])
                    > parse(quota.max_memory_total)
                    or quota.usage_gpu + desired["gpu"] > quota.max_gpu_total
                    or quota.usage_servers + 1 > quota.max_servers_total
                ):
                    raise LaunchError("quota_exceeded", 429)
                from app.services.volume_access_service import VolumeAccessService

                access = VolumeAccessService(self.db)
                for mount in previous:
                    try:
                        NormalizedVolumeMount.canonical_mount_path(mount["mount_path"])
                    except ValueError:
                        raise LaunchValidationError("invalid_mount_path", 422) from None
                    volume = await self.db.get(
                        Volume, uuid.UUID(mount["volume_id"]), populate_existing=True
                    )
                    if (
                        volume is None
                        or volume.status != "active"
                        or not await access.can_access_volume(
                            mount["volume_id"], str(owner.id), mount["mode"]
                        )
                    ):
                        raise LaunchError("volume_unavailable", 403)
                if settings.credits_enabled and (owner.nuke_balance or 0) <= 0:
                    raise LaunchError("insufficient_credits", 402)
                mounts = previous
                generation = None
                environment_slug = None
            else:
                owner, plan, environment = await self._policy(owner.id, request)
                revision = await self._revisions(owner.id).require_available(revision_id)
                if revision.template_id != request.environment_id:
                    raise LaunchError("revision_unavailable")
                await self._name_available(owner.id, server.id, request.name)
                if not (
                    await QuotaService(self.db).check_spawn_allowed(
                        str(owner.id),
                        str(plan.id),
                        str(server.id),
                        commit=False,
                        include_gpu_pool=False,
                    )
                )["allowed"]:
                    raise LaunchError("quota_exceeded", 429)
                if settings.credits_enabled and (owner.nuke_balance or 0) < (
                    plan.cost_per_hour or 0
                ):
                    raise LaunchError("insufficient_credits", 402)
                selections = await validate_launch_volumes(
                    self.db,
                    owner,
                    request,
                    plan,
                    protected_mount_paths=(
                        revision.configuration.get("tool_mounts") or ["/opt/nuke"]
                    )
                    if revision.toolchain_identity
                    else (),
                )
                request = request.model_copy(update={"volume_mounts": selections})
                mounts = []
                for selection in selections:
                    auto = selection.volume_id == ""
                    if auto:
                        volume = Volume(
                            id=uuid.uuid4(),
                            name=f"nukelab-volume-{uuid.uuid4().hex}",
                            display_name=f"{request.name} Data",
                            owner_id=owner.id,
                            visibility="private",
                            status="active",
                            max_size_bytes=selection.max_size_bytes,
                            size_bytes=0,
                            labels={"launch_id": str(operation_id)},
                        )
                        self.db.add(volume)
                        await self.db.flush()
                    else:
                        volume = await self.db.get(Volume, selection.volume_id)
                    mounts.append(
                        {
                            **selection.model_dump(mode="json"),
                            "volume_id": str(volume.id),
                            "volume_name": volume.name,
                            "auto_created": auto
                            or (volume.labels or {}).get("initialize_for_server") == str(server.id),
                        }
                    )
                desired = {
                    "cpu": plan.cpu_limit,
                    "memory": plan.memory_limit,
                    "disk": plan.disk_limit,
                    "gpu": plan.gpu_limit or 0,
                }
                generation = (
                    await self.db.scalar(
                        select(func.max(ServerLaunchRecord.generation)).where(
                            ServerLaunchRecord.server_id == server.id
                        )
                    )
                ) or 0
                generation += 1
                environment_slug = environment.slug
            if not await self._fits(server, desired["cpu"], desired["memory"], desired["disk"]):
                raise LaunchError("capacity_wait", 409)
            held_devices = await allocator.devices_for(str(server.id))
            devices = [device for device in held_devices if device in allocator.pool()][
                : desired["gpu"]
            ]
            needed = desired["gpu"] - len(devices) if allocator.enabled() else 0
            if needed:
                acquired = await allocator.allocate(str(server.id), needed, commit=False)
                if acquired is None:
                    raise LaunchError("gpu_wait", 409)
                devices.extend(acquired)
            volume_ids = {uuid.UUID(m["volume_id"]) for m in [*previous, *mounts]}
            if volume_ids:
                await acquire_volume_operations(
                    self.db,
                    volume_ids=sorted(volume_ids),
                    owner_id=owner.id,
                    operation_id=operation_id,
                    kind="mount",
                )
            for mount in mounts:
                volume = await self.db.get(Volume, uuid.UUID(mount["volume_id"]))
                self._remember_volume_use(volume, mount["mount_path"], owner.username)
            old_status, old_container = server.status, server.container_id
            operation = await create_operation(
                self.db,
                server_id=server.id,
                owner_id=owner.id,
                action=action,
                operation_id=operation_id,
                revision_id=revision_id,
                request_payload=request.model_dump(mode="json") if request is not None else None,
                mounts=mounts,
                previous_mounts=previous,
                gpu_devices=devices,
                username=owner.username,
                environment_slug=environment_slug,
                resources=desired,
                generation=generation,
                previous_container_id=old_container,
                previous_status=old_status,
            )
            # A shrinking replacement cannot release capacity while the old runtime lives.
            active = old_status in COMPUTE_STATES
            parse = ResourcePoolService._parse_memory
            server.allocated_cpu = max(server.allocated_cpu if active else 0, desired["cpu"])
            server.allocated_memory = (
                f"{max(parse(server.allocated_memory) if active else 0, parse(desired['memory']))}m"
            )
            server.allocated_disk = (
                f"{max(parse(server.allocated_disk) if active else 0, parse(desired['disk']))}m"
            )
            server.allocated_gpu = max(server.allocated_gpu if active else 0, desired["gpu"])
            server.status = "starting"
            server.status_reason = None
            await QuotaService(self.db).recalculate_usage(str(owner.id), commit=False)
            if legacy:
                result = operation.id
            else:
                result = LaunchReservation(
                    server.id,
                    owner.id,
                    revision_id,
                    request,
                    owner.username,
                    environment_slug,
                    devices,
                    mounts,
                    operation_id=operation.id,
                    generation=generation,
                    previous_container_id=old_container,
                )
        return result

    async def _resume_legacy(self, operation_id):
        from app.models.server_launch_operation import ServerLaunchOperation

        async with self.db.begin():
            operation = await self.db.get(ServerLaunchOperation, operation_id)
            claim = await claim_operation(self.db, operation.id, operation.fencing_token)
            if claim is None:
                raise LaunchError("launch_in_progress")
            server_id, token, container_id, owner_id = (
                operation.server_id,
                operation.fencing_token,
                operation.previous_container_id,
                operation.owner_id,
            )
        try:
            before = await self.driver.get_container_info(container_id)
            labels = (before.get("Config") or {}).get("Labels") or {}
            if (
                before.get("Id") != container_id
                or labels.get("nukelab.server.id") != str(server_id)
                or labels.get("nukelab.user.id") != str(owner_id)
            ):
                raise LaunchError("runtime_identity_mismatch", 503)
            try:
                await self.driver.start_container(container_id)
            except ContainerDriverError as error:
                if error.status != 304:
                    raise
            after = await self.driver.get_container_info(container_id)
            state = after.get("State") or {}
            if after.get("Image") != before.get("Image") or not (
                state.get("Running") or state.get("Status") == "running"
            ):
                raise LaunchError("runtime_verification_failed", 503)
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                server = await self._server(server_id, owner_id, lock=True)
                if server.status != "starting":
                    raise LaunchError("launch_in_progress")
                if (
                    await finish_operation(
                        self.db, operation_id, token, "succeeded", runtime_verified=True
                    )
                    is None
                ):
                    raise LaunchError("launch_in_progress")
                server.status = "running"
                server.status_reason = None
                server.started_at = server.last_activity = server.last_billed_at = utc_now()
                owner = await self.db.get(User, owner_id)
                prefs = owner.preferences or {}
                try:
                    duration = (
                        int(prefs["max_server_runtime"]) * 60
                        if prefs.get("max_server_runtime") is not None
                        else settings.server_max_runtime
                    )
                except (ValueError, TypeError):
                    duration = settings.server_max_runtime
                server.expires_at = (
                    utc_now() + timedelta(seconds=duration)
                    if prefs.get("max_server_runtime_enabled", True) and duration > 0
                    else None
                )
                return server
        except BaseException as exc:
            await self.db.rollback()
            async with self.db.begin():
                await finish_operation(
                    self.db,
                    operation_id,
                    token,
                    "uncertain",
                    reason_code="recovery_required",
                )
                server = await self.db.get(Server, server_id)
                if server and server.status == "starting":
                    server.status_reason = "recovery_required"
            if not isinstance(exc, Exception):
                raise
            raise LaunchError("recovery_required", 503) from exc

    async def start(
        self,
        server_id,
        owner_id=None,
        request=None,
        action="start",
        expected_version=None,
    ):
        reservation = await self.reserve_existing(
            server_id,
            owner_id=owner_id,
            request=request,
            action=action,
            expected_version=expected_version,
        )
        if isinstance(reservation, Server):
            return reservation
        if isinstance(reservation, uuid.UUID):
            return await self._resume_legacy(reservation)
        return await self.provision(reservation)

    async def restart(self, server_id, owner_id=None, *, expected_version=None):
        return await self.start(
            server_id,
            owner_id=owner_id,
            action="restart",
            expected_version=expected_version,
        )

    async def update(self, server_id, changes, owner_id=None):
        """Recreate a running configuration or atomically edit an offline selection."""
        from sqlalchemy import delete

        from app.services.xfs_quota_service import xfs_quota_service

        await self._clear_read_transaction()
        async with self.db.begin():
            server = await self._server(server_id, owner_id)
            expected_version = server.updated_at
            owner = await self.db.get(User, server.user_id)
            if owner is None:
                raise LaunchError("permission_revoked", 403)
            existing = await self._mounts(server, owner.username)
            if not server.plan_id or not server.environment_id:
                if (
                    set(changes).issubset({"name", "reason"})
                    and changes.get("name")
                    and server.status == "stopped"
                    and not server.container_id
                ):
                    # Reuse the same public name grammar without creating a launch selection.
                    import re

                    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", changes["name"]):
                        raise LaunchError("invalid_request", 422)
                    await acquire_admission_lock(self.db)
                    server = await self._server(server_id, owner_id, lock=True)
                    if server.updated_at != expected_version:
                        raise LaunchError("configuration_changed")
                    if (
                        server.status != "stopped"
                        or server.container_id
                        or await get_active(self.db, server_id)
                    ):
                        raise LaunchError("launch_in_progress")
                    await self._name_available(server.user_id, server.id, changes["name"])
                    server.name = changes["name"]
                    return server
                raise LaunchError("revision_unavailable")
            payload = {
                "name": server.name,
                "plan_id": str(server.plan_id),
                "environment_id": str(server.environment_id),
            }
            if existing:
                payload["volume_mounts"] = [
                    {key: mount[key] for key in ("volume_id", "mount_path", "mode")}
                    for mount in existing
                ]
            payload.update(
                {
                    key: value
                    for key, value in changes.items()
                    if key in ("name", "plan_id", "environment_id", "volume_mounts")
                    and value is not None
                }
            )
            request = normalize_launch_request(payload, username=owner.username)
            running = server.status in COMPUTE_STATES
        if running:
            return await self.start(
                server_id,
                owner_id=owner_id,
                request=request,
                action="update",
                expected_version=expected_version,
            )
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            server = await self._server(server_id, owner_id, lock=True)
            if server.updated_at != expected_version:
                raise LaunchError("configuration_changed")
            if server.status in COMPUTE_STATES or await get_active(self.db, server_id):
                raise LaunchError("launch_in_progress")
            owner, plan, environment = await self._policy(server.user_id, request)
            await self._name_available(owner.id, server.id, request.name)
            selected = await validate_launch_volumes(
                self.db,
                owner,
                request,
                plan,
                protected_mount_paths=(environment.tool_mounts or ["/opt/nuke"])
                if environment.tool_image
                else (),
            )
            request = request.model_copy(update={"volume_mounts": selected})
            old = await self._mounts(server, owner.username)
            operation_id = uuid.uuid4()
            mounts = []
            for selection in selected:
                auto = selection.volume_id == ""
                if auto:
                    volume = Volume(
                        id=uuid.uuid4(),
                        name=f"nukelab-volume-{uuid.uuid4().hex}",
                        display_name=f"{request.name} Data",
                        owner_id=owner.id,
                        visibility="private",
                        status="active",
                        max_size_bytes=selection.max_size_bytes,
                        size_bytes=0,
                        labels={"initialize_for_server": str(server.id)},
                    )
                    self.db.add(volume)
                    await self.db.flush()
                else:
                    volume = await self.db.get(Volume, selection.volume_id)
                mounts.append(
                    {
                        **selection.model_dump(mode="json"),
                        "volume_id": str(volume.id),
                        "volume_name": volume.name,
                        "auto_created": auto,
                    }
                )
            ids = {uuid.UUID(m["volume_id"]) for m in [*old, *mounts]}
            if ids:
                await acquire_volume_operations(
                    self.db,
                    volume_ids=sorted(ids),
                    owner_id=owner.id,
                    operation_id=operation_id,
                    kind="writer",
                )
            operation = await create_operation(
                self.db,
                server_id=server.id,
                owner_id=owner.id,
                action="update",
                operation_id=operation_id,
                username=owner.username,
                request_payload=request.model_dump(mode="json"),
                mounts=mounts,
                previous_mounts=old,
                resources={
                    "cpu": plan.cpu_limit,
                    "memory": plan.memory_limit,
                    "disk": plan.disk_limit,
                    "gpu": plan.gpu_limit or 0,
                },
                previous_container_id=server.container_id,
                previous_status=server.status,
                environment_slug=environment.slug,
            )
            token = operation.fencing_token
            await claim_operation(self.db, operation_id, token)
        try:
            for mount in mounts:
                if mount["auto_created"]:
                    await self.driver.ensure_volume(
                        mount["volume_name"], labels={"nukelab.managed": "true"}
                    )
                    if (
                        not xfs_quota_service.set_quota(
                            mount["volume_name"], mount["max_size_bytes"]
                        )
                        and settings.xfs_quota_enabled
                    ):
                        raise LaunchError("volume_quota_unavailable", 503)
            async with self.db.begin():
                await acquire_admission_lock(self.db)
                server = await self._server(server_id, owner_id, lock=True)
                if server.status in COMPUTE_STATES:
                    raise LaunchError("launch_in_progress")
                await self.db.execute(
                    delete(ServerVolume).where(ServerVolume.server_id == server_id)
                )
                self.db.add_all(
                    [
                        ServerVolume(
                            server_id=server_id,
                            volume_id=uuid.UUID(m["volume_id"]),
                            mount_path=m["mount_path"],
                            mode=m["mode"],
                            is_primary=m["is_primary"],
                        )
                        for m in mounts
                    ]
                )
                server.name, server.plan_id, server.environment_id = (
                    request.name,
                    request.plan_id,
                    request.environment_id,
                )
                server.volume_id = uuid.UUID(mounts[0]["volume_id"])
                server.volume_mode = mounts[0]["mode"]
                for mount in mounts:
                    volume = await self.db.get(Volume, uuid.UUID(mount["volume_id"]))
                    self._remember_volume_use(
                        volume, mount["mount_path"], owner.username, mounted=False
                    )
                from app.models.volume_operation import VolumeOperation
                from app.services.volume_operation_service import (
                    transition_volume_operation,
                )

                guards = (
                    await self.db.scalars(
                        select(VolumeOperation).where(VolumeOperation.operation_id == operation_id)
                    )
                ).all()
                for guard in guards:
                    await transition_volume_operation(
                        self.db,
                        operation_id=operation_id,
                        volume_id=guard.volume_id,
                        fencing_token=guard.fencing_token,
                        state="succeeded",
                        executor_terminated=True,
                    )
                if (
                    await finish_operation(
                        self.db, operation_id, token, "succeeded", runtime_verified=True
                    )
                    is None
                ):
                    raise LaunchError("launch_in_progress")
                await self.db.flush()
                return server
        except BaseException:
            await self.db.rollback()
            async with self.db.begin():
                await finish_operation(
                    self.db,
                    operation_id,
                    token,
                    "uncertain",
                    reason_code="recovery_required",
                )
            raise
