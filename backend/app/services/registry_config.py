# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Registry verification configuration helpers.

The allowed-host parser normalizes entries through the registry client so the
resolver and the operator-facing allowlist use one host format. The resolver
applies that allowlist to both registry hosts and token-service realms, so an
installation whose token endpoint lives on a different host must list that host
as well.

Credentials come only from an optional Docker ``config.json``-compatible file.
External credential helpers (``credsStore``/``credHelpers``) are deliberately
not supported: they are reported as a bounded limitation and never invoked.
Passwords and tokens are never included in errors, reprs, or status metadata.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.services.registry_client import (
    RegistryCredentials,
    _normalize_allowed_hosts,
)

CREDENTIAL_HELPERS_UNSUPPORTED = "credential_helpers_unsupported"
CREDENTIALS_FILE_MALFORMED = "credentials_file_malformed"
CREDENTIALS_FILE_UNREADABLE = "credentials_file_unreadable"

CREDENTIALS_CACHE_SECONDS = 60.0

_MAX_CREDENTIALS_FILE_BYTES = 1024 * 1024
_MAX_AUTH_ENTRIES = 1024
_MAX_REGISTRY_KEY_CHARS = 2048
_MAX_AUTH_FIELD_CHARS = 16384
_MAX_DECODED_AUTH_BYTES = 8192


@dataclass(frozen=True, slots=True)
class RegistryCredentialStatus:
    """Bounded credential-file metadata without host names or secret values."""

    file_configured: bool
    file_present: bool
    credential_count: int
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CredentialSnapshot:
    file_present: bool
    auths: dict[str, RegistryCredentials] = field(repr=False)
    limitations: tuple[str, ...]
    signature: tuple[int, int, int] | None
    expires_at: float


class RegistryCredentialProvider:
    """Read registry credentials from a Docker ``config.json``-compatible file.

    An empty path, a missing file, an empty file, or an unreadable file yields
    anonymous resolution rather than a launch failure. The file is re-read as
    soon as its identity changes (mtime/inode/size) and at least once every
    60 seconds. Atomic file replacement is the intended rotation procedure.

    Credentials are scoped by canonical registry host. A file that contains
    credentials for one registry never returns them for another registry.
    """

    def __init__(
        self,
        credentials_file: str = "",
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(credentials_file, str):
            raise TypeError("credentials_file must be a string path")
        self._credentials_file = credentials_file.strip()
        self._path = Path(self._credentials_file) if self._credentials_file else None
        self._clock = clock
        self._lock = threading.Lock()
        self._snapshot: _CredentialSnapshot | None = None

    def __repr__(self) -> str:
        return f"RegistryCredentialProvider(credentials_file={self._credentials_file!r})"

    def credentials_for(self, registry: str) -> RegistryCredentials | None:
        """Return credentials for exactly ``registry`` or ``None``."""
        path = self._path
        if path is None:
            return None
        normalized = _normalize_registry_key(registry)
        if normalized is None:
            return None
        snapshot = self._current_snapshot(path)
        return snapshot.auths.get(normalized)

    def status(self) -> RegistryCredentialStatus:
        """Return bounded metadata for the last observed file state."""
        with self._lock:
            snapshot = self._snapshot
            return RegistryCredentialStatus(
                file_configured=self._path is not None,
                file_present=snapshot.file_present if snapshot is not None else False,
                credential_count=len(snapshot.auths) if snapshot is not None else 0,
                limitations=snapshot.limitations if snapshot is not None else (),
            )

    def _current_snapshot(self, path: Path) -> _CredentialSnapshot:
        now = self._clock()
        with self._lock:
            stat_signature: tuple[int, int, int] | None = None
            present = False
            stat_error: str | None = None
            try:
                stat_result = path.stat()
            except FileNotFoundError:
                pass
            except OSError:
                stat_error = CREDENTIALS_FILE_UNREADABLE
            else:
                present = True
                stat_signature = (
                    stat_result.st_mtime_ns,
                    stat_result.st_ino,
                    stat_result.st_size,
                )

            cached = self._snapshot
            if (
                cached is not None
                and now < cached.expires_at
                and cached.signature == stat_signature
            ):
                return cached

            snapshot = self._load(
                path,
                now,
                stat_signature=stat_signature,
                present=present,
                stat_error=stat_error,
            )
            self._snapshot = snapshot
            return snapshot

    def _load(
        self,
        path: Path,
        now: float,
        *,
        stat_signature: tuple[int, int, int] | None,
        present: bool,
        stat_error: str | None,
    ) -> _CredentialSnapshot:
        expires_at = now + CREDENTIALS_CACHE_SECONDS
        if not present:
            limitations = (stat_error,) if stat_error is not None else ()
            return _CredentialSnapshot(
                file_present=False,
                auths={},
                limitations=limitations,
                signature=None,
                expires_at=expires_at,
            )

        try:
            with path.open("rb") as handle:
                stat_result = os.fstat(handle.fileno())
                read_signature = (
                    stat_result.st_mtime_ns,
                    stat_result.st_ino,
                    stat_result.st_size,
                )
                if stat_result.st_size > _MAX_CREDENTIALS_FILE_BYTES:
                    return _CredentialSnapshot(
                        file_present=True,
                        auths={},
                        limitations=(CREDENTIALS_FILE_MALFORMED,),
                        signature=read_signature,
                        expires_at=expires_at,
                    )
                raw = handle.read(_MAX_CREDENTIALS_FILE_BYTES + 1)
        except FileNotFoundError:
            return _CredentialSnapshot(
                file_present=False,
                auths={},
                limitations=(),
                signature=None,
                expires_at=expires_at,
            )
        except OSError:
            return _CredentialSnapshot(
                file_present=True,
                auths={},
                limitations=(CREDENTIALS_FILE_UNREADABLE,),
                signature=stat_signature,
                expires_at=expires_at,
            )

        if len(raw) > _MAX_CREDENTIALS_FILE_BYTES:
            return _CredentialSnapshot(
                file_present=True,
                auths={},
                limitations=(CREDENTIALS_FILE_MALFORMED,),
                signature=read_signature,
                expires_at=expires_at,
            )
        if not raw.strip():
            return _CredentialSnapshot(
                file_present=True,
                auths={},
                limitations=(),
                signature=read_signature,
                expires_at=expires_at,
            )

        auths, limitations = _parse_document(raw)
        return _CredentialSnapshot(
            file_present=True,
            auths=auths,
            limitations=limitations,
            signature=read_signature,
            expires_at=expires_at,
        )


def parse_allowed_hosts(value: str) -> frozenset[str] | None:
    """Normalize ``REGISTRY_ALLOWED_HOSTS`` into resolver host keys.

    Empty or blank input means no allowlist. Entries are trimmed and validated
    through the registry client, which lowercases hosts, removes default ports,
    and maps Docker Hub aliases to their canonical registry. Blank entries are
    ignored; a malformed entry raises a startup-safe ``ValueError``.
    """
    if not isinstance(value, str):
        raise ValueError("REGISTRY_ALLOWED_HOSTS must be a comma-separated string.")

    entries = [entry.strip() for entry in value.split(",") if entry.strip()]
    if not entries:
        return None

    normalized: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        try:
            hosts = _normalize_allowed_hosts(frozenset({entry}))
        except (TypeError, ValueError):
            hosts = None
        if not hosts:
            raise ValueError(f"REGISTRY_ALLOWED_HOSTS entry {index} is not a valid registry host.")
        normalized.update(hosts)
    return frozenset(normalized)


def _parse_document(raw: bytes) -> tuple[dict[str, RegistryCredentials], tuple[str, ...]]:
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError):
        return {}, (CREDENTIALS_FILE_MALFORMED,)
    if not isinstance(document, dict):
        return {}, (CREDENTIALS_FILE_MALFORMED,)

    limitations: set[str] = set()
    if document.get("credsStore") not in (None, ""):
        limitations.add(CREDENTIAL_HELPERS_UNSUPPORTED)
        if not isinstance(document.get("credsStore"), str):
            limitations.add(CREDENTIALS_FILE_MALFORMED)
    if document.get("credHelpers") not in (None, {}):
        limitations.add(CREDENTIAL_HELPERS_UNSUPPORTED)
        if not isinstance(document.get("credHelpers"), dict):
            limitations.add(CREDENTIALS_FILE_MALFORMED)

    auths = document.get("auths")
    if auths is None:
        return {}, _sorted_limitations(limitations)
    if not isinstance(auths, dict):
        limitations.add(CREDENTIALS_FILE_MALFORMED)
        return {}, _sorted_limitations(limitations)

    parsed: dict[str, RegistryCredentials] = {}
    for index, (key, entry) in enumerate(auths.items()):
        if index >= _MAX_AUTH_ENTRIES:
            limitations.add(CREDENTIALS_FILE_MALFORMED)
            break
        host = _normalize_registry_key(key)
        if host is None:
            limitations.add(CREDENTIALS_FILE_MALFORMED)
            continue
        credentials, malformed = _credentials_from_entry(entry)
        if malformed:
            limitations.add(CREDENTIALS_FILE_MALFORMED)
        if credentials is not None:
            parsed[host] = credentials
    return parsed, _sorted_limitations(limitations)


def _credentials_from_entry(entry: object) -> tuple[RegistryCredentials | None, bool]:
    if entry is None:
        return None, False
    if not isinstance(entry, dict):
        return None, True

    username = entry.get("username")
    password = entry.get("password")
    if isinstance(username, str) and username and isinstance(password, str) and password:
        return _build_credentials(username, password)

    auth = entry.get("auth")
    if auth is None:
        return None, False
    if not isinstance(auth, str) or not auth:
        return None, True
    decoded = _decode_auth(auth)
    if decoded is None:
        return None, True
    return _build_credentials(*decoded)


def _build_credentials(username: str, password: str) -> tuple[RegistryCredentials | None, bool]:
    try:
        return RegistryCredentials(username=username, password=password), False
    except ValueError:
        return None, True


def _decode_auth(value: str) -> tuple[str, str] | None:
    if len(value) > _MAX_AUTH_FIELD_CHARS:
        return None
    padded = value + "=" * (-len(value) % 4)
    try:
        raw = base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw or len(raw) > _MAX_DECODED_AUTH_BYTES:
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


def _normalize_registry_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _MAX_REGISTRY_KEY_CHARS:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return None

    scheme, separator, remainder = text.partition("://")
    if separator:
        if scheme.lower() not in {"http", "https"} or not remainder:
            return None
        authority = remainder.split("/", 1)[0]
        if not authority or "@" in authority:
            return None
        text = authority

    try:
        normalized = _normalize_allowed_hosts(frozenset({text}))
    except (TypeError, ValueError):
        return None
    if not normalized:
        return None
    return next(iter(normalized))


def _sorted_limitations(limitations: set[str]) -> tuple[str, ...]:
    return tuple(sorted(limitations))
