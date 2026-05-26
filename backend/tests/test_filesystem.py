"""Tests for filesystem security utilities."""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.filesystem import secure_path, validate_avatar_filename


class TestSecurePath:
    """Unit tests for the secure_path() traversal prevention utility."""

    def test_normal_filename_resolves_correctly(self):
        """A benign filename should resolve normally inside the base directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = secure_path(tmpdir, "subdir/file.txt")
            assert target == Path(tmpdir) / "subdir" / "file.txt"

    def test_dotdot_traversal_raises_403(self):
        """Path traversal via .. should be rejected with 403."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(HTTPException) as exc_info:
                secure_path(tmpdir, "../../../etc/passwd")
            assert exc_info.value.status_code == 403
            assert "traversal" in exc_info.value.detail.lower()

    def test_absolute_path_is_normalized_safe(self):
        """Leading slashes are stripped, making absolute paths relative and safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = secure_path(tmpdir, "/etc/passwd")
            # /etc/passwd becomes etc/passwd inside tmpdir
            assert target == Path(tmpdir) / "etc" / "passwd"

    def test_leading_slash_is_stripped_and_allowed(self):
        """Leading slashes on otherwise-safe paths should be stripped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = secure_path(tmpdir, "/safe.txt")
            assert target == Path(tmpdir) / "safe.txt"

    def test_symlink_within_base_allowed(self):
        """Symlinks that point inside the base directory are allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            real_file = Path(tmpdir) / "real.txt"
            real_file.write_text("hello")
            symlink = Path(tmpdir) / "link.txt"
            symlink.symlink_to(real_file)

            target = secure_path(tmpdir, "link.txt")
            assert target.resolve() == real_file.resolve()

    def test_symlink_escaping_base_raises_403(self):
        """Symlinks that escape the base directory should be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outside = Path(tmpdir).parent / "outside.txt"
            outside.write_text("secret")
            symlink = Path(tmpdir) / "evil.txt"
            symlink.symlink_to(outside)

            with pytest.raises(HTTPException) as exc_info:
                secure_path(tmpdir, "evil.txt")
            assert exc_info.value.status_code == 403

    def test_null_byte_in_path(self):
        """Pathlib should reject null bytes (defense against null-byte injection)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Path() itself raises ValueError on null bytes
            with pytest.raises((ValueError, HTTPException)):
                secure_path(tmpdir, "foo\x00.txt")


class TestValidateAvatarFilename:
    """Unit tests for avatar filename validation."""

    def test_valid_uuid_filenames(self):
        """Standard avatar filenames should pass validation."""
        validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.png")
        validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.jpg")
        validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.jpeg")
        validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.webp")
        validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.gif")

    def test_traversal_filename_rejected(self):
        """Traversal patterns should be rejected."""
        with pytest.raises(HTTPException) as exc_info:
            validate_avatar_filename("../../../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_no_extension_rejected(self):
        """Filenames without extension should be rejected."""
        with pytest.raises(HTTPException) as exc_info:
            validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000")
        assert exc_info.value.status_code == 400

    def test_disallowed_extension_rejected(self):
        """Non-image extensions should be rejected."""
        with pytest.raises(HTTPException) as exc_info:
            validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.exe")
        assert exc_info.value.status_code == 400
