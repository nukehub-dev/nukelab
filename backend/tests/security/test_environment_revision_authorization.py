# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Environment revision routes require admin access, the right grant, and JWT auth."""

import secrets
import uuid

import pytest

from app.api.auth import get_password_hash
from app.core.permissions import Permission
from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache
from app.models.api_token import ApiToken
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate

pytestmark = pytest.mark.asyncio


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def add_fixture_rows(db):
    name = "environment-" + uuid.uuid4().hex
    template = EnvironmentTemplate(name=name, slug=name, image="registry.example/workspace:1")
    db.add(template)
    await db.flush()
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
        template_fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
        configuration={},
        runtime_identity={},
    )
    db.add(revision)
    await db.commit()
    await db.refresh(template)
    await db.refresh(revision)
    return template, revision


async def assert_denied(client, headers, template_id, revision_id):
    listing = await client.get(f"/api/environments/{template_id}/revisions", headers=headers)
    verify = await client.post(
        f"/api/environments/{template_id}/verify-artifacts",
        headers=headers,
        json={"reason": "negative authorization check"},
    )
    revoke = await client.post(
        f"/api/admin/environment-revisions/{revision_id}/revoke",
        headers=headers,
        json={"reason": "negative authorization check"},
    )
    assert listing.status_code == 403
    assert verify.status_code == 403
    assert revoke.status_code == 403


@pytest.mark.parametrize("role_index", [0, 1, 2])
async def test_default_non_admin_roles_are_denied(
    client,
    db_session,
    user_token,
    moderator_token,
    support_token,
    role_index,
):
    template, revision = await add_fixture_rows(db_session)
    token = (user_token, moderator_token, support_token)[role_index]
    await assert_denied(client, auth(token), template.id, revision.id)


async def test_missing_jwt_is_rejected(client):
    template_id = uuid.uuid4()
    revision_id = uuid.uuid4()

    listing = await client.get(f"/api/environments/{template_id}/revisions")
    verify = await client.post(
        f"/api/environments/{template_id}/verify-artifacts",
        json={"reason": "missing token"},
    )
    revoke = await client.post(
        f"/api/admin/environment-revisions/{revision_id}/revoke",
        json={"reason": "missing token"},
    )

    assert listing.status_code == 401
    assert verify.status_code == 401
    assert revoke.status_code == 401


async def test_admin_and_super_admin_pass_authorization(
    client, db_session, admin_token, superadmin_token
):
    template, revision = await add_fixture_rows(db_session)

    for token in (admin_token, superadmin_token):
        headers = auth(token)
        listing = await client.get(f"/api/environments/{template.id}/revisions", headers=headers)
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["items"]] == [str(revision.id)]

        verify_missing = await client.post(
            f"/api/environments/{uuid.uuid4()}/verify-artifacts",
            headers=headers,
            json={"reason": "authorization probe"},
        )
        assert verify_missing.status_code == 404
        revoke_missing = await client.post(
            f"/api/admin/environment-revisions/{uuid.uuid4()}/revoke",
            headers=headers,
            json={"reason": "authorization probe"},
        )
        assert revoke_missing.status_code == 404


async def test_read_only_admin_role_can_read_but_not_verify_or_revoke(
    client, db_session, support_token
):
    template, revision = await add_fixture_rows(db_session)
    ROLE_PERMISSIONS["support"] = [
        Permission.ADMIN_ACCESS,
        Permission.ENVIRONMENT_READ,
    ]
    _rebuild_expansion_cache()
    headers = auth(support_token)

    listing = await client.get(f"/api/environments/{template.id}/revisions", headers=headers)
    assert listing.status_code == 200

    verify = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=headers,
        json={"reason": "read-only role must not verify"},
    )
    revoke = await client.post(
        f"/api/admin/environment-revisions/{revision.id}/revoke",
        headers=headers,
        json={"reason": "read-only role must not revoke"},
    )
    assert verify.status_code == 403
    assert revoke.status_code == 403
    stored = await db_session.get(EnvironmentRevision, revision.id, populate_existing=True)
    assert stored.revoked is False


async def test_environment_update_without_admin_access_is_denied(
    client, db_session, moderator_token
):
    template, revision = await add_fixture_rows(db_session)
    ROLE_PERMISSIONS["moderator"] = [
        Permission.ENVIRONMENT_READ,
        Permission.ENVIRONMENT_UPDATE,
    ]
    _rebuild_expansion_cache()

    await assert_denied(client, auth(moderator_token), template.id, revision.id)


async def test_admin_api_token_cannot_use_revision_routes(client, admin_user, db_session):
    template, revision = await add_fixture_rows(db_session)
    raw_token = "nukelab_" + secrets.token_urlsafe(32)
    db_session.add(
        ApiToken(
            user_id=admin_user.id,
            name="Revision admin token",
            token_hash=get_password_hash(raw_token),
            token_prefix=raw_token[:16],
            scopes=["*"],
            is_active=True,
        )
    )
    await db_session.commit()

    headers = auth(raw_token)
    listing = await client.get(f"/api/environments/{template.id}/revisions", headers=headers)
    verify = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=headers,
        json={"reason": "api token must not verify"},
    )
    revoke = await client.post(
        f"/api/admin/environment-revisions/{revision.id}/revoke",
        headers=headers,
        json={"reason": "api token must not revoke"},
    )

    assert listing.status_code == 403
    assert verify.status_code == 403
    assert revoke.status_code == 403
    assert "JWT" in listing.json()["detail"]
    assert "JWT" in verify.json()["detail"]
    assert "JWT" in revoke.json()["detail"]
