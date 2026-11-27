# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Owner-only single-run batch job routes. JWT authentication is mandatory."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_jwt_auth
from app.core.permissions import Permission
from app.core.security import has_permission
from app.db.session import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.batch_job import (
    BatchJobDetail,
    BatchJobListResponse,
    BatchJobSubmitRequest,
    EligibleRevisionsResponse,
    JobCapabilitiesResponse,
    JobLogsResponse,
)
from app.services.batch_job_service import BatchJobService, JobError

router = APIRouter(dependencies=[Depends(require_jwt_auth())])


def _require_job_permission(permission: str):
    async def checker(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if not has_permission(current_user, permission):
            raise HTTPException(
                status_code=403,
                detail={"code": "permission_denied"},
            )
        return current_user

    return checker


def _http_error(exc: JobError) -> HTTPException:
    detail: dict[str, str] = {"code": exc.code}
    if exc.field is not None:
        detail["field"] = exc.field
    return HTTPException(status_code=exc.status_code, detail=detail)


read_user = Annotated[User, Depends(_require_job_permission(Permission.JOBS_READ_OWN))]
write_user = Annotated[User, Depends(_require_job_permission(Permission.JOBS_WRITE_OWN))]
db_session = Annotated[AsyncSession, Depends(get_db)]


@router.get("/capabilities", response_model=JobCapabilitiesResponse)
async def job_capabilities(
    current_user: read_user,
    db: db_session,
) -> JobCapabilitiesResponse:
    return await BatchJobService(db).capabilities(current_user)


@router.get("/eligible-revisions", response_model=EligibleRevisionsResponse)
async def eligible_revisions(
    current_user: read_user,
    db: db_session,
) -> EligibleRevisionsResponse:
    return await BatchJobService(db).eligible_revisions(current_user)


@router.post("", response_model=BatchJobDetail, status_code=202)
async def submit_job(
    request: BatchJobSubmitRequest,
    response: Response,
    current_user: write_user,
    db: db_session,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BatchJobDetail:
    try:
        detail = await BatchJobService(db).submit(current_user, idempotency_key, request)
    except JobError as exc:
        raise _http_error(exc) from exc
    if detail.replayed:
        response.status_code = 200
    return detail


@router.get("", response_model=BatchJobListResponse)
async def list_jobs(
    current_user: read_user,
    db: db_session,
    state: Annotated[str, Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query()] = None,
) -> BatchJobListResponse:
    try:
        return await BatchJobService(db).list(
            current_user,
            state_filter=state,
            limit=limit,
            cursor=cursor,
        )
    except JobError as exc:
        raise _http_error(exc) from exc


@router.get("/{job_id}", response_model=BatchJobDetail)
async def get_job(
    job_id: uuid.UUID,
    current_user: read_user,
    db: db_session,
) -> BatchJobDetail:
    try:
        return await BatchJobService(db).get(current_user, job_id)
    except JobError as exc:
        raise _http_error(exc) from exc


@router.post("/{job_id}/cancel", response_model=BatchJobDetail)
async def cancel_job(
    job_id: uuid.UUID,
    current_user: write_user,
    db: db_session,
) -> BatchJobDetail:
    try:
        return await BatchJobService(db).cancel(current_user, job_id)
    except JobError as exc:
        raise _http_error(exc) from exc


@router.get("/{job_id}/logs", response_model=JobLogsResponse)
async def job_logs(
    job_id: uuid.UUID,
    current_user: read_user,
    db: db_session,
) -> JobLogsResponse:
    try:
        return await BatchJobService(db).logs(current_user, job_id)
    except JobError as exc:
        raise _http_error(exc) from exc
