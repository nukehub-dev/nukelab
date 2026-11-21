# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Registry verification policy and per-registry resolver construction.

This service decides whether an image reference is verified against a registry,
returns the verified platform identity, and applies the configured fallback
policy. It does not pull layers, inspect local ``RepoDigests``, create approval,
or mutate revisions. Those steps belong to the caller's artifact/local-proof
path.

A resolver is constructed for each lookup from the current credential provider
state, so an atomic credentials-file rotation cannot leave a resolver holding
stale credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, cast

import httpx

from app.config import Settings
from app.config import settings as app_settings
from app.services.registry_client import (
    Platform,
    RegistryCredentials,
    RegistryError,
    RegistryResolver,
    VerifiedImage,
    _local_platform,
    parse_reference,
)
from app.services.registry_config import RegistryCredentialProvider, parse_allowed_hosts

RegistryVerificationPolicy = Literal["off", "prefer", "require"]
RegistryPullPolicy = Literal["on_demand", "preload_only"]
RegistryResolutionState = Literal["skipped", "verified", "fallback"]

_VERIFICATION_POLICIES = frozenset({"off", "prefer", "require"})
_PULL_POLICIES = frozenset({"on_demand", "preload_only"})


class RegistryResolverLike(Protocol):
    async def resolve(self, reference: str) -> VerifiedImage: ...


@dataclass(frozen=True, slots=True)
class RegistryResolverSpec:
    """Inputs for one per-registry resolver construction."""

    registry: str
    credentials: RegistryCredentials | None
    allowed_hosts: frozenset[str] | None
    platform: Platform | None


ResolverFactory = Callable[[RegistryResolverSpec], RegistryResolverLike]


@dataclass(frozen=True, slots=True)
class RegistryResolution:
    """Bounded registry resolution outcome without credentials or raw payloads.

    ``state`` is ``skipped`` when policy is ``off``, ``verified`` when a
    platform manifest digest was established, and ``fallback`` when ``prefer``
    recorded a stable failure code instead. ``pull_requested`` records the
    caller's request only; layer pulling is not implemented by this service.
    """

    policy: RegistryVerificationPolicy
    state: RegistryResolutionState
    verified: VerifiedImage | None
    fallback_reason: str | None
    pull_requested: bool


class RegistryImageService:
    """Apply the verification policy and resolve references through the client."""

    def __init__(
        self,
        *,
        verification_policy: str = "off",
        pull_policy: str = "on_demand",
        allowed_hosts: frozenset[str] | None = None,
        credentials: RegistryCredentialProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        platform: Platform | None = None,
        resolver_factory: ResolverFactory | None = None,
    ) -> None:
        self._verification_policy = _validate_verification_policy(verification_policy)
        self._pull_policy = _validate_pull_policy(pull_policy)
        if isinstance(allowed_hosts, str):
            raise TypeError("allowed_hosts must be a collection of normalized host names")
        self._allowed_hosts = frozenset(allowed_hosts) if allowed_hosts is not None else None
        self._credentials = credentials or RegistryCredentialProvider()
        self._transport = transport
        # None is resolved to the local platform when verification runs; policy
        # "off" never needs platform detection.
        self._platform = platform
        self._resolver_factory = resolver_factory or self._build_resolver

    @classmethod
    def from_settings(
        cls,
        settings_obj: Settings | None = None,
        *,
        credentials: RegistryCredentialProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        platform: Platform | None = None,
        resolver_factory: ResolverFactory | None = None,
    ) -> RegistryImageService:
        """Build the service from application settings.

        Construct this once per process (or per launch path) and reuse it so the
        credential file's bounded cache is effective. A malformed
        ``REGISTRY_ALLOWED_HOSTS`` value raises ``ValueError`` here.
        """
        config = settings_obj or app_settings
        return cls(
            verification_policy=config.registry_verification_policy,
            pull_policy=config.registry_pull_policy,
            allowed_hosts=parse_allowed_hosts(config.registry_allowed_hosts),
            credentials=credentials or RegistryCredentialProvider(config.registry_credentials_file),
            transport=transport,
            platform=platform,
            resolver_factory=resolver_factory,
        )

    @property
    def verification_policy(self) -> RegistryVerificationPolicy:
        return self._verification_policy

    @property
    def pull_policy(self) -> RegistryPullPolicy:
        return self._pull_policy

    async def resolve(
        self,
        reference: str,
        *,
        policy: RegistryVerificationPolicy | None = None,
        pull: bool = False,
    ) -> RegistryResolution:
        """Resolve ``reference`` under the selected verification policy.

        ``policy=None`` uses ``REGISTRY_VERIFICATION_POLICY``. ``off`` performs
        no registry I/O and returns ``skipped``. ``prefer`` converts a stable
        ``RegistryError`` into a truthful fallback without retrying. ``require``
        propagates the error. Explicit admin verification passes
        ``policy="require"`` and therefore works while the launch policy is
        ``off``.

        ``pull`` is reserved for the exact-digest local-proof path. This service
        never pulls; it only records the request in ``pull_requested``.
        """
        selected = (
            self._verification_policy if policy is None else _validate_verification_policy(policy)
        )
        pull_requested = bool(pull)

        if selected == "off":
            return RegistryResolution(
                policy="off",
                state="skipped",
                verified=None,
                fallback_reason=None,
                pull_requested=pull_requested,
            )

        try:
            parsed = parse_reference(reference)
            platform = self._platform if self._platform is not None else _local_platform()
            resolver = self._resolver_factory(
                RegistryResolverSpec(
                    registry=parsed.registry,
                    credentials=self._credentials.credentials_for(parsed.registry),
                    allowed_hosts=self._allowed_hosts,
                    platform=platform,
                )
            )
            verified = await resolver.resolve(reference)
        except RegistryError as exc:
            if selected == "prefer":
                return RegistryResolution(
                    policy="prefer",
                    state="fallback",
                    verified=None,
                    fallback_reason=exc.code,
                    pull_requested=pull_requested,
                )
            raise

        return RegistryResolution(
            policy=selected,
            state="verified",
            verified=verified,
            fallback_reason=None,
            pull_requested=pull_requested,
        )

    def _build_resolver(self, spec: RegistryResolverSpec) -> RegistryResolver:
        return RegistryResolver(
            transport=self._transport,
            credentials=spec.credentials,
            allowed_hosts=spec.allowed_hosts,
            platform=spec.platform,
        )


def _validate_verification_policy(value: str) -> RegistryVerificationPolicy:
    if value not in _VERIFICATION_POLICIES:
        raise ValueError(
            "Unsupported registry verification policy; expected off, prefer, or require."
        )
    return cast(RegistryVerificationPolicy, value)


def _validate_pull_policy(value: str) -> RegistryPullPolicy:
    if value not in _PULL_POLICIES:
        raise ValueError("Unsupported registry pull policy; expected on_demand or preload_only.")
    return cast(RegistryPullPolicy, value)
