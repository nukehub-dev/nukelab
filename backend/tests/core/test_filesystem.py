"""Tests for app.core.filesystem security utilities."""

import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.filesystem import secure_path, validate_avatar_filename


class TestSecurePath:
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_valid_subpath(self, temp_dir):
        result = secure_path(temp_dir, "subdir/file.txt")
        assert result == temp_dir / "subdir" / "file.txt"

    def test_traversal_blocked(self, temp_dir):
        with pytest.raises(HTTPException) as exc_info:
            secure_path(temp_dir, "../../etc/passwd")
        assert exc_info.value.status_code == 403
        assert "traversal" in exc_info.value.detail.lower()

    def test_absolute_path_normalized(self, temp_dir):
        # Absolute paths are sanitized by stripping leading slash
        result = secure_path(temp_dir, "/etc/passwd")
        assert result == temp_dir / "etc" / "passwd"

    def test_dot_dot_in_middle(self, temp_dir):
        # Creating a real subdir so resolve works
        (temp_dir / "a" / "b").mkdir(parents=True)
        (temp_dir / "c").mkdir()
        result = secure_path(temp_dir, "a/b/../../c")
        assert result == temp_dir / "c"

    def test_single_dot_allowed(self, temp_dir):
        result = secure_path(temp_dir, "./file.txt")
        assert result == temp_dir / "file.txt"

    def test_empty_subpath(self, temp_dir):
        result = secure_path(temp_dir, "")
        assert result == temp_dir

    def test_existing_file(self, temp_dir):
        # Create a real file
        test_file = temp_dir / "test.txt"
        test_file.write_text("hello")
        result = secure_path(temp_dir, "test.txt")
        assert result.exists()


class TestValidateAvatarFilename:
    def test_valid_uuid_png(self):
        validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.png")

    def test_valid_uuid_jpg(self):
        validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.jpg")

    def test_valid_uuid_webp(self):
        validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.webp")

    def test_valid_uuid_gif(self):
        validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.gif")

    def test_invalid_extension(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.exe")
        assert exc_info.value.status_code == 400

    def test_invalid_filename(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_avatar_filename("../../../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_no_extension(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_avatar_filename("avatar")
        assert exc_info.value.status_code == 400

    def test_uppercase_extension_blocked(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_avatar_filename("550e8400-e29b-41d4-a716-446655440000.PNG")
        assert exc_info.value.status_code == 400
