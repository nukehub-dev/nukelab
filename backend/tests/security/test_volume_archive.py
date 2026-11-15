# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import gzip
import hashlib
import io
import os
import tarfile
from dataclasses import replace

import pytest

from app.services.volume_archive_service import ArchiveLimits, VolumeArchiveError, restore_archive


@pytest.fixture
def limits():
    return ArchiveLimits(65536, 131072, 4096, 8192, 32)


def artifact(tmp_path, entries):
    source = tmp_path / "source.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        for name, kind, content in entries:
            member = tarfile.TarInfo(name)
            member.mode = 0o6777
            member.uid = member.gid = 12345
            member.type = kind
            if kind == tarfile.REGTYPE:
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            else:
                member.linkname = content
                archive.addfile(member)
    return source


def restore(tmp_path, source, limits, **kwargs):
    root = tmp_path / "staging"
    root.mkdir(mode=0o700, exist_ok=True)
    return restore_archive(
        source,
        expected_sha256=kwargs.pop("checksum", hashlib.sha256(source.read_bytes()).hexdigest()),
        destination=tmp_path / "restored",
        staging_root=root,
        limits=limits,
        **kwargs,
    )


def test_roundtrip_preserves_links_and_maps_ownership(tmp_path, limits):
    source = artifact(
        tmp_path,
        [
            ("dir", tarfile.DIRTYPE, ""),
            ("dir/日本語", tarfile.REGTYPE, b"scientific-data"),
            ("copy", tarfile.LNKTYPE, "dir/日本語"),
            ("link", tarfile.SYMTYPE, "dir/日本語"),
        ],
    )
    before = source.read_bytes()
    metadata = restore(tmp_path, source, limits)
    root = tmp_path / "restored"
    assert (root / "dir/日本語").read_bytes() == b"scientific-data"
    assert (root / "dir/日本語").stat().st_ino == (root / "copy").stat().st_ino
    assert os.readlink(root / "link") == "dir/日本語"
    assert (root / "copy").stat().st_uid == os.getuid()
    assert (root / "copy").stat().st_mode & 0o7077 == 0
    assert metadata.logical_bytes == 15
    assert metadata.member_count == 4
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "entries",
    [
        [("../escape", tarfile.REGTYPE, b"x")],
        [("/escape", tarfile.REGTYPE, b"x")],
        [("C:/escape", tarfile.REGTYPE, b"x")],
        [("a\\b", tarfile.REGTYPE, b"x")],
        [("same", tarfile.REGTYPE, b"x"), ("same", tarfile.REGTYPE, b"y")],
        [("link", tarfile.SYMTYPE, "../../escape")],
        [("a", tarfile.SYMTYPE, "b/.."), ("b", tarfile.SYMTYPE, "dir/..")],
        [("link", tarfile.LNKTYPE, "../escape")],
        [("link", tarfile.LNKTYPE, "later"), ("later", tarfile.REGTYPE, b"x")],
        [("parent/child", tarfile.REGTYPE, b"x"), ("parent", tarfile.SYMTYPE, "dir")],
        [("parent", tarfile.SYMTYPE, "dir"), ("parent/child", tarfile.REGTYPE, b"x")],
        [("fifo", tarfile.FIFOTYPE, "")],
        [("device", tarfile.CHRTYPE, "")],
    ],
)
def test_rejects_unsafe_graph_without_publishing(tmp_path, limits, entries):
    source = artifact(tmp_path, entries)
    with pytest.raises(VolumeArchiveError):
        restore(tmp_path, source, limits)
    assert not (tmp_path / "restored").exists()
    assert not (tmp_path / "escape").exists()
    assert list((tmp_path / "staging").iterdir()) == []


@pytest.mark.parametrize(
    "changed",
    [
        {"max_compressed_bytes": 10},
        {"max_tar_bytes": 100},
        {"max_file_bytes": 1},
        {"max_logical_bytes": 1},
        {"max_members": 1},
        {"max_path_bytes": 1},
        {"max_expansion_ratio": 1},
    ],
)
def test_bounds_before_publication(tmp_path, limits, changed):
    source = artifact(
        tmp_path, [("file-one", tarfile.REGTYPE, b"hello"), ("file-two", tarfile.REGTYPE, b"world")]
    )
    with pytest.raises(VolumeArchiveError):
        restore(tmp_path, source, replace(limits, **changed))
    assert not (tmp_path / "restored").exists()


def test_checksum_rejected_before_parsing(tmp_path, limits):
    source = tmp_path / "bad.gz"
    source.write_bytes(b"not gzip")
    with pytest.raises(VolumeArchiveError, match="artifact_corrupt"):
        restore(tmp_path, source, limits, checksum="0" * 64)


def test_truncated_gzip_is_sanitized(tmp_path, limits):
    source = tmp_path / "bad.gz"
    source.write_bytes(gzip.compress(b"anything")[:-5])
    with pytest.raises(VolumeArchiveError, match="artifact_corrupt"):
        restore(tmp_path, source, limits)


def test_existing_destination_retained(tmp_path, limits):
    source = artifact(tmp_path, [("file", tarfile.REGTYPE, b"hello")])
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "sentinel").write_text("retain")
    with pytest.raises(VolumeArchiveError, match="destination_exists"):
        restore(tmp_path, source, limits)
    assert (destination / "sentinel").read_text() == "retain"


def test_extended_metadata_bounded_before_parser(tmp_path, limits):
    source = tmp_path / "pax.gz"
    with tarfile.open(source, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        member = tarfile.TarInfo("file")
        member.pax_headers = {"comment": "x" * 1000}
        archive.addfile(member, io.BytesIO())
    with pytest.raises(VolumeArchiveError, match="archive_metadata_limit"):
        restore(tmp_path, source, replace(limits, max_metadata_bytes=100))


def test_deadline_prevents_publication(tmp_path, limits, monkeypatch):
    source = artifact(tmp_path, [("file", tarfile.REGTYPE, b"hello")])
    ticks = iter([0, 100])
    monkeypatch.setattr("app.services.volume_archive_service.time.monotonic", lambda: next(ticks))
    with pytest.raises(VolumeArchiveError, match="archive_timeout"):
        restore(tmp_path, source, replace(limits, timeout_seconds=1))
    assert not (tmp_path / "restored").exists()


def test_corrupt_deflate_payload_is_sanitized(tmp_path, limits):
    source = tmp_path / "deflate.gz"
    data = bytearray(gzip.compress(b"important" * 100))
    data[12:17] = b"\xff" * 5
    source.write_bytes(data)
    with pytest.raises(VolumeArchiveError, match="artifact_corrupt"):
        restore(tmp_path, source, limits)
