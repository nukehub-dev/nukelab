# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Approved revision primitives. Callers own authorization and transaction lifetime."""

import hashlib
from collections.abc import Awaitable, Callable
from copy import deepcopy
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.schemas.environment_manifest import ImageIdentity, canonical_json
from app.services.portable_environment import (
    PortableIdentityUnavailable,
    portable_environment_identity,
)


class RevisionUnavailable(ValueError):
    code = "revision_unavailable"


class RevisionAmbiguous(RevisionUnavailable):
    """More than one current approval matches a portable environment identity."""

    code = "revision_ambiguous"


class ConfigurationChanged(ValueError):
    code = "configuration_changed"


PORTABLE_CANDIDATE_LIMIT = 64


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

    async def find_active_revision(
        self, template_id: UUID, template_fingerprint: str
    ) -> EnvironmentRevision | None:
        """Newest approved revision matching the current template configuration.

        Revoked revisions are history and never satisfy launch reuse. The
        ``created_at``/``id`` ordering keeps the choice deterministic when a
        template has several matching approved revisions.
        """
        return (
            await self.db.execute(
                select(EnvironmentRevision)
                .where(
                    EnvironmentRevision.template_id == template_id,
                    EnvironmentRevision.template_fingerprint == template_fingerprint,
                    EnvironmentRevision.revoked.is_(False),
                )
                .order_by(
                    EnvironmentRevision.created_at.desc(),
                    EnvironmentRevision.id.desc(),
                )
                .limit(1)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def find_active_portable_candidates(
        self,
        portable_fingerprint: str,
        *,
        limit: int = PORTABLE_CANDIDATE_LIMIT,
    ) -> list[EnvironmentRevision]:
        """Active revisions sharing a portable fingerprint, newest first.

        Revoked revisions are history and never satisfy cross-install matching.
        The bounded ``created_at``/``id`` ordering keeps the choice deterministic
        when a template has several matching approved revisions.
        """
        if limit < 1:
            raise ValueError("Portable candidate limit must be positive")
        result = await self.db.execute(
            select(EnvironmentRevision)
            .where(
                EnvironmentRevision.portable_fingerprint == portable_fingerprint,
                EnvironmentRevision.revoked.is_(False),
            )
            .order_by(
                EnvironmentRevision.created_at.desc(),
                EnvironmentRevision.id.desc(),
            )
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def _active_revision_by_fingerprint(
        self, template_id: UUID, revision_fingerprint: str
    ) -> EnvironmentRevision | None:
        return (
            await self.db.execute(
                select(EnvironmentRevision)
                .where(
                    EnvironmentRevision.template_id == template_id,
                    EnvironmentRevision.fingerprint == revision_fingerprint,
                    EnvironmentRevision.revoked.is_(False),
                )
                .order_by(
                    EnvironmentRevision.created_at.desc(),
                    EnvironmentRevision.id.desc(),
                )
                .limit(1)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def _has_revoked_revision(
        self,
        template_id: UUID,
        revision_fingerprint: str,
        template_fingerprint: str,
    ) -> bool:
        return (
            await self.db.execute(
                select(EnvironmentRevision.id)
                .where(
                    EnvironmentRevision.template_id == template_id,
                    EnvironmentRevision.revoked.is_(True),
                    or_(
                        EnvironmentRevision.fingerprint == revision_fingerprint,
                        EnvironmentRevision.template_fingerprint == template_fingerprint,
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    async def capture(
        self,
        template_id: UUID,
        *,
        expected_template_fingerprint: str,
        runtime: ImageIdentity,
        toolchain: ImageIdentity | None = None,
        allow_reapproval: bool = False,
    ) -> EnvironmentRevision:
        """After external resolution, lock and recheck the original approved template.

        Ordinary launch capture only reuses non-revoked revisions and fails when
        the matching approval was revoked. ``allow_reapproval`` is reserved for
        the explicit administrative re-approval path, which creates a new active
        revision while preserving the revoked row.
        """
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
        existing = await self._active_revision_by_fingerprint(template_id, revision_fingerprint)
        if existing is not None:
            return existing
        if not allow_reapproval and await self._has_revoked_revision(
            template_id, revision_fingerprint, current_fingerprint
        ):
            raise RevisionUnavailable("The environment revision has been revoked")
        portable_fingerprint = None
        try:
            portable_fingerprint = portable_environment_identity(
                configuration, runtime, toolchain
            ).fingerprint
        except PortableIdentityUnavailable:
            # A truthful local-only revision keeps NULL rather than a partial identity.
            portable_fingerprint = None
        revision = EnvironmentRevision(
            template_id=template_id,
            fingerprint=revision_fingerprint,
            template_fingerprint=current_fingerprint,
            portable_fingerprint=portable_fingerprint,
            configuration=configuration,
            runtime_identity=identities["runtime"],
            toolchain_identity=identities["toolchain"],
        )
        try:
            async with self.db.begin_nested():
                self.db.add(revision)
                await self.db.flush()
        except IntegrityError as exc:
            # A concurrent capture won the active fingerprint; reuse its row.
            existing = await self._active_revision_by_fingerprint(template_id, revision_fingerprint)
            if existing is None:
                raise exc
            return existing
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
