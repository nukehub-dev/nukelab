"""Tests for server authentication service (RS256 tokens with IP binding)."""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, UTC
from jose import jwt


@pytest_asyncio.fixture
async def test_server(db_session, test_user):
    """Create a test server for auth tests."""
    from app.models.server import Server
    import uuid

    server = Server(
        id=uuid.uuid4(),
        name="test-auth-server",
        user_id=test_user.id,
        status="running",
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    yield server


class TestServerAuthTokenGeneration:
    """Tests for server access token generation."""

    @pytest.mark.asyncio
    async def test_token_includes_client_ip(self, db_session, test_user, test_server):
        """Token should include client_ip claim when provided."""
        from app.services.server_auth_service import server_auth_service

        client_ip = "192.168.1.100"

        token = await server_auth_service.generate_access_token(
            db=db_session,
            server_id=test_server.id,
            user_id=test_user.id,
            client_ip=client_ip,
            user_agent="test-agent",
            token_type="session",
        )

        # Decode token without verification to inspect claims
        claims = jwt.decode(token, key="", audience=str(test_server.id), options={"verify_signature": False})

        assert claims["sub"] == str(test_user.id)
        assert claims["aud"] == str(test_server.id)
        assert claims["client_ip"] == client_ip
        assert claims["type"] == "session"
        assert "exp" in claims
        assert "jti" in claims
        assert "kid" in claims

    @pytest.mark.asyncio
    async def test_token_omits_client_ip_when_none(self, db_session, test_user, test_server):
        """Token should not include client_ip claim when not provided."""
        from app.services.server_auth_service import server_auth_service

        token = await server_auth_service.generate_access_token(
            db=db_session,
            server_id=test_server.id,
            user_id=test_user.id,
            client_ip=None,
            token_type="session",
        )

        claims = jwt.decode(token, key="", audience=str(test_server.id), options={"verify_signature": False})

        assert "client_ip" not in claims
        assert claims["sub"] == str(test_user.id)
        assert claims["aud"] == str(test_server.id)

    @pytest.mark.asyncio
    async def test_token_includes_custom_claims(self, db_session, test_user, test_server):
        """Token should include custom claims when provided."""
        from app.services.server_auth_service import server_auth_service

        token = await server_auth_service.generate_access_token(
            db=db_session,
            server_id=test_server.id,
            user_id=test_user.id,
            client_ip="10.0.0.1",
            custom_claims={"server_name": "test-server", "env": "prod"},
        )

        claims = jwt.decode(token, key="", audience=str(test_server.id), options={"verify_signature": False})

        assert claims["client_ip"] == "10.0.0.1"
        assert claims["server_name"] == "test-server"
        assert claims["env"] == "prod"

    @pytest.mark.asyncio
    async def test_token_is_short_lived(self, db_session, test_user, test_server):
        """Token should expire within a reasonable time (default 5 minutes)."""
        from app.services.server_auth_service import server_auth_service
        from app.config import settings

        before = datetime.now(UTC).replace(tzinfo=None)

        token = await server_auth_service.generate_access_token(
            db=db_session,
            server_id=test_server.id,
            user_id=test_user.id,
            token_type="session",
        )

        claims = jwt.decode(token, key="", audience=str(test_server.id), options={"verify_signature": False})
        exp = datetime.utcfromtimestamp(claims["exp"])
        iat = datetime.utcfromtimestamp(claims["iat"])

        # Token should expire within configured TTL + small buffer
        ttl = timedelta(seconds=settings.server_auth_token_ttl)
        assert iat <= before + timedelta(seconds=5)
        assert exp <= before + ttl + timedelta(seconds=5)
        assert exp > before + ttl - timedelta(seconds=5)


class TestServerAuthTokenVerification:
    """Tests for token validation with public key (sidecar perspective)."""

    @pytest.mark.asyncio
    async def test_token_verifies_with_public_key(self, db_session, test_user, test_server):
        """Token signed by backend should verify with the public key."""
        from app.services.server_auth_service import server_auth_service
        import asyncio

        token = await server_auth_service.generate_access_token(
            db=db_session,
            server_id=test_server.id,
            user_id=test_user.id,
            client_ip="10.0.0.1",
            token_type="session",
        )

        public_key = server_auth_service.get_public_key_pem()
        from app.config import settings

        # This should not raise
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=str(test_server.id),
            issuer=settings.app_name,
        )

        assert claims["sub"] == str(test_user.id)
        assert claims["client_ip"] == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_token_fails_with_wrong_audience(self, db_session, test_user, test_server):
        """Token should fail verification with wrong audience."""
        from app.services.server_auth_service import server_auth_service
        from jose.exceptions import JWTError
        from app.config import settings

        token = await server_auth_service.generate_access_token(
            db=db_session,
            server_id=test_server.id,
            user_id=test_user.id,
            token_type="session",
        )

        public_key = server_auth_service.get_public_key_pem()

        with pytest.raises(JWTError):
            jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience="wrong-server-id",
            )

    @pytest.mark.asyncio
    async def test_token_fails_after_expiry(self, db_session, test_user, test_server):
        """Expired token should fail verification."""
        from app.services.server_auth_service import server_auth_service
        from jose.exceptions import ExpiredSignatureError
        from app.config import settings
        import asyncio

        # Temporarily set very short TTL
        original_ttl = settings.server_auth_token_ttl
        settings.server_auth_token_ttl = 1  # 1 second

        try:
            token = await server_auth_service.generate_access_token(
                db=db_session,
                server_id=test_server.id,
                user_id=test_user.id,
                token_type="session",
            )

            # Wait for expiry
            await asyncio.sleep(2)

            public_key = server_auth_service.get_public_key_pem()

            with pytest.raises(ExpiredSignatureError):
                jwt.decode(token, public_key, algorithms=["RS256"])
        finally:
            settings.server_auth_token_ttl = original_ttl
