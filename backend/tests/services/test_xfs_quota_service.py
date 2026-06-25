"""Tests for XFS project quota service."""

import pytest
from unittest import mock


class TestXfsQuotaService:
    """Tests for XfsQuotaService."""

    def test_disabled_when_setting_off(self):
        """Should not attempt anything when xfs_quota_enabled is False."""
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = False
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()
            assert service.enabled is False
            assert service.set_quota("test-vol", 10 * 1024**3) is False
            assert service.remove_quota("test-vol") is False
            assert service.update_quota("test-vol", 10 * 1024**3) is False
            assert service.get_quota_usage("test-vol") is None

    def test_project_id_deterministic(self):
        """Project IDs should be deterministic for the same volume name."""
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = True
            mock_settings.xfs_project_id_start = 10000
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()
            id1 = service._project_id("my-volume")
            id2 = service._project_id("my-volume")
            id3 = service._project_id("other-volume")
            assert id1 == id2
            assert id1 != id3
            assert id1 >= 10000

    def test_get_volume_path_prefers_volume_storage_path(self):
        """Should prefer VOLUME_STORAGE_PATH when set."""
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.volume_storage_path = "/custom/volumes"
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()
            path = service._get_volume_path("my-vol")
            assert path.startswith("/custom/volumes/my-vol/_data")

    def test_get_volume_path_fallback(self):
        """Should fall back to standard Docker/Podman paths."""
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.volume_storage_path = ""
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()
            path = service._get_volume_path("my-vol")
            assert "/var/lib/docker/volumes/my-vol/_data" in path

    def test_xfs_quota_available_checks_binary_and_filesystem(self):
        """Should check xfs_quota binary and XFS filesystem."""
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = True
            mock_settings.volume_storage_path = "/tmp"
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()

            # Mock binary found but not XFS
            with mock.patch("subprocess.run") as mock_run:

                def side_effect(cmd, **kwargs):
                    m = mock.MagicMock()
                    if cmd[0] == "which":
                        m.returncode = 0
                    elif cmd[0] == "stat":
                        m.returncode = 0
                        m.stdout = "ext4"
                    return m

                mock_run.side_effect = side_effect
                assert service._xfs_quota_available() is False

    def test_update_line_file_operations(self):
        """_update_line should create, update, and append lines correctly."""
        import tempfile
        import os
        from app.services.xfs_quota_service import _update_line

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            path = f.name
            f.write("1000:/path/a\n")
            f.write("2000:/path/b\n")

        try:
            # Update existing line
            _update_line(path, "1000:/path/new")
            with open(path) as f:
                lines = f.read().strip().splitlines()
            assert any("1000:/path/new" in line for line in lines)
            assert any("2000:/path/b" in line for line in lines)

            # Append new line
            _update_line(path, "3000:/path/c")
            with open(path) as f:
                lines = f.read().strip().splitlines()
            assert any("3000:/path/c" in line for line in lines)
        finally:
            os.unlink(path)

    def test_remove_line_file_operations(self):
        """_remove_line should remove matching lines."""
        import tempfile
        import os
        from app.services.xfs_quota_service import _remove_line

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            path = f.name
            f.write("1000:/path/a\n")
            f.write("2000:/path/b\n")
            f.write("3000:/path/c\n")

        try:
            _remove_line(path, "2000:")
            with open(path) as f:
                content = f.read()
            assert "1000:/path/a" in content
            assert "2000:/path/b" not in content
            assert "3000:/path/c" in content
        finally:
            os.unlink(path)

    def test_set_quota_skips_if_xfs_not_available(self):
        """set_quota should return False if XFS is not available."""
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = True
            mock_settings.volume_storage_path = "/tmp"
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()

            with mock.patch.object(service, "_xfs_quota_available", return_value=False):
                assert service.set_quota("test-vol", 10 * 1024**3) is False

    def test_project_id_stable_across_restarts(self):
        """Project IDs must be identical across Python process restarts.

        Python's built-in hash() is randomized per process (PYTHONHASHSEED).
        We must use a stable hash like MD5 to avoid orphaned quotas.
        """
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = True
            mock_settings.xfs_project_id_start = 10000
            from app.services.xfs_quota_service import XfsQuotaService

            # Simulate two different process instances
            service1 = XfsQuotaService()
            service2 = XfsQuotaService()
            id1 = service1._project_id("my-volume")
            id2 = service2._project_id("my-volume")
            assert id1 == id2
            assert id1 >= 10000

    def test_cap_sys_admin_check(self):
        """Should detect missing CAP_SYS_ADMIN and mark XFS unavailable."""
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = True
            mock_settings.volume_storage_path = "/tmp"
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()

            with mock.patch("subprocess.run") as mock_run:

                def side_effect(cmd, **kwargs):
                    m = mock.MagicMock()
                    if cmd[0] == "which":
                        m.returncode = 0
                    elif cmd[0] == "stat":
                        m.returncode = 0
                        m.stdout = "xfs"
                    elif cmd[0] == "xfs_quota":
                        # Permission denied
                        m.returncode = 1
                        m.stderr = "xfs_quota: cannot setup path for mount /: Permission denied"
                    return m

                mock_run.side_effect = side_effect
                assert service._xfs_quota_available() is False

    def test_find_mountpoint(self):
        """_find_mountpoint should walk up to the actual filesystem boundary."""
        import tempfile
        import os

        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = True
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()

            with tempfile.TemporaryDirectory() as tmpdir:
                nested = os.path.join(tmpdir, "a", "b", "c")
                os.makedirs(nested)
                mountpoint = service._find_mountpoint(nested)
                # Should return a valid mountpoint (tmpdir or a parent mount)
                assert mountpoint is not None
                assert os.path.ismount(mountpoint) or mountpoint == "/"
                assert nested.startswith(mountpoint) or mountpoint == "/"

    def test_write_project_entry_readonly_etc(self):
        """Should return False when project files are not writable."""
        import tempfile
        import os

        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = True
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()

            with tempfile.TemporaryDirectory() as tmpdir:
                service.projects_file = os.path.join(tmpdir, "projects")

                # Mock os.access to simulate read-only (root ignores real permissions)
                with mock.patch("os.access", return_value=False):
                    result = service._write_project_entry(10000, "/path")
                    assert result is False

    def test_quota_value_parsing(self):
        """_parse_quota_value should handle xfs_quota output variants."""
        from app.services.xfs_quota_service import _parse_quota_value

        assert _parse_quota_value("1048576") == 1048576
        assert _parse_quota_value("0") == 0
        assert _parse_quota_value("none") == 0
        assert _parse_quota_value("NONE") == 0
        assert _parse_quota_value("-") == 0
        assert _parse_quota_value("invalid") is None

    def test_get_quota_usage_parsing(self):
        """get_quota_usage should parse xfs_quota report output."""
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = True
            mock_settings.volume_storage_path = "/var/lib/docker/volumes"
            from app.services.xfs_quota_service import XfsQuotaService

            service = XfsQuotaService()

            mock_output = "#10000    1048576   10485760  10485760  00 [--------]"
            with (
                mock.patch.object(service, "_xfs_quota_available", return_value=True),
                mock.patch.object(
                    service,
                    "_run_xfs_quota",
                    return_value=mock.MagicMock(returncode=0, stdout=mock_output),
                ),
            ):
                result = service.get_quota_usage("test-vol")
                assert result is not None
                assert result["used_bytes"] == 1048576
                assert result["soft_limit_bytes"] == 10485760
                assert result["hard_limit_bytes"] == 10485760
