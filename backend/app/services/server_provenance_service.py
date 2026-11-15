# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Sanitized manifests and append-only launch capture; no provisioning side effects."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment_revision import EnvironmentRevision
from app.models.server_launch_record import ServerLaunchRecord
from app.schemas.environment_manifest import (
    EnvironmentManifest,
    ImageIdentity,
    ManifestResources,
    VolumeRequirement,
)
from app.services.environment_revision_service import (
    EnvironmentRevisionService,
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
    portable = all(image.registry_verified for image in (runtime, toolchain) if image)
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
        template_label=template_label,
        runtime=runtime,
        toolchain=toolchain,
        toolchain_mounts=revision.configuration.get("tool_mounts", []),
        environment_variable_names=sorted(revision.configuration.get("environment_variables", {})),
        resources=resources,
        volume_requirements=volumes or [],
        portability="registry_verified" if portable else "local_only",
        limitations=limitations,
    )


class ServerProvenanceService:
    def __init__(self, db: AsyncSession, revisions: EnvironmentRevisionService):
        self.db = db
        self.revisions = revisions

    async def validate_recreation(self, raw: str | bytes) -> EnvironmentRevision:
        manifest = EnvironmentManifest.parse_import(raw)
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
