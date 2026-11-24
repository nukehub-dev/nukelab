# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Fenced stop/delete with reservations retained until runtime deletion is proven.

Authorization, billing reconciliation and notifications belong to the caller.
The service owns clean-session transactions; runtime I/O occurs after commit.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container.driver import ContainerDriver, ContainerDriverError
from app.core.time_utils import utc_now
from app.models.credit_transaction import CreditTransaction
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_volume import ServerVolume
from app.models.user import User
from app.models.volume_operation import VolumeOperation
from app.services.admission_service import acquire_admission_lock
from app.services.gpu_allocator import GpuAllocatorService
from app.services.quota_service import QuotaService
from app.services.server_launch_service import LaunchError
from app.services.server_operation_service import (
    claim_operation,
    create_operation,
    finish_operation,
    get_active,
)
from app.services.volume_operation_service import ACTIVE_STATES, transition_volume_operation
from app.services.worker_heartbeat import current_executor_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Termination:
    server_id: uuid.UUID
    owner_id: uuid.UUID
    operation_id: uuid.UUID
    fencing_token: uuid.UUID
    action: str
    container_id: str | None
    previous_status: str


class ServerTerminationService:
    def __init__(self, db: AsyncSession, driver: ContainerDriver):
        self.db = db
        self.driver = driver

    async def _clean_session(self):
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError("Server termination requires a clean session")
        if self.db.in_transaction():
            await self.db.rollback()

    async def _reserve(self, server_id, owner_id, action, expected_version=None) -> _Termination:
        await self._clean_session()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            conditions = [Server.id == server_id]
            if owner_id is not None:
                conditions.append(Server.user_id == owner_id)
            server = await self.db.scalar(
                select(Server)
                .where(*conditions)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if server is None:
                raise LaunchError("server_not_found", 404)
            if expected_version is not None and server.updated_at != expected_version:
                raise LaunchError("configuration_changed", 409)
            if await get_active(self.db, server_id) is not None or server.status in (
                "starting",
                "stopping",
            ):
                raise LaunchError("launch_in_progress", 409)
            owner = await self.db.scalar(
                select(User)
                .where(User.id == server.user_id)
                .execution_options(populate_existing=True)
            )
            if owner is None:
                raise LaunchError("server_owner_unavailable", 409)
            associations = (
                await self.db.scalars(
                    select(ServerVolume)
                    .where(ServerVolume.server_id == server_id)
                    .order_by(ServerVolume.volume_id)
                    .execution_options(populate_existing=True)
                )
            ).all()
            mounts = [
                {
                    "volume_id": str(mount.volume_id),
                    "mount_path": mount.mount_path,
                    "mode": mount.mode,
                    "is_primary": mount.is_primary,
                }
                for mount in associations
            ]
            if server.volume_id and all(
                mount.volume_id != server.volume_id for mount in associations
            ):
                mounts.append(
                    {
                        "volume_id": str(server.volume_id),
                        "mount_path": f"/home/{owner.username}",
                        "mode": server.volume_mode or "read_write",
                        "is_primary": not any(mount["is_primary"] for mount in mounts),
                    }
                )
            operation = await create_operation(
                self.db,
                server_id=server.id,
                owner_id=server.user_id,
                action=action,
                username=owner.username,
                mounts=mounts,
                resources={
                    "cpu": server.allocated_cpu,
                    "memory": server.allocated_memory,
                    "disk": server.allocated_disk,
                    "gpu": server.allocated_gpu,
                },
                previous_container_id=server.container_id,
                previous_status=server.status,
            )
            operation = await claim_operation(
                self.db,
                operation.id,
                operation.fencing_token,
                executor_id=current_executor_id(),
            )
            if operation is None:
                raise LaunchError("launch_in_progress", 409)
            reservation = _Termination(
                server.id,
                server.user_id,
                operation.id,
                operation.fencing_token,
                action,
                server.container_id,
                server.status,
            )
            server.status = "stopping"
            await self.db.flush()
            return reservation

    async def _remove_runtime(self, operation: _Termination):
        container_id = operation.container_id
        if container_id is None:
            if operation.previous_status not in ("stopped", "pending", "failed", "error"):
                raise LaunchError("runtime_unverified", 503)
            return
        try:
            info = await self.driver.get_container_info(container_id)
        except ContainerDriverError as exc:
            if exc.status == 404:
                return
            raise
        if not isinstance(info, dict) or info.get("Id") != container_id:
            raise LaunchError("runtime_identity_mismatch", 503)
        config = info.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if (
            not isinstance(labels, dict)
            or labels.get("nukelab.server.id") != str(operation.server_id)
            or labels.get("nukelab.user.id") != str(operation.owner_id)
        ):
            raise LaunchError("runtime_identity_mismatch", 503)
        state = info.get("State")
        if not isinstance(state, dict) or type(state.get("Running")) is not bool:
            raise LaunchError("runtime_unverified", 503)
        try:
            if state["Running"]:
                try:
                    await self.driver.stop_container(container_id)
                except ContainerDriverError as exc:
                    if exc.status == 404:
                        return
                    if exc.status != 304:
                        raise
            await self.driver.delete_container(container_id, force=False)
        except ContainerDriverError as exc:
            if exc.status == 404:
                return
            raise
        try:
            await self.driver.get_container_info(container_id)
        except ContainerDriverError as exc:
            if exc.status == 404:
                return
            raise
        raise LaunchError("runtime_unverified", 503)

    async def _release_mounts(self, server_id):
        operation_ids = set(
            (
                await self.db.scalars(
                    select(ServerLaunchOperation.id).where(
                        ServerLaunchOperation.server_id == server_id
                    )
                )
            ).all()
        ) | {server_id}
        guards = (
            await self.db.scalars(
                select(VolumeOperation)
                .where(
                    VolumeOperation.operation_id.in_(operation_ids),
                    VolumeOperation.kind == "mount",
                    VolumeOperation.state.in_(ACTIVE_STATES),
                )
                .order_by(VolumeOperation.volume_id, VolumeOperation.operation_id)
                .execution_options(populate_existing=True)
            )
        ).all()
        for guard in guards:
            await transition_volume_operation(
                self.db,
                operation_id=guard.operation_id,
                volume_id=guard.volume_id,
                fencing_token=guard.fencing_token,
                state="succeeded",
                executor_terminated=True,
            )

    async def _finalize(self, operation: _Termination) -> Server | None:
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            server = await self.db.scalar(
                select(Server)
                .where(Server.id == operation.server_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            active = await get_active(self.db, operation.server_id)
            if (
                server is None
                or active is None
                or active.id != operation.operation_id
                or active.fencing_token != operation.fencing_token
                or server.status != "stopping"
                or server.container_id != operation.container_id
            ):
                raise LaunchError("launch_in_progress", 409)
            server.status = "stopped"
            server.container_id = None
            if operation.previous_status != "stopped":
                server.stopped_at = utc_now()
            server.expires_at = None
            server.status_reason = None
            await GpuAllocatorService(self.db).release(str(server.id), commit=False)
            await self._release_mounts(server.id)
            finished = await finish_operation(
                self.db,
                operation.operation_id,
                operation.fencing_token,
                "succeeded",
                runtime_verified=True,
            )
            if finished is None:
                raise LaunchError("launch_in_progress", 409)
            await self.db.flush()
            if operation.action == "delete":
                await self.db.execute(
                    delete(CreditTransaction).where(CreditTransaction.server_id == server.id)
                )
                await self.db.delete(server)
                await self.db.flush()
            await QuotaService(self.db).recalculate_usage(str(operation.owner_id), commit=False)
            return server if operation.action == "stop" else None

    async def _uncertain(self, operation: _Termination):
        await self.db.rollback()
        async with self.db.begin():
            await acquire_admission_lock(self.db)
            server = await self.db.scalar(
                select(Server)
                .where(Server.id == operation.server_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            active = await get_active(self.db, operation.server_id)
            if (
                active is None
                or active.id != operation.operation_id
                or active.fencing_token != operation.fencing_token
            ):
                return
            if server is not None and server.status == "stopping":
                server.status_reason = "recovery_required"
            await finish_operation(
                self.db,
                operation.operation_id,
                operation.fencing_token,
                "uncertain",
                reason_code="recovery_required",
            )

    async def _terminate(self, server_id, owner_id, action, expected_version=None):
        operation = await self._reserve(server_id, owner_id, action, expected_version)
        try:
            await self._remove_runtime(operation)
            return await self._finalize(operation)
        except BaseException as exc:
            try:
                await self._uncertain(operation)
            except Exception:
                logger.exception("Server termination requires reconciliation")
            if not isinstance(exc, Exception):
                raise
            raise LaunchError("recovery_required", 503) from exc

    async def stop(
        self, server_id: uuid.UUID, owner_id: uuid.UUID | None = None, *, expected_version=None
    ) -> Server:
        return await self._terminate(server_id, owner_id, "stop", expected_version)

    async def delete(self, server_id: uuid.UUID, owner_id: uuid.UUID | None = None) -> None:
        await self._terminate(server_id, owner_id, "delete")
