"""Tests for the shared Redis client singleton."""

import pytest
from unittest import mock


class TestGetRedisClient:
    """Tests for get_redis_client singleton behavior."""

    def test_returns_same_instance_on_multiple_calls(self):
        """The singleton must return the same Redis client object."""
        from app.core.redis_client import get_redis_client, _redis_client

        # Clear any existing singleton
        from app.core import redis_client as rc_module
        original = rc_module._redis_client
        rc_module._redis_client = None

        try:
            client1 = get_redis_client()
            client2 = get_redis_client()
            assert client1 is client2
        finally:
            rc_module._redis_client = original

    def test_creates_client_with_decode_responses(self):
        """Client must be created with decode_responses=True."""
        from app.core.redis_client import get_redis_client

        with mock.patch("app.core.redis_client.redis.from_url") as mock_from_url:
            mock_client = mock.Mock()
            mock_from_url.return_value = mock_client

            # Clear singleton to force creation
            from app.core import redis_client as rc_module
            original = rc_module._redis_client
            rc_module._redis_client = None

            try:
                get_redis_client()
                mock_from_url.assert_called_once()
                call_kwargs = mock_from_url.call_args.kwargs
                assert call_kwargs.get("decode_responses") is True
            finally:
                rc_module._redis_client = original


class TestCloseRedisClient:
    """Tests for close_redis_client."""

    @pytest.mark.asyncio
    async def test_closes_and_clears_singleton(self):
        """Closing must call client.close() and null the singleton."""
        from app.core.redis_client import close_redis_client, _redis_client
        from app.core import redis_client as rc_module

        mock_client = mock.AsyncMock()
        original = rc_module._redis_client
        rc_module._redis_client = mock_client

        try:
            await close_redis_client()
            mock_client.close.assert_awaited_once()
            assert rc_module._redis_client is None
        finally:
            rc_module._redis_client = original

    @pytest.mark.asyncio
    async def test_idempotent_when_already_none(self):
        """Closing when no client exists must not raise."""
        from app.core.redis_client import close_redis_client
        from app.core import redis_client as rc_module

        original = rc_module._redis_client
        rc_module._redis_client = None

        try:
            await close_redis_client()  # should not raise
        finally:
            rc_module._redis_client = original
