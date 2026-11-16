# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Normalize and authorize launch volume intent without runtime provisioning.

Admission must repeat this validation under its transaction and persist writer/
mount reservations before external work. Enqueue validation reserves no storage.
"""

import re
from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.server_plan import ServerPlan
from app.models.user import User
from app.models.volume import Volume
from app.schemas.server_launch import (
    NormalizedLaunchRequest,
    NormalizedVolumeMount,
    VolumeMode,
    VolumeSelection,
)
from app.services.quota_service import QuotaService
from app.services.volume_access_service import VolumeAccessService
from app.services.volume_service import VolumeService


class LaunchValidationError(ValueError):
    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class _LaunchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    plan_id: UUID
    environment_id: UUID
    volume_id: VolumeSelection | None = None
    volume_mode: VolumeMode | None = "read_write"
    volume_mounts: list[NormalizedVolumeMount] | None = Field(default=None, max_length=32)


def normalize_launch_request(
    request: Mapping | BaseModel, *, username: str
) -> NormalizedLaunchRequest:
    """Preserve blank selections; legacy/default mounts target the user's home.

    A nonempty multi-mount selection takes precedence over legacy fields, matching
    the existing API. An empty multi-mount list uses the legacy/default behavior.
    The configured runtime home alias is resolved before checking path collisions.
    """
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", username):
        raise LaunchValidationError("invalid_username")
    source = request.model_dump(mode="json") if isinstance(request, BaseModel) else dict(request)
    parsed = _LaunchInput.model_validate(source)
    mounts = parsed.volume_mounts
    if not mounts:
        mounts = [
            NormalizedVolumeMount(
                volume_id=parsed.volume_id or "",
                mount_path=f"/home/{username}",
                mode=parsed.volume_mode or "read_write" if parsed.volume_id else "read_write",
            )
        ]
    return NormalizedLaunchRequest(
        name=parsed.name,
        plan_id=parsed.plan_id,
        environment_id=parsed.environment_id,
        volume_mounts=[
            mount.model_copy(
                update={
                    "is_primary": index == 0,
                    "mount_path": f"/home/{username}"
                    if mount.mount_path == f"/home/{settings.container_user}"
                    else mount.mount_path,
                }
            )
            for index, mount in enumerate(mounts)
        ],
    )


async def validate_launch_volumes(
    db: AsyncSession,
    user: User,
    request: NormalizedLaunchRequest,
    plan: ServerPlan,
) -> list[NormalizedVolumeMount]:
    """Validate stored capacity, current access/status, and total new reservation.

    No filesystem measurements or runtime calls occur here. Admission/launch must
    enforce actual storage limits as usual; persisted usage is not a live snapshot.
    Pending requests do not consume quota. Missing auto-create sizes are made
    explicit using the selected plan's disk capacity, while IDs remain blank.
    """
    # Revalidate copies, since frozen Pydantic models still contain mutable lists.
    request = NormalizedLaunchRequest.model_validate(request.model_dump())
    if request.plan_id != plan.id:
        raise LaunchValidationError("configuration_changed", 409)
    try:
        plan_bytes = VolumeService(db)._parse_memory(plan.disk_limit)
    except (TypeError, ValueError, OverflowError):
        raise LaunchValidationError("configuration_changed", 409) from None
    if not 0 < plan_bytes <= 2**63 - 1:
        raise LaunchValidationError("configuration_changed", 409)
    selected_ids = [mount.volume_id for mount in request.volume_mounts if mount.volume_id != ""]
    volumes = {}
    if selected_ids:
        result = await db.execute(
            select(Volume)
            .where(Volume.id.in_(selected_ids))
            .execution_options(populate_existing=True)
        )
        volumes = {volume.id: volume for volume in result.scalars().all()}
    access = VolumeAccessService(db)
    total_capacity = new_capacity = 0
    validated = []
    for mount in request.volume_mounts:
        if mount.volume_id == "":
            capacity = mount.max_size_bytes or plan_bytes
            if capacity > plan_bytes:
                raise LaunchValidationError("volume_capacity_exceeded")
            new_capacity += capacity
            validated.append(mount.model_copy(update={"max_size_bytes": capacity}))
        else:
            volume = volumes.get(mount.volume_id)
            # Do not expose foreign or unavailable volume names/metadata.
            if volume is None or not await access.can_access_volume(
                str(mount.volume_id), str(user.id), mount.mode
            ):
                raise LaunchValidationError("volume_unavailable", 403)
            if volume.status != "active":
                raise LaunchValidationError("volume_unavailable", 409)
            used = volume.size_bytes or 0
            capacity = volume.max_size_bytes if volume.max_size_bytes is not None else used
            if used < 0 or capacity < 0 or used > plan_bytes or capacity > plan_bytes:
                raise LaunchValidationError("volume_capacity_exceeded")
            # Persisted over-limit usage must not bypass plan accounting.
            capacity = max(used, capacity)
            validated.append(mount)
        total_capacity += capacity
    if total_capacity > plan_bytes:
        raise LaunchValidationError("volume_capacity_exceeded")
    if new_capacity:
        quota = await QuotaService(db).check_volume_creation_allowed(
            user_id=str(user.id), requested_size_bytes=new_capacity, commit=False
        )
        if not quota["allowed"]:
            raise LaunchValidationError("quota_exceeded", 429)
    return validated
