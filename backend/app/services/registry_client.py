# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded OCI/Docker Registry v2 manifest resolution.

The resolver establishes that an image reference points to a specific platform
manifest digest by reading manifests and the small image config blob. It does
not pull layers, change local images, read credential files, or create
approval.

DNS names are resolved separately for the host policy check and by httpx at
connect time. The resolver does not pin the checked address; a DNS name that
rebinds between those lookups is an accepted limitation.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import platform as host_platform
import re
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import (
    SplitResult,
    parse_qsl,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import httpx

REGISTRY_REFERENCE_INVALID = "registry_reference_invalid"
REGISTRY_UNREACHABLE = "registry_unreachable"
REGISTRY_AUTH_FAILED = "registry_auth_failed"
REGISTRY_PLATFORM_UNAVAILABLE = "platform_unavailable"
REGISTRY_ARTIFACT_MISMATCH = "artifact_mismatch"
REGISTRY_ARTIFACT_MISSING = "artifact_missing"

_ERROR_CODES = frozenset(
    {
        REGISTRY_REFERENCE_INVALID,
        REGISTRY_UNREACHABLE,
        REGISTRY_AUTH_FAILED,
        REGISTRY_PLATFORM_UNAVAILABLE,
        REGISTRY_ARTIFACT_MISMATCH,
        REGISTRY_ARTIFACT_MISSING,
    }
)

_OCI_INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
_DOCKER_INDEX_MEDIA_TYPE = "application/vnd.docker.distribution.manifest.list.v2+json"
_OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
_DOCKER_MANIFEST_MEDIA_TYPE = "application/vnd.docker.distribution.manifest.v2+json"

_INDEX_MEDIA_TYPES = frozenset({_OCI_INDEX_MEDIA_TYPE, _DOCKER_INDEX_MEDIA_TYPE})
_MANIFEST_MEDIA_TYPES = frozenset({_OCI_MANIFEST_MEDIA_TYPE, _DOCKER_MANIFEST_MEDIA_TYPE})
_MANIFEST_ACCEPT = ", ".join(
    (
        _OCI_INDEX_MEDIA_TYPE,
        _DOCKER_INDEX_MEDIA_TYPE,
        _OCI_MANIFEST_MEDIA_TYPE,
        _DOCKER_MANIFEST_MEDIA_TYPE,
    )
)
_CONFIG_ACCEPT = "application/octet-stream"

_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_CONNECT_TIMEOUT_SECONDS = 3.0
_READ_TIMEOUT_SECONDS = 10.0
_TOTAL_TIMEOUT_SECONDS = 20.0
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_TOKEN_BYTES = 1024 * 1024
_MAX_REDIRECTS = 3
_MAX_REFERENCE_CHARS = 500
_MAX_TOKEN_CHARS = 8192
_TOKEN_CACHE_LIMIT = 64
_AUTH_HOST_CACHE_LIMIT = 64
_DEFAULT_TOKEN_TTL_SECONDS = 300.0
_MAX_TOKEN_TTL_SECONDS = 300.0
_USER_AGENT = "nukelab-registry-resolver/1"

_HTTP_TIMEOUT = httpx.Timeout(
    connect=_CONNECT_TIMEOUT_SECONDS,
    read=_READ_TIMEOUT_SECONDS,
    write=_READ_TIMEOUT_SECONDS,
    pool=_CONNECT_TIMEOUT_SECONDS,
)

_HOST_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME_RE = re.compile(rf"{_HOST_LABEL}(?:\.{_HOST_LABEL})*\Z")
_PLATFORM_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}\Z")
_REPOSITORY_COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*"
_REPOSITORY_RE = re.compile(rf"{_REPOSITORY_COMPONENT}(?:/{_REPOSITORY_COMPONENT})*\Z")
_TAG_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_DIGEST_RE = re.compile(r"sha256:([A-Fa-f0-9]{64})\Z")
_AUTH_SCHEME_RE = re.compile(r"(?:^|,)\s*(Bearer|Basic)\b", re.IGNORECASE)
_AUTH_PARAM_RE = re.compile(r'([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^,\s]+))')

_DOCKER_HUB_REGISTRIES = frozenset({"docker.io", "index.docker.io", "registry-1.docker.io"})
_DOCKER_HUB_CANONICAL = "registry-1.docker.io"
_BLOCKED_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("168.63.129.16"),
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("169.254.170.2"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)


class RegistryError(Exception):
    """Stable registry resolution failure.

    ``code`` is always one of the bounded registry failure codes. Messages are
    deliberately generic: they never include credentials, tokens, response
    bodies, or the caller's reference.
    """

    def __init__(self, code: str, message: str):
        if code not in _ERROR_CODES:
            raise ValueError(f"Unsupported registry error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class RegistryReference:
    """A normalized OCI/Docker reference.

    ``registry`` is the canonical registry host (Docker Hub aliases normalize to
    ``registry-1.docker.io``). ``repository`` is the registry-relative
    repository path. ``reference`` is either a tag or a ``sha256`` digest.
    """

    registry: str
    repository: str
    reference: str
    is_digest: bool


@dataclass(frozen=True, slots=True)
class Platform:
    os: str
    architecture: str
    variant: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.os, str) or not isinstance(self.architecture, str):
            raise ValueError("Invalid image platform")
        os_name = self.os.strip().lower()
        architecture = self.architecture.strip().lower()
        if not _PLATFORM_TOKEN_RE.fullmatch(os_name) or not _PLATFORM_TOKEN_RE.fullmatch(
            architecture
        ):
            raise ValueError("Invalid image platform")
        variant = self.variant
        if variant is not None:
            if not isinstance(variant, str):
                raise ValueError("Invalid image platform")
            variant = variant.strip().lower() or None
            if variant is not None and not _PLATFORM_TOKEN_RE.fullmatch(variant):
                raise ValueError("Invalid image platform")
        object.__setattr__(self, "os", os_name)
        object.__setattr__(self, "architecture", architecture)
        object.__setattr__(self, "variant", variant)


@dataclass(frozen=True, slots=True)
class RegistryCredentials:
    """Injected credentials for a Bearer token service or Basic challenge.

    The resolver never reads credentials from disk. Callers own credential
    loading and scope the injected value to the registry being resolved.
    """

    username: str
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        for value, label, limit in (
            (self.username, "username", 1024),
            (self.password, "password", 8192),
        ):
            if not isinstance(value, str) or not value or len(value) > limit:
                raise ValueError(f"Invalid registry {label}")
            if _has_control_chars(value):
                raise ValueError(f"Invalid registry {label}")


@dataclass(frozen=True, slots=True)
class VerifiedImage:
    """Verified artifact identity returned by the resolver.

    ``requested_reference`` preserves the caller's input string so callers can
    compare it with their approved template. ``verified_reference`` is exactly
    ``<registry>/<repository>@<manifest_digest>``. Registry verification proves
    artifact retrievability and identity; it does not create or imply approval.
    """

    requested_reference: str
    verified_reference: str
    manifest_digest: str
    index_digest: str | None
    descriptor_media_type: str
    os: str
    architecture: str
    variant: str | None

    def __post_init__(self) -> None:
        if _normalize_digest(self.manifest_digest) != self.manifest_digest:
            raise ValueError("Invalid manifest digest")
        if self.index_digest is not None and (
            _normalize_digest(self.index_digest) != self.index_digest
        ):
            raise ValueError("Invalid index digest")
        if not self.verified_reference.endswith(f"@{self.manifest_digest}"):
            raise ValueError("Verified reference does not match the manifest digest")
        if len(self.verified_reference) > _MAX_REFERENCE_CHARS:
            raise ValueError("Verified reference is too long")
        if not self.requested_reference or len(self.requested_reference) > _MAX_REFERENCE_CHARS:
            raise ValueError("Invalid requested reference")
        if not self.descriptor_media_type:
            raise ValueError("Missing descriptor media type")
        if not self.os or not self.architecture:
            raise ValueError("Invalid image platform")


def parse_reference(value: str) -> RegistryReference:
    """Parse and normalize an OCI/Docker image reference.

    URLs, credential-bearing values, control characters, oversized values, and
    malformed tags or digests are rejected. Docker Hub aliases normalize to one
    registry host and a single-component Docker Hub repository gets the
    ``library/`` prefix. ``latest`` is used only when neither a tag nor a digest
    is present.
    """

    if not isinstance(value, str) or not value or len(value) > _MAX_REFERENCE_CHARS:
        raise _invalid_reference()
    if value != value.strip():
        raise _invalid_reference()
    if _has_control_chars(value):
        raise _invalid_reference()
    if "://" in value or value.startswith("//") or "\\" in value:
        raise _invalid_reference()
    if value.count("@") > 1:
        raise _invalid_reference()

    name = value
    digest: str | None = None
    if "@" in value:
        name, digest_text = value.split("@", 1)
        digest = _normalize_digest(digest_text)
        if digest is None or not name:
            raise _invalid_reference()

    name, tag = _split_tag(name)
    if digest is not None:
        if tag is not None and not _TAG_RE.fullmatch(tag):
            raise _invalid_reference()
        reference = digest
        is_digest = True
    else:
        if tag is None:
            tag = "latest"
        elif not _TAG_RE.fullmatch(tag):
            raise _invalid_reference()
        reference = tag
        is_digest = False

    parts = name.split("/")
    if any(part == "" for part in parts):
        raise _invalid_reference()
    first = parts[0]
    if len(parts) > 1 and _looks_like_registry(first):
        registry = _validate_registry(first)
        repository = "/".join(parts[1:])
    else:
        registry = _DOCKER_HUB_CANONICAL
        repository = name

    if registry == _DOCKER_HUB_CANONICAL and "/" not in repository:
        repository = f"library/{repository}"

    if not repository or len(repository) > 255 or not _REPOSITORY_RE.fullmatch(repository):
        raise _invalid_reference()

    if len(f"{registry}/{repository}@sha256:") + 64 > _MAX_REFERENCE_CHARS:
        raise _invalid_reference()
    if len(_format_reference(registry, repository, reference, is_digest)) > _MAX_REFERENCE_CHARS:
        raise _invalid_reference()

    return RegistryReference(
        registry=registry,
        repository=repository,
        reference=reference,
        is_digest=is_digest,
    )


class RegistryResolver:
    """Resolve an image reference to a verified platform manifest digest."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        credentials: RegistryCredentials | None = None,
        allowed_hosts: frozenset[str] | None = None,
        platform: Platform | None = None,
    ) -> None:
        if allowed_hosts is not None and isinstance(allowed_hosts, str):
            raise TypeError("allowed_hosts must be a collection of host names")
        self._transport = transport
        self._credentials = credentials
        self._allowed_hosts = _normalize_allowed_hosts(allowed_hosts)
        self._platform = platform
        self._token_cache: dict[_TokenKey, _CachedToken] = {}
        self._basic_hosts: dict[str, None] = {}

    async def resolve(self, reference: str) -> VerifiedImage:
        """Verify ``reference`` and return its platform manifest identity."""

        parsed = parse_reference(reference)
        try:
            async with asyncio.timeout(_TOTAL_TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=_HTTP_TIMEOUT,
                    follow_redirects=False,
                    trust_env=False,
                    headers={"User-Agent": _USER_AGENT},
                ) as client:
                    return await self._resolve(client, parsed, reference)
        except (httpx.HTTPError, httpx.InvalidURL):
            raise RegistryError(REGISTRY_UNREACHABLE, "Registry request failed.") from None
        except TimeoutError:
            raise RegistryError(REGISTRY_UNREACHABLE, "Registry verification timed out.") from None

    async def _resolve(
        self,
        client: httpx.AsyncClient,
        reference: RegistryReference,
        requested_reference: str,
    ) -> VerifiedImage:
        root_url = _manifest_url(reference.registry, reference.repository, reference.reference)
        result = await self._authorized_get(
            client,
            reference,
            root_url,
            _MANIFEST_ACCEPT,
            _MAX_MANIFEST_BYTES,
        )
        _require_ok(result)
        body_digest = _verify_body_digest(
            result,
            reference.reference if reference.is_digest else None,
        )
        document = _parse_json_object(result.body, "manifest")
        media_type = _document_media_type(document, result.headers)
        if media_type in _INDEX_MEDIA_TYPES:
            return await self._from_index(
                client,
                reference,
                requested_reference,
                document,
                body_digest,
            )
        if media_type in _MANIFEST_MEDIA_TYPES:
            return await self._from_manifest(
                client,
                reference,
                requested_reference,
                document,
                body_digest,
                media_type,
            )
        raise RegistryError(
            REGISTRY_ARTIFACT_MISMATCH,
            "Registry returned an unsupported manifest type.",
        )

    async def _from_index(
        self,
        client: httpx.AsyncClient,
        reference: RegistryReference,
        requested_reference: str,
        document: dict,
        index_digest: str,
    ) -> VerifiedImage:
        requested = self._platform or _local_platform()
        manifests = document.get("manifests")
        if not isinstance(manifests, list):
            raise RegistryError(
                REGISTRY_ARTIFACT_MISMATCH,
                "Registry returned an invalid manifest index.",
            )

        exact_matches: list[tuple[str, str | None, str | None]] = []
        fallback_matches: list[tuple[str, str | None, str | None]] = []
        for descriptor in manifests:
            if not isinstance(descriptor, dict):
                raise RegistryError(
                    REGISTRY_ARTIFACT_MISMATCH,
                    "Registry returned an invalid manifest index.",
                )
            descriptor_platform = descriptor.get("platform")
            if not isinstance(descriptor_platform, dict):
                continue
            descriptor_os = descriptor_platform.get("os")
            descriptor_architecture = descriptor_platform.get("architecture")
            if not isinstance(descriptor_os, str) or not isinstance(descriptor_architecture, str):
                continue
            descriptor_os = descriptor_os.strip().lower()
            descriptor_architecture = descriptor_architecture.strip().lower()
            if descriptor_os == "unknown" and descriptor_architecture == "unknown":
                continue
            descriptor_variant = descriptor_platform.get("variant")
            if descriptor_variant is None:
                descriptor_variant = None
            elif isinstance(descriptor_variant, str):
                descriptor_variant = descriptor_variant.strip().lower() or None
            else:
                continue
            if descriptor_os != requested.os or descriptor_architecture != requested.architecture:
                continue

            if requested.variant is None:
                if descriptor_variant is not None:
                    continue
                candidate_matches = exact_matches
            elif descriptor_variant == requested.variant:
                candidate_matches = exact_matches
            elif descriptor_variant is None:
                candidate_matches = fallback_matches
            else:
                continue

            descriptor_media_type = descriptor.get("mediaType")
            if isinstance(descriptor_media_type, str):
                descriptor_media_type = _normalize_media_type(descriptor_media_type)
                if descriptor_media_type not in _MANIFEST_MEDIA_TYPES:
                    continue
            elif descriptor_media_type is not None:
                continue

            descriptor_digest = descriptor.get("digest")
            if not isinstance(descriptor_digest, str):
                raise RegistryError(
                    REGISTRY_ARTIFACT_MISMATCH,
                    "Registry returned an invalid platform descriptor.",
                )
            normalized_digest = _normalize_digest(descriptor_digest.strip())
            if normalized_digest is None:
                raise RegistryError(
                    REGISTRY_ARTIFACT_MISMATCH,
                    "Registry returned an invalid platform descriptor.",
                )
            candidate_matches.append((normalized_digest, descriptor_media_type, descriptor_variant))

        if len(exact_matches) > 1:
            raise RegistryError(
                REGISTRY_ARTIFACT_MISMATCH,
                "Multiple manifests match the requested platform.",
            )
        if exact_matches:
            selected = exact_matches[0]
        elif requested.variant is not None and len(fallback_matches) > 1:
            raise RegistryError(
                REGISTRY_ARTIFACT_MISMATCH,
                "Multiple manifests match the requested platform.",
            )
        elif requested.variant is not None and len(fallback_matches) == 1:
            selected = fallback_matches[0]
        else:
            raise RegistryError(
                REGISTRY_PLATFORM_UNAVAILABLE,
                "No manifest matches the requested platform.",
            )

        child_digest_expected, descriptor_media_type, descriptor_variant = selected
        child_url = _manifest_url(
            reference.registry,
            reference.repository,
            child_digest_expected,
        )
        child = await self._authorized_get(
            client,
            reference,
            child_url,
            _MANIFEST_ACCEPT,
            _MAX_MANIFEST_BYTES,
        )
        _require_ok(child)
        child_digest = _verify_body_digest(child, child_digest_expected)
        child_document = _parse_json_object(child.body, "manifest")
        child_media_type = _document_media_type(child_document, child.headers)
        if child_media_type not in _MANIFEST_MEDIA_TYPES:
            raise RegistryError(
                REGISTRY_ARTIFACT_MISMATCH,
                "Platform descriptor does not reference an image manifest.",
            )
        if descriptor_media_type is not None and descriptor_media_type != child_media_type:
            raise RegistryError(
                REGISTRY_ARTIFACT_MISMATCH,
                "Platform descriptor media type does not match the manifest.",
            )
        return _verified_image(
            reference,
            requested_reference=requested_reference,
            manifest_digest=child_digest,
            index_digest=index_digest,
            media_type=child_media_type,
            platform=Platform(
                requested.os,
                requested.architecture,
                descriptor_variant,
            ),
        )

    async def _from_manifest(
        self,
        client: httpx.AsyncClient,
        reference: RegistryReference,
        requested_reference: str,
        document: dict,
        manifest_digest: str,
        media_type: str,
    ) -> VerifiedImage:
        actual_platform = await self._platform_from_config(client, reference, document)
        requested_platform = self._platform
        if requested_platform is not None:
            if (
                actual_platform.os != requested_platform.os
                or actual_platform.architecture != requested_platform.architecture
            ):
                raise _platform_unavailable()
            if (
                requested_platform.variant is not None
                and actual_platform.variant is not None
                and requested_platform.variant != actual_platform.variant
            ):
                raise _platform_unavailable()
        return _verified_image(
            reference,
            requested_reference=requested_reference,
            manifest_digest=manifest_digest,
            index_digest=None,
            media_type=media_type,
            platform=actual_platform,
        )

    async def _platform_from_config(
        self,
        client: httpx.AsyncClient,
        reference: RegistryReference,
        document: dict,
    ) -> Platform:
        config = document.get("config")
        if not isinstance(config, dict):
            raise _platform_unavailable()
        digest_value = config.get("digest")
        if not isinstance(digest_value, str):
            raise _platform_unavailable()
        config_digest = _normalize_digest(digest_value.strip())
        if config_digest is None:
            raise _platform_unavailable()
        size = config.get("size")
        if isinstance(size, int) and not isinstance(size, bool) and size > _MAX_CONFIG_BYTES:
            raise RegistryError(
                REGISTRY_ARTIFACT_MISMATCH,
                "Registry artifact exceeds the size limit.",
            )

        config_url = _blob_url(reference.registry, reference.repository, config_digest)
        result = await self._authorized_get(
            client,
            reference,
            config_url,
            _CONFIG_ACCEPT,
            _MAX_CONFIG_BYTES,
        )
        _require_ok(result)
        _verify_body_digest(result, config_digest)
        config_document = _parse_json_object(result.body, "image config")
        try:
            return Platform(
                config_document.get("os"),
                config_document.get("architecture"),
                config_document.get("variant"),
            )
        except ValueError:
            raise _platform_unavailable() from None

    async def _authorized_get(
        self,
        client: httpx.AsyncClient,
        reference: RegistryReference,
        url: str,
        accept: str,
        max_bytes: int,
    ) -> _HttpResult:
        headers = {"Accept": accept, "Accept-Encoding": "identity"}
        basic_auth = self._basic_auth_for(reference)
        token_key: _TokenKey | None = None
        cached: _CachedToken | None = None
        if basic_auth is None:
            token_key, cached = self._cached_token_for(reference)
            if cached is not None:
                headers["Authorization"] = f"Bearer {cached.token}"

        result = await self._request(
            client,
            "GET",
            url,
            headers=headers,
            auth=basic_auth,
            max_bytes=max_bytes,
            oversize_code=REGISTRY_ARTIFACT_MISMATCH,
        )
        if result.status != 401:
            return result

        challenge = _parse_auth_challenge(result.headers)
        if challenge is None:
            raise _auth_failed()

        if challenge.scheme == "basic":
            if self._credentials is None:
                raise _auth_failed()
            if basic_auth is not None:
                # Basic credentials were already sent and rejected.
                raise _auth_failed()
            self._remember_basic_host(reference)
            basic_auth = self._basic_auth()
            if basic_auth is None:
                raise _auth_failed()
            headers.pop("Authorization", None)
            result = await self._request(
                client,
                "GET",
                url,
                headers=headers,
                auth=basic_auth,
                max_bytes=max_bytes,
                oversize_code=REGISTRY_ARTIFACT_MISMATCH,
            )
            if result.status == 401:
                raise _auth_failed()
            return result

        if challenge.scheme != "bearer" or challenge.realm is None:
            raise _auth_failed()
        self._forget_basic_host(reference)
        if token_key is not None:
            self._token_cache.pop(token_key, None)
        token_key, token = await self._get_token(client, reference, challenge)
        headers["Authorization"] = f"Bearer {token.token}"
        result = await self._request(
            client,
            "GET",
            url,
            headers=headers,
            auth=None,
            max_bytes=max_bytes,
            oversize_code=REGISTRY_ARTIFACT_MISMATCH,
        )
        if result.status == 401:
            self._token_cache.pop(token_key, None)
            raise _auth_failed()
        return result

    def _basic_auth_for(self, reference: RegistryReference) -> httpx.BasicAuth | None:
        if reference.registry.lower() not in self._basic_hosts:
            return None
        return self._basic_auth()

    def _basic_auth(self) -> httpx.BasicAuth | None:
        credentials = self._credentials
        if credentials is None:
            return None
        return httpx.BasicAuth(credentials.username, credentials.password)

    def _remember_basic_host(self, reference: RegistryReference) -> None:
        key = reference.registry.lower()
        if key in self._basic_hosts:
            return
        while len(self._basic_hosts) >= _AUTH_HOST_CACHE_LIMIT:
            self._basic_hosts.pop(next(iter(self._basic_hosts)), None)
        self._basic_hosts[key] = None

    def _forget_basic_host(self, reference: RegistryReference) -> None:
        self._basic_hosts.pop(reference.registry.lower(), None)

    async def _get_token(
        self,
        client: httpx.AsyncClient,
        reference: RegistryReference,
        challenge: _AuthChallenge,
    ) -> tuple[_TokenKey, _CachedToken]:
        if challenge.scheme != "bearer" or challenge.realm is None:
            raise _auth_failed()
        realm = _validate_auth_realm(challenge.realm)
        key = _TokenKey(
            registry=reference.registry,
            repository=reference.repository,
            realm=realm,
            service=challenge.service,
            scope=challenge.scope,
        )
        now = time.monotonic()
        cached = self._token_cache.get(key)
        if cached is not None and cached.expires_at > now:
            return key, cached
        if cached is not None:
            self._token_cache.pop(key, None)

        token_url = _build_token_url(challenge, reference.repository)
        await self._check_url_host(token_url)

        credentials = self._credentials
        auth = (
            httpx.BasicAuth(credentials.username, credentials.password)
            if credentials is not None
            else None
        )
        result = await self._request(
            client,
            "GET",
            token_url,
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            auth=auth,
            max_bytes=_MAX_TOKEN_BYTES,
            oversize_code=REGISTRY_AUTH_FAILED,
        )
        if result.status in (401, 403, 404):
            raise _auth_failed()
        if result.status != 200:
            raise RegistryError(
                REGISTRY_UNREACHABLE,
                "Registry token service is unavailable.",
            )

        try:
            payload = json.loads(result.body)
        except (ValueError, RecursionError):
            raise _auth_failed() from None
        if not isinstance(payload, dict):
            raise _auth_failed()
        token_value = payload.get("token") or payload.get("access_token")
        if (
            not isinstance(token_value, str)
            or not token_value
            or len(token_value) > _MAX_TOKEN_CHARS
        ):
            raise _auth_failed()
        if any(ord(char) < 33 or ord(char) == 127 for char in token_value):
            raise _auth_failed()

        cached_token = _CachedToken(
            token=token_value,
            expires_at=time.monotonic() + _token_ttl(payload.get("expires_in")),
        )
        self._store_token(key, cached_token)
        return key, cached_token

    def _cached_token_for(
        self,
        reference: RegistryReference,
    ) -> tuple[_TokenKey | None, _CachedToken | None]:
        now = time.monotonic()
        for key, cached in list(self._token_cache.items()):
            if cached.expires_at <= now:
                self._token_cache.pop(key, None)
                continue
            if key.registry == reference.registry and key.repository == reference.repository:
                return key, cached
        return None, None

    def _store_token(self, key: _TokenKey, token: _CachedToken) -> None:
        now = time.monotonic()
        for existing_key in [
            existing_key
            for existing_key, cached in self._token_cache.items()
            if cached.expires_at <= now
        ]:
            self._token_cache.pop(existing_key, None)
        while len(self._token_cache) >= _TOKEN_CACHE_LIMIT:
            self._token_cache.pop(next(iter(self._token_cache)), None)
        self._token_cache[key] = token

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        auth: httpx.Auth | None = None,
        max_bytes: int,
        oversize_code: str,
    ) -> _HttpResult:
        current_url = url
        for _ in range(_MAX_REDIRECTS + 1):
            await self._check_url_host(current_url)
            try:
                async with client.stream(
                    method,
                    current_url,
                    headers=headers,
                    auth=auth,
                ) as response:
                    status = response.status_code
                    response_headers = response.headers
                    if status in _REDIRECT_STATUS_CODES:
                        location = response_headers.get("location")
                        if not location or _has_control_chars(location):
                            raise RegistryError(
                                REGISTRY_UNREACHABLE,
                                "Registry redirect is not permitted.",
                            )
                        next_url = urljoin(current_url, location)
                        if not _same_origin(current_url, next_url):
                            raise RegistryError(
                                REGISTRY_UNREACHABLE,
                                "Registry redirect is not permitted.",
                            )
                        current_url = next_url
                        continue
                    if status != 200:
                        return _HttpResult(status, response_headers, b"")
                    body = await _read_bounded(response, max_bytes, oversize_code)
                    return _HttpResult(status, response_headers, body)
            except httpx.TimeoutException:
                raise RegistryError(
                    REGISTRY_UNREACHABLE,
                    "Registry request timed out.",
                ) from None
            except httpx.InvalidURL:
                raise RegistryError(REGISTRY_UNREACHABLE, "Registry URL is invalid.") from None
            except httpx.HTTPError:
                raise RegistryError(REGISTRY_UNREACHABLE, "Registry request failed.") from None
        raise RegistryError(REGISTRY_UNREACHABLE, "Too many registry redirects.")

    async def _check_url_host(self, url: str) -> None:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise RegistryError(REGISTRY_UNREACHABLE, "Registry URL is invalid.") from None
        if parts.scheme.lower() != "https" or not parts.hostname:
            raise RegistryError(REGISTRY_UNREACHABLE, "Registry requests require HTTPS.")
        if parts.username is not None or parts.password is not None:
            raise RegistryError(
                REGISTRY_UNREACHABLE,
                "Registry URL credentials are not permitted.",
            )
        await self._check_host(parts.hostname, port)

    async def _check_host(self, host: str, port: int | None) -> None:
        normalized = host.strip().lower()
        if not normalized:
            raise RegistryError(REGISTRY_UNREACHABLE, "Registry host is not permitted.")
        key = _host_key(normalized, port)
        if self._allowed_hosts is not None:
            if key not in self._allowed_hosts:
                raise RegistryError(REGISTRY_UNREACHABLE, "Registry host is not permitted.")
            return

        address = _parse_ip_address(normalized)
        if address is not None:
            if not _is_public_address(address):
                raise RegistryError(REGISTRY_UNREACHABLE, "Registry host is not permitted.")
            return

        addresses = await _resolve_addresses(normalized, port)
        if not addresses or any(not _is_public_address(address) for address in addresses):
            raise RegistryError(REGISTRY_UNREACHABLE, "Registry host is not permitted.")


@dataclass(frozen=True, slots=True)
class _AuthChallenge:
    scheme: str
    realm: str | None = None
    service: str | None = None
    scope: str | None = None


@dataclass(frozen=True, slots=True)
class _HttpResult:
    status: int
    headers: httpx.Headers
    body: bytes


@dataclass(frozen=True, slots=True)
class _TokenKey:
    registry: str
    repository: str
    realm: str
    service: str | None
    scope: str | None


@dataclass(frozen=True, slots=True)
class _CachedToken:
    token: str = field(repr=False)
    expires_at: float = 0.0


def _invalid_reference() -> RegistryError:
    return RegistryError(REGISTRY_REFERENCE_INVALID, "Invalid image reference.")


def _auth_failed() -> RegistryError:
    return RegistryError(REGISTRY_AUTH_FAILED, "Registry authentication failed.")


def _platform_unavailable() -> RegistryError:
    return RegistryError(
        REGISTRY_PLATFORM_UNAVAILABLE,
        "The image platform could not be established.",
    )


def _has_control_chars(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _normalize_digest(value: str) -> str | None:
    match = _DIGEST_RE.fullmatch(value)
    if match is None:
        return None
    return f"sha256:{match.group(1).lower()}"


def _normalize_media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _format_reference(
    registry: str,
    repository: str,
    reference: str,
    is_digest: bool,
) -> str:
    separator = "@" if is_digest else ":"
    return f"{registry}/{repository}{separator}{reference}"


def _manifest_url(registry: str, repository: str, reference: str) -> str:
    return f"https://{registry}/v2/{repository}/manifests/{reference}"


def _blob_url(registry: str, repository: str, digest: str) -> str:
    return f"https://{registry}/v2/{repository}/blobs/{digest}"


def _looks_like_registry(first: str) -> bool:
    return "." in first or ":" in first or first.lower() == "localhost" or first.startswith("[")


def _looks_like_bare_registry(prefix: str, suffix: str) -> bool:
    return (
        suffix.isascii()
        and suffix.isdigit()
        and ("." in prefix or prefix.lower() == "localhost" or prefix.startswith("["))
    )


def _split_tag(name: str) -> tuple[str, str | None]:
    in_brackets = False
    last_colon = -1
    for index, char in enumerate(name):
        if char == "[":
            in_brackets = True
        elif char == "]":
            in_brackets = False
        elif char == ":" and not in_brackets:
            last_colon = index
    last_slash = name.rfind("/")
    if last_colon <= last_slash:
        return name, None
    prefix = name[:last_colon]
    suffix = name[last_colon + 1 :]
    if not prefix or not suffix:
        raise _invalid_reference()
    if "/" not in name and _looks_like_bare_registry(prefix, suffix):
        raise _invalid_reference()
    return prefix, suffix


def _parse_port(value: str) -> int:
    if not value or not value.isascii() or not value.isdigit():
        raise ValueError("Invalid registry port")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid registry port")
    return port


def _split_registry(registry: str) -> tuple[str, int | None]:
    if registry.startswith("["):
        end = registry.find("]")
        if end == -1:
            raise ValueError("Invalid registry host")
        host = registry[1:end]
        remainder = registry[end + 1 :]
        if not remainder:
            return host.lower(), None
        if not remainder.startswith(":"):
            raise ValueError("Invalid registry host")
        return host.lower(), _parse_port(remainder[1:])
    if registry.count(":") > 1:
        raise ValueError("Invalid registry host")
    if ":" in registry:
        host, port_text = registry.rsplit(":", 1)
        return host.lower(), _parse_port(port_text)
    return registry.lower(), None


def _validate_registry(registry: str) -> str:
    if not registry or len(registry) > 260:
        raise _invalid_reference()
    bracketed = registry.startswith("[")
    try:
        host, port = _split_registry(registry)
    except ValueError:
        raise _invalid_reference() from None
    if not host or len(host) > 253:
        raise _invalid_reference()

    if bracketed or ":" in host:
        try:
            address = ipaddress.IPv6Address(host)
        except ValueError:
            raise _invalid_reference() from None
        if address.ipv4_mapped is not None:
            raise _invalid_reference()
        normalized_host = f"[{host}]"
    else:
        if not _HOSTNAME_RE.fullmatch(host):
            raise _invalid_reference()
        normalized_host = host

    if port == 443:
        port = None
    if host in _DOCKER_HUB_REGISTRIES and port is None:
        return _DOCKER_HUB_CANONICAL
    if port is not None:
        normalized_host = f"{normalized_host}:{port}"
    return normalized_host


def _host_key(host: str, port: int | None) -> str:
    normalized = host.strip().lower()
    if ":" in normalized and not (normalized.startswith("[") and normalized.endswith("]")):
        normalized = f"[{normalized}]"
    if port is None or port == 443:
        return normalized
    return f"{normalized}:{port}"


def _normalize_allowed_hosts(
    allowed_hosts: frozenset[str] | None,
) -> frozenset[str] | None:
    if allowed_hosts is None:
        return None
    normalized: set[str] = set()
    for host in allowed_hosts:
        if not isinstance(host, str):
            raise TypeError("allowed_hosts entries must be strings")
        if not host.strip():
            continue
        try:
            registry = _validate_registry(host.strip())
            host_name, port = _split_registry(registry)
        except (ValueError, RegistryError):
            raise ValueError("Invalid allowed registry host") from None
        normalized.add(_host_key(host_name, port))
    return frozenset(normalized)


def _parse_ip_address(
    host: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def _is_public_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return _is_public_address(address.ipv4_mapped)
    if address in _BLOCKED_ADDRESSES:
        return False
    return (
        address.is_global
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_private
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


async def _resolve_addresses(
    host: str,
    port: int | None,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    # This lookup is separate from httpx's connection-time resolution; the
    # checked address is not pinned. See the module docstring.
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM),
            timeout=_CONNECT_TIMEOUT_SECONDS,
        )
    except OSError:
        raise RegistryError(
            REGISTRY_UNREACHABLE,
            "Registry host could not be resolved.",
        ) from None
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        raw_address = str(info[4][0]).split("%", 1)[0]
        try:
            addresses.append(ipaddress.ip_address(raw_address))
        except ValueError:
            continue
    return addresses


def _same_origin(first: str, second: str) -> bool:
    try:
        left = urlsplit(first)
        right = urlsplit(second)
        if left.scheme.lower() != "https" or right.scheme.lower() != "https":
            return False
        if (
            left.username is not None
            or left.password is not None
            or right.username is not None
            or right.password is not None
        ):
            return False
        if not left.hostname or not right.hostname:
            return False
        return left.hostname.lower() == right.hostname.lower() and _effective_port(
            left
        ) == _effective_port(right)
    except ValueError:
        return False


def _effective_port(parts: SplitResult) -> int:
    return parts.port or 443


async def _read_bounded(response: httpx.Response, limit: int, oversize_code: str) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > limit:
            raise RegistryError(oversize_code, "Registry response exceeds the size limit.")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise RegistryError(oversize_code, "Registry response exceeds the size limit.")
    return bytes(body)


def _verify_body_digest(result: _HttpResult, expected: str | None) -> str:
    actual = f"sha256:{hashlib.sha256(result.body).hexdigest()}"
    header_digest = result.headers.get("docker-content-digest")
    if header_digest is not None:
        normalized_header = _normalize_digest(header_digest.strip())
        if normalized_header is None or normalized_header != actual:
            raise RegistryError(
                REGISTRY_ARTIFACT_MISMATCH,
                "Registry artifact digest does not match.",
            )
    if expected is not None and expected != actual:
        raise RegistryError(
            REGISTRY_ARTIFACT_MISMATCH,
            "Registry artifact digest does not match.",
        )
    return actual


def _parse_json_object(body: bytes, description: str) -> dict:
    try:
        value = json.loads(body)
    except (ValueError, RecursionError):
        raise RegistryError(
            REGISTRY_ARTIFACT_MISMATCH,
            f"Registry returned an invalid {description}.",
        ) from None
    if not isinstance(value, dict):
        raise RegistryError(
            REGISTRY_ARTIFACT_MISMATCH,
            f"Registry returned an invalid {description}.",
        )
    return value


def _document_media_type(document: dict, headers: httpx.Headers) -> str:
    value = document.get("mediaType")
    if isinstance(value, str):
        normalized = _normalize_media_type(value)
        if normalized:
            return normalized
    return _normalize_media_type(headers.get("content-type", ""))


def _require_ok(result: _HttpResult) -> None:
    if result.status == 200:
        return
    if result.status in (401, 403):
        raise _auth_failed()
    if result.status in (404, 410):
        raise RegistryError(REGISTRY_ARTIFACT_MISSING, "Registry artifact is missing.")
    if result.status == 429 or 500 <= result.status < 600:
        raise RegistryError(REGISTRY_UNREACHABLE, "Registry is unavailable.")
    raise RegistryError(REGISTRY_UNREACHABLE, "Registry request failed.")


def _parse_auth_params(value: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for key, quoted, bare in _AUTH_PARAM_RE.findall(value):
        param_value = quoted if quoted is not None else bare
        if quoted is not None:
            param_value = re.sub(r"\\(.)", r"\1", param_value)
        params.setdefault(key.lower(), param_value)
    return params


def _parse_auth_challenge(headers: httpx.Headers) -> _AuthChallenge | None:
    for header in headers.get_list("www-authenticate"):
        if not isinstance(header, str):
            continue
        match = _AUTH_SCHEME_RE.search(header)
        if match is None:
            continue
        scheme = match.group(1).lower()
        if scheme == "basic":
            # A Basic realm is a display string and is not used for requests.
            return _AuthChallenge(scheme="basic")

        params = _parse_auth_params(header[match.end() :])
        realm = params.get("realm")
        if not realm:
            continue
        if len(realm) > 2048 or _has_control_chars(realm) or any(char.isspace() for char in realm):
            return None
        service = params.get("service")
        scope = params.get("scope")
        if service is not None and (len(service) > 512 or _has_control_chars(service)):
            return None
        if scope is not None and (len(scope) > 1024 or _has_control_chars(scope)):
            return None
        return _AuthChallenge(
            scheme="bearer",
            realm=realm,
            service=service or None,
            scope=scope or None,
        )
    return None


def _validate_auth_realm(realm: str) -> str:
    if (
        not realm
        or len(realm) > 2048
        or _has_control_chars(realm)
        or any(char.isspace() for char in realm)
    ):
        raise _auth_failed()
    try:
        parts = urlsplit(realm)
        _ = parts.port
    except ValueError:
        raise _auth_failed() from None
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise _auth_failed()
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise _auth_failed()
    return realm


def _build_token_url(challenge: _AuthChallenge, repository: str) -> str:
    if challenge.realm is None:
        raise _auth_failed()
    try:
        parts = urlsplit(challenge.realm)
        query = list(parse_qsl(parts.query, keep_blank_values=True))
    except ValueError:
        raise _auth_failed() from None
    if challenge.service is not None:
        query = [(key, value) for key, value in query if key != "service"]
        query.append(("service", challenge.service))
    if challenge.scope is not None:
        query = [(key, value) for key, value in query if key != "scope"]
        query.append(("scope", challenge.scope))
    if not any(key == "scope" for key, _ in query):
        query.append(("scope", f"repository:{repository}:pull"))
    return urlunsplit(
        (
            "https",
            parts.netloc,
            parts.path or "/",
            urlencode(query),
            "",
        )
    )


def _token_ttl(value: object) -> float:
    if isinstance(value, bool):
        return _DEFAULT_TOKEN_TTL_SECONDS
    if isinstance(value, (int, float)):
        seconds = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        seconds = int(value.strip())
    else:
        return _DEFAULT_TOKEN_TTL_SECONDS
    if seconds <= 0:
        return _DEFAULT_TOKEN_TTL_SECONDS
    return min(float(seconds), _MAX_TOKEN_TTL_SECONDS)


def _local_platform() -> Platform:
    system = host_platform.system().strip().lower()
    machine = host_platform.machine().strip().lower()
    os_name = {"linux": "linux", "darwin": "darwin", "windows": "windows"}.get(
        system,
        system,
    )
    architecture = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "i386": "386",
        "i686": "386",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "arm",
        "armv6l": "arm",
        "ppc64le": "ppc64le",
        "s390x": "s390x",
        "riscv64": "riscv64",
    }.get(machine, machine)
    variant = {
        "aarch64": "v8",
        "arm64": "v8",
        "armv7l": "v7",
        "armv6l": "v6",
    }.get(machine)
    try:
        return Platform(os_name, architecture, variant)
    except ValueError:
        raise RegistryError(
            REGISTRY_PLATFORM_UNAVAILABLE,
            "The local image platform could not be established.",
        ) from None


def _verified_image(
    reference: RegistryReference,
    *,
    requested_reference: str,
    manifest_digest: str,
    index_digest: str | None,
    media_type: str,
    platform: Platform,
) -> VerifiedImage:
    return VerifiedImage(
        requested_reference=requested_reference,
        verified_reference=(f"{reference.registry}/{reference.repository}@{manifest_digest}"),
        manifest_digest=manifest_digest,
        index_digest=index_digest,
        descriptor_media_type=media_type,
        os=platform.os,
        architecture=platform.architecture,
        variant=platform.variant,
    )
