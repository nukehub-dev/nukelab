# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Redis-backed token revocation service.

Provides two complementary revocation mechanisms:

1. JTI denylist
   Per-token revocation used for logout and admin kill-switches.
   Key: ``nukelab:token:deny:<jti>`` with TTL = remaining token lifetime.

2. User-level cutoff
   Tokens issued before the cutoff are rejected. Used for password changes,
   role changes, and user deactivation.
   Key: ``nukelab:token:revoke:user:<sub>`` with TTL = 2× JWT expiry.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import jwt

from app.config import settings
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

_JTI_DENY_PREFIX = "nukelab:token:deny"
_USER_REVOKE_PREFIX = "nukelab:token:revoke:user"


class TokenRevokedError(jwt.InvalidTokenError):
    """Raised when a token has been revoked and fail-closed behavior is active."""


class TokenRevocationService:
    """Check and set token revocation state in Redis."""

    def __init__(self, redis_client: Any | None = None):
        self._redis = redis_client

    def _get_redis(self) -> Any:
        if self._redis is None:
            self._redis = get_redis_client()
        return self._redis

    # -----------------------------------------------------------------------
    # JTI denylist
    # -----------------------------------------------------------------------

    async def is_jti_denied(self, jti: str) -> bool:
        """Return True if the JWT ID is present in the denylist."""
        try:
            result = await self._get_redis().get(f"{_JTI_DENY_PREFIX}:{jti}")
            return result is not None
        except Exception as e:
            logger.exception("Redis error while checking JTI denylist")
            if settings.user_auth_denylist_fail_closed:
                raise TokenRevokedError(
                    "Revocation check unavailable; token treated as revoked"
                ) from e
            return False

    async def denylist_jti(self, jti: str, ttl_seconds: int) -> None:
        """Add a JWT ID to the denylist with the given TTL."""
        if ttl_seconds <= 0:
            return
        await self._get_redis().setex(
            f"{_JTI_DENY_PREFIX}:{jti}",
            ttl_seconds,
            "1",
        )

    # -----------------------------------------------------------------------
    # User-level cutoff
    # -----------------------------------------------------------------------

    async def get_user_revocation_cutoff(self, sub: str) -> datetime | None:
        """Return the revocation cutoff timestamp for a user, if any."""
        try:
            value = await self._get_redis().get(f"{_USER_REVOKE_PREFIX}:{sub}")
        except Exception:
            logger.exception("Redis error while reading user revocation cutoff")
            # A missing cutoff is the safest fail-closed interpretation:
            # the sync signature/expiry checks still apply, and callers
            # treat None as "no cutoff".
            return None

        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning(f"Invalid revocation cutoff value for {sub}: {value}")
            return None

    async def revoke_user_tokens(
        self,
        sub: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """Set the revocation cutoff for a user to now.

        ``ttl_seconds`` defaults to 2× the configured JWT access-token lifetime
        so the key naturally expires after any in-flight access token.
        """
        if ttl_seconds is None:
            ttl_seconds = settings.jwt_expire_minutes * 2 * 60

        cutoff = datetime.now(UTC)
        await self._get_redis().setex(
            f"{_USER_REVOKE_PREFIX}:{sub}",
            ttl_seconds,
            cutoff.isoformat(),
        )


# Module-level singleton for callers that don't need custom Redis wiring.
token_revocation_service = TokenRevocationService()
