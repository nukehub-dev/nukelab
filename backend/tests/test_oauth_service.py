"""Tests for OAuthService."""

import pytest
from unittest import mock

from app.services.oauth_service import OAuthService


def _make_async_context_manager(return_value):
    """Helper to create an async context manager mock."""
    ctx = mock.AsyncMock()
    ctx.__aenter__ = mock.AsyncMock(return_value=return_value)
    ctx.__aexit__ = mock.AsyncMock(return_value=False)
    return ctx


class TestOAuthServiceProperties:
    """Tests for basic OAuth service properties."""

    def test_is_configured_false_when_empty(self):
        """OAuth should not be configured when settings are empty."""
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_client_id = None
            mock_settings.oauth_client_secret = None
            mock_settings.oauth_discovery_url = None
            mock_settings.oauth_authorize_url = None
            svc = OAuthService()
            assert svc.is_configured is False

    def test_is_configured_true_with_manual(self):
        """OAuth should be configured with manual URLs."""
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_client_id = "client-id"
            mock_settings.oauth_client_secret = "secret"
            mock_settings.oauth_authorize_url = "http://auth"
            mock_settings.oauth_discovery_url = None
            svc = OAuthService()
            assert svc.is_configured is True

    def test_is_configured_true_with_discovery(self):
        """OAuth should be configured with discovery URL."""
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_client_id = "client-id"
            mock_settings.oauth_client_secret = "secret"
            mock_settings.oauth_authorize_url = None
            mock_settings.oauth_discovery_url = "http://discovery"
            svc = OAuthService()
            assert svc.is_configured is True


class TestOAuthServiceDiscovery:
    """Tests for OIDC discovery."""

    @pytest.mark.asyncio
    async def test_load_discovery_success(self):
        """Discovery document should be fetched and cached."""
        svc = OAuthService()
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_discovery_url = "http://discovery/.well-known"
            mock_response = mock.AsyncMock()
            mock_response.json = mock.AsyncMock(return_value={
                "authorization_endpoint": "http://auth",
                "token_endpoint": "http://token",
            })
            mock_response.raise_for_status = mock.Mock()

            get_ctx = _make_async_context_manager(mock_response)
            mock_session = mock.AsyncMock()
            mock_session.get = mock.Mock(return_value=get_ctx)
            session_ctx = _make_async_context_manager(mock_session)

            with mock.patch("aiohttp.ClientSession", return_value=session_ctx):
                data = await svc._load_discovery()

        assert data["authorization_endpoint"] == "http://auth"
        assert svc._discovery_loaded is True

    @pytest.mark.asyncio
    async def test_load_discovery_caches(self):
        """Second call should return cached data."""
        svc = OAuthService()
        svc.discovery_data = {"cached": True}
        svc._discovery_loaded = True
        data = await svc._load_discovery()
        assert data == {"cached": True}

    @pytest.mark.asyncio
    async def test_load_discovery_no_url(self):
        """If no discovery URL, return empty dict."""
        svc = OAuthService()
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_discovery_url = None
            data = await svc._load_discovery()
        assert data == {}

    @pytest.mark.asyncio
    async def test_load_discovery_failure(self):
        """Failed discovery should return empty dict."""
        svc = OAuthService()
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_discovery_url = "http://bad"

            get_ctx = _make_async_context_manager(mock.AsyncMock())
            get_ctx.__aenter__ = mock.AsyncMock(side_effect=Exception("network error"))
            mock_session = mock.AsyncMock()
            mock_session.get = mock.Mock(return_value=get_ctx)
            session_ctx = _make_async_context_manager(mock_session)

            with mock.patch("aiohttp.ClientSession", return_value=session_ctx):
                data = await svc._load_discovery()
        assert data == {}


class TestOAuthServiceEndpoints:
    """Tests for endpoint resolution."""

    def test_get_endpoint_from_discovery(self):
        """Should prefer discovery endpoints."""
        svc = OAuthService()
        svc.discovery_data = {"authorization_endpoint": "http://discovered-auth"}
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_authorize_url = "http://manual-auth"
            url = svc._get_endpoint("authorize")
        assert url == "http://discovered-auth"

    def test_get_endpoint_manual_fallback(self):
        """Should fall back to manual config."""
        svc = OAuthService()
        svc.discovery_data = None
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_authorize_url = "http://manual-auth"
            url = svc._get_endpoint("authorize")
        assert url == "http://manual-auth"

    def test_get_endpoint_unknown_type(self):
        """Unknown endpoint type returns None."""
        svc = OAuthService()
        assert svc._get_endpoint("unknown") is None


class TestOAuthServiceAuthorizeUrl:
    """Tests for authorization URL building."""

    @pytest.mark.asyncio
    async def test_get_authorize_url_basic(self):
        """Should build authorize URL with required params."""
        svc = OAuthService()
        svc.discovery_data = {"authorization_endpoint": "http://auth"}
        svc._discovery_loaded = True

        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_client_id = "client-id"
            mock_settings.oauth_callback_url = "http://callback"
            mock_settings.oauth_scope = "openid profile"
            mock_settings.oauth_pkce_enabled = False

            url = await svc.get_authorize_url("state123")

        assert url.startswith("http://auth?")
        assert "client_id=client-id" in url
        assert "state=state123" in url
        assert "response_type=code" in url

    @pytest.mark.asyncio
    async def test_get_authorize_url_with_pkce(self):
        """Should include PKCE params when enabled."""
        svc = OAuthService()
        svc.discovery_data = {"authorization_endpoint": "http://auth"}
        svc._discovery_loaded = True

        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_client_id = "client-id"
            mock_settings.oauth_callback_url = "http://callback"
            mock_settings.oauth_scope = "openid"
            mock_settings.oauth_pkce_enabled = True

            url = await svc.get_authorize_url("state", code_challenge="challenge123")

        assert "code_challenge=challenge123" in url
        assert "code_challenge_method=S256" in url

    @pytest.mark.asyncio
    async def test_get_authorize_url_not_configured(self):
        """Should raise ValueError when authorize URL missing."""
        svc = OAuthService()
        svc.discovery_data = {}
        svc._discovery_loaded = True

        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_authorize_url = None
            with pytest.raises(ValueError, match="authorize URL not configured"):
                await svc.get_authorize_url("state")


class TestOAuthServiceTokenExchange:
    """Tests for token exchange."""

    @pytest.mark.asyncio
    async def test_exchange_code_success(self):
        """Should exchange code for tokens."""
        svc = OAuthService()
        svc.discovery_data = {"token_endpoint": "http://token"}
        svc._discovery_loaded = True

        mock_response = mock.AsyncMock()
        mock_response.json = mock.AsyncMock(return_value={"access_token": "tok", "id_token": "id"})
        mock_response.raise_for_status = mock.Mock()

        post_ctx = _make_async_context_manager(mock_response)
        mock_session = mock.AsyncMock()
        mock_session.post = mock.Mock(return_value=post_ctx)
        session_ctx = _make_async_context_manager(mock_session)

        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_client_id = "client"
            mock_settings.oauth_client_secret = "secret"
            mock_settings.oauth_callback_url = "http://cb"
            mock_settings.oauth_pkce_enabled = False
            with mock.patch("aiohttp.ClientSession", return_value=session_ctx):
                result = await svc.exchange_code("code123")

        assert result["access_token"] == "tok"

    @pytest.mark.asyncio
    async def test_exchange_code_with_pkce(self):
        """Should include code_verifier with PKCE."""
        svc = OAuthService()
        svc.discovery_data = {"token_endpoint": "http://token"}
        svc._discovery_loaded = True

        mock_response = mock.AsyncMock()
        mock_response.json = mock.AsyncMock(return_value={"access_token": "tok"})
        mock_response.raise_for_status = mock.Mock()

        post_ctx = _make_async_context_manager(mock_response)
        mock_session = mock.AsyncMock()
        mock_session.post = mock.Mock(return_value=post_ctx)
        session_ctx = _make_async_context_manager(mock_session)

        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_client_id = "client"
            mock_settings.oauth_client_secret = "secret"
            mock_settings.oauth_callback_url = "http://cb"
            mock_settings.oauth_pkce_enabled = True
            with mock.patch("aiohttp.ClientSession", return_value=session_ctx):
                await svc.exchange_code("code123", code_verifier="verifier")

        call_args = mock_session.post.call_args
        passed_data = call_args[1]["data"]
        assert passed_data.get("code_verifier") == "verifier"


class TestOAuthServiceUserInfo:
    """Tests for user info fetching."""

    @pytest.mark.asyncio
    async def test_get_user_info_success(self):
        """Should fetch user info."""
        svc = OAuthService()
        svc.discovery_data = {"userinfo_endpoint": "http://userinfo"}
        svc._discovery_loaded = True

        mock_response = mock.AsyncMock()
        mock_response.json = mock.AsyncMock(return_value={"sub": "123", "email": "a@b.com"})
        mock_response.raise_for_status = mock.Mock()

        get_ctx = _make_async_context_manager(mock_response)
        mock_session = mock.AsyncMock()
        mock_session.get = mock.Mock(return_value=get_ctx)
        session_ctx = _make_async_context_manager(mock_session)

        with mock.patch("aiohttp.ClientSession", return_value=session_ctx):
            result = await svc.get_user_info("token123")

        assert result["email"] == "a@b.com"

    @pytest.mark.asyncio
    async def test_get_user_info_no_endpoint(self):
        """Should return empty dict if no userinfo endpoint."""
        svc = OAuthService()
        svc.discovery_data = {}
        svc._discovery_loaded = True
        result = await svc.get_user_info("token")
        assert result == {}


class TestOAuthServiceHelpers:
    """Tests for helper methods."""

    def test_generate_state(self):
        """State should be a non-empty string."""
        svc = OAuthService()
        state = svc.generate_state()
        assert isinstance(state, str)
        assert len(state) > 0

    def test_generate_pkce(self):
        """PKCE should return verifier and challenge."""
        svc = OAuthService()
        verifier, challenge = svc.generate_pkce()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)
        assert len(verifier) > 0
        assert len(challenge) > 0

    def test_extract_user_data_basic(self):
        """Should extract normalized user data."""
        svc = OAuthService()
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_username_claim = "preferred_username"
            mock_settings.oauth_email_claim = "email"
            mock_settings.oauth_name_claim = "name"

            result = svc.extract_user_data({
                "sub": "oauth-123",
                "preferred_username": "john",
                "email": "john@example.com",
                "name": "John Doe",
            })

        assert result["username"] == "john"
        assert result["email"] == "john@example.com"
        assert result["first_name"] == "John"
        assert result["last_name"] == "Doe"
        assert result["oauth_id"] == "oauth-123"

    def test_extract_user_data_fallbacks(self):
        """Should use fallback claims when primary missing."""
        svc = OAuthService()
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_username_claim = "preferred_username"
            mock_settings.oauth_email_claim = "email"
            mock_settings.oauth_name_claim = "name"

            result = svc.extract_user_data({
                "email": "jane@example.com",
            })

        assert result["username"] == "jane"
        assert result["email"] == "jane@example.com"

    def test_extract_user_data_extra_profile(self):
        """Should extract extra profile fields."""
        svc = OAuthService()
        with mock.patch("app.services.oauth_service.settings") as mock_settings:
            mock_settings.oauth_username_claim = "preferred_username"
            mock_settings.oauth_email_claim = "email"
            mock_settings.oauth_name_claim = "name"

            result = svc.extract_user_data({
                "sub": "1",
                "preferred_username": "user",
                "email": "u@e.com",
                "organization": "Org",
                "department": "Eng",
            })

        assert result["extra_profile"]["organization"] == "Org"
        assert result["extra_profile"]["department"] == "Eng"
