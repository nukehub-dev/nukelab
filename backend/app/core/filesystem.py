# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Filesystem security utilities for safe path resolution."""

import re
from pathlib import Path

from fastapi import HTTPException


def secure_path(base_path: Path | str, subpath: str) -> Path:
    """Resolve subpath within base_path, rejecting path traversal attempts.

    Uses pathlib.Path.resolve() to normalize the path (eliminates '..',
    follows symlinks) and then verifies the resolved path is still inside
    the base directory via relative_to().

    Args:
        base_path: The root directory that subpath must stay within.
        subpath: A user-supplied relative path (may contain '..' or be absolute).

    Returns:
        A resolved Path object guaranteed to be inside base_path.

    Raises:
        HTTPException(403): If subpath escapes base_path after resolution.
    """
    base = Path(base_path).resolve()
    requested = (base / subpath.lstrip("/")).resolve()
    try:
        requested.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
    return requested


def validate_avatar_filename(filename: str) -> None:
    """Validate that an avatar filename matches the expected safe pattern.

    Avatars are stored as {uuid}.{ext} where ext is one of the allowed
    image formats. This provides a defense-in-depth layer on top of
    secure_path().

    Args:
        filename: The filename to validate.

    Raises:
        HTTPException(400): If the filename does not match the expected pattern.
    """
    if not re.match(
        r"^[0-9a-fA-F-]+\.(jpg|jpeg|png|webp|gif)$",
        filename,
    ):
        raise HTTPException(status_code=400, detail="Invalid filename")
