# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Sanitized manifests and append-only launch capture; no provisioning side effects."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server_launch_record import ServerLaunchRecord
from app.schemas.environment_manifest import (
    EnvironmentManifest,
    ImageIdentity,
    ManifestResources,
    VolumeRequirement,
)
from app.services.environment_revision_service import (
    PORTABLE_CANDIDATE_LIMIT,
    EnvironmentRevisionService,
    RevisionAmbiguous,
    RevisionUnavailable,
)


def build_manifest(
    revision: EnvironmentRevision,
    *,
    template_label: str,
    resources: ManifestResources,
    volumes: list[VolumeRequirement] | None = None,
) -> EnvironmentManifest:
    runtime = ImageIdentity.model_validate(revision.runtime_identity)
    toolchain = (
        ImageIdentity.model_validate(revision.toolchain_identity)
        if revision.toolchain_identity
        else None
    )
    portable = revision.portable_fingerprint is not None and all(
        image.registry_verified for image in (runtime, toolchain) if image
    )
    limitations = [
        "Mutable volume data requires a separate verified backup.",
        "Host kernel, GPU drivers and external services are not captured.",
        "Environment variable values require manual input.",
    ]
    if not portable:
        limitations.append("Local image artifacts must remain available on the original engine.")
    return EnvironmentManifest(
        revision_id=revision.id,
        revision_fingerprint=revision.fingerprint,
        portable_fingerprint=revision.portable_fingerprint if portable else None,
        template_label=template_label,
        runtime=runtime,
        toolchain=toolchain,
        toolchain_mounts=revision.configuration.get("tool_mounts")
        or (["/opt/nuke"] if toolchain else []),
        environment_variable_names=sorted(revision.configuration.get("environment_variables", {})),
        resources=resources,
        volume_requirements=volumes or [],
        portability="registry_verified" if portable else "local_only",
        limitations=limitations,
    )


class ServerProvenanceService:
    def __init__(
        self,
        db: AsyncSession,
        revisions: EnvironmentRevisionService,
        *,
        can_use_template: Callable[[EnvironmentTemplate], Awaitable[bool]] | None = None,
    ):
        self.db = db
        self.revisions = revisions
        # Optional non-raising authorization predicate used for portable matching.
        # Unauthorized candidates are omitted rather than disclosed.
        self.can_use_template = can_use_template

    async def validate_recreation(self, raw: str | bytes) -> EnvironmentRevision:
        manifest = EnvironmentManifest.parse_import(raw)
        if manifest.portability == "registry_verified" and manifest.portable_fingerprint:
            return await self._match_portable_revision(manifest)
        revision = await self.revisions.require_available(manifest.revision_id)
        expected = build_manifest(
            revision, template_label=manifest.template_label, resources=manifest.resources
        )
        if manifest.canonical_environment() != expected.canonical_environment():
            raise RevisionUnavailable(
                "The manifest does not match an approved environment revision"
            )
        # Deliberately return only approval, never imported mounts, resources or environment.
        # The launch boundary must validate current plan and explicit volume selections.
        return revision

    async def _match_portable_revision(self, manifest: EnvironmentManifest) -> EnvironmentRevision:
        """Resolve a portable manifest by current approval, never origin metadata."""
        candidates = await self.revisions.find_active_portable_candidates(
            manifest.portable_fingerprint
        )
        if len(candidates) >= PORTABLE_CANDIDATE_LIMIT:
            # The bounded lookup cannot prove that only one template matches.
            raise RevisionAmbiguous("Multiple approved environments match this portable manifest")
        newest_by_template: dict[UUID, EnvironmentRevision] = {}
        for candidate in candidates:
            newest_by_template.setdefault(candidate.template_id, candidate)
        if not newest_by_template:
            raise RevisionUnavailable("No approved environment matches this portable manifest")
        templates = (
            (
                await self.db.execute(
                    select(EnvironmentTemplate)
                    .where(EnvironmentTemplate.id.in_(list(newest_by_template)))
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        matches = []
        for template in templates:
            if not template.is_active or not await self._can_use(template):
                continue
            matches.append(newest_by_template[template.id])
        if not matches:
            raise RevisionUnavailable("No approved environment matches this portable manifest")
        if len(matches) > 1:
            raise RevisionAmbiguous("Multiple approved environments match this portable manifest")
        # Re-read the chosen approval so current revocation, template status and
        # actor authorization are authoritative for both preview and submit.
        return await self.revisions.require_available(matches[0].id)

    async def _can_use(self, template: EnvironmentTemplate) -> bool:
        if self.can_use_template is not None:
            return bool(await self.can_use_template(template))
        try:
            await self.revisions.authorize_template(template)
        except ValueError:
            # Launch/authorization errors are ValueErrors; omitted, not disclosed.
            return False
        return True

    async def record_launch(
        self,
        *,
        operation_id: UUID,
        server_id: UUID,
        owner_id: UUID,
        generation: int,
        manifest: EnvironmentManifest,
        actual_runtime: ImageIdentity,
        actual_toolchain: ImageIdentity | None,
    ) -> ServerLaunchRecord:
        if generation < 1:
            raise ValueError("Launch generation must be positive")
        revision = await self.revisions.require_available(manifest.revision_id)
        expected = build_manifest(
            revision, template_label=manifest.template_label, resources=manifest.resources
        )
        if manifest.canonical_environment() != expected.canonical_environment():
            raise RevisionUnavailable("Launch configuration does not match the approved revision")
        for approved, observed in (
            (manifest.runtime, actual_runtime),
            (manifest.toolchain, actual_toolchain),
        ):
            if bool(approved) != bool(observed) or (
                approved
                and (
                    approved.local_id != observed.local_id
                    or approved.os != observed.os
                    or approved.architecture != observed.architecture
                )
            ):
                raise RevisionUnavailable("The observed launch artifact does not match approval")
        payload = {
            "server_id": server_id,
            "user_id": owner_id,
            "revision_id": manifest.revision_id,
            "generation": generation,
            "manifest": manifest.model_dump(mode="json"),
            "actual_runtime_identity": actual_runtime.model_dump(mode="json"),
            "actual_toolchain_identity": actual_toolchain.model_dump(mode="json")
            if actual_toolchain
            else None,
        }
        existing = (
            await self.db.execute(
                select(ServerLaunchRecord).where(ServerLaunchRecord.id == operation_id)
            )
        ).scalar_one_or_none()
        if existing:
            if any(getattr(existing, key) != value for key, value in payload.items()):
                raise ValueError("Launch operation identity cannot be reused")
            return existing
        record = ServerLaunchRecord(id=operation_id, **payload)
        self.db.add(record)
        await self.db.flush()
        return record

    async def latest_owned(self, server_id: UUID, owner_id: UUID) -> dict:
        """Caller separately checks server read permission and token scope."""
        record = (
            await self.db.execute(
                select(ServerLaunchRecord)
                .where(
                    ServerLaunchRecord.server_id == server_id,
                    ServerLaunchRecord.user_id == owner_id,
                )
                .order_by(ServerLaunchRecord.generation.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if record is None:
            return {"state": "unrecorded", "manifest": None}
        return {"state": "recorded", "manifest": record.manifest, "launch_id": str(record.id)}
