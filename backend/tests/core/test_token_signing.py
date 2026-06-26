"""Tests for app.core.token_signing."""

from datetime import timedelta
from unittest import mock

import jwt
import pytest

from app.config import settings
from app.core import token_signing


class TestUserAuthKeyManager:
    def test_key_id_is_stable(self):
        kid1 = token_signing.user_auth_key_manager.get_key_id()
        kid2 = token_signing.user_auth_key_manager.get_key_id()
        assert kid1 == kid2
        assert len(kid1) == 16

    def test_public_key_pem_starts_with_header(self):
        pem = token_signing.user_auth_key_manager.get_public_key_pem()
        assert "-----BEGIN PUBLIC KEY-----" in pem

    def test_jwks_contains_valid_key(self):
        jwks = token_signing.user_auth_key_manager.get_jwks()
        assert "keys" in jwks
        assert len(jwks["keys"]) == 1
        key = jwks["keys"][0]
        assert key["kty"] == "OKP"
        assert key["crv"] == "Ed25519"
        assert key["alg"] == "EdDSA"
        assert key["kid"] == token_signing.user_auth_key_manager.get_key_id()
        assert key["use"] == "sig"
        assert key["x"]


class TestCreateAccessToken:
    def test_create_and_decode_access_token(self):
        token = token_signing.create_access_token(data={"sub": "testuser", "role": "user"})
        payload = token_signing.decode_access_token(token)
        assert payload["sub"] == "testuser"
        assert payload["role"] == "user"
        assert payload["iss"] == settings.user_auth_issuer
        assert payload["aud"] == settings.user_auth_audience
        assert payload["ver"] == "2"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload
        assert payload["kid"] == token_signing.user_auth_key_manager.get_key_id()

    def test_tampered_token_rejected(self):
        token = token_signing.create_access_token(data={"sub": "testuser"})
        tampered = token[:-5] + ("X" * 5)
        with pytest.raises(jwt.InvalidTokenError):
            token_signing.decode_access_token(tampered)

    def test_expired_token_rejected(self):
        token = token_signing.create_access_token(
            data={"sub": "testuser"},
            expires_delta=timedelta(minutes=-1),
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            token_signing.decode_access_token(token)

    def test_wrong_issuer_rejected(self):
        token = token_signing.create_access_token(data={"sub": "testuser"})
        with mock.patch.object(settings, "user_auth_issuer", "Attacker"):
            with pytest.raises(jwt.InvalidTokenError):
                token_signing.decode_access_token(token)

    def test_wrong_audience_rejected(self):
        token = token_signing.create_access_token(data={"sub": "testuser"})
        with mock.patch.object(settings, "user_auth_audience", "attacker-api"):
            with pytest.raises(jwt.InvalidTokenError):
                token_signing.decode_access_token(token)

    def test_legacy_hs256_token_rejected(self):
        legacy_token = jwt.encode(
            {"sub": "testuser", "exp": 1893456000},
            settings.jwt_secret,
            algorithm="HS256",
        )
        with pytest.raises(jwt.InvalidTokenError):
            token_signing.decode_access_token(legacy_token)
