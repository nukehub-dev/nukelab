"""Extended tests for ServerAuthService (revocation, cleanup, stats, rate limits)."""

import pytest
import uuid
from datetime import datetime, timedelta, UTC
from jose import jwt, JWTError
from sqlalchemy import select

from app.services.server_auth_service import ServerAuthService
from app.models.server_access_token import ServerAccessToken
from app.models.server import Server
from app.config import settings


class TestServerAuthServiceRevocation:
    """Tests for token revocation."""

    @pytest.mark.asyncio
    async def test_revoke_token(self, db_session, test_user):
        """Revoking a token should mark it revoked."""
        service = ServerAuthService()
        server = Server(name="revoke-test", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        token = await service.generate_access_token(
            db=db_session, server_id=server.id, user_id=test_user.id
        )
        claims = jwt.decode(token, key="", options={"verify_signature": False, "verify_aud": False})
        jti = claims["jti"]

        result = await service.revoke_token(db_session, jti, reason="test_revoke")
        assert result is True

        is_revoked = await service.is_token_revoked(db_session, jti)
        assert is_revoked is True

    @pytest.mark.asyncio
    async def test_revoke_token_already_revoked(self, db_session, test_user):
        """Revoking an already revoked token should return False."""
        service = ServerAuthService()
        server = Server(name="revoke-dup", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        token = await service.generate_access_token(
            db=db_session, server_id=server.id, user_id=test_user.id
        )
        claims = jwt.decode(token, key="", options={"verify_signature": False, "verify_aud": False})
        jti = claims["jti"]

        await service.revoke_token(db_session, jti)
        result = await service.revoke_token(db_session, jti)
        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_token_not_found(self, db_session):
        """Revoking a non-existent token should return False."""
        service = ServerAuthService()
        result = await service.revoke_token(db_session, "nonexistent-jti")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_token_revoked_false(self, db_session, test_user):
        """Active token should not be reported as revoked."""
        service = ServerAuthService()
        server = Server(name="not-revoked", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        token = await service.generate_access_token(
            db=db_session, server_id=server.id, user_id=test_user.id
        )
        claims = jwt.decode(token, key="", options={"verify_signature": False, "verify_aud": False})
        jti = claims["jti"]

        assert await service.is_token_revoked(db_session, jti) is False

    @pytest.mark.asyncio
    async def test_revoke_server_tokens(self, db_session, test_user):
        """Revoking all tokens for a server should affect only that server."""
        service = ServerAuthService()
        server1 = Server(name="srv1", user_id=test_user.id, status="running")
        server2 = Server(name="srv2", user_id=test_user.id, status="running")
        db_session.add_all([server1, server2])
        await db_session.commit()
        await db_session.refresh(server1)
        await db_session.refresh(server2)

        await service.generate_access_token(db=db_session, server_id=server1.id, user_id=test_user.id)
        await service.generate_access_token(db=db_session, server_id=server1.id, user_id=test_user.id)
        await service.generate_access_token(db=db_session, server_id=server2.id, user_id=test_user.id)

        count = await service.revoke_server_tokens(db_session, server1.id, reason="server_stopped")
        assert count == 2

        # server2 token should still be active
        result = await db_session.execute(
            select(ServerAccessToken).where(ServerAccessToken.server_id == server2.id)
        )
        token2 = result.scalar_one()
        assert token2.revoked_at is None


class TestServerAuthServiceRateLimit:
    """Tests for token generation rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, db_session, test_user):
        """Generating too many tokens quickly should raise ValueError."""
        service = ServerAuthService()
        server = Server(name="rate-limit", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        original_limit = settings.server_auth_max_tokens_per_minute
        settings.server_auth_max_tokens_per_minute = 2
        try:
            await service.generate_access_token(db=db_session, server_id=server.id, user_id=test_user.id)
            await service.generate_access_token(db=db_session, server_id=server.id, user_id=test_user.id)
            with pytest.raises(ValueError, match="Rate limit exceeded"):
                await service.generate_access_token(db=db_session, server_id=server.id, user_id=test_user.id)
        finally:
            settings.server_auth_max_tokens_per_minute = original_limit


class TestServerAuthServiceValidation:
    """Tests for token validation edge cases."""

    @pytest.mark.asyncio
    async def test_validate_token_wrong_server(self, db_session, test_user):
        """Token validated against wrong server should raise JWTError."""
        service = ServerAuthService()
        server = Server(name="val-srv", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        token = await service.generate_access_token(
            db=db_session, server_id=server.id, user_id=test_user.id
        )

        wrong_id = uuid.uuid4()
        with pytest.raises(JWTError):
            await service.validate_token(token, expected_server_id=wrong_id)

    @pytest.mark.asyncio
    async def test_validate_token_disabled(self, db_session, test_user):
        """When auth is disabled, validate_token should raise JWTError."""
        service = ServerAuthService()
        original = settings.server_auth_enabled
        settings.server_auth_enabled = False
        try:
            with pytest.raises(JWTError, match="Server authentication is disabled"):
                await service.validate_token("dummy")
        finally:
            settings.server_auth_enabled = original


class TestServerAuthServiceCleanup:
    """Tests for expired token cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens(self, db_session, test_user):
        """Cleanup should remove expired tokens older than cutoff."""
        service = ServerAuthService()
        server = Server(name="cleanup", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        # Create an expired token manually
        old_token = ServerAccessToken(
            server_id=server.id,
            user_id=test_user.id,
            jti="old-jti-123",
            key_id="key1",
            issued_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10),
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=9),
        )
        db_session.add(old_token)
        await db_session.commit()

        count = await service.cleanup_expired_tokens(db_session, max_age_days=7)
        assert count == 1

        result = await db_session.execute(
            select(ServerAccessToken).where(ServerAccessToken.jti == "old-jti-123")
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_cleanup_no_old_tokens(self, db_session, test_user):
        """Cleanup should return 0 when no old tokens exist."""
        service = ServerAuthService()
        count = await service.cleanup_expired_tokens(db_session, max_age_days=7)
        assert count == 0


class TestServerAuthServiceStats:
    """Tests for server access statistics."""

    @pytest.mark.asyncio
    async def test_get_server_access_stats(self, db_session, test_user):
        """Stats should reflect active and recently issued tokens."""
        service = ServerAuthService()
        server = Server(name="stats", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        # Generate a token
        await service.generate_access_token(db=db_session, server_id=server.id, user_id=test_user.id)

        stats = await service.get_server_access_stats(db_session, server.id)
        assert stats["active_tokens"] == 1
        assert stats["tokens_issued_24h"] == 1
        assert stats["unique_users_24h"] == 1

    @pytest.mark.asyncio
    async def test_get_server_access_stats_empty(self, db_session):
        """Stats for server with no tokens should be zero."""
        service = ServerAuthService()
        stats = await service.get_server_access_stats(db_session, uuid.uuid4())
        assert stats["active_tokens"] == 0
        assert stats["tokens_issued_24h"] == 0
        assert stats["unique_users_24h"] == 0


class TestServerAuthServiceProperties:
    """Tests for service properties."""

    def test_is_enabled(self):
        """is_enabled should reflect settings."""
        service = ServerAuthService()
        original = settings.server_auth_enabled
        settings.server_auth_enabled = True
        assert service.is_enabled is True
        settings.server_auth_enabled = False
        assert service.is_enabled is False
        settings.server_auth_enabled = original

    def test_algorithm(self):
        """algorithm should return settings value."""
        service = ServerAuthService()
        assert service.algorithm == settings.server_auth_key_algorithm

    def test_get_key_id(self):
        """get_key_id should return a non-empty string."""
        service = ServerAuthService()
        key_id = service.get_key_id()
        assert isinstance(key_id, str)
        assert len(key_id) > 0

    def test_get_public_key_pem(self):
        """get_public_key_pem should return PEM formatted key."""
        service = ServerAuthService()
        pem = service.get_public_key_pem()
        assert "BEGIN PUBLIC KEY" in pem
        assert "END PUBLIC KEY" in pem
