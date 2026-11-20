# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Bounded gzip/tar validation for a trusted, unprivileged recovery helper.

Paths are service-selected private paths, never user input. Runtime resource/time
limits and durable exclusion remain mandatory; these checks do not snapshot live data.
"""

import gzip
import hashlib
import os
import posixpath
import re
import tarfile
import tempfile
import time
import zlib
from dataclasses import dataclass
from pathlib import Path


class VolumeArchiveError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ArchiveLimits:
    max_compressed_bytes: int
    max_tar_bytes: int
    max_file_bytes: int
    max_logical_bytes: int
    max_members: int
    max_path_bytes: int = 1024
    max_metadata_bytes: int = 1024 * 1024
    max_expansion_ratio: int = 1000
    timeout_seconds: float = 1800

    def __post_init__(self):
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("Archive limits must be positive")


@dataclass(frozen=True)
class ArchiveMetadata:
    sha256: str
    compressed_bytes: int
    logical_bytes: int
    member_count: int


def _check_deadline(deadline: float):
    if time.monotonic() >= deadline:
        raise VolumeArchiveError("archive_timeout")


def _safe_name(name: str, limit: int) -> str:
    name = name.rstrip("/")
    if (
        not name
        or len(name.encode("utf-8")) > limit
        or name.startswith("/")
        or "\\" in name
        or re.match(r"^[A-Za-z]:", name)
        or any(part in ("", ".", "..") for part in name.split("/"))
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise VolumeArchiveError("unsafe_archive_path")
    return name


def _scan_headers(raw: Path, limits: ArchiveLimits, deadline: float):
    """Bound extension metadata before tarfile parses PAX/GNU long headers."""
    count = metadata_bytes = 0
    with raw.open("rb") as stream:
        while block := stream.read(512):
            _check_deadline(deadline)
            if len(block) != 512:
                raise VolumeArchiveError("artifact_corrupt")
            if block == b"\0" * 512:
                break
            count += 1
            if count > limits.max_members * 4:
                raise VolumeArchiveError("archive_member_limit")
            member = tarfile.TarInfo.frombuf(block, "utf-8", "strict")
            if member.size < 0:
                raise VolumeArchiveError("artifact_corrupt")
            if member.type in (
                tarfile.XHDTYPE,
                tarfile.XGLTYPE,
                tarfile.GNUTYPE_LONGNAME,
                tarfile.GNUTYPE_LONGLINK,
            ):
                metadata_bytes += member.size
                if metadata_bytes > limits.max_metadata_bytes:
                    raise VolumeArchiveError("archive_metadata_limit")
            if stream.tell() + ((member.size + 511) // 512) * 512 > raw.stat().st_size:
                raise VolumeArchiveError("artifact_corrupt")
            stream.seek(((member.size + 511) // 512) * 512, os.SEEK_CUR)


def _members(archive: tarfile.TarFile, limits: ArchiveLimits, deadline: float):
    members, kinds, regular = [], {}, set()
    logical = 0
    for member in archive:
        _check_deadline(deadline)
        if len(members) >= limits.max_members:
            raise VolumeArchiveError("archive_member_limit")
        name = _safe_name(member.name, limits.max_path_bytes)
        if name in kinds:
            raise VolumeArchiveError("duplicate_archive_path")
        if member.sparse is not None or any(
            key.startswith("GNU.sparse") for key in member.pax_headers
        ):
            raise VolumeArchiveError("unsupported_archive_member")
        if member.isfile():
            if member.size < 0 or member.size > limits.max_file_bytes:
                raise VolumeArchiveError("archive_file_limit")
            logical += member.size
            if logical > limits.max_logical_bytes:
                raise VolumeArchiveError("archive_logical_limit")
            regular.add(name)
            kind = "file"
        elif member.isdir():
            kind = "directory"
        elif member.issym():
            target = member.linkname
            if (
                not target
                or target.startswith("/")
                or "\\" in target
                or re.match(r"^[A-Za-z]:", target)
                or ".." in target.split("/")
                or len(target.encode("utf-8")) > limits.max_path_bytes
                or any(ord(char) < 32 or ord(char) == 127 for char in target)
            ):
                raise VolumeArchiveError("unsafe_archive_link")
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
            if resolved == ".." or resolved.startswith("../"):
                raise VolumeArchiveError("unsafe_archive_link")
            kind = "symlink"
        elif member.islnk():
            if member.linkname not in regular:
                raise VolumeArchiveError("unsafe_archive_link")
            kind = "hardlink"
        else:
            raise VolumeArchiveError("unsupported_archive_member")
        kinds[name] = kind
        members.append(member)
    for name in kinds:
        parts = name.split("/")
        for index in range(1, len(parts)):
            if kinds.get("/".join(parts[:index]), "directory") != "directory":
                raise VolumeArchiveError("unsafe_archive_parent")
    return members, logical


def restore_archive(
    source: Path,
    *,
    expected_sha256: str,
    destination: Path,
    staging_root: Path,
    limits: ArchiveLimits,
) -> ArchiveMetadata:
    """Verify fixed bytes, validate the full graph, then publish a fresh directory.

    Symlink targets must be relative and contain no parent components, including
    otherwise in-root parent references: forward symlink chains can change their
    meaning after extraction. Hardlinks must target an earlier regular member.
    The helper must run as the platform UID/GID. Extraction strips ownership,
    privilege bits and executable permissions on directories/files as appropriate.
    The destination parent and staging root must be exclusively helper-controlled.
    """
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise VolumeArchiveError("artifact_corrupt")
    if os.path.lexists(destination):
        raise VolumeArchiveError("destination_exists")
    root_stat = staging_root.lstat()
    if (
        staging_root.is_symlink()
        or not staging_root.is_dir()
        or root_stat.st_uid != os.getuid()
        or root_stat.st_mode & 0o077
    ):
        raise VolumeArchiveError("unsafe_staging_root")
    deadline = time.monotonic() + limits.timeout_seconds
    try:
        with tempfile.TemporaryDirectory(dir=staging_root) as temporary:
            work = Path(temporary)
            compressed = work / "artifact.gz"
            digest = hashlib.sha256()
            compressed_bytes = 0
            with source.open("rb") as reader, compressed.open("xb") as writer:
                os.chmod(compressed, 0o600)
                while chunk := reader.read(65536):
                    _check_deadline(deadline)
                    compressed_bytes += len(chunk)
                    if compressed_bytes > limits.max_compressed_bytes:
                        raise VolumeArchiveError("archive_compressed_limit")
                    digest.update(chunk)
                    writer.write(chunk)
            if digest.hexdigest() != expected_sha256:
                raise VolumeArchiveError("artifact_corrupt")
            raw = work / "artifact.tar"
            raw_bytes = 0
            with gzip.open(compressed, "rb") as reader, raw.open("xb") as writer:
                os.chmod(raw, 0o600)
                while chunk := reader.read(65536):
                    _check_deadline(deadline)
                    raw_bytes += len(chunk)
                    if (
                        raw_bytes > limits.max_tar_bytes
                        or raw_bytes > compressed_bytes * limits.max_expansion_ratio
                    ):
                        raise VolumeArchiveError("archive_expansion_limit")
                    writer.write(chunk)
            _scan_headers(raw, limits, deadline)
            with tarfile.open(raw, "r:") as archive:
                members, logical = _members(archive, limits, deadline)
                files = work / "files"
                files.mkdir(mode=0o700)

                def extraction_filter(member, target):
                    _check_deadline(deadline)
                    filtered = tarfile.data_filter(member, target)
                    # No arbitrary ownership or privilege bits from the artifact.
                    return filtered.replace(
                        uid=None,
                        gid=None,
                        uname=None,
                        gname=None,
                        mode=0o700 if filtered.isdir() else (filtered.mode or 0o600) & 0o700,
                    )

                archive.extractall(files, members=members, filter=extraction_filter)
            _check_deadline(deadline)
            # Private parent is part of the helper contract; never replace an existing path.
            try:
                destination.mkdir(mode=0o700)
            except FileExistsError:
                raise VolumeArchiveError("destination_exists") from None
            try:
                os.rename(files, destination)
            except BaseException:
                destination.rmdir()
                raise
            return ArchiveMetadata(expected_sha256, compressed_bytes, logical, len(members))
    except VolumeArchiveError:
        raise
    except (
        OSError,
        EOFError,
        UnicodeError,
        tarfile.TarError,
        ValueError,
        zlib.error,
        RecursionError,
        OverflowError,
    ):
        raise VolumeArchiveError("artifact_corrupt") from None
