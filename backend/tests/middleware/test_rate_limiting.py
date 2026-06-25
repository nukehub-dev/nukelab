"""
Rate limiting tests — HTTP middleware + WebSocket message throttling.

Uses a mock Redis to avoid requiring a real Redis server in tests.
"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.config import settings
from app.core.roles import ROLE_RATE_LIMITS as ROLE_LIMITS
from app.middleware.rate_limit import RateLimitMiddleware
from app.websocket.metrics_socket import _check_ws_message_rate_limit

# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_maintenance_mode():
    """Ensure maintenance mode is off before each rate limit test.

    test_system.py enables maintenance mode and may not reset it in all
    failure paths, which would cause our tests to get 503 instead of 429.
    """
    settings.maintenance_mode = False
    settings.rate_limit_enabled = True
    yield


# ─── Mock Redis ────────────────────────────────────────────────────────────


class MockRedis:
    """Simple async Redis mock supporting INCR, EXPIRE, EVALSHA, script_load."""

    def __init__(self):
        self._data = {}
        self._ttl = {}
        self._scripts = {}

    async def incr(self, key):
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]

    async def expire(self, key, ttl):
        self._ttl[key] = ttl
        return True

    async def script_load(self, script):
        sha = str(hash(script))
        self._scripts[sha] = script
        return sha

    async def evalsha(self, sha, numkeys, key, *args):
        # Simulate the Lua script: EXISTS → INCR → conditional EXPIRE
        exists = 1 if key in self._data else 0
        count = self._data.get(key, 0) + 1
        self._data[key] = count
        if exists == 0:
            self._ttl[key] = args[0] if args else 120
        return count

    async def close(self):
        pass


@pytest_asyncio.fixture
def mock_redis():
    """Provide a fresh MockRedis instance."""
    return MockRedis()


# ─── HTTP Middleware Tests ─────────────────────────────────────────────────


class TestRateLimitMiddleware:
    """Tests for the HTTP per-user rate limiting middleware."""

    @pytest.mark.asyncio
    async def test_exempt_paths_not_rate_limited(self, client, user_token):
        """Health checks and auth endpoints should bypass rate limiting."""
        settings.rate_limit_enabled = True

        # Health check should never be rate limited
        for _ in range(5):
            response = await client.get("/api/health")
            assert response.status_code == 200

        # Auth endpoints are exempt from our middleware (handled by slowapi).
        # Slowapi may return 429 if IP budget is exhausted by prior tests.
        for _ in range(5):
            response = await client.post("/api/auth/login", data={"username": "x", "password": "y"})
            assert response.status_code in (200, 401, 422, 429)

    @pytest.mark.asyncio
    async def test_user_tier_rate_limit(self, client, user_token, mock_redis):
        """Standard user should be limited to 120 req/min."""
        settings.rate_limit_enabled = True
        user_limit = ROLE_LIMITS["user"]

        with patch.object(RateLimitMiddleware, "_get_redis", return_value=mock_redis):
            # Fire requests up to the limit
            for _i in range(user_limit + 2):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {user_token}"},
                )

            # The last request should be rate limited (429)
            assert response.status_code == 429
            data = response.json()
            assert data["error"] == "rate_limit_exceeded"
            assert "retry_after" in data
            assert response.headers.get("Retry-After")
            assert response.headers.get("X-RateLimit-Limit") == str(user_limit)
            assert response.headers.get("X-RateLimit-Remaining") == "0"

    @pytest.mark.asyncio
    async def test_admin_tier_higher_limit(self, client, admin_token, mock_redis):
        """Admin should have a higher rate limit than standard users."""
        settings.rate_limit_enabled = True
        admin_limit = ROLE_LIMITS["admin"]
        user_limit = ROLE_LIMITS["user"]

        assert admin_limit > user_limit

        with patch.object(RateLimitMiddleware, "_get_redis", return_value=mock_redis):
            # Fire requests up to the user limit — admin should NOT be limited yet
            for _ in range(user_limit + 2):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {admin_token}"},
                )

            # Admin should still be allowed (limit is higher)
            assert response.status_code in (200, 404)  # 404 if no servers exist

    @pytest.mark.asyncio
    async def test_super_admin_tier(self, client, superadmin_token, mock_redis):
        """Super admins use the highest tier (3000/min) but are still rate-limited."""
        settings.rate_limit_enabled = True

        with patch.object(RateLimitMiddleware, "_get_redis", return_value=mock_redis):
            # Fire requests — super admin gets high limit but still has headers
            for _ in range(50):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {superadmin_token}"},
                )

            assert response.status_code in (200, 404)
            assert response.headers.get("X-RateLimit-Limit") == "3000"

    @pytest.mark.asyncio
    async def test_expired_jwt_does_not_exhaust_quota(self, client, test_user, mock_redis):
        """Expired tokens should not consume the real user's rate limit budget."""
        from datetime import UTC, datetime, timedelta

        from jose import jwt as jose_jwt

        settings.rate_limit_enabled = True

        # Create an expired token
        expired_token = jose_jwt.encode(
            {
                "sub": test_user.username,
                "role": test_user.role,
                "exp": datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        with patch.object(RateLimitMiddleware, "_get_redis", return_value=mock_redis):
            # Fire many requests with expired token
            for _ in range(50):
                response = await client.get(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {expired_token}"},
                )

            # Should get 401 (unauthorized), NOT 429 (rate limited)
            assert response.status_code == 401

            # Now use a valid token — should NOT be rate limited because
            # the expired token requests didn't count against the user's quota
            from app.api.auth import create_access_token

            valid_token = create_access_token(
                data={"sub": test_user.username, "role": test_user.role}
            )
            response = await client.get(
                "/api/servers/",
                headers={"Authorization": f"Bearer {valid_token}"},
            )
            assert response.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_rate_limit_headers_on_success(self, client, user_token, mock_redis):
        """Successful responses should include rate limit headers."""
        settings.rate_limit_enabled = True

        with patch.object(RateLimitMiddleware, "_get_redis", return_value=mock_redis):
            response = await client.get(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
            )

            assert response.status_code in (200, 404)
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers
            assert "X-RateLimit-Reset" in response.headers
            assert int(response.headers["X-RateLimit-Limit"]) == ROLE_LIMITS["user"]
            assert int(response.headers["X-RateLimit-Remaining"]) == ROLE_LIMITS["user"] - 1

    @pytest.mark.asyncio
    async def test_redis_fail_open(self, client, user_token):
        """If Redis is unavailable, traffic should continue (fail-open)."""
        settings.rate_limit_enabled = True

        with patch.object(RateLimitMiddleware, "_get_redis", side_effect=Exception("Redis down")):
            response = await client.get(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
            )

            # Should succeed despite Redis being down
            assert response.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_strict_multiplier_on_admin_endpoints(self, client, user_token, mock_redis):
        """Admin endpoints should use the strict multiplier (0.5x)."""
        settings.rate_limit_enabled = True
        strict_limit = int(ROLE_LIMITS["user"] * settings.rate_limit_strict_multiplier)

        with patch.object(RateLimitMiddleware, "_get_redis", return_value=mock_redis):
            # Fire requests to an admin endpoint up to strict limit
            for _i in range(strict_limit + 2):
                response = await client.get(
                    "/api/admin/users",
                    headers={"Authorization": f"Bearer {user_token}"},
                )

            # Should be rate limited at the strict threshold
            assert response.status_code == 429
            assert response.headers.get("X-RateLimit-Limit") == str(strict_limit)

    @pytest.mark.asyncio
    async def test_unauthenticated_fallback_ip_based(self, client, mock_redis):
        """Unauthenticated requests should fall back to IP-based limiting."""
        settings.rate_limit_enabled = True

        with patch.object(RateLimitMiddleware, "_get_redis", return_value=mock_redis):
            # Make many unauthenticated requests
            for _ in range(ROLE_LIMITS["user"] + 2):
                response = await client.get("/api/servers/")

            # Should eventually be rate limited
            assert response.status_code == 429


# ─── WebSocket Message Throttling Tests ────────────────────────────────────


class TestWebSocketRateLimiting:
    """Tests for WebSocket message-level rate throttling."""

    @pytest.mark.asyncio
    async def test_ws_message_rate_limit(self, mock_redis):
        """WS messages should be rate limited per user."""
        settings.rate_limit_enabled = True
        user_limit = ROLE_LIMITS["user"]

        # Simulate sending messages up to the limit
        exceeded = False
        for _i in range(user_limit + 2):
            is_limited, limit, remaining = await _check_ws_message_rate_limit(
                mock_redis, "testuser", "user"
            )
            if is_limited:
                exceeded = True
                break

        assert exceeded, "WebSocket message rate limit should have triggered"
        assert limit == user_limit

    @pytest.mark.asyncio
    async def test_ws_super_admin_tier(self, mock_redis):
        """Super admins use the highest WS tier (3000/min)."""
        settings.rate_limit_enabled = True

        for _ in range(200):
            is_limited, limit, remaining = await _check_ws_message_rate_limit(
                mock_redis, "superadmin", "super_admin"
            )
            assert not is_limited
            assert limit == 3000

    @pytest.mark.asyncio
    async def test_ws_redis_fail_open(self):
        """WS rate limiter should fail open when Redis is unavailable."""
        settings.rate_limit_enabled = True

        broken_redis = AsyncMock()
        broken_redis.script_load = AsyncMock(side_effect=Exception("Redis down"))

        is_limited, limit, remaining = await _check_ws_message_rate_limit(
            broken_redis, "testuser", "user"
        )
        assert not is_limited

    @pytest.mark.asyncio
    async def test_ws_different_roles_different_limits(self, mock_redis):
        """Different roles should have different WS message limits."""
        settings.rate_limit_enabled = True

        # Guest should hit limit first
        guest_exceeded_at = None
        for i in range(ROLE_LIMITS["admin"] + 5):
            is_limited, _, _ = await _check_ws_message_rate_limit(mock_redis, "guest_user", "guest")
            if is_limited and guest_exceeded_at is None:
                guest_exceeded_at = i + 1
                break

        # Admin should hit limit later
        mock_redis._data.clear()
        admin_exceeded_at = None
        for i in range(ROLE_LIMITS["admin"] + 5):
            is_limited, _, _ = await _check_ws_message_rate_limit(mock_redis, "admin_user", "admin")
            if is_limited and admin_exceeded_at is None:
                admin_exceeded_at = i + 1
                break

        assert guest_exceeded_at == ROLE_LIMITS["guest"] + 1
        assert admin_exceeded_at == ROLE_LIMITS["admin"] + 1
        assert admin_exceeded_at > guest_exceeded_at

    @pytest.mark.asyncio
    async def test_ws_rate_limit_disabled(self, mock_redis):
        """When rate limiting is disabled, no WS messages should be throttled."""
        settings.rate_limit_enabled = False

        for _ in range(500):
            is_limited, _, _ = await _check_ws_message_rate_limit(mock_redis, "testuser", "user")
            assert not is_limited

        # Restore
        settings.rate_limit_enabled = True
