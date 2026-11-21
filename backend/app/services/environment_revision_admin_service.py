# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin-only revision inspection, explicit artifact verification, and revocation.

The service owns sanitization, exact-digest resolution, immutable capture, and
audit details. It never exposes environment-variable values, host paths, local
image IDs, repository digest lists, or raw runtime payloads. Revocation only
flips ``revoked`` under a template-row lock; there is no un-revoke path.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.security import has_all_permissions
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.user import User
from app.schemas.environment_manifest import ImageIdentity
from app.schemas.environment_revision import (
    EnvironmentRevisionPage,
    EnvironmentRevisionPagination,
    EnvironmentRevisionSummary,
    RevisionConfigurationSummary,
    RevisionImageSummary,
    RevisionVolumeSummary,
)
from app.services.activity_service import ActivityService
from app.services.environment_revision_service import (
    ConfigurationChanged,
    EnvironmentRevisionService,
    RevisionUnavailable,
    fingerprint,
    template_configuration,
)
from app.services.registry_client import (
    REGISTRY_AUTH_FAILED,
    REGISTRY_UNREACHABLE,
    RegistryError,
    VerifiedImage,
)
from app.services.registry_image_service import RegistryResolution

MAX_PAGE_LIMIT = 100
MAX_PAGE_OFFSET = 1000
MAX_PACKAGES = 256
MAX_PACKAGE_CHARS = 200
MAX_PORTS = 256
MAX_ENVIRONMENT_NAMES = 256
MAX_VOLUMES = 32
MAX_LIMITATIONS = 16

LOCAL_ONLY_ARTIFACT = "local_only_artifact"
REGISTRY_VERIFICATION_REQUIRED = "registry_verification_required"
CONFIGURATION_NOT_DISPLAYABLE = "configuration_not_displayable"
RUNTIME_REFERENCE_NOT_DISPLAYABLE = "runtime_reference_not_displayable"
TOOLCHAIN_REFERENCE_NOT_DISPLAYABLE = "toolchain_reference_not_displayable"
PACKAGES_NOT_DISPLAYABLE = "packages_not_displayable"
PACKAGES_TRUNCATED = "packages_truncated"
PORTS_NOT_DISPLAYABLE = "ports_not_displayable"
PORTS_TRUNCATED = "ports_truncated"
TOOL_MOUNTS_NOT_DISPLAYABLE = "tool_mounts_not_displayable"
ENVIRONMENT_NAMES_NOT_DISPLAYABLE = "environment_variable_names_not_displayable"
ENVIRONMENT_NAMES_TRUNCATED = "environment_variable_names_truncated"
VOLUME_CONFIGURATION_LOCAL_ONLY = "volume_configuration_local_only"
VOLUMES_TRUNCATED = "volume_configuration_truncated"
RUNTIME_IDENTITY_NOT_DISPLAYABLE = "runtime_identity_not_displayable"
TOOLCHAIN_IDENTITY_NOT_DISPLAYABLE = "toolchain_identity_not_displayable"

_SAFE_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ENVIRONMENT_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_PORT_RE = re.compile(r"[0-9]+\Z")
_VOLUME_MODES = frozenset({"read_only", "read_write"})
_VOLUME_KEYS = frozenset({"mount_path", "mode"})
_REFERENCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*(?:@sha256:[a-f0-9]{64})?\Z")
_VERIFIED_REFERENCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}\Z")


class RegistryResolverLike(Protocol):
    async def resolve(
        self, reference: str, *, policy: str | None = None, pull: bool = False
    ) -> RegistryResolution: ...


class RegistryArtifactsLike(Protocol):
    async def ensure_local(self, verified: VerifiedImage) -> ImageIdentity: ...


class RevisionAdminError(Exception):
    """Bounded failure translated to a stable API code by the router."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int = 409,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.context = dict(context or {})

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, **self.context}


class RevocationResult:
    def __init__(
        self,
        revision: EnvironmentRevision,
        *,
        selectable_revision_count: int,
        already_revoked: bool,
    ) -> None:
        self.revision = revision
        self.selectable_revision_count = selectable_revision_count
        self.template_has_selectable_revision = selectable_revision_count > 0
        self.already_revoked = already_revoked


class EnvironmentRevisionAdminService:
    """Sanitized revision reads plus explicit verify/revoke actions."""

    def __init__(self, db: AsyncSession, actor: User):
        self.db = db
        self.actor = actor

    async def require_environment(self, environment_id: UUID) -> EnvironmentTemplate:
        template = (
            await self.db.execute(
                select(EnvironmentTemplate)
                .where(EnvironmentTemplate.id == environment_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if template is None:
            raise RevisionAdminError("environment_not_found", status_code=404)
        return template

    async def require_verifiable_environment(self, environment_id: UUID) -> EnvironmentTemplate:
        """Check active status before the router constructs registry services."""
        template = await self.require_environment(environment_id)
        if not template.is_active:
            raise RevisionAdminError("template_inactive", status_code=409)
        return template

    async def list_revisions(
        self,
        environment_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> EnvironmentRevisionPage:
        conditions = (EnvironmentRevision.template_id == environment_id,)
        total = int(
            await self.db.scalar(
                select(func.count()).select_from(EnvironmentRevision).where(*conditions)
            )
            or 0
        )
        rows = (
            (
                await self.db.execute(
                    select(EnvironmentRevision)
                    .where(*conditions)
                    .order_by(
                        EnvironmentRevision.created_at.desc(),
                        EnvironmentRevision.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        items = [self.summary(revision) for revision in rows]
        return EnvironmentRevisionPage(
            items=items,
            pagination=EnvironmentRevisionPagination(
                limit=limit,
                offset=offset,
                total=total,
                has_more=offset + len(items) < total,
            ),
        )

    def require_registry_references(self, template: EnvironmentTemplate) -> None:
        """Reject local-ID references before any registry or runtime construction."""
        configuration = template_configuration(template)
        references = [configuration["image"]]
        if configuration["tool_image"]:
            references.append(configuration["tool_image"])
        if any(isinstance(value, str) and value.startswith("sha256:") for value in references):
            # Local IDs have no registry identity. Reject before any registry
            # call instead of partially verifying other references.
            raise RevisionAdminError("revision_unavailable", status_code=409)

    async def verify_template(
        self,
        template: EnvironmentTemplate,
        *,
        reason: str,
        registry: RegistryResolverLike,
        artifacts: RegistryArtifactsLike,
    ) -> EnvironmentRevision:
        """Resolve current approved references to exact verified digests and capture."""
        self.require_registry_references(template)
        configuration = template_configuration(template)
        runtime = await self._verified_identity(
            configuration["image"], registry=registry, artifacts=artifacts
        )
        toolchain = None
        if configuration["tool_image"]:
            toolchain = await self._verified_identity(
                configuration["tool_image"], registry=registry, artifacts=artifacts
            )

        revisions = EnvironmentRevisionService(self.db, self._authorize_template)
        try:
            revision = await revisions.capture(
                template.id,
                expected_template_fingerprint=fingerprint(configuration),
                runtime=runtime,
                toolchain=toolchain,
                allow_reapproval=True,
            )
        except (RevisionUnavailable, ConfigurationChanged) as error:
            raise RevisionAdminError(
                getattr(error, "code", "revision_unavailable"), status_code=409
            ) from None

        summary = self.summary(revision)
        await self._audit_verify(
            template=template,
            revision=revision,
            reason=reason,
            summary=summary,
        )
        return revision

    async def revoke_revision(
        self,
        revision_id: UUID,
        *,
        reason: str,
        confirm_last_revision: bool,
    ) -> RevocationResult:
        """Revoke under a template row lock; idempotent and last-row confirmed."""
        head = await self.db.get(EnvironmentRevision, revision_id)
        if head is None:
            await self._audit_revoke(
                revision_id=revision_id,
                template_id=None,
                reason=reason,
                outcome="not_found",
                confirm_last_revision=confirm_last_revision,
                selectable_revision_count=0,
            )
            raise RevisionAdminError("revision_not_found", status_code=404)

        # Serialize revocations per template. Capture locks the same template
        # row before inserting, so a concurrent verify cannot race the count.
        template = (
            await self.db.execute(
                select(EnvironmentTemplate)
                .where(EnvironmentTemplate.id == head.template_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if template is None:
            await self._audit_revoke(
                revision_id=revision_id,
                template_id=None,
                reason=reason,
                outcome="not_found",
                confirm_last_revision=confirm_last_revision,
                selectable_revision_count=0,
            )
            raise RevisionAdminError("revision_not_found", status_code=404)

        revision = (
            await self.db.execute(
                select(EnvironmentRevision)
                .where(EnvironmentRevision.id == revision_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if revision is None:
            await self._audit_revoke(
                revision_id=revision_id,
                template_id=template.id,
                reason=reason,
                outcome="not_found",
                confirm_last_revision=confirm_last_revision,
                selectable_revision_count=0,
            )
            raise RevisionAdminError("revision_not_found", status_code=404)

        selectable_before = await self._selectable_count(template.id)
        if revision.revoked:
            await self._audit_revoke(
                revision_id=revision.id,
                template_id=template.id,
                reason=reason,
                outcome="already_revoked",
                confirm_last_revision=confirm_last_revision,
                selectable_revision_count=selectable_before,
            )
            return RevocationResult(
                revision,
                selectable_revision_count=selectable_before,
                already_revoked=True,
            )

        if selectable_before <= 1 and not confirm_last_revision:
            await self._audit_revoke(
                revision_id=revision.id,
                template_id=template.id,
                reason=reason,
                outcome="last_revision_confirmation_required",
                confirm_last_revision=False,
                selectable_revision_count=0,
            )
            raise RevisionAdminError(
                "last_revision_confirmation_required",
                status_code=409,
                context={
                    "selectable_revision_count": 0,
                    "replacement_available": False,
                },
            )

        revision.revoked = True
        await self.db.flush()
        selectable_after = await self._selectable_count(template.id)
        await self._audit_revoke(
            revision_id=revision.id,
            template_id=template.id,
            reason=reason,
            outcome="revoked",
            confirm_last_revision=bool(confirm_last_revision),
            selectable_revision_count=selectable_after,
        )
        return RevocationResult(
            revision,
            selectable_revision_count=selectable_after,
            already_revoked=False,
        )

    def summary(self, revision: EnvironmentRevision) -> EnvironmentRevisionSummary:
        limitations: list[str] = []
        configuration, configuration_limits = _configuration_summary(revision.configuration)
        limitations.extend(configuration_limits)
        runtime, runtime_limits = _image_summary(
            revision.runtime_identity, limitation=RUNTIME_IDENTITY_NOT_DISPLAYABLE
        )
        limitations.extend(runtime_limits)
        if revision.toolchain_identity is None:
            toolchain = None
        else:
            toolchain, toolchain_limits = _image_summary(
                revision.toolchain_identity, limitation=TOOLCHAIN_IDENTITY_NOT_DISPLAYABLE
            )
            limitations.extend(toolchain_limits)

        portable = revision.portable_fingerprint
        assets_verified = runtime.registry_verified and (
            toolchain is None or toolchain.registry_verified
        )
        if portable is not None and assets_verified:
            portability = "registry_verified"
        else:
            portability = "local_only"
            if portable is not None:
                limitations.append(REGISTRY_VERIFICATION_REQUIRED)
            else:
                limitations.append(LOCAL_ONLY_ARTIFACT)
        return EnvironmentRevisionSummary(
            id=revision.id,
            template_id=revision.template_id,
            fingerprint=revision.fingerprint,
            portable_fingerprint=portable,
            portability=portability,
            revoked=bool(revision.revoked),
            created_at=revision.created_at,
            runtime=runtime,
            toolchain=toolchain,
            configuration=configuration,
            limitations=_bounded_limitations(limitations),
        )

    async def _verified_identity(
        self,
        reference: str,
        *,
        registry: RegistryResolverLike,
        artifacts: RegistryArtifactsLike,
    ) -> ImageIdentity:
        if not isinstance(reference, str) or not reference:
            raise RevisionAdminError("revision_unavailable", status_code=409)
        if reference.startswith("sha256:"):
            # A local image ID has no registry identity. Never pull a tag or
            # silently relabel a local-only artifact as verified.
            raise RevisionAdminError("revision_unavailable", status_code=409)
        try:
            resolution = await registry.resolve(reference, policy="require")
        except RegistryError as error:
            raise _registry_failure(error) from None
        if resolution.state != "verified" or resolution.verified is None:
            raise RevisionAdminError("artifact_missing", status_code=409)
        try:
            return await artifacts.ensure_local(resolution.verified)
        except RegistryError as error:
            raise _registry_failure(error) from None

    async def _authorize_template(self, template: EnvironmentTemplate) -> None:
        if not has_all_permissions(
            self.actor, [Permission.ENVIRONMENT_UPDATE, Permission.ADMIN_ACCESS]
        ):
            raise RevisionAdminError("permission_revoked", status_code=403)

    async def _selectable_count(self, template_id: UUID) -> int:
        return int(
            await self.db.scalar(
                select(func.count())
                .select_from(EnvironmentRevision)
                .where(
                    EnvironmentRevision.template_id == template_id,
                    EnvironmentRevision.revoked.is_(False),
                )
            )
            or 0
        )

    async def _audit_verify(
        self,
        *,
        template: EnvironmentTemplate,
        revision: EnvironmentRevision,
        reason: str,
        summary: EnvironmentRevisionSummary,
    ) -> None:
        details = {
            "reason": reason,
            "template_id": str(template.id),
            "revision_id": str(revision.id),
            "revision_fingerprint": revision.fingerprint,
            "portable_fingerprint": revision.portable_fingerprint,
            "portability": summary.portability,
            "runtime_manifest_digest": summary.runtime.manifest_digest,
            "toolchain_manifest_digest": (
                summary.toolchain.manifest_digest if summary.toolchain is not None else None
            ),
            "limitations": summary.limitations,
        }
        try:
            await ActivityService(self.db).log(
                action="environment.revision.verify",
                target_type="environment_revision",
                target_id=str(revision.id),
                actor_id=str(self.actor.id),
                details=details,
            )
        except Exception:
            await self.db.rollback()
            raise RevisionAdminError("audit_unavailable", status_code=500) from None

    async def _audit_revoke(
        self,
        *,
        revision_id: UUID,
        template_id: UUID | None,
        reason: str,
        outcome: str,
        confirm_last_revision: bool,
        selectable_revision_count: int,
    ) -> None:
        details = {
            "reason": reason,
            "template_id": str(template_id) if template_id is not None else None,
            "revision_id": str(revision_id),
            "outcome": outcome,
            "confirm_last_revision": bool(confirm_last_revision),
            "selectable_revision_count": selectable_revision_count,
            "template_has_selectable_revision": selectable_revision_count > 0,
        }
        try:
            await ActivityService(self.db).log(
                action="environment.revision.revoke",
                target_type="environment_revision",
                target_id=str(revision_id),
                actor_id=str(self.actor.id),
                details=details,
            )
        except Exception:
            await self.db.rollback()
            raise RevisionAdminError("audit_unavailable", status_code=500) from None


def _registry_failure(error: RegistryError) -> RevisionAdminError:
    status_code = 503 if error.code in {REGISTRY_UNREACHABLE, REGISTRY_AUTH_FAILED} else 409
    return RevisionAdminError(error.code, status_code=status_code)


def _image_summary(value: Any, *, limitation: str) -> tuple[RevisionImageSummary, list[str]]:
    if value is None:
        return RevisionImageSummary(), []
    try:
        image = ImageIdentity.model_validate(value)
    except (TypeError, ValueError):
        return RevisionImageSummary(), [limitation]
    summary = RevisionImageSummary(
        registry_verified=image.registry_verified,
        os=image.os,
        architecture=image.architecture,
        variant=image.variant,
    )
    if not image.registry_verified:
        return summary, []
    if not _safe_verified_reference(image.verified_reference):
        return summary, [limitation]
    return (
        RevisionImageSummary(
            registry_verified=True,
            os=image.os,
            architecture=image.architecture,
            variant=image.variant,
            verified_reference=image.verified_reference,
            manifest_digest=image.manifest_digest,
            index_digest=image.index_digest,
            descriptor_media_type=image.descriptor_media_type,
        ),
        [],
    )


def _configuration_summary(value: Any) -> tuple[RevisionConfigurationSummary, list[str]]:
    if not isinstance(value, dict):
        return RevisionConfigurationSummary(), [CONFIGURATION_NOT_DISPLAYABLE]
    limitations: list[str] = []

    image = _safe_reference(value.get("image"))
    if value.get("image") is not None and image is None:
        limitations.append(RUNTIME_REFERENCE_NOT_DISPLAYABLE)
    tool_image = _safe_reference(value.get("tool_image"))
    if value.get("tool_image") is not None and tool_image is None:
        limitations.append(TOOLCHAIN_REFERENCE_NOT_DISPLAYABLE)

    packages, package_limitation = _safe_packages(value.get("packages"))
    if package_limitation:
        limitations.append(package_limitation)
    ports, port_limitation = _safe_ports(value.get("ports"))
    if port_limitation:
        limitations.append(port_limitation)
    tool_mounts, mount_limitation = _safe_tool_mounts(value.get("tool_mounts"))
    if mount_limitation:
        limitations.append(mount_limitation)
    names, name_limitation = _safe_environment_names(value.get("environment_variables"))
    if name_limitation:
        limitations.append(name_limitation)
    volumes, volume_limitation = _safe_volumes(value.get("volumes"))
    if volume_limitation:
        limitations.append(volume_limitation)

    return (
        RevisionConfigurationSummary(
            image=image,
            tool_image=tool_image,
            packages=packages,
            ports=ports,
            tool_mounts=tool_mounts,
            environment_variable_names=names,
            volumes=volumes,
        ),
        limitations,
    )


def _safe_reference(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if (
        not text
        or len(text) > 500
        or "://" in text
        or _SAFE_CONTROL_RE.search(text)
        or _REFERENCE_RE.fullmatch(text) is None
    ):
        return None
    return text


def _safe_verified_reference(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 500
        and "://" not in value
        and _VERIFIED_REFERENCE_RE.fullmatch(value) is not None
    )


def _safe_packages(value: Any) -> tuple[list[str], str | None]:
    if value is None:
        return [], None
    if not isinstance(value, list):
        return [], PACKAGES_NOT_DISPLAYABLE
    packages: set[str] = set()
    for item in value:
        if (
            not isinstance(item, str)
            or not item.strip()
            or len(item.strip()) > MAX_PACKAGE_CHARS
            or _SAFE_CONTROL_RE.search(item)
        ):
            return [], PACKAGES_NOT_DISPLAYABLE
        packages.add(item.strip())
    ordered = sorted(packages)
    if len(ordered) > MAX_PACKAGES:
        return ordered[:MAX_PACKAGES], PACKAGES_TRUNCATED
    return ordered, None


def _safe_ports(value: Any) -> tuple[list[str], str | None]:
    if value is None:
        return [], None
    if not isinstance(value, list):
        return [], PORTS_NOT_DISPLAYABLE
    ports: set[str] = set()
    for item in value:
        if isinstance(item, bool):
            return [], PORTS_NOT_DISPLAYABLE
        if isinstance(item, int):
            if item < 0:
                return [], PORTS_NOT_DISPLAYABLE
            ports.add(str(item))
            continue
        if not isinstance(item, str):
            return [], PORTS_NOT_DISPLAYABLE
        text = item.strip()
        if not _PORT_RE.fullmatch(text) or len(text) > 20:
            return [], PORTS_NOT_DISPLAYABLE
        ports.add(str(int(text, 10)))
    ordered = sorted(ports, key=int)
    if len(ordered) > MAX_PORTS:
        return ordered[:MAX_PORTS], PORTS_TRUNCATED
    return ordered, None


def _safe_tool_mounts(value: Any) -> tuple[list[str], str | None]:
    if value is None:
        return [], None
    if not isinstance(value, list) or len(value) > 1:
        return [], TOOL_MOUNTS_NOT_DISPLAYABLE
    if not value:
        return [], None
    mount_path = value[0]
    if not isinstance(mount_path, str):
        return [], TOOL_MOUNTS_NOT_DISPLAYABLE
    path = _container_path(mount_path)
    if path is None or path == "/toolchain-target" or path.startswith("/toolchain-target/"):
        return [], TOOL_MOUNTS_NOT_DISPLAYABLE
    return [path], None


def _safe_environment_names(value: Any) -> tuple[list[str], str | None]:
    if value is None:
        return [], None
    if not isinstance(value, dict):
        return [], ENVIRONMENT_NAMES_NOT_DISPLAYABLE
    names: set[str] = set()
    for name in value:
        if not isinstance(name, str) or not _ENVIRONMENT_NAME_RE.fullmatch(name):
            return [], ENVIRONMENT_NAMES_NOT_DISPLAYABLE
        names.add(name)
    ordered = sorted(names)
    if len(ordered) > MAX_ENVIRONMENT_NAMES:
        return ordered[:MAX_ENVIRONMENT_NAMES], ENVIRONMENT_NAMES_TRUNCATED
    return ordered, None


def _safe_volumes(value: Any) -> tuple[list[RevisionVolumeSummary], str | None]:
    if value is None:
        return [], None
    if not isinstance(value, list):
        return [], VOLUME_CONFIGURATION_LOCAL_ONLY
    mounts: set[tuple[str, str]] = set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != _VOLUME_KEYS:
            return [], VOLUME_CONFIGURATION_LOCAL_ONLY
        mount_path = entry["mount_path"]
        mode = entry["mode"]
        if not isinstance(mode, str) or mode not in _VOLUME_MODES:
            return [], VOLUME_CONFIGURATION_LOCAL_ONLY
        path = _container_path(mount_path)
        if path is None:
            return [], VOLUME_CONFIGURATION_LOCAL_ONLY
        mounts.add((path, mode))
    ordered = sorted(mounts)
    if len(ordered) > MAX_VOLUMES:
        return (
            [
                RevisionVolumeSummary(mount_path=path, mode=mode)
                for path, mode in ordered[:MAX_VOLUMES]
            ],
            VOLUMES_TRUNCATED,
        )
    return (
        [RevisionVolumeSummary(mount_path=path, mode=mode) for path, mode in ordered],
        None,
    )


def _container_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith("//") or _SAFE_CONTROL_RE.search(text):
        return None
    path = PurePosixPath(text)
    if not path.is_absolute() or ".." in path.parts:
        return None
    return str(path)


def _bounded_limitations(values: list[str]) -> list[str]:
    seen: set[str] = set()
    bounded: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        bounded.append(value)
        if len(bounded) >= MAX_LIMITATIONS:
            break
    return bounded
