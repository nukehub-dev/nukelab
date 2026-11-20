# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Approved revision primitives. Callers own authorization and transaction lifetime."""

import hashlib
from collections.abc import Awaitable, Callable
from copy import deepcopy
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.schemas.environment_manifest import ImageIdentity, canonical_json


class RevisionUnavailable(ValueError):
    code = "revision_unavailable"


class ConfigurationChanged(ValueError):
    code = "configuration_changed"


def template_configuration(template: EnvironmentTemplate) -> dict:
    """Private configuration: never serialize this object to a browser."""
    return deepcopy(
        {
            "image": template.image,
            "tool_image": template.tool_image,
            "tool_mounts": (template.tool_mounts or ["/opt/nuke"]) if template.tool_image else [],
            "environment_variables": template.environment_variables or {},
            "packages": template.packages or [],
            "volumes": template.volumes or [],
            "ports": template.ports or [],
        }
    )


def fingerprint(configuration: dict) -> str:
    return hashlib.sha256(canonical_json(configuration).encode()).hexdigest()


class EnvironmentRevisionService:
    def __init__(
        self,
        db: AsyncSession,
        authorize_template: Callable[[EnvironmentTemplate], Awaitable[None]],
    ):
        # This callback must raise on current permission/template access failure.
        self.db = db
        self.authorize_template = authorize_template

    async def capture(
        self,
        template_id: UUID,
        *,
        expected_template_fingerprint: str,
        runtime: ImageIdentity,
        toolchain: ImageIdentity | None = None,
    ) -> EnvironmentRevision:
        """After external resolution, lock and recheck the original approved template."""
        template = (
            await self.db.execute(
                select(EnvironmentTemplate)
                .where(EnvironmentTemplate.id == template_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if template is None or not template.is_active:
            raise RevisionUnavailable("The approved environment is unavailable")
        await self.authorize_template(template)
        configuration = template_configuration(template)
        current_fingerprint = fingerprint(configuration)
        if current_fingerprint != expected_template_fingerprint:
            raise ConfigurationChanged("The environment changed during image resolution")
        if runtime.requested_reference != template.image or (
            bool(toolchain) != bool(template.tool_image)
            or (toolchain and toolchain.requested_reference != template.tool_image)
        ):
            raise ConfigurationChanged("Resolved artifacts do not match the approved template")
        if toolchain and (runtime.os, runtime.architecture) != (
            toolchain.os,
            toolchain.architecture,
        ):
            raise RevisionUnavailable("Runtime and toolchain platforms do not match")
        identities = {
            "configuration": configuration,
            "runtime": runtime.model_dump(mode="json"),
            "toolchain": toolchain.model_dump(mode="json") if toolchain else None,
        }
        revision_fingerprint = fingerprint(identities)
        existing = (
            await self.db.execute(
                select(EnvironmentRevision).where(
                    EnvironmentRevision.template_id == template_id,
                    EnvironmentRevision.fingerprint == revision_fingerprint,
                )
            )
        ).scalar_one_or_none()
        if existing:
            if existing.revoked:
                raise RevisionUnavailable("The environment revision has been revoked")
            return existing
        revision = EnvironmentRevision(
            template_id=template_id,
            fingerprint=revision_fingerprint,
            template_fingerprint=current_fingerprint,
            configuration=configuration,
            runtime_identity=identities["runtime"],
            toolchain_identity=identities["toolchain"],
        )
        self.db.add(revision)
        await self.db.flush()
        return revision

    async def require_available(self, revision_id: UUID) -> EnvironmentRevision:
        revision = (
            await self.db.execute(
                select(EnvironmentRevision)
                .where(EnvironmentRevision.id == revision_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if revision is None or revision.revoked:
            raise RevisionUnavailable("The environment revision is unavailable")
        template = (
            await self.db.execute(
                select(EnvironmentTemplate)
                .where(EnvironmentTemplate.id == revision.template_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if template is None or not template.is_active:
            raise RevisionUnavailable("The approved environment is unavailable")
        await self.authorize_template(template)
        return revision
