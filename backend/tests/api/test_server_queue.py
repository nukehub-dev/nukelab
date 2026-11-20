# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Queue resource permission, token-scope and ownership boundaries."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.auth import get_current_user
from app.api.server_queue import router
from app.db.session import get_db
from app.models.user import User
from app.services.server_queue_service import QueueError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "scopes", "role", "expected"),
    [
        ("GET", "", ["servers:read"], "user", 200),
        ("GET", "", ["volumes:read"], "user", 403),
        ("POST", "/{id}/cancel", ["servers:read"], "user", 403),
        ("POST", "/{id}/cancel", ["servers:manage"], "guest", 403),
        ("POST", "/{id}/cancel", ["servers:manage"], "user", 404),
        ("GET", "/{id}", ["servers:read"], "admin", 404),
    ],
)
async def test_queue_requires_scope_permission_and_owner(method, path, scopes, role, expected):
    user = User(id=uuid.uuid4(), username="queue-reader", role=role, is_active=True)
    app = FastAPI()
    app.include_router(router, prefix="/api/server-queue")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: None

    @app.middleware("http")
    async def context(request, call_next):
        request.state.auth_context = SimpleNamespace(auth_method="api_token", token_scopes=scopes)
        return await call_next(request)

    service = SimpleNamespace(
        describe=AsyncMock(),
        list_owned=AsyncMock(return_value={"items": [], "total": 0, "page": 1, "page_size": 25}),
        get_owned=AsyncMock(side_effect=QueueError("request_not_found", 404)),
        cancel=AsyncMock(side_effect=QueueError("request_not_found", 404)),
    )
    target_id = uuid.uuid4()
    with patch("app.api.server_queue.ServerQueueService", return_value=service):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(method, "/api/server-queue" + path.format(id=target_id))
    assert response.status_code == expected
    if expected == 403:
        service.list_owned.assert_not_awaited()
        service.get_owned.assert_not_awaited()
        service.cancel.assert_not_awaited()
    if method == "GET" and expected == 404:
        service.get_owned.assert_awaited_once_with(target_id, user.id)
    if method == "POST" and expected == 404:
        service.cancel.assert_awaited_once_with(target_id, user.id)
