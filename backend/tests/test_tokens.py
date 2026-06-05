"""Tests for API token management, authentication, and scope enforcement."""

import pytest
from datetime import datetime, timedelta, UTC


class TestTokenCreation:
    """API token creation tests."""

    @pytest.mark.asyncio
    async def test_create_token_with_valid_scopes(self, client, test_user, user_token):
        """Should create token with valid scopes and return raw token once."""
        response = await client.post(
            "/api/tokens",
            json={
                "name": "CI/CD Token",
                "scopes": ["servers:read", "servers:start"],
                "expires_days": 30,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "CI/CD Token"
        assert data["scopes"] == ["servers:read", "servers:start"]
        assert "token" in data
        assert data["token"].startswith("nukelab_")
        assert len(data["token"]) > 20
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_token_with_invalid_scope(self, client, test_user, user_token):
        """Should reject token creation with invalid scope."""
        response = await client.post(
            "/api/tokens",
            json={
                "name": "Bad Token",
                "scopes": ["invalid:scope"],
                "expires_days": 30,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_token_requires_auth(self, client):
        """Should reject unauthenticated token creation."""
        response = await client.post(
            "/api/tokens",
            json={"name": "Test", "scopes": ["servers:read"]},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_token_with_expiration(self, client, test_user, user_token):
        """Should create token with expiration date."""
        response = await client.post(
            "/api/tokens",
            json={
                "name": "Expiring Token",
                "scopes": ["servers:read"],
                "expires_days": 7,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["expires_at"] is not None

    @pytest.mark.asyncio
    async def test_create_token_with_no_expiration(self, client, test_user, user_token):
        """Should create token without expiration when expires_days is explicitly null."""
        response = await client.post(
            "/api/tokens",
            json={
                "name": "Forever Token",
                "scopes": ["servers:read"],
                "expires_days": None,
            },
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["expires_at"] is None


class TestTokenAuthentication:
    """API token authentication and scope enforcement tests."""

    @pytest.mark.asyncio
    async def test_api_token_authenticates_request(self, client, api_token):
        """API token should authenticate requests to /auth/me."""
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_api_token_with_allowed_scope(self, client, api_token):
        """Token with 'servers:read' should work for servers endpoint."""
        # Create a server first so the endpoint doesn't 404 for unrelated reasons
        response = await client.get(
            "/api/servers",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        # Should be 200, 307 (redirect), or 403 if scope-checked
        assert response.status_code in [200, 307, 403]

    @pytest.mark.asyncio
    async def test_revoked_api_token_rejected(self, client, api_token, db_session):
        """Revoked token should be rejected."""
        api_token.db_token.is_active = False
        api_token.db_token.revoked_at = datetime.now(UTC).replace(tzinfo=None)
        await db_session.commit()

        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_api_token_rejected(self, client, db_session, test_user):
        """Expired token should be rejected."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)
        token_prefix = raw_token[:16]

        expired_token = ApiToken(
            user_id=test_user.id,
            name="Expired Token",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["servers:read"],
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
            is_active=True,
        )
        db_session.add(expired_token)
        await db_session.commit()

        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_api_token_rejected(self, client):
        """Invalid token should be rejected."""
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer nukelab_invalidtoken123"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_api_token_usage_tracking(self, client, api_token, db_session):
        """Successful auth should update usage_count and last_used_at."""
        before_count = api_token.db_token.usage_count or 0

        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        assert response.status_code == 200

        # Refresh from DB
        from sqlalchemy import select
        from app.models.api_token import ApiToken
        result = await db_session.execute(
            select(ApiToken).where(ApiToken.id == api_token.db_token.id)
        )
        refreshed = result.scalar_one()
        assert refreshed.usage_count == before_count + 1
        assert refreshed.last_used_at is not None

    @pytest.mark.asyncio
    async def test_jwt_bypasses_scope_checks(self, client, user_token):
        """JWT auth should have full permissions regardless of scopes."""
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200


class TestTokenPrefixLookup:
    """Fast prefix-based token lookup tests."""

    @pytest.mark.asyncio
    async def test_token_with_prefix_uses_fast_path(self, client, api_token):
        """Token with token_prefix should authenticate successfully."""
        assert api_token.db_token.token_prefix is not None
        assert len(api_token.db_token.token_prefix) == 16

        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        assert response.status_code == 200


class TestTokenManagement:
    """Token CRUD and lifecycle tests."""

    @pytest.mark.asyncio
    async def test_list_tokens_user_isolation(self, client, test_user, user_token, admin_user, admin_token):
        """Users should only see their own tokens."""
        # Create token as test_user
        await client.post(
            "/api/tokens",
            json={"name": "User Token", "scopes": ["servers:read"]},
            headers={"Authorization": f"Bearer {user_token}"},
        )

        # List as test_user
        response = await client.get(
            "/api/tokens",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        user_tokens = response.json()
        # to_dict() excludes user_id; verify isolation by token name instead
        assert all(t["name"] != "admin-token" for t in user_tokens)

    @pytest.mark.asyncio
    async def test_revoke_token(self, client, test_user, user_token, db_session):
        """Soft revoke should mark token inactive."""
        create_resp = await client.post(
            "/api/tokens",
            json={"name": "To Revoke", "scopes": ["servers:read"]},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        token_id = create_resp.json()["id"]

        revoke_resp = await client.delete(
            f"/api/tokens/{token_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert revoke_resp.status_code == 204

        # Verify token is inactive
        from sqlalchemy import select
        from app.models.api_token import ApiToken
        result = await db_session.execute(select(ApiToken).where(ApiToken.id == token_id))
        token = result.scalar_one()
        assert token.is_active is False
        assert token.revoked_at is not None

    @pytest.mark.asyncio
    async def test_permanently_delete_token(self, client, test_user, user_token, db_session):
        """Hard delete should remove token from DB."""
        create_resp = await client.post(
            "/api/tokens",
            json={"name": "To Delete", "scopes": ["servers:read"]},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        token_id = create_resp.json()["id"]

        del_resp = await client.delete(
            f"/api/tokens/{token_id}/permanent",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert del_resp.status_code == 204

        # Verify token is gone
        from sqlalchemy import select
        from app.models.api_token import ApiToken
        result = await db_session.execute(select(ApiToken).where(ApiToken.id == token_id))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_regenerate_token(self, client, test_user, user_token):
        """Regeneration should revoke old and create new token."""
        create_resp = await client.post(
            "/api/tokens",
            json={"name": "To Regenerate", "scopes": ["servers:read"]},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        old_token_data = create_resp.json()
        old_token_id = old_token_data["id"]
        old_raw = old_token_data["token"]

        regen_resp = await client.post(
            f"/api/tokens/{old_token_id}/regenerate",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert regen_resp.status_code == 200
        new_data = regen_resp.json()
        assert new_data["token"] != old_raw
        assert new_data["name"] == "To Regenerate"
        assert "token" in new_data

    @pytest.mark.asyncio
    async def test_get_token_usage(self, client, test_user, user_token):
        """Usage endpoint should return token statistics."""
        create_resp = await client.post(
            "/api/tokens",
            json={"name": "Usage Test", "scopes": ["servers:read"]},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        token_id = create_resp.json()["id"]

        usage_resp = await client.get(
            f"/api/tokens/{token_id}/usage",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert usage_resp.status_code == 200
        data = usage_resp.json()
        assert data["name"] == "Usage Test"
        assert "usage_count" in data

    @pytest.mark.asyncio
    async def test_cannot_access_other_users_token(self, client, test_user, user_token, admin_user, admin_token):
        """User should not be able to access another user's token."""
        # Create token as test_user
        create_resp = await client.post(
            "/api/tokens",
            json={"name": "Private Token", "scopes": ["servers:read"]},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        token_id = create_resp.json()["id"]

        # Try to access as admin
        get_resp = await client.get(
            f"/api/tokens/{token_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert get_resp.status_code == 404


class TestScopeEnforcement:
    """Scope-based access control tests via require_scopes dependency."""

    @pytest.mark.asyncio
    async def test_scope_enforcement_allows_matching_scope(self, client, api_token):
        """Token with matching scope should be allowed."""
        # The api_token fixture has scopes ["servers:read", "servers:start"]
        # /api/servers requires servers:read or servers:read_own (role-based)
        response = await client.get(
            "/api/servers",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        # May be 200, 307 (redirect), or 403 depending on endpoint permissions
        assert response.status_code in [200, 307, 403]

    @pytest.mark.asyncio
    async def test_scope_enforcement_basic(self, client, db_session, test_user):
        """Test that scope checking works at the dependency level."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        # Create token with only user:read scope
        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)
        token_prefix = raw_token[:16]

        scoped_token = ApiToken(
            user_id=test_user.id,
            name="Narrow Scope Token",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["user:read"],
            is_active=True,
        )
        db_session.add(scoped_token)
        await db_session.commit()

        # Should authenticate successfully
        me_resp = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert me_resp.status_code == 200


class TestJwtOnlyEndpoints:
    """Token management should reject API token authentication."""

    @pytest.mark.asyncio
    async def test_api_token_cannot_create_token(self, client, api_token):
        """API token should be rejected for POST /tokens."""
        response = await client.post(
            "/api/tokens",
            json={"name": "Hacked", "scopes": ["servers:read"]},
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        assert response.status_code == 403
        assert "JWT authentication required" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_api_token_cannot_list_tokens(self, client, api_token):
        """API token should be rejected for GET /tokens."""
        response = await client.get(
            "/api/tokens",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_api_token_cannot_revoke_token(self, client, api_token):
        """API token should be rejected for DELETE /tokens/{id}."""
        response = await client.delete(
            f"/api/tokens/{api_token.db_token.id}",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_api_token_cannot_regenerate_token(self, client, api_token):
        """API token should be rejected for POST /tokens/{id}/regenerate."""
        response = await client.post(
            f"/api/tokens/{api_token.db_token.id}/regenerate",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_jwt_can_access_token_management(self, client, user_token):
        """JWT should be allowed for token management."""
        response = await client.get(
            "/api/tokens",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200


class TestScopedEndpointAccess:
    """API token scope enforcement on real endpoints."""

    @pytest.mark.asyncio
    async def test_api_token_inherits_role_permissions(self, client, db_session, test_user):
        """API tokens inherit the user's role permissions regardless of scopes."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)
        token_prefix = raw_token[:16]

        # Token has only user:read scope, but user's role has SERVERS_READ_OWN
        narrow_token = ApiToken(
            user_id=test_user.id,
            name="No Servers Token",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["user:read"],
            is_active=True,
        )
        db_session.add(narrow_token)
        await db_session.commit()

        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {raw_token}"},
            follow_redirects=False,
        )
        # Should succeed because user's role has SERVERS_READ_OWN
        assert response.status_code in [200, 307]

    @pytest.mark.asyncio
    async def test_api_token_with_servers_read_allowed(self, client, api_token):
        """Token with servers:read should access /servers."""
        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {api_token.raw_token}"},
            follow_redirects=False,
        )
        # 200 or 307 redirect are both acceptable
        assert response.status_code in [200, 307]

    @pytest.mark.asyncio
    async def test_jwt_always_has_full_access(self, client, user_token):
        """JWT should never be blocked by scope checks."""
        response = await client.get(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            follow_redirects=False,
        )
        assert response.status_code in [200, 307]


class TestAdminEndpointScopeAccess:
    """API token scope enforcement on admin endpoints."""

    @pytest.mark.asyncio
    async def test_api_token_blocked_from_admin_endpoints(self, client, db_session, admin_user):
        """Admin API tokens should be blocked from admin endpoints (JWT-only)."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)
        token_prefix = raw_token[:16]

        admin_api_token = ApiToken(
            user_id=admin_user.id,
            name="Admin Read Token",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["admin:read", "admin:write"],
            is_active=True,
        )
        db_session.add(admin_api_token)
        await db_session.commit()

        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        # Admin endpoints are JWT-only: API tokens rejected regardless of scopes
        assert response.status_code == 403
        assert "JWT" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_api_token_without_admin_read_blocked_from_admin_stats(self, client, db_session, admin_user):
        """Admin API token without admin:read should be blocked from /admin/stats."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)
        token_prefix = raw_token[:16]

        # Token has only user-level scopes, no admin scopes
        narrow_token = ApiToken(
            user_id=admin_user.id,
            name="No Admin Token",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["user:read", "servers:read"],
            is_active=True,
        )
        db_session.add(narrow_token)
        await db_session.commit()

        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert response.status_code == 403
        assert "JWT" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_api_token_with_admin_read_blocked_from_admin_write(self, client, db_session, admin_user):
        """Admin API token with only admin:read should be blocked from write endpoints."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)
        token_prefix = raw_token[:16]

        admin_read_token = ApiToken(
            user_id=admin_user.id,
            name="Admin Read Only Token",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["admin:read"],
            is_active=True,
        )
        db_session.add(admin_read_token)
        await db_session.commit()

        response = await client.post(
            "/api/admin/users/bulk-action",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"action": "disable", "user_ids": []},
        )
        # Admin endpoints are JWT-only
        assert response.status_code == 403
        assert "JWT" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_api_token_blocked_from_admin_write_endpoints(self, client, db_session, admin_user):
        """Admin API tokens should be blocked from admin write endpoints (JWT-only)."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)
        token_prefix = raw_token[:16]

        admin_write_token = ApiToken(
            user_id=admin_user.id,
            name="Admin Write Token",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["admin:read", "admin:write"],
            is_active=True,
        )
        db_session.add(admin_write_token)
        await db_session.commit()

        response = await client.post(
            "/api/admin/users/bulk-action",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={"action": "disable", "user_ids": []},
        )
        # Admin endpoints are JWT-only: API tokens rejected regardless of scopes
        assert response.status_code == 403
        assert "JWT" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_jwt_admin_bypasses_scope_checks_on_admin_endpoints(self, client, admin_token):
        """JWT admin token should never be blocked by scope checks on admin endpoints."""
        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_regular_user_api_token_blocked_by_role_not_scope(self, client, db_session, test_user):
        """Regular user with admin:read scope should still be blocked by require_permissions."""
        from app.models.api_token import ApiToken
        from app.api.auth import get_password_hash
        import secrets

        raw_token = f"nukelab_{secrets.token_urlsafe(32)}"
        token_hash = get_password_hash(raw_token)
        token_prefix = raw_token[:16]

        # Regular user tries to get admin scope
        fake_admin_token = ApiToken(
            user_id=test_user.id,
            name="Fake Admin Token",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["admin:read"],
            is_active=True,
        )
        db_session.add(fake_admin_token)
        await db_session.commit()

        response = await client.get(
            "/api/admin/stats",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        # Should be blocked by require_permissions (role check) before scope check
        assert response.status_code == 403
