"""Tests for the Redis caching utility."""

import asyncio
import pytest
from unittest import mock


@pytest.fixture
def mock_redis():
    """Provide a mock Redis client and patch get_redis_client."""
    client = mock.AsyncMock()
    with mock.patch("app.core.cache.get_redis_client", return_value=client):
        yield client


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset the circuit breaker to closed state before each test."""
    from app.core.cache import _circuit_breaker
    _circuit_breaker._state = "closed"
    _circuit_breaker._failures = 0
    _circuit_breaker._last_failure_time = 0


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    """Tests that serialize/deserialize round-trip correctly."""

    def test_round_trip_dict(self):
        from app.core.cache import _serialize, _deserialize
        original = {"foo": "bar", "count": 42, "active": True}
        data = _serialize(original)
        assert isinstance(data, str)
        restored = _deserialize(data)
        assert restored == original

    def test_round_trip_list(self):
        from app.core.cache import _serialize, _deserialize
        original = [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}]
        data = _serialize(original)
        restored = _deserialize(data)
        assert restored == original

    def test_round_trip_nested(self):
        from app.core.cache import _serialize, _deserialize
        original = {"servers": [{"id": "s1", "tags": ["web", "prod"]}], "meta": {"page": 1}}
        data = _serialize(original)
        restored = _deserialize(data)
        assert restored == original


# ---------------------------------------------------------------------------
# Basic primitives
# ---------------------------------------------------------------------------

class TestCacheGet:
    """Tests for cache_get."""

    @pytest.mark.asyncio
    async def test_returns_none_on_miss(self, mock_redis):
        from app.core.cache import cache_get
        mock_redis.get.return_value = None
        result = await cache_get("test-key")
        assert result is None
        mock_redis.get.assert_awaited_once_with("nukelab:cache:test-key")

    @pytest.mark.asyncio
    async def test_returns_deserialized_value_on_hit(self, mock_redis):
        from app.core.cache import cache_get, _serialize
        mock_redis.get.return_value = _serialize({"foo": "bar"})
        result = await cache_get("test-key")
        assert result == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_deletes_corrupted_entry(self, mock_redis):
        from app.core.cache import cache_get
        mock_redis.get.return_value = "not-valid-data"
        result = await cache_get("test-key")
        assert result is None
        mock_redis.delete.assert_awaited_once_with("nukelab:cache:test-key")

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_error(self, mock_redis):
        """Fail-safe: Redis errors are treated as cache misses."""
        from app.core.cache import cache_get
        mock_redis.get.side_effect = ConnectionError("Redis down")
        result = await cache_get("test-key")
        assert result is None


class TestCacheSet:
    """Tests for cache_set."""

    @pytest.mark.asyncio
    async def test_stores_serialized_value_with_ttl(self, mock_redis):
        from app.core.cache import cache_set, _serialize
        await cache_set("test-key", {"foo": "bar"}, ttl=60)
        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        assert call_args.args[0] == "nukelab:cache:test-key"
        # Value should be a serialized string that round-trips correctly
        from app.core.cache import _deserialize
        assert _deserialize(call_args.args[1]) == {"foo": "bar"}
        assert call_args.kwargs == {"ex": 60}

    @pytest.mark.asyncio
    async def test_silently_ignores_redis_error(self, mock_redis):
        """Fail-safe: Redis errors during set are logged, not raised."""
        from app.core.cache import cache_set
        mock_redis.set.side_effect = ConnectionError("Redis down")
        # Should not raise
        await cache_set("test-key", {"foo": "bar"}, ttl=60)


class TestCacheDelete:
    """Tests for cache_delete."""

    @pytest.mark.asyncio
    async def test_deletes_key(self, mock_redis):
        from app.core.cache import cache_delete
        await cache_delete("test-key")
        mock_redis.delete.assert_awaited_once_with("nukelab:cache:test-key")

    @pytest.mark.asyncio
    async def test_silently_ignores_redis_error(self, mock_redis):
        from app.core.cache import cache_delete
        mock_redis.delete.side_effect = ConnectionError("Redis down")
        await cache_delete("test-key")


class TestCacheDeleteMulti:
    """Tests for cache_delete_multi."""

    @pytest.mark.asyncio
    async def test_deletes_multiple_keys(self, mock_redis):
        from app.core.cache import cache_delete_multi
        count = await cache_delete_multi(["a", "b", "c"])
        mock_redis.delete.assert_awaited_once_with(
            "nukelab:cache:a", "nukelab:cache:b", "nukelab:cache:c"
        )
        assert count == mock_redis.delete.return_value

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_list(self, mock_redis):
        from app.core.cache import cache_delete_multi
        count = await cache_delete_multi([])
        assert count == 0
        mock_redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_silently_ignores_redis_error(self, mock_redis):
        from app.core.cache import cache_delete_multi
        mock_redis.delete.side_effect = ConnectionError("Redis down")
        count = await cache_delete_multi(["a", "b"])
        assert count == 0


class TestCacheDeletePattern:
    """Tests for cache_delete_pattern."""

    @pytest.mark.asyncio
    async def test_deletes_matching_keys(self, mock_redis):
        from app.core.cache import cache_delete_pattern

        async def _scan_iter(*args, **kwargs):
            for item in ["nukelab:cache:a:1", "nukelab:cache:a:2"]:
                yield item

        mock_redis.scan_iter = _scan_iter
        count = await cache_delete_pattern("a:*")
        assert count == 2
        mock_redis.delete.assert_awaited_once_with(
            "nukelab:cache:a:1", "nukelab:cache:a:2"
        )

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_matches(self, mock_redis):
        from app.core.cache import cache_delete_pattern

        async def _scan_iter(*args, **kwargs):
            return
            yield  # make it an async generator

        mock_redis.scan_iter = _scan_iter
        count = await cache_delete_pattern("nomatch:*")
        assert count == 0
        mock_redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_silently_ignores_redis_error(self, mock_redis):
        from app.core.cache import cache_delete_pattern
        mock_redis.scan_iter.side_effect = ConnectionError("Redis down")
        count = await cache_delete_pattern("a:*")
        assert count == 0


# ---------------------------------------------------------------------------
# Stampede-protected get-or-set
# ---------------------------------------------------------------------------

class TestCacheGetOrSet:
    """Tests for cache_get_or_set."""

    @pytest.mark.asyncio
    async def test_returns_cached_value_on_hit(self, mock_redis):
        from app.core.cache import cache_get_or_set, _serialize
        mock_redis.get.return_value = _serialize({"cached": True})
        builder = mock.AsyncMock(return_value={"fresh": True})

        result = await cache_get_or_set("key", builder, ttl=60)
        assert result == {"cached": True}
        builder.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_builds_and_caches_on_miss(self, mock_redis):
        from app.core.cache import cache_get_or_set
        mock_redis.get.return_value = None
        mock_redis.set.return_value = True  # lock acquired
        builder = mock.AsyncMock(return_value={"fresh": True})

        result = await cache_get_or_set("key", builder, ttl=60)
        assert result == {"fresh": True}
        builder.assert_awaited_once()
        # Lock released
        mock_redis.delete.assert_awaited_with("nukelab:cache:key:lock")

    @pytest.mark.asyncio
    async def test_waits_for_lock_holder_when_cache_empty(self, mock_redis):
        from app.core.cache import cache_get_or_set, _serialize
        # First call: miss, lock not acquired (someone else has it)
        # Second call after retry: hit
        mock_redis.get.side_effect = [None, _serialize({"cached": True})]
        mock_redis.set.return_value = None  # lock not acquired
        builder = mock.AsyncMock(return_value={"fresh": True})

        result = await cache_get_or_set("key", builder, ttl=60)
        assert result == {"cached": True}
        # Builder should not be called because cache populated during wait
        builder.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_builder_when_lock_holder_slow(self, mock_redis):
        from app.core.cache import cache_get_or_set
        # Always miss, never acquire lock
        mock_redis.get.return_value = None
        mock_redis.set.return_value = None
        builder = mock.AsyncMock(return_value={"fallback": True})

        result = await cache_get_or_set("key", builder, ttl=60)
        assert result == {"fallback": True}
        builder.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lock_released_even_if_builder_raises(self, mock_redis):
        from app.core.cache import cache_get_or_set
        mock_redis.get.return_value = None
        mock_redis.set.return_value = True
        builder = mock.AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            await cache_get_or_set("key", builder, ttl=60)

        mock_redis.delete.assert_awaited_with("nukelab:cache:key:lock")

    @pytest.mark.asyncio
    async def test_graceful_when_lock_acquisition_fails(self, mock_redis):
        from app.core.cache import cache_get_or_set
        mock_redis.get.return_value = None
        mock_redis.set.side_effect = ConnectionError("Redis down")
        builder = mock.AsyncMock(return_value={"direct": True})

        result = await cache_get_or_set("key", builder, ttl=60)
        assert result == {"direct": True}
        builder.assert_awaited_once()


# ---------------------------------------------------------------------------
# SET-based invalidation
# ---------------------------------------------------------------------------

class TestCacheTrackKey:
    """Tests for cache_track_key."""

    @pytest.mark.asyncio
    async def test_adds_key_to_set(self, mock_redis):
        from app.core.cache import cache_track_key
        await cache_track_key("my:set", "member-key")
        mock_redis.sadd.assert_awaited_once_with(
            "nukelab:cache:my:set", "member-key"
        )

    @pytest.mark.asyncio
    async def test_silently_ignores_redis_error(self, mock_redis):
        from app.core.cache import cache_track_key
        mock_redis.sadd.side_effect = ConnectionError("Redis down")
        await cache_track_key("my:set", "member-key")


class TestCacheDeleteTracked:
    """Tests for cache_delete_tracked."""

    @pytest.mark.asyncio
    async def test_deletes_tracked_keys_and_set(self, mock_redis):
        from app.core.cache import cache_delete_tracked
        mock_redis.smembers.return_value = {"a", "b"}
        count = await cache_delete_tracked("my:set")
        assert count == 2
        assert mock_redis.delete.await_count == 2
        call_args = [call.args for call in mock_redis.delete.await_args_list]
        member_call = [c for c in call_args if len(c) > 1][0]
        set_call = [c for c in call_args if len(c) == 1][0]
        assert set(member_call) == {"nukelab:cache:a", "nukelab:cache:b"}
        assert set_call == ("nukelab:cache:my:set",)

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_set(self, mock_redis):
        from app.core.cache import cache_delete_tracked
        mock_redis.smembers.return_value = set()
        count = await cache_delete_tracked("my:set")
        assert count == 0
        # Should still delete the empty set
        mock_redis.delete.assert_awaited_with("nukelab:cache:my:set")

    @pytest.mark.asyncio
    async def test_silently_ignores_redis_error(self, mock_redis):
        from app.core.cache import cache_delete_tracked
        mock_redis.smembers.side_effect = ConnectionError("Redis down")
        count = await cache_delete_tracked("my:set")
        assert count == 0


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """Tests for the cache circuit breaker."""

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold_failures(self, mock_redis):
        from app.core.cache import cache_get, _circuit_breaker
        mock_redis.get.side_effect = ConnectionError("Redis down")

        # First 5 calls should all attempt Redis
        for _ in range(5):
            await cache_get("key")

        assert _circuit_breaker._state == "open"
        assert _circuit_breaker._failures == 5

    @pytest.mark.asyncio
    async def test_circuit_skips_redis_when_open(self, mock_redis):
        from app.core.cache import cache_get, _circuit_breaker
        # Force circuit open
        _circuit_breaker._state = "open"
        _circuit_breaker._last_failure_time = asyncio.get_event_loop().time()

        result = await cache_get("key")
        assert result is None
        # Redis should not have been called
        mock_redis.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_circuit_closes_after_recovery_timeout(self, mock_redis):
        from app.core.cache import cache_get, _circuit_breaker
        _circuit_breaker._state = "open"
        _circuit_breaker._last_failure_time = asyncio.get_event_loop().time() - 31
        _circuit_breaker._failures = 10

        mock_redis.get.return_value = None
        await cache_get("key")

        # Should have transitioned to half-open and attempted the call
        mock_redis.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_circuit_resets_on_success(self, mock_redis):
        from app.core.cache import cache_get, _circuit_breaker
        # Start with some failures
        _circuit_breaker._failures = 3
        mock_redis.get.return_value = None

        await cache_get("key")

        assert _circuit_breaker._state == "closed"
        assert _circuit_breaker._failures == 0
