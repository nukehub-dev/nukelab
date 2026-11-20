# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import importlib.util
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.services import volume_archive_service

sys.modules["nukelab_volume_archive"] = volume_archive_service
spec = importlib.util.spec_from_file_location(
    "volume_helper", Path(__file__).with_name("helper.py")
)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
ArchiveLimits = volume_archive_service.ArchiveLimits
VolumeArchiveError = volume_archive_service.VolumeArchiveError


@pytest.fixture
def tree(tmp_path):
    source, artifact, target, scratch = (
        tmp_path / name for name in ("source", "artifact", "target", "scratch")
    )
    for path in (source, artifact, target, scratch):
        path.mkdir(mode=0o700)
    return source, artifact, target, scratch


@pytest.fixture
def limits():
    return ArchiveLimits(65536, 131072, 4096, 8192, 32, max_expansion_ratio=10000)


def test_capture_restore_unicode_links_and_safe_modes(tree, limits):
    source, artifact, target, scratch = tree
    (source / "日本語").mkdir()
    file = source / "日本語" / "data"
    file.write_bytes(b"research data")
    file.chmod(0o6755)
    os.link(file, source / "copy")
    (source / "link").symlink_to("日本語/data")
    before = file.stat()
    captured = helper.capture(source, artifact, limits)
    restored = helper.restore(
        artifact / "archive.tar.gz", scratch, target, captured["sha256"], limits
    )
    assert restored == captured
    assert (target / "copy").read_bytes() == b"research data"
    assert (target / "copy").stat().st_ino == (target / "日本語/data").stat().st_ino
    assert os.readlink(target / "link") == "日本語/data"
    assert (target / "copy").stat().st_mode & 0o7077 == 0
    assert (file.stat().st_mode, file.stat().st_mtime_ns) == (
        before.st_mode,
        before.st_mtime_ns,
    )


@pytest.mark.parametrize(
    "target", ["/etc/passwd", "../outside", "C:/bad", "dir/../bad", "bad\\name"]
)
def test_capture_refuses_unsafe_links_without_publishing(tree, limits, target):
    source, artifact, _, _ = tree
    (source / "link").symlink_to(target)
    with pytest.raises(VolumeArchiveError, match="unsafe_archive_link"):
        helper.capture(source, artifact, limits)
    assert not (artifact / "archive.tar.gz").exists()


@pytest.mark.parametrize(
    "kind", ["fifo", "unreadable", "too_large", "member_limit", "metadata_limit"]
)
def test_capture_bounds_and_unsupported_data(tree, limits, kind):
    source, artifact, _, _ = tree
    if kind == "fifo":
        os.mkfifo(source / "pipe")
        reason = "unsupported_archive_member"
    elif kind == "unreadable":
        (source / "file").write_bytes(b"x")
        (source / "file").chmod(0)
        reason = "source_unreadable"
    elif kind == "too_large":
        (source / "file").write_bytes(b"x" * 4097)
        reason = "archive_logical_limit"
    elif kind == "member_limit":
        for name in ("one", "two"):
            (source / name).write_bytes(b"x")
        limits = replace(limits, max_members=1)
        reason = "archive_member_limit"
    else:
        (source / ("long" * 40)).write_bytes(b"x")
        limits = replace(limits, max_metadata_bytes=16)
        reason = "archive_metadata_limit"
    with pytest.raises(VolumeArchiveError, match=reason):
        helper.capture(source, artifact, limits)
    assert not (artifact / "archive.tar.gz").exists()


def test_restore_checksum_failure_does_not_touch_destination(tree, limits):
    source, artifact, target, scratch = tree
    (source / "file").write_bytes(b"data")
    helper.capture(source, artifact, limits)
    with pytest.raises(VolumeArchiveError, match="artifact_corrupt"):
        helper.restore(artifact / "archive.tar.gz", scratch, target, "0" * 64, limits)
    assert list(target.iterdir()) == []


def test_refuses_existing_archive_and_nonempty_destination(tree, limits):
    source, artifact, target, scratch = tree
    captured = helper.capture(source, artifact, limits)
    with pytest.raises(VolumeArchiveError, match="artifact_exists"):
        helper.capture(source, artifact, limits)
    (target / "keep").write_text("untouched")
    with pytest.raises(VolumeArchiveError, match="destination_exists"):
        helper.restore(
            artifact / "archive.tar.gz", scratch, target, captured["sha256"], limits
        )
    assert (target / "keep").read_text() == "untouched"


def test_private_staging_required(tree, limits):
    source, artifact, _, _ = tree
    artifact.chmod(0o755)
    with pytest.raises(VolumeArchiveError, match="unsafe_staging_root"):
        helper.capture(source, artifact, limits)


def test_deadline_and_compressed_output_limits(tree, limits):
    source, artifact, _, _ = tree
    (source / "file").write_bytes(b"data")
    with pytest.raises(VolumeArchiveError, match="archive_compressed_limit"):
        helper.capture(source, artifact, replace(limits, max_compressed_bytes=1))
    assert not (artifact / "archive.tar.gz").exists()
