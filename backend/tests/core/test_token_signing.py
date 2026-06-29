# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

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
        assert len(jwks["keys"]) >= 1
        key = jwks["keys"][0]
        assert key["kty"] == "OKP"
        assert key["crv"] == "Ed25519"
        assert key["alg"] == "EdDSA"
        assert key["kid"] == token_signing.user_auth_key_manager.get_key_id()
        assert key["use"] == "sig"
        assert key["x"]

    def test_missing_kid_rejected(self):
        # Token without a kid in the header should be rejected.
        private_key = token_signing.user_auth_key_manager._load_private_key()
        token = jwt.encode(
            {"sub": "testuser", "exp": 1893456000, "iat": 1893455900},
            private_key,
            algorithm="EdDSA",
        )
        with pytest.raises(jwt.InvalidTokenError):
            token_signing.decode_access_token(token)

    def test_unknown_kid_rejected(self, tmp_path):
        """Tokens signed by a key not present in the ring are rejected."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        # Generate an unrelated key pair.
        rogue_private = Ed25519PrivateKey.generate()
        rogue_public = rogue_private.public_key()
        rogue_public_pem = rogue_public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        rogue_kid = token_signing.user_auth_key_manager._compute_key_id(rogue_public_pem)

        token = jwt.encode(
            {"sub": "testuser"},
            rogue_private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("utf-8"),
            algorithm="EdDSA",
            headers={"kid": rogue_kid},
        )
        with pytest.raises(jwt.InvalidTokenError):
            token_signing.decode_access_token(token)


class TestKeyRingRotation:
    @pytest.fixture
    def isolated_key_manager(self, tmp_path, monkeypatch):
        """Provide a UserAuthKeyManager backed by a temp directory."""
        secrets_dir = tmp_path / "user-secrets"
        secrets_dir.mkdir()
        private_path = secrets_dir / "user-auth-private.pem"
        public_path = secrets_dir / "user-auth-public.pem"

        monkeypatch.setattr(settings, "user_auth_secrets_dir", str(secrets_dir))
        monkeypatch.setattr(settings, "user_auth_private_key_path", str(private_path))
        monkeypatch.setattr(settings, "user_auth_public_key_path", str(public_path))

        # Reset the global singleton cache so it reloads from the temp dir.
        manager = token_signing.user_auth_key_manager
        manager._active_private_key = None
        manager._active_public_pem = None
        manager._active_kid = None
        manager._key_ring = None
        manager._last_mtime = None

        yield manager

        # Restore cache after test so subsequent tests use the default keys.
        manager._active_private_key = None
        manager._active_public_pem = None
        manager._active_kid = None
        manager._key_ring = None
        manager._last_mtime = None

    def test_old_token_verifies_after_rotation(self, isolated_key_manager, tmp_path):
        """A token signed before rotation still verifies using the retired key."""
        token = token_signing.create_access_token(data={"sub": "testuser", "role": "user"})
        old_kid = isolated_key_manager.get_key_id()
        old_public_pem = isolated_key_manager.get_public_key_pem()

        # Rotate: move the active public key to a retired filename and generate new active keys.
        secrets_dir = tmp_path / "user-secrets"
        retired_path = secrets_dir / f"user-auth-public-{old_kid}.pem"
        retired_path.write_text(old_public_pem)

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        new_private = Ed25519PrivateKey.generate()
        new_private_pem = new_private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        new_public_pem = new_private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        (secrets_dir / "user-auth-private.pem").write_bytes(new_private_pem)
        (secrets_dir / "user-auth-public.pem").write_bytes(new_public_pem)

        # Force reload by clearing mtime cache.
        isolated_key_manager._last_mtime = None

        payload = token_signing.decode_access_token(token)
        assert payload["sub"] == "testuser"
        assert payload["kid"] == old_kid

        # New tokens use the new active key.
        new_token = token_signing.create_access_token(data={"sub": "newuser"})
        new_header = jwt.get_unverified_header(new_token)
        assert new_header["kid"] == isolated_key_manager.get_key_id()
        assert new_header["kid"] != old_kid

    def test_jwks_contains_multiple_keys_after_rotation(self, isolated_key_manager, tmp_path):
        """JWKS publishes both active and retired public keys."""
        # Create a retired key file.
        old_kid = isolated_key_manager.get_key_id()
        old_public_pem = isolated_key_manager.get_public_key_pem()
        secrets_dir = tmp_path / "user-secrets"
        retired_path = secrets_dir / f"user-auth-public-{old_kid}.pem"
        retired_path.write_text(old_public_pem)

        # Generate new active keys.
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        new_private = Ed25519PrivateKey.generate()
        new_private_pem = new_private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        new_public_pem = new_private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        (secrets_dir / "user-auth-private.pem").write_bytes(new_private_pem)
        (secrets_dir / "user-auth-public.pem").write_bytes(new_public_pem)

        isolated_key_manager._last_mtime = None

        jwks = isolated_key_manager.get_jwks()
        kids = {k["kid"] for k in jwks["keys"]}
        assert old_kid in kids
        assert isolated_key_manager.get_key_id() in kids
        assert len(jwks["keys"]) == 2


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


class TestVerifyAccessToken:
    @pytest.mark.asyncio
    async def test_verify_valid_token(self):
        token = token_signing.create_access_token(data={"sub": "testuser", "role": "user"})
        payload = await token_signing.verify_access_token(token)
        assert payload["sub"] == "testuser"

    @pytest.mark.asyncio
    async def test_verify_denies_revoked_jti(self, monkeypatch):
        from app.services.token_revocation_service import TokenRevokedError

        token = token_signing.create_access_token(data={"sub": "testuser"})
        jti = token_signing.decode_access_token(token)["jti"]

        async def fake_is_denied(j):
            return j == jti

        monkeypatch.setattr(
            "app.core.token_signing.token_revocation_service.is_jti_denied", fake_is_denied
        )

        with pytest.raises(TokenRevokedError):
            await token_signing.verify_access_token(token)

    @pytest.mark.asyncio
    async def test_verify_denies_user_cutoff(self, monkeypatch):
        from datetime import UTC, datetime

        from app.services.token_revocation_service import TokenRevokedError

        token = token_signing.create_access_token(data={"sub": "testuser"})

        async def fake_cutoff(sub):
            # Cutoff is in the future relative to the token's iat, so the token
            # was issued before the cutoff and should be rejected.
            return datetime.now(UTC)

        monkeypatch.setattr(
            "app.core.token_signing.token_revocation_service.get_user_revocation_cutoff",
            fake_cutoff,
        )

        with pytest.raises(TokenRevokedError):
            await token_signing.verify_access_token(token)


class TestLeeway:
    def test_leeway_allows_small_clock_skew(self):
        # Token that expired 3 seconds ago should still verify with 5s leeway.
        token = token_signing.create_access_token(
            data={"sub": "testuser"},
            expires_delta=timedelta(seconds=-3),
        )
        payload = token_signing.decode_access_token(token)
        assert payload["sub"] == "testuser"

    def test_leeway_does_not_allow_large_skew(self):
        token = token_signing.create_access_token(
            data={"sub": "testuser"},
            expires_delta=timedelta(seconds=-10),
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            token_signing.decode_access_token(token)
