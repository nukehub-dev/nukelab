"""Asymmetric EdDSA (Ed25519) signing for user access tokens.

The private key lives only on the backend. Consumers (sidecars, proxies,
future microservices) receive the public key and validate tokens locally.
"""

import base64
import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import settings

logger = logging.getLogger(__name__)


class UserAuthKeyManager:
    """Load or generate an Ed25519 key pair for signing user access tokens."""

    _private_key: str | None = None
    _public_key: str | None = None
    _key_id: str | None = None
    _public_key_raw: bytes | None = None

    @property
    def algorithm(self) -> str:
        return settings.user_auth_key_algorithm

    def _ensure_keys_exist(self) -> None:
        """Generate an Ed25519 key pair if it doesn't exist."""
        private_path = settings.user_auth_private_key_path
        public_path = settings.user_auth_public_key_path

        if not private_path or not public_path:
            raise RuntimeError(
                "USER_AUTH_PRIVATE_KEY_PATH and USER_AUTH_PUBLIC_KEY_PATH must be set"
            )

        os.makedirs(os.path.dirname(private_path) or ".", mode=0o700, exist_ok=True)

        if not os.path.exists(private_path) or not os.path.exists(public_path):
            if settings.app_env == "production":
                raise RuntimeError(
                    f"User auth keys are missing in production: {private_path}, {public_path}"
                )
            logger.info("Generating new Ed25519 key pair for user authentication")
            self._generate_key_pair(private_path, public_path)

    def _generate_key_pair(self, private_path: str, public_path: str) -> None:
        """Generate a new Ed25519 key pair and write PEM files."""
        private_key = Ed25519PrivateKey.generate()

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(private_path, "wb") as f:
            f.write(private_pem)
        os.chmod(private_path, 0o600)

        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        with open(public_path, "wb") as f:
            f.write(public_pem)
        os.chmod(public_path, 0o644)

        logger.info(f"Ed25519 key pair generated: {private_path}, {public_path}")

    def _load_private_key(self) -> str:
        if self._private_key is None:
            self._ensure_keys_exist()
            with open(settings.user_auth_private_key_path, "rb") as f:
                self._private_key = f.read().decode("utf-8")
        return self._private_key

    def _load_public_key(self) -> str:
        if self._public_key is None:
            self._ensure_keys_exist()
            with open(settings.user_auth_public_key_path, "rb") as f:
                self._public_key = f.read().decode("utf-8")
        return self._public_key

    def _load_public_key_raw(self) -> bytes:
        """Return the 32-byte raw Ed25519 public key for JWKS."""
        if self._public_key_raw is None:
            public_pem = self._load_public_key()
            public_key = serialization.load_pem_public_key(
                public_pem.encode("utf-8"), backend=default_backend()
            )
            self._public_key_raw = public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        return self._public_key_raw

    def get_key_id(self) -> str:
        """Return a stable key ID derived from the public key."""
        if self._key_id is None:
            public_pem = self._load_public_key()
            self._key_id = hashlib.sha256(public_pem.encode("utf-8")).hexdigest()[:16]
        return self._key_id

    def get_public_key_pem(self) -> str:
        return self._load_public_key()

    def get_jwks(self) -> dict[str, Any]:
        """Return a JWKS containing the current public key."""
        raw = self._load_public_key_raw()
        return {
            "keys": [
                {
                    "kty": "OKP",
                    "crv": "Ed25519",
                    "use": "sig",
                    "kid": self.get_key_id(),
                    "alg": self.algorithm,
                    "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"),
                }
            ]
        }


user_auth_key_manager = UserAuthKeyManager()


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create an EdDSA-signed access token.

    Adds issuer, audience, issued-at, expiry, JWT ID, key ID, and version claims.
    """
    to_encode = data.copy()
    now = datetime.now(UTC).replace(tzinfo=None)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))

    to_encode.update(
        {
            "iss": settings.user_auth_issuer,
            "aud": settings.user_auth_audience,
            "iat": now,
            "exp": expire,
            "jti": str(uuid.uuid4()),
            "kid": user_auth_key_manager.get_key_id(),
            "ver": "2",
        }
    )

    private_key = user_auth_key_manager._load_private_key()
    return jwt.encode(
        to_encode,
        private_key,
        algorithm=user_auth_key_manager.algorithm,
        headers={"kid": user_auth_key_manager.get_key_id()},
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify an EdDSA-signed access token.

    Raises jwt.InvalidTokenError subclasses on any validation failure.
    """
    public_key = user_auth_key_manager._load_public_key()
    return jwt.decode(
        token,
        public_key,
        algorithms=[user_auth_key_manager.algorithm],
        options={
            "require": ["exp", "iat", "sub", "iss", "aud"],
            "verify_exp": True,
            "verify_iat": True,
        },
        issuer=settings.user_auth_issuer,
        audience=settings.user_auth_audience,
    )
