# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for admin user-detail privacy: /resources authorization and
PII redaction in GET /users/{id} for non-admin viewers."""

import pytest


class TestUserResourcesAuthorization:
    """GET /users/{id}/resources previously had no permission check."""

    @pytest.mark.asyncio
    async def test_resources_self_allowed(self, client, user_token, test_user):
        response = await client.get(
            f"/api/users/{test_user.id}/resources",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == str(test_user.id)

    @pytest.mark.asyncio
    async def test_resources_other_user_forbidden(self, client, user_token, admin_user):
        """Regular users must not read another user's stats."""
        response = await client.get(
            f"/api/users/{admin_user.id}/resources",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_resources_moderator_allowed(self, client, moderator_token, test_user):
        response = await client.get(
            f"/api/users/{test_user.id}/resources",
            headers={"Authorization": f"Bearer {moderator_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_resources_unauthenticated_rejected(self, client, test_user):
        response = await client.get(f"/api/users/{test_user.id}/resources")
        assert response.status_code == 401


class TestGetUserPiiRedaction:
    """GET /users/{id} redacts PII for non-admin, non-self viewers."""

    @pytest.mark.asyncio
    async def test_moderator_gets_redacted_pii(self, client, moderator_token, test_user):
        response = await client.get(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {moderator_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        # Email stays visible (consistent with the users list endpoint)
        assert data["email"] == test_user.email
        # PII / activity metrics are redacted
        assert data["login_count"] == 0
        assert data["profile"] == {}
        assert data["preferences"] == {}
        assert data["oauth_provider"] is None
        # Operational fields remain visible
        assert data["username"] == test_user.username
        assert "role" in data
        assert "last_login" in data

    @pytest.mark.asyncio
    async def test_admin_gets_full_profile(self, client, admin_token, test_user):
        response = await client.get(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["login_count"] == test_user.login_count

    @pytest.mark.asyncio
    async def test_self_gets_full_profile(self, client, user_token, test_user):
        response = await client.get(
            f"/api/users/{test_user.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        assert response.json()["email"] == test_user.email

    @pytest.mark.asyncio
    async def test_regular_user_cannot_view_other_user(self, client, user_token, admin_user):
        response = await client.get(
            f"/api/users/{admin_user.id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 403
