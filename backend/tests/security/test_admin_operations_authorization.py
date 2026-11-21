# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin operation visibility requires admin access, new grants, and JWT auth."""

import secrets
import uuid

import pytest

from app.api.auth import get_password_hash
from app.core.permissions import Permission
from app.core.roles import (
    ROLE_PERMISSIONS,
    _rebuild_expansion_cache,
    get_role_permissions,
)
from app.models.api_token import ApiToken
from tests.services.test_operation_finalizer import FakeDriver

pytestmark = pytest.mark.asyncio


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def fake_runtime(monkeypatch):
    driver = FakeDriver()

    async def _get_driver():
        return driver

    monkeypatch.setattr("app.api.admin_operations.get_driver", _get_driver)
    return driver


async def test_permission_catalog_and_default_role_grants(client, admin_token):
    operations = {
        Permission.OPERATIONS_READ_ALL,
        Permission.OPERATIONS_MANAGE_ALL,
    }
    for role in ("user", "moderator", "support"):
        assert operations.isdisjoint(get_role_permissions(role))
    assert operations <= set(get_role_permissions("admin"))
    assert get_role_permissions("super_admin") == [Permission.ALL]

    matrix = await client.get("/api/admin/permissions", headers=auth(admin_token))
    assert matrix.status_code == 200
    assert operations <= set(matrix.json()["permissions"])
    assert operations <= set(matrix.json()["matrix"]["admin"])


async def _denied(client, headers):
    listing = await client.get("/api/admin/operations", headers=headers)
    detail = await client.get(f"/api/admin/operations/launch/{uuid.uuid4()}", headers=headers)
    reconcile = await client.post(
        f"/api/admin/operations/launch/{uuid.uuid4()}/reconcile",
        headers=headers,
        json={"reason": "negative authorization check"},
    )
    assert listing.status_code == 403
    assert detail.status_code == 403
    assert reconcile.status_code == 403


@pytest.mark.parametrize("role_index", [0, 1, 2])
async def test_default_non_admin_roles_are_denied(
    client, user_token, moderator_token, support_token, role_index
):
    token = (user_token, moderator_token, support_token)[role_index]
    await _denied(client, auth(token))


async def test_missing_jwt_is_rejected(client):
    assert (await client.get("/api/admin/operations")).status_code == 401
    assert (
        await client.post(
            f"/api/admin/operations/launch/{uuid.uuid4()}/reconcile",
            json={"reason": "missing token"},
        )
    ).status_code == 401


async def test_admin_and_super_admin_can_read_and_reconcile(client, admin_token, superadmin_token):
    for token in (admin_token, superadmin_token):
        headers = auth(token)
        listing = await client.get("/api/admin/operations", headers=headers)
        assert listing.status_code == 200
        assert listing.json()["pagination"]["total"] == 0

        reconcile = await client.post(
            f"/api/admin/operations/launch/{uuid.uuid4()}/reconcile",
            headers=headers,
            json={"reason": "permission probe for a missing operation"},
        )
        assert reconcile.status_code == 404
        assert reconcile.json()["detail"] == {"code": "operation_not_found"}


async def test_operations_grant_without_admin_access_is_denied(client, moderator_token):
    ROLE_PERMISSIONS["moderator"] = [
        Permission.OPERATIONS_READ_ALL,
        Permission.OPERATIONS_MANAGE_ALL,
    ]
    _rebuild_expansion_cache()

    await _denied(client, auth(moderator_token))


async def test_read_only_operations_role_cannot_reconcile(client, support_token):
    ROLE_PERMISSIONS["support"] = [
        Permission.ADMIN_ACCESS,
        Permission.OPERATIONS_READ_ALL,
    ]
    _rebuild_expansion_cache()
    headers = auth(support_token)

    listing = await client.get("/api/admin/operations", headers=headers)
    assert listing.status_code == 200

    reconcile = await client.post(
        f"/api/admin/operations/launch/{uuid.uuid4()}/reconcile",
        headers=headers,
        json={"reason": "read-only role must not reconcile"},
    )
    assert reconcile.status_code == 403


async def test_admin_api_token_cannot_use_operations_routes(client, admin_user, db_session):
    raw_token = "nukelab_" + secrets.token_urlsafe(32)
    db_session.add(
        ApiToken(
            user_id=admin_user.id,
            name="Operations admin token",
            token_hash=get_password_hash(raw_token),
            token_prefix=raw_token[:16],
            scopes=["*"],
            is_active=True,
        )
    )
    await db_session.commit()

    headers = auth(raw_token)
    listing = await client.get("/api/admin/operations", headers=headers)
    assert listing.status_code == 403
    assert "JWT" in listing.json()["detail"]
    reconcile = await client.post(
        f"/api/admin/operations/launch/{uuid.uuid4()}/reconcile",
        headers=headers,
        json={"reason": "api token must not reconcile"},
    )
    assert reconcile.status_code == 403
