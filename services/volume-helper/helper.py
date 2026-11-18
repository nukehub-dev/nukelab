# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Fixed-path, unprivileged capture/restore command; authorization belongs upstream."""

import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import time
from pathlib import Path
from uuid import UUID

from nukelab_volume_archive import (
    ArchiveLimits,
    VolumeArchiveError,
    _safe_name,
    restore_archive,
)


class BoundedWriter:
    def __init__(self, stream, maximum, deadline, code="archive_compressed_limit"):
        self.stream, self.maximum, self.deadline, self.count = (
            stream,
            maximum,
            deadline,
            0,
        )
        self.code = code

    def write(self, data):
        if time.monotonic() >= self.deadline:
            raise VolumeArchiveError("archive_timeout")
        self.count += len(data)
        if self.count > self.maximum:
            raise VolumeArchiveError(self.code)
        return self.stream.write(data)

    def flush(self):
        return self.stream.flush()


class BoundedReader:
    def __init__(self, stream, deadline):
        self.stream, self.deadline = stream, deadline

    def read(self, size=-1):
        if time.monotonic() >= self.deadline:
            raise VolumeArchiveError("archive_timeout")
        return self.stream.read(size)


def _private_directory(path):
    value = path.lstat()
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.getuid()
        or value.st_mode & 0o077
    ):
        raise VolumeArchiveError("unsafe_staging_root")


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def capture(source: Path, artifact: Path, limits: ArchiveLimits):
    """Read a protected tree without following links or changing source metadata."""
    _private_directory(artifact)
    final, partial = artifact / "archive.tar.gz", artifact / "archive.partial"
    if os.path.lexists(final) or os.path.lexists(partial):
        raise VolumeArchiveError("artifact_exists")
    deadline = time.monotonic() + limits.timeout_seconds
    count = logical = metadata_bytes = 0
    inodes = {}
    with partial.open("xb") as output:
        os.chmod(partial, 0o600)
        limited = BoundedWriter(output, limits.max_compressed_bytes, deadline)
        with gzip.GzipFile(
            fileobj=limited, mode="wb", filename="", mtime=0
        ) as compressed:
            with tarfile.open(
                fileobj=BoundedWriter(
                    compressed,
                    limits.max_tar_bytes,
                    deadline,
                    "archive_expansion_limit",
                ),
                mode="w|",
                format=tarfile.PAX_FORMAT,
            ) as archive:

                def add(member, reader=None):
                    nonlocal metadata_bytes
                    # Match the restore scanner's bound on generated PAX data.
                    # A completed capture must not exceed its own restore limits.
                    headers = member.tobuf(format=tarfile.PAX_FORMAT)
                    offset = 0
                    while offset < len(headers) - 512:
                        extension = tarfile.TarInfo.frombuf(
                            headers[offset : offset + 512], "utf-8", "strict"
                        )
                        metadata_bytes += extension.size
                        if metadata_bytes > limits.max_metadata_bytes:
                            raise VolumeArchiveError("archive_metadata_limit")
                        offset += 512 + ((extension.size + 511) // 512) * 512
                    archive.addfile(member, reader)

                def visit(directory, prefix=""):
                    nonlocal count, logical
                    for item in sorted(
                        os.scandir(directory), key=lambda entry: entry.name
                    ):
                        if time.monotonic() >= deadline:
                            raise VolumeArchiveError("archive_timeout")
                        name = _safe_name(prefix + item.name, limits.max_path_bytes)
                        info = item.stat(follow_symlinks=False)
                        count += 1
                        if count > limits.max_members:
                            raise VolumeArchiveError("archive_member_limit")
                        member = tarfile.TarInfo(name)
                        member.mode, member.uid, member.gid, member.mtime = (
                            stat.S_IMODE(info.st_mode),
                            info.st_uid,
                            info.st_gid,
                            int(info.st_mtime),
                        )
                        member.uname = member.gname = ""
                        if stat.S_ISDIR(info.st_mode):
                            if not info.st_mode & 0o444 or not info.st_mode & 0o111:
                                raise VolumeArchiveError("source_unreadable")
                            member.type = tarfile.DIRTYPE
                            add(member)
                            visit(Path(item.path), name + "/")
                        elif stat.S_ISLNK(info.st_mode):
                            target = os.readlink(item.path)
                            if (
                                not target
                                or target.startswith("/")
                                or ".." in target.split("/")
                                or re.match(r"^[A-Za-z]:", target)
                                or "\\" in target
                                or len(target.encode()) > limits.max_path_bytes
                                or any(
                                    ord(char) < 32 or ord(char) == 127
                                    for char in target
                                )
                            ):
                                raise VolumeArchiveError("unsafe_archive_link")
                            member.type, member.linkname = tarfile.SYMTYPE, target
                            add(member)
                        elif stat.S_ISREG(info.st_mode):
                            inode = (info.st_dev, info.st_ino)
                            if inode in inodes:
                                member.type, member.linkname = (
                                    tarfile.LNKTYPE,
                                    inodes[inode],
                                )
                                add(member)
                                continue
                            if not info.st_mode & 0o444:
                                raise VolumeArchiveError("source_unreadable")
                            logical += info.st_size
                            if (
                                info.st_size > limits.max_file_bytes
                                or logical > limits.max_logical_bytes
                            ):
                                raise VolumeArchiveError("archive_logical_limit")
                            fd = os.open(item.path, os.O_RDONLY | os.O_NOFOLLOW)
                            with os.fdopen(fd, "rb") as reader:
                                opened = os.fstat(reader.fileno())
                                if (opened.st_dev, opened.st_ino, opened.st_size) != (
                                    info.st_dev,
                                    info.st_ino,
                                    info.st_size,
                                ):
                                    raise VolumeArchiveError("source_changed")
                                member.size = info.st_size
                                add(member, BoundedReader(reader, deadline))
                                after = os.fstat(reader.fileno())
                                if (
                                    after.st_size != info.st_size
                                    or after.st_mtime_ns != info.st_mtime_ns
                                ):
                                    raise VolumeArchiveError("source_changed")
                            inodes[inode] = name
                        else:
                            raise VolumeArchiveError("unsupported_archive_member")

                visit(source)
        output.flush()
        os.fsync(output.fileno())
    digest = hashlib.sha256()
    with partial.open("rb") as reader:
        while chunk := reader.read(65536):
            if time.monotonic() >= deadline:
                raise VolumeArchiveError("archive_timeout")
            digest.update(chunk)
    if partial.stat().st_size * limits.max_expansion_ratio < logical:
        raise VolumeArchiveError("archive_expansion_limit")
    os.rename(partial, final)
    _sync_directory(artifact)
    return {
        "sha256": digest.hexdigest(),
        "compressed_bytes": final.stat().st_size,
        "logical_bytes": logical,
        "member_count": count,
    }


def restore(
    source: Path, artifact: Path, target: Path, checksum: str, limits: ArchiveLimits
):
    _private_directory(artifact)
    if (
        target.is_symlink()
        or target.stat().st_uid != os.getuid()
        or list(target.iterdir())
    ):
        raise VolumeArchiveError("destination_exists")
    staging = artifact / "staging"
    staging.mkdir(mode=0o700)
    verified = artifact / "verified"
    metadata = restore_archive(
        source,
        expected_sha256=checksum,
        destination=verified,
        staging_root=staging,
        limits=limits,
    )
    deadline = time.monotonic() + limits.timeout_seconds
    inodes = {}

    def publish(directory, destination):
        for item in sorted(os.scandir(directory), key=lambda entry: entry.name):
            if time.monotonic() >= deadline:
                raise VolumeArchiveError("archive_timeout")
            origin, output = Path(item.path), destination / item.name
            info = item.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                output.mkdir(mode=0o700)
                publish(origin, output)
                shutil.copystat(origin, output, follow_symlinks=False)
                _sync_directory(output)
            elif stat.S_ISLNK(info.st_mode):
                output.symlink_to(os.readlink(origin))
            elif stat.S_ISREG(info.st_mode):
                key = (info.st_dev, info.st_ino)
                if key in inodes:
                    os.link(inodes[key], output)
                else:
                    with origin.open("rb") as reader, output.open("xb") as writer:
                        while chunk := BoundedReader(reader, deadline).read(65536):
                            writer.write(chunk)
                        shutil.copystat(origin, output, follow_symlinks=False)
                        writer.flush()
                        os.fsync(writer.fileno())
                    inodes[key] = output
            else:
                raise VolumeArchiveError("unsupported_archive_member")
        _sync_directory(destination)

    publish(verified, target)
    return vars(metadata)


def main():
    os.umask(0o077)
    if os.getuid() != 65532 or os.getgid() != 65532:
        return 2
    try:
        action, operation, fence, backup, raw_limits, *extra = sys.argv[1:]
        operation, fence, backup = (
            str(UUID(operation)),
            str(UUID(fence)),
            str(UUID(backup)),
        )
        limits = ArchiveLimits(**json.loads(raw_limits))
        artifact = Path("/artifact")
        if action == "capture" and not extra:
            result = capture(Path("/source"), artifact, limits)
        elif action == "restore" and len(extra) == 1:
            result = restore(
                Path("/archive/archive.tar.gz"),
                artifact,
                Path("/target"),
                extra[0],
                limits,
            )
        else:
            return 2
        result.update(
            operation_id=operation, fencing_token=fence, backup_id=backup, action=action
        )
        completion = artifact / "completion.partial"
        with completion.open("x", encoding="utf-8") as output:
            json.dump(result, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.rename(completion, artifact / "completion.json")
        _sync_directory(artifact)
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError, tarfile.TarError):
        # Errors intentionally contain no source names or host paths.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
