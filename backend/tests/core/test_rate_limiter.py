"""Tests for app.core.rate_limiter."""

from unittest import mock

import pytest
from fastapi import Request

from app.core.rate_limiter import (
    RateLimitExceeded,
    _check_limit,
    _extract_jwt_sub,
    _get_user_key_and_role,
    _hash_token,
    rate_limit_auth,
    rate_limit_general,
    rate_limit_strict,
    rate_limit_websocket,
)


class TestExtractJwtSub:
    def test_extracts_sub_from_valid_token(self, admin_token):
        result = _extract_jwt_sub(admin_token)
        assert result == "adminuser"

    def test_returns_none_for_invalid_token(self):
        result = _extract_jwt_sub("not.a.token")
        assert result is None

    def test_returns_none_for_empty(self):
        assert _extract_jwt_sub("") is None


class TestHashToken:
    def test_hashes_consistently(self):
        h1 = _hash_token("test-token-123")
        h2 = _hash_token("test-token-123")
        assert h1 == h2
        assert len(h1) == 16

    def test_different_tokens_different_hashes(self):
        assert _hash_token("a") != _hash_token("b")


class TestGetUserKeyAndRole:
    def test_bearer_jwt(self, admin_token):
        scope = {"type": "http", "headers": [(b"authorization", f"Bearer {admin_token}".encode())]}
        request = Request(scope)
        key, role = _get_user_key_and_role(request)
        assert key == "adminuser"
        assert role == "admin"

    def test_token_prefix(self):
        scope = {"type": "http", "headers": [(b"authorization", b"Token faketoken123")]}
        request = Request(scope)
        key, role = _get_user_key_and_role(request)
        assert key.startswith("tkn:")
        assert role == "user"

    def test_cookie_fallback(self):
        scope = {
            "type": "http",
            "headers": [(b"cookie", b"nukelab_token=cookietok")],
        }
        request = Request(scope)
        key, role = _get_user_key_and_role(request)
        assert key.startswith("tkn:")
        assert role == "user"

    def test_ip_fallback(self):
        scope = {
            "type": "http",
            "headers": [],
            "client": ("192.168.1.5", 12345),
        }
        request = Request(scope)
        key, role = _get_user_key_and_role(request)
        assert key == "ip:192.168.1.5"
        assert role == "unauthenticated"

    def test_x_forwarded_for(self):
        scope = {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"10.0.0.1, 10.0.0.2")],
            "client": ("192.168.1.5", 12345),
        }
        request = Request(scope)
        key, role = _get_user_key_and_role(request)
        assert key == "ip:10.0.0.1"


class TestCheckLimit:
    @pytest.mark.asyncio
    async def test_disabled_returns_zero(self):
        with mock.patch("app.core.rate_limiter.settings.rate_limit_enabled", False):
            req = Request({"type": "http", "headers": []})
            limit, remaining = await _check_limit(req)
            assert limit == 0
            assert remaining == 0

    @pytest.mark.asyncio
    async def test_within_limit(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=3)

        with mock.patch("app.core.rate_limiter._get_redis_client", return_value=mock_redis):
            with mock.patch("app.core.rate_limiter.settings.rate_limit_enabled", True):
                with mock.patch("app.core.rate_limiter.settings.rate_limit_window_seconds", 60):
                    with mock.patch(
                        "app.core.rate_limiter.settings.rate_limit_bucket_ttl_multiplier", 2
                    ):
                        req = Request({"type": "http", "headers": [], "client": ("1.1.1.1", 12345)})
                        limit, remaining = await _check_limit(req, multiplier=10.0)
                        assert remaining >= 0

    @pytest.mark.asyncio
    async def test_exceeds_limit_raises(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=9999)

        with mock.patch("app.core.rate_limiter._get_redis_client", return_value=mock_redis):
            with mock.patch("app.core.rate_limiter.settings.rate_limit_enabled", True):
                with mock.patch("app.core.rate_limiter.settings.rate_limit_window_seconds", 60):
                    req = Request({"type": "http", "headers": [], "client": ("1.1.1.1", 12345)})
                    with pytest.raises(RateLimitExceeded):
                        await _check_limit(req, multiplier=1.0)

    @pytest.mark.asyncio
    async def test_redis_error_fails_open(self):
        with (
            mock.patch(
                "app.core.rate_limiter._get_redis_client", side_effect=Exception("Redis down")
            ),
            mock.patch("app.core.rate_limiter.settings.rate_limit_enabled", True),
        ):
            req = Request({"type": "http", "headers": [], "client": ("1.1.1.1", 12345)})
            limit, remaining = await _check_limit(req)
            assert limit == 0
            assert remaining == 0

    @pytest.mark.asyncio
    async def test_custom_limit_override(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=1)

        with mock.patch("app.core.rate_limiter._get_redis_client", return_value=mock_redis):
            with mock.patch("app.core.rate_limiter.settings.rate_limit_enabled", True):
                with mock.patch("app.core.rate_limiter.settings.rate_limit_window_seconds", 60):
                    req = Request({"type": "http", "headers": [], "client": ("1.1.1.1", 12345)})
                    limit, remaining = await _check_limit(req, limit_override=5)
                    assert limit == 5


class TestRateLimitDependencies:
    @pytest.mark.asyncio
    async def test_rate_limit_general(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=1)

        with mock.patch("app.core.rate_limiter._get_redis_client", return_value=mock_redis):
            with mock.patch("app.core.rate_limiter.settings.rate_limit_enabled", True):
                req = Request({"type": "http", "headers": [], "client": ("1.1.1.1", 12345)})
                await rate_limit_general(req)

    @pytest.mark.asyncio
    async def test_rate_limit_strict(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=1)

        with mock.patch("app.core.rate_limiter._get_redis_client", return_value=mock_redis):
            with mock.patch("app.core.rate_limiter.settings.rate_limit_enabled", True):
                with mock.patch("app.core.rate_limiter.settings.rate_limit_strict_multiplier", 0.5):
                    req = Request({"type": "http", "headers": [], "client": ("1.1.1.1", 12345)})
                    await rate_limit_strict(req)

    @pytest.mark.asyncio
    async def test_rate_limit_auth(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=1)

        with mock.patch("app.core.rate_limiter._get_redis_client", return_value=mock_redis):
            with mock.patch("app.core.rate_limiter.settings.rate_limit_enabled", True):
                req = Request({"type": "http", "headers": [], "client": ("1.1.1.1", 12345)})
                await rate_limit_auth(req)

    @pytest.mark.asyncio
    async def test_rate_limit_websocket(self):
        mock_redis = mock.AsyncMock()
        mock_redis.script_load = mock.AsyncMock(return_value="sha1")
        mock_redis.evalsha = mock.AsyncMock(return_value=1)

        with mock.patch("app.core.rate_limiter._get_redis_client", return_value=mock_redis):
            with mock.patch("app.core.rate_limiter.settings.rate_limit_enabled", True):
                with mock.patch("app.core.rate_limiter.settings.rate_limit_websocket_cpm", 100):
                    req = Request({"type": "http", "headers": [], "client": ("1.1.1.1", 12345)})
                    await rate_limit_websocket(req)


class TestRateLimitExceeded:
    def test_exception_attributes(self):
        exc = RateLimitExceeded(retry_after=120, limit=100)
        assert exc.status_code == 429
        assert exc.headers["Retry-After"] == "120"
        assert exc.headers["X-RateLimit-Limit"] == "100"
