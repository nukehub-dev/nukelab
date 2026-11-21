# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin queue visibility requires cross-user read, admin access, and JWT auth."""

import secrets
import uuid

import pytest

from app.api.auth import get_password_hash
from app.core.permissions import Permission
from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache
from app.models.api_token import ApiToken

pytestmark = pytest.mark.asyncio


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _queue(client, headers):
    return await client.get("/api/admin/server-queue", headers=headers)


@pytest.mark.parametrize("role_index", [0, 1, 2])
async def test_default_non_admin_roles_are_denied(
    client, user_token, moderator_token, support_token, role_index
):
    token = (user_token, moderator_token, support_token)[role_index]
    assert (await _queue(client, auth(token))).status_code == 403


async def test_missing_jwt_is_rejected(client):
    assert (await client.get("/api/admin/server-queue")).status_code == 401


async def test_admin_and_super_admin_can_read(client, admin_token, superadmin_token):
    for token in (admin_token, superadmin_token):
        response = await _queue(client, auth(token))
        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "pagination": {"limit": 50, "offset": 0, "total": 0, "has_more": False},
        }


async def test_admin_access_alone_is_insufficient(client, support_token):
    ROLE_PERMISSIONS["support"] = [Permission.ADMIN_ACCESS]
    _rebuild_expansion_cache()
    assert (await _queue(client, auth(support_token))).status_code == 403


async def test_cross_user_server_read_alone_is_insufficient(client, moderator_token):
    ROLE_PERMISSIONS["moderator"] = [Permission.SERVERS_READ_ALL]
    _rebuild_expansion_cache()
    assert (await _queue(client, auth(moderator_token))).status_code == 403


async def test_read_only_queue_role_can_read_but_cannot_mutate(client, support_token):
    ROLE_PERMISSIONS["support"] = [
        Permission.ADMIN_ACCESS,
        Permission.SERVERS_READ_ALL,
    ]
    _rebuild_expansion_cache()
    headers = auth(support_token)
    assert (await _queue(client, headers)).status_code == 200

    target = uuid.uuid4()
    assert (
        await client.post("/api/admin/server-queue", headers=headers, json={})
    ).status_code == 405
    assert (
        await client.post(f"/api/admin/server-queue/{target}/cancel", headers=headers)
    ).status_code == 404
    assert (
        await client.delete(f"/api/admin/server-queue/{target}", headers=headers)
    ).status_code == 404
    assert (
        await client.patch(f"/api/admin/server-queue/{target}", headers=headers, json={})
    ).status_code == 404


async def test_admin_api_token_cannot_use_queue_view(client, admin_user, db_session):
    raw_token = "nukelab_" + secrets.token_urlsafe(32)
    db_session.add(
        ApiToken(
            user_id=admin_user.id,
            name="Admin queue token",
            token_hash=get_password_hash(raw_token),
            token_prefix=raw_token[:16],
            scopes=["*"],
            is_active=True,
        )
    )
    await db_session.commit()

    response = await _queue(client, auth(raw_token))
    assert response.status_code == 403
    assert "JWT" in response.json()["detail"]
