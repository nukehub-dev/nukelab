# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin-only environment revision read, verify, and revoke routes."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_jwt_auth
from app.container.factory import get_driver
from app.core.permissions import Permission
from app.db.session import get_db
from app.dependencies import PermissionChecker, get_current_active_user, no_store_cache
from app.models.user import User
from app.schemas.environment_revision import (
    EnvironmentRevisionPage,
    RevokeRevisionRequest,
    RevokeRevisionResponse,
    VerifyArtifactsRequest,
    VerifyArtifactsResponse,
)
from app.services.environment_revision_admin_service import (
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
    EnvironmentRevisionAdminService,
    RevisionAdminError,
)
from app.services.registry_artifact_service import RegistryArtifactService
from app.services.registry_image_service import RegistryImageService

router = APIRouter()
admin_router = APIRouter()
Database = Annotated[AsyncSession, Depends(get_db)]
logger = logging.getLogger(__name__)


async def require_revision_read(
    current_user: User = Depends(get_current_active_user),
    _jwt=Depends(require_jwt_auth()),
) -> User:
    """Require environment read, admin dashboard access, and a JWT session."""
    PermissionChecker(current_user).require_all(
        [Permission.ENVIRONMENT_READ, Permission.ADMIN_ACCESS]
    )
    return current_user


async def require_revision_manage(
    current_user: User = Depends(get_current_active_user),
    _jwt=Depends(require_jwt_auth()),
) -> User:
    """Require environment update, admin dashboard access, and a JWT session."""
    PermissionChecker(current_user).require_all(
        [Permission.ENVIRONMENT_UPDATE, Permission.ADMIN_ACCESS]
    )
    return current_user


async def _registry_service() -> RegistryImageService:
    return RegistryImageService.from_settings()


async def _artifact_service() -> RegistryArtifactService:
    driver = await get_driver()
    return RegistryArtifactService.from_settings(driver)


def _http_error(error: RevisionAdminError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail())


@router.get("/{environment_id}/revisions", response_model=EnvironmentRevisionPage)
async def list_environment_revisions(
    environment_id: UUID,
    response: Response,
    db: Database,
    current_user: User = Depends(require_revision_read),
    limit: int = Query(50, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0, le=MAX_PAGE_OFFSET),
):
    """List every revision for an environment, newest first, including revoked history."""
    no_store_cache(response)
    service = EnvironmentRevisionAdminService(db, current_user)
    try:
        template = await service.require_environment(environment_id)
        return await service.list_revisions(template.id, limit=limit, offset=offset)
    except RevisionAdminError as error:
        raise _http_error(error) from None


@router.post("/{environment_id}/verify-artifacts", response_model=VerifyArtifactsResponse)
async def verify_environment_artifacts(
    environment_id: UUID,
    body: VerifyArtifactsRequest,
    response: Response,
    db: Database,
    current_user: User = Depends(require_revision_manage),
):
    """Verify the current approved references and capture/reuse a verified revision."""
    no_store_cache(response)
    service = EnvironmentRevisionAdminService(db, current_user)
    try:
        template = await service.require_verifiable_environment(environment_id)
        service.require_registry_references(template)
        try:
            registry = await _registry_service()
            artifacts = await _artifact_service()
        except ValueError:
            raise HTTPException(
                status_code=503,
                detail={"code": "registry_configuration_invalid"},
            ) from None
        except Exception as exc:
            logger.warning(
                "Revision verification runtime unavailable (%s)",
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail={"code": "runtime_unavailable"},
            ) from None
        revision = await service.verify_template(
            template,
            reason=body.reason,
            registry=registry,
            artifacts=artifacts,
        )
    except RevisionAdminError as error:
        raise _http_error(error) from None
    return VerifyArtifactsResponse(data=service.summary(revision))


@admin_router.post("/{revision_id}/revoke", response_model=RevokeRevisionResponse)
async def revoke_environment_revision(
    revision_id: UUID,
    body: RevokeRevisionRequest,
    response: Response,
    db: Database,
    current_user: User = Depends(require_revision_manage),
):
    """Revoke one revision under a row lock; the last selectable row needs confirmation."""
    no_store_cache(response)
    service = EnvironmentRevisionAdminService(db, current_user)
    try:
        result = await service.revoke_revision(
            revision_id,
            reason=body.reason,
            confirm_last_revision=body.confirm_last_revision,
        )
    except RevisionAdminError as error:
        raise _http_error(error) from None
    return RevokeRevisionResponse(
        data=service.summary(result.revision),
        template_has_selectable_revision=result.template_has_selectable_revision,
        selectable_revision_count=result.selectable_revision_count,
        already_revoked=result.already_revoked,
    )
