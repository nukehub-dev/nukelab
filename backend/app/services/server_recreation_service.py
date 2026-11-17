# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Owner-checked history and current-approved recreation without imported authority."""

from pathlib import PurePosixPath
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.permissions import Permission
from app.core.security import has_permission
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_launch_record import ServerLaunchRecord
from app.models.user import User
from app.schemas.environment_manifest import (
    EnvironmentManifest,
    ImageIdentity,
    VolumeRequirement,
    canonical_json,
)
from app.schemas.server_launch import NormalizedVolumeMount, validate_mount_destination
from app.schemas.server_provenance import (
    RecreationPreviewResponse,
    RecreationSource,
    ServerProvenanceResponse,
    ServerRecreateRequest,
)
from app.services.environment_revision_service import (
    EnvironmentRevisionService,
    RevisionUnavailable,
)
from app.services.environment_service import EnvironmentService
from app.services.server_launch_service import LaunchError
from app.services.server_launch_validation import normalize_launch_request
from app.services.server_provenance_service import ServerProvenanceService


class ProvenanceError(ValueError):
    def __init__(self, code: str, status_code: int = 409):
        self.code, self.status_code = code, status_code
        super().__init__(code)


class ServerRecreationService:
    def __init__(self, db: AsyncSession, actor_id: UUID):
        self.db, self.actor_id = db, actor_id
        self.revisions = EnvironmentRevisionService(db, self._authorize_template)
        self.provenance = ServerProvenanceService(db, self.revisions)

    async def _actor(self):
        actor = await self.db.get(User, self.actor_id, populate_existing=True)
        if actor is None or not has_permission(actor, Permission.SERVERS_WRITE_OWN):
            raise LaunchError("permission_revoked", 403)
        return actor

    async def _authorize_template(self, template):
        actor = await self._actor()
        if not await EnvironmentService(self.db).can_user_use_env(str(template.id), actor.role):
            raise LaunchError("permission_revoked", 403)

    @staticmethod
    def _saved_manifest(raw):
        try:
            return EnvironmentManifest.parse_import(canonical_json(raw))
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise ProvenanceError("provenance_unavailable") from None

    async def _history_record(self, server_id, owner_id, launch_id=None):
        statement = select(ServerLaunchRecord).where(
            ServerLaunchRecord.server_id == server_id,
            ServerLaunchRecord.user_id == owner_id,
        )
        if launch_id is not None:
            statement = statement.where(ServerLaunchRecord.id == launch_id)
        record = await self.db.scalar(
            statement.order_by(ServerLaunchRecord.generation.desc()).limit(1)
        )
        if record is None and launch_id is not None:
            raise ProvenanceError("source_launch_not_found", 404)
        return record

    async def history(self, server_id, owner_id, launch_id=None):
        record = await self._history_record(server_id, owner_id, launch_id)
        if record is None:
            return ServerProvenanceResponse(state="unrecorded", recreation_reason_code="unrecorded")
        manifest = self._saved_manifest(record.manifest)
        try:
            runtime = ImageIdentity.model_validate(record.actual_runtime_identity)
            toolchain = (
                ImageIdentity.model_validate(record.actual_toolchain_identity)
                if record.actual_toolchain_identity
                else None
            )
        except (ValidationError, ValueError, TypeError):
            raise ProvenanceError("provenance_unavailable") from None
        reason = "source_not_owned" if owner_id != self.actor_id else None
        if reason is None:
            try:
                await self.preview(RecreationSource(source_launch_id=record.id))
            except (
                ProvenanceError,
                LaunchError,
                RevisionUnavailable,
                ValidationError,
            ) as error:
                reason = getattr(error, "code", "revision_unavailable")
        return ServerProvenanceResponse(
            state="recorded",
            launch_id=record.id,
            generation=record.generation,
            captured_at=record.created_at,
            manifest=manifest,
            actual_runtime=runtime,
            actual_toolchain=toolchain,
            can_recreate=reason is None,
            recreation_reason_code=reason,
        )

    async def export(self, server_id, owner_id, launch_id=None):
        record = await self._history_record(server_id, owner_id, launch_id)
        if record is None:
            raise ProvenanceError("unrecorded")
        return record.id, self._saved_manifest(record.manifest)

    async def _source(self, source: RecreationSource):
        await self._actor()
        if source.source_launch_id is not None:
            record = await self.db.scalar(
                select(ServerLaunchRecord)
                .join(Server, Server.id == ServerLaunchRecord.server_id)
                .where(
                    ServerLaunchRecord.id == source.source_launch_id,
                    ServerLaunchRecord.user_id == self.actor_id,
                    Server.user_id == self.actor_id,
                )
            )
            if record is None:
                raise ProvenanceError("source_launch_not_found", 404)
            manifest = self._saved_manifest(record.manifest)
        else:
            # Revalidate frozen models: their contained collections remain mutable.
            manifest = self._saved_manifest(source.manifest.model_dump(mode="json"))
        revision = await self.provenance.validate_recreation(manifest.model_dump_json())
        return manifest, revision

    @staticmethod
    def _volume_requirements(manifest, username, protected_paths=()):
        if not manifest.volume_requirements:
            raise ProvenanceError("invalid_volume_requirement", 422)
        requirements = []
        paths = set()
        for requirement in manifest.volume_requirements:
            try:
                original = NormalizedVolumeMount(
                    volume_id="",
                    mount_path=requirement.mount_path,
                    mode=requirement.mode,
                )
                path = PurePosixPath(original.mount_path)
                destination = original.mount_path
                if requirement.purpose == "home" and path.parent == PurePosixPath("/home"):
                    destination = f"/home/{username}"
                # Mirror the shared launch alias even for historic data-purpose mounts.
                if destination == f"/home/{settings.container_user}":
                    destination = f"/home/{username}"
                mount = NormalizedVolumeMount(
                    volume_id="", mount_path=destination, mode=requirement.mode
                )
                validate_mount_destination(mount.mount_path, protected_paths=protected_paths)
            except (ValidationError, ValueError):
                raise ProvenanceError("invalid_volume_requirement", 422) from None
            if mount.mount_path in paths:
                raise ProvenanceError("invalid_volume_requirement", 422)
            paths.add(mount.mount_path)
            requirements.append(
                VolumeRequirement(
                    purpose=requirement.purpose,
                    mount_path=mount.mount_path,
                    mode=mount.mode,
                )
            )
        return requirements

    async def preview(self, source: RecreationSource):
        manifest, revision = await self._source(source)
        actor = await self._actor()
        template = await self.db.get(EnvironmentTemplate, revision.template_id)
        return RecreationPreviewResponse(
            manifest=manifest,
            environment_label=template.name,
            volume_requirements=self._volume_requirements(
                manifest,
                actor.username,
                (revision.configuration.get("tool_mounts") or ["/opt/nuke"])
                if revision.toolchain_identity
                else (),
            ),
        )

    async def prepare(self, request: ServerRecreateRequest):
        manifest, revision = await self._source(request)
        actor = await self._actor()
        # A preview is advisory. Repeat source approval and mount grammar on submit.
        requirements = self._volume_requirements(
            manifest,
            actor.username,
            (revision.configuration.get("tool_mounts") or ["/opt/nuke"])
            if revision.toolchain_identity
            else (),
        )
        normalized = normalize_launch_request(
            {
                "name": request.name,
                "plan_id": str(request.plan_id),
                "environment_id": str(revision.template_id),
                "volume_mounts": [mount.model_dump(mode="json") for mount in request.volume_mounts],
            },
            username=actor.username,
        )
        if [(mount.mount_path, mount.mode) for mount in normalized.volume_mounts] != [
            (requirement.mount_path, requirement.mode) for requirement in requirements
        ]:
            raise ProvenanceError("volume_bindings_mismatch", 422)
        return normalized, revision.id
