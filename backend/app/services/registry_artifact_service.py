# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Local proof and exact-digest pulls for registry-verified artifacts.

A registry-verified artifact is usable only when the local runtime holds the
approved platform manifest digest for the same canonical repository and
platform. Local metadata alone is never treated as proof: a tag-pulled
multi-architecture image stores the index digest, not the platform digest.

When proof is absent, ``on_demand`` pulls exactly
``<repository>@sha256:<platform digest>`` under a per-digest PostgreSQL
advisory lock and re-proves the result. ``preload_only`` never pulls. Failed
or partial pulls never produce a verified identity.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from enum import Enum
from typing import Protocol, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings as app_settings
from app.container.driver import ContainerDriver, ContainerDriverError
from app.core.logging import get_logger
from app.schemas.environment_manifest import ImageIdentity
from app.services.registry_client import (
    REGISTRY_ARTIFACT_MISMATCH,
    REGISTRY_ARTIFACT_MISSING,
    REGISTRY_AUTH_FAILED,
    REGISTRY_UNREACHABLE,
    RegistryError,
    RegistryReference,
    VerifiedImage,
    parse_reference,
)
from app.services.registry_image_service import RegistryPullPolicy

logger = get_logger(__name__)

PULL_LOCK_NAMESPACE = "nukelab:registry-pull:"
PULL_LOCK_TIMEOUT_SECONDS = 600.0
PULL_LOCK_POLL_SECONDS = 0.25

_PULL_POLICIES = frozenset({"on_demand", "preload_only"})
_DIGEST_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")

_TRY_LOCK_SQL = text("SELECT pg_try_advisory_lock(:key)")
_UNLOCK_SQL = text("SELECT pg_advisory_unlock(:key)")


class DigestPullLock(Protocol):
    """Serialize pulls for one manifest digest across processes."""

    def hold(self, digest: str) -> AbstractAsyncContextManager[None]: ...


def pull_lock_key(digest: str) -> int:
    """Derive a stable signed 64-bit advisory-lock key for one digest."""
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise ValueError("Invalid manifest digest for the pull lock")
    material = f"{PULL_LOCK_NAMESPACE}{digest}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)


class PostgresDigestPullLock:
    """Hold a PostgreSQL session-level advisory lock on a dedicated connection.

    The lock always uses the direct database URL, never the PgBouncer URL:
    transaction pooling cannot guarantee session-lock affinity. The connection
    is opened outside the request session, runs in autocommit mode so no
    transaction is held across a pull, and is always closed in ``finally``.
    PostgreSQL releases a session-level lock automatically when the connection
    is lost.
    """

    def __init__(
        self,
        *,
        engine_factory: Callable[[], AsyncEngine] | None = None,
        timeout_seconds: float = PULL_LOCK_TIMEOUT_SECONDS,
        poll_interval_seconds: float = PULL_LOCK_POLL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise ValueError("Lock timing must be positive")
        self._engine_factory = engine_factory
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._clock = clock
        self._sleep = sleep

    @asynccontextmanager
    async def hold(self, digest: str) -> AsyncIterator[None]:
        key = pull_lock_key(digest)
        owns_engine = self._engine_factory is None
        engine: AsyncEngine | None = None
        connection = None
        acquired = False
        try:
            try:
                engine = self._create_engine()
                connection = await engine.connect()
                # Statement-level autocommit keeps the dedicated connection out
                # of a transaction while the pull runs. The advisory lock is
                # session-scoped, so it survives statement completion.
                connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            except Exception:
                raise _lock_unavailable() from None

            deadline = self._clock() + self._timeout_seconds
            while not acquired:
                try:
                    result = await connection.execute(_TRY_LOCK_SQL, {"key": key})
                    acquired = bool(result.scalar())
                except Exception:
                    raise _lock_unavailable() from None
                if acquired:
                    break
                if self._clock() >= deadline:
                    raise RegistryError(
                        REGISTRY_UNREACHABLE,
                        "Timed out waiting for the registry pull lock.",
                    )
                await self._sleep(self._poll_interval_seconds)

            yield
        finally:
            if connection is not None:
                if acquired:
                    try:
                        await connection.execute(_UNLOCK_SQL, {"key": key})
                    except Exception:
                        # Connection loss already released the session lock.
                        logger.warning(
                            "Registry pull lock release failed; closing the connection releases it."
                        )
                try:
                    await connection.close()
                except Exception:
                    pass
            if owns_engine and engine is not None:
                try:
                    await engine.dispose()
                except Exception:
                    pass

    def _create_engine(self) -> AsyncEngine:
        if self._engine_factory is not None:
            return self._engine_factory()
        # Direct URL on purpose: PgBouncer transaction pooling cannot preserve a
        # session-level lock. NullPool keeps the lock connection dedicated.
        return create_async_engine(
            app_settings.database_url,
            poolclass=NullPool,
            echo=False,
            connect_args={
                "command_timeout": app_settings.database_query_timeout_seconds,
            },
        )


class _LocalProof(Enum):
    VERIFIED = "verified"
    ABSENT = "absent"
    PLATFORM_MISMATCH = "platform_mismatch"


class RegistryArtifactService:
    """Prove a verified platform digest locally, or pull exactly that digest."""

    def __init__(
        self,
        *,
        driver: ContainerDriver,
        pull_policy: str | None = None,
        lock_factory: Callable[[], DigestPullLock] | None = None,
        pull_timeout_seconds: float = PULL_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        if pull_timeout_seconds <= 0:
            raise ValueError("Pull timeout must be positive")
        self._driver = driver
        self._pull_policy = _validate_pull_policy(
            app_settings.registry_pull_policy if pull_policy is None else pull_policy
        )
        self._lock_factory = lock_factory or PostgresDigestPullLock
        self._pull_timeout_seconds = pull_timeout_seconds

    @classmethod
    def from_settings(
        cls,
        driver: ContainerDriver,
        *,
        lock_factory: Callable[[], DigestPullLock] | None = None,
    ) -> RegistryArtifactService:
        return cls(
            driver=driver,
            pull_policy=app_settings.registry_pull_policy,
            lock_factory=lock_factory,
        )

    @property
    def pull_policy(self) -> RegistryPullPolicy:
        return self._pull_policy

    async def ensure_local(self, verified: VerifiedImage) -> ImageIdentity:
        """Return a verified local identity or raise a bounded registry error."""
        canonical = _canonical_reference(verified)
        local = await self._resolve(verified.verified_reference)
        proof = _prove_local(local, verified, canonical)
        if proof is _LocalProof.VERIFIED:
            return _identity_from_local(verified, local)

        if proof is _LocalProof.PLATFORM_MISMATCH and self._pull_policy == "preload_only":
            raise RegistryError(
                REGISTRY_ARTIFACT_MISMATCH,
                "The local image platform does not match the verified platform.",
            )
        if self._pull_policy == "preload_only":
            raise RegistryError(
                REGISTRY_ARTIFACT_MISSING,
                "The exact verified artifact is not available locally.",
            )

        try:
            pull_lock = self._lock_factory()
        except Exception:
            raise _lock_unavailable() from None

        async with pull_lock.hold(verified.manifest_digest):
            # Another process may have completed the exact pull while this one
            # waited for the per-digest lock.
            local = await self._resolve(verified.verified_reference)
            if _prove_local(local, verified, canonical) is _LocalProof.VERIFIED:
                return _identity_from_local(verified, local)

            try:
                async with asyncio.timeout(self._pull_timeout_seconds):
                    await self._driver.pull_image_by_digest(verified.verified_reference)
            except TimeoutError:
                raise RegistryError(
                    REGISTRY_UNREACHABLE,
                    "The verified artifact pull timed out.",
                ) from None
            except ContainerDriverError as exc:
                raise _map_pull_error(exc) from None

            local = await self._resolve_after_pull(verified.verified_reference)
            if _prove_local(local, verified, canonical) is not _LocalProof.VERIFIED:
                raise RegistryError(
                    REGISTRY_ARTIFACT_MISMATCH,
                    "The pulled artifact does not match the verified identity.",
                )
            return _identity_from_local(verified, local)

    async def _resolve(self, reference: str) -> dict | None:
        try:
            return await self._driver.resolve_image(reference)
        except ContainerDriverError:
            return None

    async def _resolve_after_pull(self, reference: str) -> dict:
        try:
            return await self._driver.resolve_image(reference)
        except ContainerDriverError:
            raise RegistryError(
                REGISTRY_ARTIFACT_MISMATCH,
                "The pulled artifact could not be resolved locally.",
            ) from None


def _validate_pull_policy(value: str) -> RegistryPullPolicy:
    if value not in _PULL_POLICIES:
        raise ValueError("Unsupported registry pull policy; expected on_demand or preload_only.")
    return cast(RegistryPullPolicy, value)


def _lock_unavailable() -> RegistryError:
    return RegistryError(REGISTRY_UNREACHABLE, "The registry pull lock is unavailable.")


def _canonical_reference(verified: VerifiedImage) -> RegistryReference:
    try:
        parsed = parse_reference(verified.verified_reference)
    except RegistryError:
        raise RegistryError(
            REGISTRY_ARTIFACT_MISMATCH,
            "The verified reference is invalid.",
        ) from None
    if not parsed.is_digest or parsed.reference != verified.manifest_digest:
        raise RegistryError(
            REGISTRY_ARTIFACT_MISMATCH,
            "The verified reference does not match the manifest digest.",
        )
    return parsed


def _prove_local(
    local: object,
    verified: VerifiedImage,
    canonical: RegistryReference,
) -> _LocalProof:
    if not isinstance(local, dict):
        return _LocalProof.ABSENT
    if not _platform_matches(local, verified):
        return _LocalProof.PLATFORM_MISMATCH
    if _has_repository_digest(local.get("repository_digests"), canonical, verified.manifest_digest):
        return _LocalProof.VERIFIED
    return _LocalProof.ABSENT


def _platform_matches(local: dict, verified: VerifiedImage) -> bool:
    local_os = local.get("os")
    local_architecture = local.get("architecture")
    if not isinstance(local_os, str) or not isinstance(local_architecture, str):
        return False
    return (
        local_os.strip().lower() == verified.os.strip().lower()
        and local_architecture.strip().lower() == verified.architecture.strip().lower()
    )


def _has_repository_digest(
    values: object,
    canonical: RegistryReference,
    manifest_digest: str,
) -> bool:
    if not isinstance(values, list):
        return False
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            candidate = parse_reference(value)
        except RegistryError:
            continue
        if not candidate.is_digest or candidate.reference != manifest_digest:
            continue
        if candidate.registry != canonical.registry or candidate.repository != canonical.repository:
            continue
        return True
    return False


def _identity_from_local(verified: VerifiedImage, local: dict) -> ImageIdentity:
    try:
        return ImageIdentity(
            requested_reference=verified.requested_reference,
            local_id=local.get("local_id"),
            repository_digests=list(local.get("repository_digests") or []),
            os=local.get("os"),
            architecture=local.get("architecture"),
            registry_verified=True,
            verified_reference=verified.verified_reference,
            manifest_digest=verified.manifest_digest,
            index_digest=verified.index_digest,
            descriptor_media_type=verified.descriptor_media_type,
            variant=verified.variant,
        )
    except ValueError:
        raise RegistryError(
            REGISTRY_ARTIFACT_MISMATCH,
            "The local artifact identity is invalid.",
        ) from None


def _map_pull_error(exc: ContainerDriverError) -> RegistryError:
    code = getattr(exc, "code", None)
    if code in (
        REGISTRY_ARTIFACT_MISMATCH,
        REGISTRY_ARTIFACT_MISSING,
        REGISTRY_AUTH_FAILED,
        REGISTRY_UNREACHABLE,
    ):
        return RegistryError(code, "The verified artifact could not be pulled.")
    if code == "image_identity_invalid" or code == "invalid_digest_reference":
        return RegistryError(REGISTRY_ARTIFACT_MISMATCH, "The pulled artifact identity is invalid.")
    status = getattr(exc, "status", None)
    if status in (404, 410):
        return RegistryError(REGISTRY_ARTIFACT_MISSING, "The verified artifact is missing.")
    if status in (401, 403):
        return RegistryError(REGISTRY_AUTH_FAILED, "The registry rejected the pull credentials.")
    return RegistryError(REGISTRY_UNREACHABLE, "The verified artifact could not be pulled.")
