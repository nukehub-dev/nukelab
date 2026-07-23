# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Additional auth coverage tests for easier endpoints and branches."""

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest


class TestCsrfToken:
    """GET /auth/csrf-token coverage."""

    @pytest.mark.asyncio
    async def test_get_csrf_token(self, client):
        response = await client.get("/api/auth/csrf-token")
        assert response.status_code == 200
        data = response.json()
        assert "csrf_token" in data
        assert len(data["csrf_token"]) > 0


class TestAuthMethods:
    """GET /auth/methods coverage."""

    @pytest.mark.asyncio
    async def test_get_auth_methods_local_mode(self, client):
        with mock.patch("app.api.auth.settings.auth_mode", "local"):
            with mock.patch("app.api.auth.settings.oauth_client_id", ""):
                response = await client.get("/api/auth/methods")
                assert response.status_code == 200
                data = response.json()
                assert data["auth_mode"] == "local"
                assert data["oauth_enabled"] is False
                methods = [m["type"] for m in data["methods"]]
                assert "local" in methods

    @pytest.mark.asyncio
    async def test_get_auth_methods_oauth_mode(self, client):
        with mock.patch("app.api.auth.settings.auth_mode", "oauth"):
            with mock.patch(
                "app.services.oauth_service.OAuthService.is_configured",
                new_callable=mock.PropertyMock,
                return_value=True,
            ):
                response = await client.get("/api/auth/methods")
                assert response.status_code == 200
                data = response.json()
                assert data["auth_mode"] == "oauth"
                assert data["oauth_enabled"] is True

    @pytest.mark.asyncio
    async def test_get_auth_methods_both_mode(self, client):
        with mock.patch("app.api.auth.settings.auth_mode", "both"):
            with mock.patch(
                "app.services.oauth_service.OAuthService.is_configured",
                new_callable=mock.PropertyMock,
                return_value=True,
            ):
                response = await client.get("/api/auth/methods")
                assert response.status_code == 200
                data = response.json()
                methods = [m["type"] for m in data["methods"]]
                assert "local" in methods
                assert "oauth" in methods


class TestVerifyAuth:
    """GET /auth/verify coverage for nginx auth_request."""

    @pytest.mark.asyncio
    async def test_verify_auth_jwt_valid(self, client, admin_token):
        response = await client.get(
            "/api/auth/verify", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert "X-User-Id" in response.headers

    @pytest.mark.asyncio
    async def test_verify_auth_missing_token(self, client):
        response = await client.get("/api/auth/verify")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_auth_invalid_scheme(self, client):
        response = await client.get(
            "/api/auth/verify", headers={"Authorization": "Basic dXNlcjpwYXNz"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_auth_cookie_token(self, client, admin_token):
        response = await client.get("/api/auth/verify", cookies={"nukelab_token": admin_token})
        assert response.status_code == 200
        assert "X-User-Id" in response.headers

    @pytest.mark.asyncio
    async def test_verify_auth_bearer_no_space(self, client, admin_token):
        response = await client.get("/api/auth/verify", headers={"Authorization": admin_token})
        # No space - treated as bare token
        assert response.status_code in (200, 401)


class TestLogin:
    """POST /auth/login coverage."""

    @pytest.mark.asyncio
    async def test_login_oauth_mode_disabled(self, client):
        with mock.patch("app.api.auth.settings.auth_mode", "oauth"):
            response = await client.post(
                "/api/auth/login", data={"username": "test", "password": "test"}
            )
            assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client):
        with mock.patch("app.api.auth.settings.auth_mode", "local"):
            response = await client.post(
                "/api/auth/login",
                data={"username": "nonexistent_user_xyz", "password": "wrongpass"},
            )
            assert response.status_code == 401


class TestRefreshToken:
    """POST /auth/refresh coverage."""

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, client):
        response = await client.post(
            "/api/auth/refresh", json={"refresh_token": "invalid-token-12345"}
        )
        assert response.status_code == 401


class TestLogout:
    """POST /auth/logout coverage."""

    @pytest.mark.asyncio
    async def test_logout_without_body(self, client, admin_token):
        response = await client.post(
            "/api/auth/logout", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert "message" in response.json()

    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self, client, admin_token):
        response = await client.post(
            "/api/auth/logout", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        # Check Clear-Site-Data header
        assert "Clear-Site-Data" in response.headers

    @pytest.mark.asyncio
    async def test_logout_with_refresh_token(self, client, test_user, db_session):
        from app.api.auth import create_refresh_token_for_user

        rt = await create_refresh_token_for_user(str(test_user.id), db_session)

        response = await client.post(
            "/api/auth/logout",
            headers={"Authorization": "Bearer dummy"},
            json={"refresh_token": rt},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_logout_stop_on_logout(self, client, test_user, db_session):
        from app.api.auth import create_refresh_token_for_user
        from app.models.server import Server
        from app.models.server_plan import ServerPlan

        test_user.preferences = {"stop_on_logout": True}

        plan = ServerPlan(
            name="logout-plan",
            slug="logout-plan",
            cpu_limit=1.0,
            memory_limit="512m",
            disk_limit="10g",
            is_active=True,
        )
        db_session.add(plan)
        await db_session.flush()

        server = Server(
            name="srv-logout",
            user_id=test_user.id,
            status="running",
            container_id="c1",
            plan_id=plan.id,
        )
        db_session.add(server)
        await db_session.flush()

        rt = await create_refresh_token_for_user(str(test_user.id), db_session)
        await db_session.commit()

        with mock.patch("app.api.auth.spawner.get_status", return_value="running"):
            with mock.patch("app.api.auth.spawner.delete", return_value=True):
                with mock.patch("app.services.credit_service.CreditService") as MockCS:
                    cs_inst = MockCS.return_value
                    cs_inst.reconcile_server_billing = mock.AsyncMock()
                    with mock.patch("app.services.quota_service.QuotaService") as MockQS:
                        qs_inst = MockQS.return_value
                        qs_inst.decrement_usage = mock.AsyncMock()
                        with mock.patch("app.api.auth.NotificationService") as MockNS:
                            ns_inst = MockNS.return_value
                            ns_inst.server_stopped = mock.AsyncMock()
                            with mock.patch(
                                "app.api.auth.broadcast_server_status_change", mock.AsyncMock()
                            ):
                                response = await client.post(
                                    "/api/auth/logout",
                                    headers={"Authorization": "Bearer dummy"},
                                    json={"refresh_token": rt},
                                )

        assert response.status_code == 200
        cs_inst.reconcile_server_billing.assert_awaited_once()
        qs_inst.decrement_usage.assert_awaited_once()
        ns_inst.server_stopped.assert_awaited_once()


class TestCustomHTTPBearer:
    """Direct tests for CustomHTTPBearer."""

    @pytest.mark.asyncio
    async def test_bearer_no_authorization_header(self):
        from unittest.mock import AsyncMock

        from app.api.auth import CustomHTTPBearer

        request = AsyncMock()
        request.headers = {}
        bearer = CustomHTTPBearer(auto_error=True)
        with pytest.raises(Exception) as exc_info:
            await bearer(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_bearer_invalid_scheme(self):
        from unittest.mock import AsyncMock

        from app.api.auth import CustomHTTPBearer

        request = AsyncMock()
        request.headers = {"Authorization": "Basic abc123"}
        bearer = CustomHTTPBearer(auto_error=True)
        with pytest.raises(Exception) as exc_info:
            await bearer(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_bearer_auto_error_false_returns_none(self):
        from unittest.mock import AsyncMock

        from app.api.auth import CustomHTTPBearer

        request = AsyncMock()
        request.headers = {}
        bearer = CustomHTTPBearer(auto_error=False)
        result = await bearer(request)
        assert result is None

    @pytest.mark.asyncio
    async def test_bearer_valid_token(self):
        from unittest.mock import AsyncMock

        from app.api.auth import CustomHTTPBearer

        request = AsyncMock()
        request.headers = {"Authorization": "Bearer validtoken123"}
        bearer = CustomHTTPBearer(auto_error=True)
        result = await bearer(request)
        assert result == "validtoken123"

    @pytest.mark.asyncio
    async def test_bearer_token_scheme(self):
        from unittest.mock import AsyncMock

        from app.api.auth import CustomHTTPBearer

        request = AsyncMock()
        request.headers = {"Authorization": "Token validtoken123"}
        bearer = CustomHTTPBearer(auto_error=True)
        result = await bearer(request)
        assert result == "validtoken123"


class TestRequireScopes:
    """Direct tests for require_scopes dependency factory."""

    @pytest.mark.asyncio
    async def test_require_scopes_jwt_bypasses(self):
        from unittest.mock import AsyncMock

        from app.api.auth import AuthContext, require_scopes

        request = AsyncMock()
        user = AsyncMock()
        request.state.auth_context = AuthContext(user=user, auth_method="jwt", token_scopes=[])
        checker = require_scopes("servers:read")
        result = await checker(request, user)
        assert result is None

    @pytest.mark.asyncio
    async def test_require_scopes_api_token_matching(self):
        from unittest.mock import AsyncMock

        from app.api.auth import AuthContext, require_scopes

        request = AsyncMock()
        user = AsyncMock()
        request.state.auth_context = AuthContext(
            user=user, auth_method="api_token", token_scopes=["servers:read"]
        )
        checker = require_scopes("servers:read")
        result = await checker(request, user)
        assert result is None

    @pytest.mark.asyncio
    async def test_require_scopes_api_token_wildcard(self):
        from unittest.mock import AsyncMock

        from app.api.auth import AuthContext, require_scopes

        request = AsyncMock()
        user = AsyncMock()
        request.state.auth_context = AuthContext(
            user=user, auth_method="api_token", token_scopes=["servers:*"]
        )
        checker = require_scopes("servers:read")
        result = await checker(request, user)
        assert result is None

    @pytest.mark.asyncio
    async def test_require_scopes_api_token_missing(self):
        from unittest.mock import AsyncMock

        from fastapi import HTTPException

        from app.api.auth import AuthContext, require_scopes

        request = AsyncMock()
        user = AsyncMock()
        request.state.auth_context = AuthContext(
            user=user, auth_method="api_token", token_scopes=["other:read"]
        )
        checker = require_scopes("servers:read")
        with pytest.raises(HTTPException) as exc_info:
            await checker(request, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_scopes_no_auth_context(self):
        from unittest.mock import AsyncMock

        from fastapi import HTTPException

        from app.api.auth import require_scopes

        request = AsyncMock()
        request.state.auth_context = None
        user = AsyncMock()
        checker = require_scopes("servers:read")
        with pytest.raises(HTTPException) as exc_info:
            await checker(request, user)
        assert exc_info.value.status_code == 401


class TestRequireJwtAuth:
    """Direct tests for require_jwt_auth dependency factory."""

    @pytest.mark.asyncio
    async def test_require_jwt_auth_passes(self):
        from unittest.mock import AsyncMock

        from app.api.auth import AuthContext, require_jwt_auth

        request = AsyncMock()
        user = AsyncMock()
        request.state.auth_context = AuthContext(user=user, auth_method="jwt", token_scopes=[])
        checker = require_jwt_auth()
        result = await checker(request, user)
        assert result is None

    @pytest.mark.asyncio
    async def test_require_jwt_auth_rejects_api_token(self):
        from unittest.mock import AsyncMock

        from fastapi import HTTPException

        from app.api.auth import AuthContext, require_jwt_auth

        request = AsyncMock()
        user = AsyncMock()
        request.state.auth_context = AuthContext(
            user=user, auth_method="api_token", token_scopes=[]
        )
        checker = require_jwt_auth()
        with pytest.raises(HTTPException) as exc_info:
            await checker(request, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_jwt_auth_no_context(self):
        from unittest.mock import AsyncMock

        from fastapi import HTTPException

        from app.api.auth import require_jwt_auth

        request = AsyncMock()
        request.state.auth_context = None
        user = AsyncMock()
        checker = require_jwt_auth()
        with pytest.raises(HTTPException) as exc_info:
            await checker(request, user)
        assert exc_info.value.status_code == 401


class TestCreateRefreshTokenForUser:
    """Direct test for create_refresh_token_for_user."""

    @pytest.mark.asyncio
    async def test_create_refresh_token(self, db_session, test_user):
        from app.api.auth import create_refresh_token_for_user

        token = await create_refresh_token_for_user(
            str(test_user.id), db_session, user_agent="test-agent", ip_address="127.0.0.1"
        )
        assert token is not None
        assert len(token) > 0

    @pytest.mark.asyncio
    async def test_create_refresh_token_enforces_limit(self, db_session, test_user):
        from app.api.auth import MAX_REFRESH_TOKENS_PER_USER, create_refresh_token_for_user

        # Create max + 1 tokens
        for _i in range(MAX_REFRESH_TOKENS_PER_USER + 1):
            await create_refresh_token_for_user(str(test_user.id), db_session)
        # Count active tokens
        from sqlalchemy import select

        from app.models.refresh_token import RefreshToken

        result = await db_session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == test_user.id, RefreshToken.revoked_at.is_(None)
            )
        )
        tokens = result.scalars().all()
        assert len(tokens) == MAX_REFRESH_TOKENS_PER_USER


class TestCleanupExpiredRefreshTokens:
    """Direct test for cleanup_expired_refresh_tokens."""

    @pytest.mark.asyncio
    async def test_cleanup_no_expired_tokens(self, db_session):
        from app.api.auth import cleanup_expired_refresh_tokens

        deleted = await cleanup_expired_refresh_tokens(db_session)
        assert deleted >= 0


class TestAuthContextEdgeCases:
    """Edge cases for get_auth_context."""

    @pytest.mark.asyncio
    async def test_get_auth_context_api_token_expired(self, client, db_session, test_user):
        import uuid
        from unittest.mock import AsyncMock

        from app.api.auth import get_auth_context
        from app.models.api_token import ApiToken

        # Create an expired API token
        token_str = "test_expired_token_123456789012345678901234567890"
        api_token = ApiToken(
            id=uuid.uuid4(),
            user_id=test_user.id,
            name="test expired",
            token_prefix=token_str[:16],
            token_hash="$2b$12$testhash",  # won't match verify_password but let's see
            is_active=True,
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        db_session.add(api_token)
        await db_session.commit()

        request = AsyncMock()
        request.state = AsyncMock()
        with pytest.raises(Exception):
            await get_auth_context(request, token_str, db_session)


class TestLoginHappyPath:
    """POST /auth/login happy path."""

    @pytest.mark.asyncio
    async def test_login_success(self, client, test_user):
        with mock.patch("app.api.auth.settings.auth_mode", "local"):
            response = await client.post(
                "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in data
            assert "token_type" in data

    @pytest.mark.asyncio
    async def test_login_sets_cookie(self, client, test_user):
        with mock.patch("app.api.auth.settings.auth_mode", "local"):
            response = await client.post(
                "/api/auth/login", data={"username": "testuser", "password": "testpass123"}
            )
            assert response.status_code == 200
            assert "set-cookie" in response.headers


class TestRefreshHappyPath:
    """POST /auth/refresh with valid token."""

    @pytest.mark.asyncio
    async def test_refresh_success(self, client, test_user, db_session):
        from app.api.auth import create_refresh_token_for_user

        rt = await create_refresh_token_for_user(str(test_user.id), db_session)
        response = await client.post("/api/auth/refresh", json={"refresh_token": rt})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data


class TestMeEndpoint:
    """GET /auth/me coverage."""

    @pytest.mark.asyncio
    async def test_get_me(self, client, user_token):
        response = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert "permissions" in data
        assert "nuke_balance" in data


class TestVerifyAuthEndpoint:
    """GET /auth/verify with various auth methods."""

    @pytest.mark.asyncio
    async def test_verify_auth_api_token(self, client, db_session, test_user):
        import secrets
        import uuid

        from app.api.auth import get_password_hash
        from app.models.api_token import ApiToken

        # Create an active API token with matching hash
        token_str = "nl_" + secrets.token_urlsafe(32)
        api_token = ApiToken(
            id=uuid.uuid4(),
            user_id=test_user.id,
            name="test token",
            token_prefix=token_str[:16],
            token_hash=get_password_hash(token_str),
            is_active=True,
        )
        db_session.add(api_token)
        await db_session.commit()
        response = await client.get(
            "/api/auth/verify", headers={"Authorization": f"Bearer {token_str}"}
        )
        assert response.status_code == 200
        assert "X-User-Id" in response.headers

    @pytest.mark.asyncio
    async def test_verify_auth_invalid_bearer(self, client):
        response = await client.get(
            "/api/auth/verify", headers={"Authorization": "Bearer invalidtoken"}
        )
        assert response.status_code == 401


class TestAuthContextSnapshot:
    """AuthContext snapshots user primitives for post-session middleware use."""

    def test_snapshots_user_id_and_role(self):
        import uuid
        from unittest.mock import MagicMock

        from app.api.auth import AuthContext

        user = MagicMock()
        user.id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        user.role = "admin"

        context = AuthContext(user=user, auth_method="jwt", token_scopes=[])

        assert context.user_id == "12345678-1234-5678-1234-567812345678"
        assert context.user_role == "admin"

    def test_snapshot_survives_detached_user(self):
        """Snapshots stay readable when ORM attribute access later fails."""
        from sqlalchemy.orm.exc import DetachedInstanceError

        from app.api.auth import AuthContext

        class _User:
            id = "user-uuid-1"
            role = "user"

        context = AuthContext(user=_User(), auth_method="jwt", token_scopes=[])
        assert context.user_id == "user-uuid-1"
        assert context.user_role == "user"

        # Simulate the post-rollback state: ORM attributes can no longer load.
        class _DetachedUser:
            @property
            def id(self):
                raise DetachedInstanceError("Instance is not bound to a Session")

            @property
            def role(self):
                raise DetachedInstanceError("Instance is not bound to a Session")

        context.user = _DetachedUser()
        assert context.user_id == "user-uuid-1"
        assert context.user_role == "user"
