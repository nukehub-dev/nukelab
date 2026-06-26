"""Asymmetric EdDSA (Ed25519) signing for user access tokens.

The private key lives only on the backend. Consumers (sidecars, proxies,
future microservices) receive the public key and validate tokens locally.

The key manager supports a small key ring so that active-key rotation is
zero-downtime: recently-retired public keys remain available for verification
until their grace period expires.
"""

import base64
import glob
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
from app.services.token_revocation_service import TokenRevokedError, token_revocation_service

logger = logging.getLogger(__name__)


class UserAuthKeyManager:
    """Load or generate an Ed25519 key ring for signing user access tokens."""

    _active_private_key: str | None = None
    _active_public_pem: str | None = None
    _active_kid: str | None = None
    _key_ring: dict[str, str] | None = None
    _last_mtime: float | None = None

    @property
    def algorithm(self) -> str:
        return settings.user_auth_key_algorithm

    @property
    def _private_path(self) -> str:
        return settings.user_auth_private_key_path

    @property
    def _public_path(self) -> str:
        return settings.user_auth_public_key_path

    @property
    def _secrets_dir(self) -> str:
        return settings.user_auth_secrets_dir

    def _ensure_keys_exist(self) -> None:
        """Generate an Ed25519 key pair if it doesn't exist."""
        private_path = self._private_path
        public_path = self._public_path

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

    @staticmethod
    def _compute_key_id(public_pem: str) -> str:
        """Return a stable key ID derived from the public key PEM."""
        return hashlib.sha256(public_pem.encode("utf-8")).hexdigest()[:16]

    def _reload_if_changed(self) -> None:
        """Rescan the secrets directory when the active private key file changes."""
        private_path = self._private_path
        self._ensure_keys_exist()

        try:
            mtime = os.stat(private_path).st_mtime
        except FileNotFoundError:
            # Key was removed/rotated underneath us; force regeneration in dev
            # or raise in production (already validated by config).
            self._last_mtime = None
            self._ensure_keys_exist()
            mtime = os.stat(private_path).st_mtime

        if self._last_mtime == mtime and self._key_ring is not None:
            return

        with open(private_path, "rb") as f:
            self._active_private_key = f.read().decode("utf-8")

        with open(self._public_path, "rb") as f:
            self._active_public_pem = f.read().decode("utf-8")

        self._active_kid = self._compute_key_id(self._active_public_pem)

        ring: dict[str, str] = {self._active_kid: self._active_public_pem}

        # Load retired verification-only public keys.
        retired_pattern = os.path.join(self._secrets_dir, "user-auth-public-*.pem")
        for retired_path in glob.glob(retired_pattern):
            try:
                with open(retired_path, "rb") as f:
                    retired_pem = f.read().decode("utf-8")
                kid = self._compute_key_id(retired_pem)
                ring[kid] = retired_pem
            except Exception:
                logger.warning(f"Failed to load retired public key: {retired_path}")

        self._key_ring = ring
        self._last_mtime = mtime

        logger.debug(
            f"Loaded user auth key ring with {len(ring)} key(s); active kid={self._active_kid}"
        )

    def _load_private_key(self) -> str:
        self._reload_if_changed()
        return self._active_private_key  # type: ignore[return-value]

    def get_key_id(self) -> str:
        """Return the active signing key ID."""
        self._reload_if_changed()
        return self._active_kid  # type: ignore[return-value]

    def get_public_key_pem(self) -> str:
        """Return the active public key PEM."""
        self._reload_if_changed()
        return self._active_public_pem  # type: ignore[return-value]

    def get_public_key_pem_for_kid(self, kid: str) -> str | None:
        """Return the public key PEM for a given key ID, if present in the ring."""
        self._reload_if_changed()
        return self._key_ring.get(kid) if self._key_ring else None

    @property
    def key_ring(self) -> dict[str, str]:
        """Return the full map of kid -> public PEM."""
        self._reload_if_changed()
        return self._key_ring.copy()  # type: ignore[return-value]

    def _public_key_raw(self, public_pem: str) -> bytes:
        """Return the 32-byte raw Ed25519 public key for JWKS."""
        public_key = serialization.load_pem_public_key(
            public_pem.encode("utf-8"), backend=default_backend()
        )
        return public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def get_jwks(self) -> dict[str, Any]:
        """Return a JWKS containing all public keys in the ring."""
        keys = []
        for kid, public_pem in self.key_ring.items():
            raw = self._public_key_raw(public_pem)
            keys.append(
                {
                    "kty": "OKP",
                    "crv": "Ed25519",
                    "use": "sig",
                    "kid": kid,
                    "alg": self.algorithm,
                    "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"),
                }
            )
        return {"keys": keys}


user_auth_key_manager = UserAuthKeyManager()


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create an EdDSA-signed access token.

    Adds issuer, audience, issued-at, expiry, JWT ID, key ID, and version claims.
    """
    to_encode = data.copy()
    now = datetime.now(UTC).replace(tzinfo=None)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))

    kid = user_auth_key_manager.get_key_id()
    to_encode.update(
        {
            "iss": settings.user_auth_issuer,
            "aud": settings.user_auth_audience,
            "iat": now,
            "exp": expire,
            "jti": str(uuid.uuid4()),
            "kid": kid,
            "ver": "2",
        }
    )

    private_key = user_auth_key_manager._load_private_key()
    return jwt.encode(
        to_encode,
        private_key,
        algorithm=user_auth_key_manager.algorithm,
        headers={"kid": kid},
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify an EdDSA-signed access token.

    Selects the verification key from the key ring based on the JWT header's
    ``kid`` claim. Raises jwt.InvalidTokenError subclasses on any validation
    failure.
    """
    unverified_header = jwt.get_unverified_header(token)
    if not unverified_header:
        raise jwt.InvalidTokenError("Token missing header")

    kid = unverified_header.get("kid")
    if not kid:
        raise jwt.InvalidTokenError("Token missing kid header")

    public_pem = user_auth_key_manager.get_public_key_pem_for_kid(kid)
    if not public_pem:
        raise jwt.InvalidTokenError(f"Unknown key id: {kid}")

    return jwt.decode(
        token,
        public_pem,
        algorithms=[user_auth_key_manager.algorithm],
        options={
            "require": ["exp", "iat", "sub", "iss", "aud", "jti"],
            "verify_exp": True,
            "verify_iat": True,
        },
        issuer=settings.user_auth_issuer,
        audience=settings.user_auth_audience,
        leeway=settings.user_auth_leeway_seconds,
    )


async def verify_access_token(token: str) -> dict[str, Any]:
    """Decode and verify an EdDSA-signed access token, including revocation checks.

    This is the production entry point. It validates the signature and claims
    synchronously, then checks Redis-backed JTI and user-level revocation.

    Raises:
        jwt.InvalidTokenError: if the token is malformed, expired, or missing claims.
        TokenRevokedError: if the token or user has been revoked and fail-closed
            behavior is enabled.
    """
    payload = decode_access_token(token)

    jti = payload.get("jti")
    sub = payload.get("sub")
    iat = payload.get("iat")
    if not jti or not sub or not iat:
        raise jwt.InvalidTokenError("Token missing jti, sub, or iat")

    if await token_revocation_service.is_jti_denied(jti):
        raise TokenRevokedError("Token has been revoked")

    cutoff = await token_revocation_service.get_user_revocation_cutoff(sub)
    if cutoff is not None:
        # ``iat`` is a timezone-naive UTC datetime in tokens produced by
        # ``create_access_token``. ``cutoff`` is also timezone-naive UTC.
        if isinstance(iat, (int, float)):
            iat_dt = datetime.fromtimestamp(iat, tz=UTC).replace(tzinfo=None)
        else:
            iat_dt = iat
        if iat_dt <= cutoff.replace(tzinfo=None):
            raise TokenRevokedError("User tokens have been revoked")

    return payload
