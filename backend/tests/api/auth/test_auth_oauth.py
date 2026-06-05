"""Coverage-focused tests for auth.py gaps."""

import pytest
from unittest import mock
from datetime import datetime, timedelta, UTC
from jose import jwt as jose_jwt

from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.models.api_token import ApiToken
from app.models.login_event import LoginEvent


def _make_oauth_mock():
    """Create a mock OAuthService that appears configured."""
    m = mock.MagicMock()
    m.is_configured = True
    m.generate_state = mock.Mock(return_value="state123")
    m.generate_pkce = mock.Mock(return_value=("verifier", "challenge"))
    m.get_authorize_url = mock.AsyncMock(return_value="http://oauth/authorize")
    m.exchange_code = mock.AsyncMock(return_value={"access_token": "at"})
    m.get_user_info = mock.AsyncMock(return_value={"sub": "oauth123", "email": "test@example.com"})
    m.extract_user_data = mock.Mock(return_value={
        "oauth_id": "oauth123",
        "username": "oauthuser",
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "User",
        "extra_profile": {}
    })
    return m


class TestOAuthCallbackErrors:
    """OAuth callback error paths."""

    @pytest.mark.asyncio
    async def test_oauth_callback_error_param(self, client):
        with mock.patch("app.services.oauth_service.oauth_service", _make_oauth_mock()):
            client.cookies.set("oauth_state", "test_state")
            response = await client.get(
                "/api/auth/oauth/callback?error=access_denied&state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "access_denied" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_oauth_callback_missing_code(self, client):
        with mock.patch("app.services.oauth_service.oauth_service", _make_oauth_mock()):
            client.cookies.set("oauth_state", "test_state")
            response = await client.get(
                "/api/auth/oauth/callback?state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "missing" in response.headers["location"].lower()

    @pytest.mark.asyncio
    async def test_oauth_callback_invalid_state(self, client):
        with mock.patch("app.services.oauth_service.oauth_service", _make_oauth_mock()):
            client.cookies.set("oauth_state", "real_state")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=fake_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "invalid" in response.headers["location"].lower()

    @pytest.mark.asyncio
    async def test_oauth_callback_sync_error_param(self, client):
        with mock.patch("app.services.oauth_service.oauth_service", _make_oauth_mock()):
            client.cookies.set("oauth_state", "test_state")
            client.cookies.set("oauth_sync", "1")
            response = await client.get(
                "/api/auth/oauth/callback?error=access_denied&state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "sync=error" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_oauth_callback_sync_missing_code(self, client):
        with mock.patch("app.services.oauth_service.oauth_service", _make_oauth_mock()):
            client.cookies.set("oauth_state", "test_state")
            client.cookies.set("oauth_sync", "1")
            response = await client.get(
                "/api/auth/oauth/callback?state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "sync=error" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_oauth_callback_exception_handling(self, client):
        m = _make_oauth_mock()
        m.exchange_code = mock.AsyncMock(side_effect=RuntimeError("boom"))
        with mock.patch("app.services.oauth_service.oauth_service", m):
            client.cookies.set("oauth_state", "test_state")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "failed" in response.headers["location"].lower()

    @pytest.mark.asyncio
    async def test_oauth_callback_sync_exception_handling(self, client):
        m = _make_oauth_mock()
        m.exchange_code = mock.AsyncMock(side_effect=RuntimeError("boom"))
        with mock.patch("app.services.oauth_service.oauth_service", m):
            client.cookies.set("oauth_state", "test_state")
            client.cookies.set("oauth_sync", "1")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "sync=error" in response.headers["location"]


class TestOAuthCallbackHappyPaths:
    """OAuth callback user creation and linking."""

    @pytest.mark.asyncio
    async def test_oauth_callback_create_new_user(self, client, db_session):
        # Avoid login_events NotNullViolation by mocking db.add to skip LoginEvent
        m = _make_oauth_mock()
        m.exchange_code = mock.AsyncMock(return_value={"access_token": "at", "refresh_token": "rt"})
        m.get_user_info = mock.AsyncMock(return_value={
            "sub": "oauth123",
            "email": "oauth_new@example.com",
            "preferred_username": "oauthnewuser"
        })
        m.extract_user_data = mock.Mock(return_value={
            "oauth_id": "oauth123",
            "username": "oauthnewuser",
            "email": "oauth_new@example.com",
            "first_name": "OAuth",
            "last_name": "New",
            "extra_profile": {"org": "test"}
        })
        with mock.patch("app.services.oauth_service.oauth_service", m):
            with mock.patch("app.api.auth.get_db") as mock_get_db:
                from app.db.session import AsyncSessionLocal
                # Use a session that wraps add to ignore LoginEvent
                real_session = db_session
                orig_add = real_session.add
                def safe_add(instance):
                    from app.models.login_event import LoginEvent
                    if isinstance(instance, LoginEvent):
                        return
                    return orig_add(instance)
                with mock.patch.object(real_session, 'add', safe_add):
                    mock_get_db.return_value = __import__('typing').cast(__import__('typing').AsyncIterator, iter([real_session]))
                    client.cookies.set("oauth_state", "test_state")
                    response = await client.get(
                        "/api/auth/oauth/callback?code=abc&state=test_state",
                        follow_redirects=False
                    )
                    assert response.status_code == 307
                    assert "token=" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_oauth_callback_link_existing_user_by_email(self, client, test_user, db_session):
        test_user.oauth_id = None
        test_user.oauth_provider = None
        await db_session.commit()

        m = _make_oauth_mock()
        m.get_user_info = mock.AsyncMock(return_value={
            "sub": "oauth456",
            "email": test_user.email,
            "preferred_username": test_user.username
        })
        m.extract_user_data = mock.Mock(return_value={
            "oauth_id": "oauth456",
            "username": test_user.username,
            "email": test_user.email,
            "first_name": "Linked",
            "last_name": "User",
            "extra_profile": {}
        })
        with mock.patch("app.services.oauth_service.oauth_service", m):
            client.cookies.set("oauth_state", "test_state")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "token=" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_oauth_callback_sync_mode(self, client, test_user, db_session):
        test_user.oauth_provider = "oauth"
        test_user.oauth_id = "oauth789"
        await db_session.commit()

        m = _make_oauth_mock()
        m.get_user_info = mock.AsyncMock(return_value={
            "sub": "oauth789",
            "email": test_user.email,
        })
        m.extract_user_data = mock.Mock(return_value={
            "oauth_id": "oauth789",
            "username": test_user.username,
            "email": test_user.email,
            "first_name": "Sync",
            "last_name": "Mode",
            "extra_profile": {}
        })
        with mock.patch("app.services.oauth_service.oauth_service", m):
            client.cookies.set("oauth_state", "test_state")
            client.cookies.set("oauth_sync", "1")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "sync=success" in response.headers["location"]

    @pytest.mark.asyncio
    async def test_oauth_callback_no_access_token(self, client):
        m = _make_oauth_mock()
        m.exchange_code = mock.AsyncMock(return_value={})
        with mock.patch("app.services.oauth_service.oauth_service", m):
            client.cookies.set("oauth_state", "test_state")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "failed" in response.headers["location"].lower()

    @pytest.mark.asyncio
    async def test_oauth_callback_no_userinfo(self, client):
        m = _make_oauth_mock()
        m.exchange_code = mock.AsyncMock(return_value={"access_token": "at"})
        m.get_user_info = mock.AsyncMock(return_value=None)
        with mock.patch("app.services.oauth_service.oauth_service", m):
            client.cookies.set("oauth_state", "test_state")
            response = await client.get(
                "/api/auth/oauth/callback?code=abc&state=test_state",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "failed" in response.headers["location"].lower()

    @pytest.mark.asyncio
    async def test_oauth_callback_id_token_fallback(self, client, db_session):
        m = _make_oauth_mock()
        m.exchange_code = mock.AsyncMock(return_value={"access_token": "at", "id_token": "fake_id_token"})
        m.get_user_info = mock.AsyncMock(return_value=None)
        m.extract_user_data = mock.Mock(return_value={
            "oauth_id": "oauth999",
            "username": "idtokenuser",
            "email": "idtoken@example.com",
            "first_name": "",
            "last_name": "",
            "extra_profile": {}
        })
        with mock.patch("app.services.oauth_service.oauth_service", m):
            with mock.patch("app.api.auth.jwt.decode", return_value={
                "sub": "oauth999",
                "email": "idtoken@example.com",
                "preferred_username": "idtokenuser"
            }):
                with mock.patch("app.api.auth.get_db") as mock_get_db:
                    real_session = db_session
                    orig_add = real_session.add
                    def safe_add(instance):
                        from app.models.login_event import LoginEvent
                        if isinstance(instance, LoginEvent):
                            return
                        return orig_add(instance)
                    with mock.patch.object(real_session, 'add', safe_add):
                        mock_get_db.return_value = __import__('typing').cast(__import__('typing').AsyncIterator, iter([real_session]))
                        client.cookies.set("oauth_state", "test_state")
                        response = await client.get(
                            "/api/auth/oauth/callback?code=abc&state=test_state",
                            follow_redirects=False
                        )
                        assert response.status_code == 307
                        assert "token=" in response.headers["location"]


class TestOAuthLoginPKCEAndSync:
    """GET /oauth/login PKCE and sync coverage."""

    @pytest.mark.asyncio
    async def test_oauth_login_pkce_enabled(self, client):
        m = _make_oauth_mock()
        with mock.patch("app.services.oauth_service.oauth_service", m):
            with mock.patch("app.api.auth.settings.oauth_pkce_enabled", True):
                response = await client.get(
                    "/api/auth/oauth/login",
                    follow_redirects=False
                )
                assert response.status_code == 307
                assert "oauth_verifier" in response.cookies

    @pytest.mark.asyncio
    async def test_oauth_login_sync_mode(self, client):
        m = _make_oauth_mock()
        with mock.patch("app.services.oauth_service.oauth_service", m):
            response = await client.get(
                "/api/auth/oauth/login?sync=1",
                follow_redirects=False
            )
            assert response.status_code == 307
            assert "oauth_sync" in response.cookies
            assert "prompt=none" in response.headers["location"]


class TestGetAuthContextEdgeCases:
    """get_auth_context untested branches."""

    @pytest.mark.asyncio
    async def test_expired_api_token(self, client, db_session, test_user):
        from app.api.auth import get_password_hash
        import secrets

        raw = f"nukelab_{secrets.token_urlsafe(32)}"
        token = ApiToken(
            user_id=test_user.id,
            name="expired",
            token_hash=get_password_hash(raw),
            token_prefix=raw[:16],
            scopes=["user:read"],
            is_active=True,
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        )
        db_session.add(token)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {raw}"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_api_token_inactive_user(self, client, db_session, test_user):
        from app.api.auth import get_password_hash
        import secrets

        test_user.is_active = False
        raw = f"nukelab_{secrets.token_urlsafe(32)}"
        token = ApiToken(
            user_id=test_user.id,
            name="inactive",
            token_hash=get_password_hash(raw),
            token_prefix=raw[:16],
            scopes=["user:read"],
            is_active=True
        )
        db_session.add(token)
        await db_session.commit()

        response = await client.get(
            "/api/users/me/profile",
            headers={"Authorization": f"Bearer {raw}"}
        )
        assert response.status_code == 401


class TestVerifyRefreshTokenLegacy:
    """verify_refresh_token legacy fallback."""

    @pytest.mark.asyncio
    async def test_legacy_refresh_token_lookup(self, db_session, test_user):
        from app.api.auth import verify_refresh_token, pwd_context
        import secrets
        import hashlib

        plaintext = secrets.token_urlsafe(32)
        token_hash = pwd_context.hash(plaintext)
        rt = RefreshToken(
            user_id=test_user.id,
            token_hash=token_hash,
            token_lookup=None,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7)
        )
        db_session.add(rt)
        await db_session.commit()

        result = await verify_refresh_token(plaintext, db_session)
        assert result is not None
        assert result.id == rt.id


class TestEnforceRefreshTokenLimit:
    """_enforce_refresh_token_limit coverage."""

    @pytest.mark.asyncio
    async def test_enforce_token_limit_revokes_oldest(self, db_session, test_user):
        from app.api.auth import _enforce_refresh_token_limit
        import uuid
        from sqlalchemy import select, func

        uid = uuid.UUID(str(test_user.id))
        for i in range(11):
            rt = RefreshToken(
                user_id=uid,
                token_hash="hash",
                token_lookup=f"lookup{i}",
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
                created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=i)
            )
            db_session.add(rt)
        await db_session.commit()

        await _enforce_refresh_token_limit(uid, db_session)
        await db_session.commit()

        result = await db_session.execute(
            select(func.count()).select_from(RefreshToken).where(
                RefreshToken.revoked_at == None,
                RefreshToken.user_id == uid
            )
        )
        count = result.scalar()
        assert count <= 10


class TestRevokeRefreshTokenValueError:
    """revoke_refresh_token ValueError."""

    @pytest.mark.asyncio
    async def test_revoke_no_args_raises(self):
        from app.api.auth import revoke_refresh_token
        with pytest.raises(ValueError):
            await revoke_refresh_token()


class TestVerifyInactiveUser:
    """GET /verify inactive user branches."""

    @pytest.mark.asyncio
    async def test_verify_inactive_jwt_user(self, client, test_user, db_session):
        from app.api.auth import create_access_token
        test_user.is_active = False
        await db_session.commit()

        token = create_access_token(data={"sub": test_user.username, "role": test_user.role})
        response = await client.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_inactive_api_token_user(self, client, db_session, test_user):
        from app.api.auth import get_password_hash
        import secrets

        test_user.is_active = False
        raw = f"nukelab_{secrets.token_urlsafe(32)}"
        token = ApiToken(
            user_id=test_user.id,
            name="inactive",
            token_hash=get_password_hash(raw),
            token_prefix=raw[:16],
            scopes=["user:read"],
            is_active=True
        )
        db_session.add(token)
        await db_session.commit()

        response = await client.get(
            "/api/auth/verify",
            headers={"Authorization": f"Bearer {raw}"}
        )
        assert response.status_code == 401


class _MockAiohttpResponse:
    def __init__(self, json_data, status=200):
        self._json = json_data
        self.status = status

    async def json(self):
        return self._json

    def raise_for_status(self):
        if self.status >= 400:
            raise Exception(f"HTTP {self.status}")


class _MockAiohttpSession:
    def __init__(self, response_json, status=200):
        self._response = _MockAiohttpResponse(response_json, status)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, *args, **kwargs):
        return _MockAiohttpResponseContext(self._response)


class _MockAiohttpResponseContext:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        pass


class _MockAiohttpClientSession:
    def __init__(self, response_json, status=200):
        self._session = _MockAiohttpSession(response_json, status)

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


class TestOAuthSync:
    """POST /oauth/sync endpoint coverage."""

    @pytest.mark.asyncio
    async def test_oauth_sync_not_oauth_user(self, client, user_token, test_user):
        response = await client.post(
            "/api/auth/oauth/sync",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 400
        assert "not an oauth user" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_oauth_sync_no_refresh_token(self, client, user_token, test_user, db_session):
        test_user.oauth_provider = "oauth"
        test_user.security = {"other": "value"}
        await db_session.commit()

        response = await client.post(
            "/api/auth/oauth/sync",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 400
        assert "no refresh token" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_oauth_sync_invalid_refresh_token(self, client, user_token, test_user, db_session):
        test_user.oauth_provider = "oauth"
        test_user.security = {"oauth_refresh_token": "invalid"}
        await db_session.commit()

        with mock.patch("app.core.token_encryption.decrypt_token", return_value=None):
            response = await client.post(
                "/api/auth/oauth/sync",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 400
        assert "invalid refresh token" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_oauth_sync_success(self, client, user_token, test_user, db_session):
        from app.core.token_encryption import encrypt_token
        test_user.oauth_provider = "oauth"
        test_user.security = {"oauth_refresh_token": encrypt_token("rt123")}
        test_user.profile = {}
        await db_session.commit()

        mock_oauth = _make_oauth_mock()
        mock_oauth._load_discovery = mock.AsyncMock()
        mock_oauth._get_endpoint = mock.Mock(return_value="http://test/token")
        mock_oauth.get_user_info = mock.AsyncMock(return_value={"sub": "oauth123", "email": "new@example.com"})
        mock_oauth.extract_user_data = mock.Mock(return_value={
            "oauth_id": "oauth123",
            "username": "oauthuser",
            "email": "new@example.com",
            "first_name": "New",
            "last_name": "Name",
            "extra_profile": {"org": "TestOrg"},
        })

        mock_session = _MockAiohttpClientSession({"access_token": "at_new", "refresh_token": "rt_new"})

        with mock.patch("app.services.oauth_service.oauth_service", mock_oauth):
            with mock.patch("aiohttp.ClientSession", return_value=mock_session):
                response = await client.post(
                    "/api/auth/oauth/sync",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "new@example.com"
        assert data["first_name"] == "New"
        assert data["last_name"] == "Name"

    @pytest.mark.asyncio
    async def test_oauth_sync_generic_exception(self, client, user_token, test_user, db_session):
        from app.core.token_encryption import encrypt_token
        test_user.oauth_provider = "oauth"
        test_user.security = {"oauth_refresh_token": encrypt_token("rt123")}
        await db_session.commit()

        mock_oauth = _make_oauth_mock()
        mock_oauth._load_discovery = mock.AsyncMock(side_effect=RuntimeError("boom"))

        with mock.patch("app.services.oauth_service.oauth_service", mock_oauth):
            response = await client.post(
                "/api/auth/oauth/sync",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 500
        assert "sync failed" in response.json()["detail"].lower()
