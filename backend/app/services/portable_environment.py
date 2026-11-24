# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Canonical portable identity for registry-verified environment revisions.

The fingerprint deliberately excludes references, repository digests, local
image IDs, database IDs, timestamps, tag strings, environment values, and host
paths. Only normalized template configuration plus the verified platform
manifest identity of the runtime and optional toolchain are hashed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.schemas.environment_manifest import ImageIdentity

PORTABLE_ENVIRONMENT_SCHEMA = "nukelab.portable-environment/v1"

REGISTRY_VERIFICATION_REQUIRED = "registry_verification_required"
VOLUME_CONFIGURATION_LOCAL_ONLY = "volume_configuration_local_only"
CONFIGURATION_NOT_PORTABLE = "configuration_not_portable"

_ERROR_CODES = frozenset(
    {
        REGISTRY_VERIFICATION_REQUIRED,
        VOLUME_CONFIGURATION_LOCAL_ONLY,
        CONFIGURATION_NOT_PORTABLE,
    }
)

_DIGEST_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")
_ENVIRONMENT_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_PLATFORM_VARIANT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")
_PORT_RE = re.compile(r"[0-9]+\Z")
_TOOL_MOUNT_RE = re.compile(r"/[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_VOLUME_KEYS = frozenset({"mount_path", "mode"})
_VOLUME_MODES = frozenset({"read_only", "read_write"})


class PortableIdentityUnavailable(ValueError):
    """A truthful portable identity cannot be derived from this revision."""

    def __init__(self, code: str, message: str | None = None):
        if code not in _ERROR_CODES:
            raise ValueError(f"Unsupported portable identity error code: {code}")
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PortableIdentity:
    fingerprint: str
    canonical_bytes: bytes


def portable_environment_identity(
    configuration: dict,
    runtime: ImageIdentity,
    toolchain: ImageIdentity | None,
) -> PortableIdentity:
    """Return the canonical v1 identity or raise on any non-portable input."""
    if not isinstance(configuration, dict):
        raise PortableIdentityUnavailable(
            CONFIGURATION_NOT_PORTABLE, "Environment configuration is not portable"
        )
    runtime_identity = _platform_identity(runtime, required=True)
    toolchain_identity = _platform_identity(toolchain, required=False)
    canonical_bytes = _canonical_bytes(
        {
            "schema": PORTABLE_ENVIRONMENT_SCHEMA,
            "configuration": {
                "tool_mounts": _tool_mounts(configuration.get("tool_mounts")),
                "packages": _packages(configuration.get("packages")),
                "ports": _ports(configuration.get("ports")),
                "volume_mounts": _volume_mounts(configuration.get("volumes")),
                "environment_variable_names": _environment_variable_names(
                    configuration.get("environment_variables")
                ),
            },
            "runtime": runtime_identity,
            "toolchain": toolchain_identity,
        }
    )
    return PortableIdentity(hashlib.sha256(canonical_bytes).hexdigest(), canonical_bytes)


def _platform_identity(image: ImageIdentity | None, *, required: bool) -> dict | None:
    if image is None:
        if required:
            raise PortableIdentityUnavailable(
                REGISTRY_VERIFICATION_REQUIRED, "A verified runtime artifact is required"
            )
        return None
    if not image.registry_verified:
        raise PortableIdentityUnavailable(
            REGISTRY_VERIFICATION_REQUIRED, "The artifact is not registry-verified"
        )
    digest = image.manifest_digest
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise PortableIdentityUnavailable(
            REGISTRY_VERIFICATION_REQUIRED, "A verified manifest digest is required"
        )
    if (
        not isinstance(image.os, str)
        or not image.os
        or not isinstance(image.architecture, str)
        or not image.architecture
    ):
        raise PortableIdentityUnavailable(
            REGISTRY_VERIFICATION_REQUIRED, "A verified image platform is required"
        )
    variant = image.variant
    if variant is not None and (
        not isinstance(variant, str) or not _PLATFORM_VARIANT_RE.fullmatch(variant)
    ):
        raise PortableIdentityUnavailable(
            REGISTRY_VERIFICATION_REQUIRED, "A verified image platform is required"
        )
    return {
        "manifest_digest": digest,
        "os": image.os,
        "architecture": image.architecture,
        "variant": variant,
    }


def _tool_mounts(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 1:
        raise PortableIdentityUnavailable(
            CONFIGURATION_NOT_PORTABLE, "Tool mounts are not portable"
        )
    if not value:
        return []
    mount_path = value[0]
    if not _tool_mount_path(mount_path):
        raise PortableIdentityUnavailable(
            CONFIGURATION_NOT_PORTABLE, "Tool mounts are not portable"
        )
    return [mount_path]


def _tool_mount_path(value) -> bool:
    """Match the approved launch layout: one absolute path, no special targets."""
    if not isinstance(value, str) or not _TOOL_MOUNT_RE.fullmatch(value):
        return False
    if any(part in ("", ".", "..") for part in value.split("/")[1:]):
        return False
    return value != "/toolchain-target" and not value.startswith("/toolchain-target/")


def _packages(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PortableIdentityUnavailable(CONFIGURATION_NOT_PORTABLE, "Packages are not portable")
    packages = []
    for item in value:
        if not isinstance(item, str):
            raise PortableIdentityUnavailable(
                CONFIGURATION_NOT_PORTABLE, "Packages are not portable"
            )
        package = item.strip()
        if not package or _CONTROL_CHARACTER_RE.search(package):
            raise PortableIdentityUnavailable(
                CONFIGURATION_NOT_PORTABLE, "Packages are not portable"
            )
        packages.append(package)
    return _sorted_unique(packages)


def _ports(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PortableIdentityUnavailable(CONFIGURATION_NOT_PORTABLE, "Ports are not portable")
    ports = []
    for item in value:
        if isinstance(item, bool):
            raise PortableIdentityUnavailable(CONFIGURATION_NOT_PORTABLE, "Ports are not portable")
        if isinstance(item, int):
            if item < 0:
                raise PortableIdentityUnavailable(
                    CONFIGURATION_NOT_PORTABLE, "Ports are not portable"
                )
            port = str(item)
        elif isinstance(item, str):
            text = item.strip()
            if not _PORT_RE.fullmatch(text):
                raise PortableIdentityUnavailable(
                    CONFIGURATION_NOT_PORTABLE, "Ports are not portable"
                )
            try:
                port = str(int(text, 10))
            except ValueError:
                raise PortableIdentityUnavailable(
                    CONFIGURATION_NOT_PORTABLE, "Ports are not portable"
                ) from None
        else:
            raise PortableIdentityUnavailable(CONFIGURATION_NOT_PORTABLE, "Ports are not portable")
        ports.append(port)
    return _sorted_unique(ports)


def _environment_variable_names(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        raise PortableIdentityUnavailable(
            CONFIGURATION_NOT_PORTABLE, "Environment variable names are not portable"
        )
    names = []
    for name in value:
        if not isinstance(name, str) or not _ENVIRONMENT_NAME_RE.fullmatch(name):
            raise PortableIdentityUnavailable(
                CONFIGURATION_NOT_PORTABLE, "Environment variable names are not portable"
            )
        names.append(name)
    return _sorted_unique(names)


def _volume_mounts(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PortableIdentityUnavailable(
            VOLUME_CONFIGURATION_LOCAL_ONLY, "Template volumes are not portable"
        )
    mounts = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != _VOLUME_KEYS:
            raise PortableIdentityUnavailable(
                VOLUME_CONFIGURATION_LOCAL_ONLY, "Template volumes are not portable"
            )
        mount_path = entry["mount_path"]
        mode = entry["mode"]
        if (
            not isinstance(mount_path, str)
            or not isinstance(mode, str)
            or mode not in _VOLUME_MODES
        ):
            raise PortableIdentityUnavailable(
                VOLUME_CONFIGURATION_LOCAL_ONLY, "Template volumes are not portable"
            )
        path = _absolute_path(mount_path, VOLUME_CONFIGURATION_LOCAL_ONLY)
        mounts.append(f"{mode}:{path}")
    return _sorted_unique(mounts)


def _absolute_path(value, code: str) -> str:
    if not isinstance(value, str):
        raise PortableIdentityUnavailable(code, "A container path is not portable")
    path = value.strip()
    if not path or path.startswith("//") or _CONTROL_CHARACTER_RE.search(path):
        raise PortableIdentityUnavailable(code, "A container path is not portable")
    parsed = PurePosixPath(path)
    if not parsed.is_absolute() or ".." in parsed.parts:
        raise PortableIdentityUnavailable(code, "A container path is not portable")
    return str(parsed)


def _sorted_unique(values) -> list[str]:
    return sorted(set(values))


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
