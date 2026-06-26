"""Tests for app.services.token_revocation_service."""

from datetime import UTC, datetime
from unittest import mock

import pytest

from app.services.token_revocation_service import TokenRevocationService, TokenRevokedError


class FakeRedis:
    """In-memory async Redis clone sufficient for revocation tests."""

    def __init__(self):
        self._data = {}

    async def get(self, key):
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at is not None and datetime.now(UTC).timestamp() > expires_at:
            del self._data[key]
            return None
        return value

    async def setex(self, key, seconds, value):
        expires_at = datetime.now(UTC).timestamp() + seconds
        self._data[key] = (expires_at, value)

    async def close(self):
        pass


@pytest.fixture
def service():
    return TokenRevocationService(redis_client=FakeRedis())


class TestJTIDenylist:
    @pytest.mark.asyncio
    async def test_jti_not_denied_initially(self, service):
        assert await service.is_jti_denied("jti-1") is False

    @pytest.mark.asyncio
    async def test_denylist_and_check(self, service):
        await service.denylist_jti("jti-1", ttl_seconds=60)
        assert await service.is_jti_denied("jti-1") is True
        assert await service.is_jti_denied("jti-2") is False

    @pytest.mark.asyncio
    async def test_denylist_ignores_non_positive_ttl(self, service):
        await service.denylist_jti("jti-1", ttl_seconds=0)
        assert await service.is_jti_denied("jti-1") is False

        await service.denylist_jti("jti-1", ttl_seconds=-1)
        assert await service.is_jti_denied("jti-1") is False


class TestUserCutoff:
    @pytest.mark.asyncio
    async def test_no_cutoff_initially(self, service):
        assert await service.get_user_revocation_cutoff("alice") is None

    @pytest.mark.asyncio
    async def test_revoke_and_read_cutoff(self, service):
        before = datetime.now(UTC)
        await service.revoke_user_tokens("alice", ttl_seconds=120)
        cutoff = await service.get_user_revocation_cutoff("alice")
        after = datetime.now(UTC)
        assert cutoff is not None
        assert before <= cutoff <= after

    @pytest.mark.asyncio
    async def test_revoke_uses_default_ttl(self, service):
        with mock.patch("app.services.token_revocation_service.settings") as fake_settings:
            fake_settings.jwt_expire_minutes = 15
            fake_redis = FakeRedis()
            svc = TokenRevocationService(redis_client=fake_redis)
            await svc.revoke_user_tokens("bob")
            # Default TTL is 2 × JWT_EXPIRE_MINUTES in seconds.
            key = "nukelab:token:revoke:user:bob"
            expires_at, _ = fake_redis._data[key]
            expected_ttl = 15 * 2 * 60
            actual_ttl = expires_at - datetime.now(UTC).timestamp()
            assert abs(actual_ttl - expected_ttl) < 5


class TestTTL:
    @pytest.mark.asyncio
    async def test_jti_denylist_expires(self, service):
        await service.denylist_jti("jti-short", ttl_seconds=0)
        # FakeRedis expires entries on get; setex with 0 stores an already-expired key.
        assert await service.is_jti_denied("jti-short") is False

    @pytest.mark.asyncio
    async def test_user_cutoff_expires(self, service):
        await service.revoke_user_tokens("carol", ttl_seconds=0)
        assert await service.get_user_revocation_cutoff("carol") is None


class TestFailClosed:
    @pytest.mark.asyncio
    async def test_fail_closed_raises_on_redis_error(self, monkeypatch):
        broken_redis = mock.AsyncMock()
        broken_redis.get = mock.AsyncMock(side_effect=ConnectionError("Redis down"))
        service = TokenRevocationService(redis_client=broken_redis)

        monkeypatch.setattr(
            "app.services.token_revocation_service.settings.user_auth_denylist_fail_closed",
            True,
        )

        with pytest.raises(TokenRevokedError):
            await service.is_jti_denied("jti-1")

    @pytest.mark.asyncio
    async def test_fail_open_returns_false_on_redis_error(self, monkeypatch):
        broken_redis = mock.AsyncMock()
        broken_redis.get = mock.AsyncMock(side_effect=ConnectionError("Redis down"))
        service = TokenRevocationService(redis_client=broken_redis)

        monkeypatch.setattr(
            "app.services.token_revocation_service.settings.user_auth_denylist_fail_closed",
            False,
        )

        assert await service.is_jti_denied("jti-1") is False

    @pytest.mark.asyncio
    async def test_user_cutoff_returns_none_on_redis_error(self):
        broken_redis = mock.AsyncMock()
        broken_redis.get = mock.AsyncMock(side_effect=ConnectionError("Redis down"))
        service = TokenRevocationService(redis_client=broken_redis)

        # A Redis error reading the cutoff is treated as "no cutoff" so that
        # signature/expiry checks remain authoritative.
        assert await service.get_user_revocation_cutoff("dave") is None
