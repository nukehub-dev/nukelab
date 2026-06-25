"""Integration-style tests for XFS quota service using mocked subprocess.

These tests simulate the full xfs_quota command flow without requiring
an actual XFS filesystem. They verify that the service constructs the
correct commands and handles all output formats.
"""

import pytest
from unittest import mock
import tempfile
import os


class TestXfsQuotaFullFlow:
    """Simulate the complete set_quota → get_quota_usage → remove_quota cycle."""

    @pytest.fixture
    def service(self):
        with mock.patch("app.services.xfs_quota_service.settings") as mock_settings:
            mock_settings.xfs_quota_enabled = True
            mock_settings.xfs_project_id_start = 10000
            mock_settings.xfs_projects_file = "/tmp/test-projects"
            mock_settings.volume_storage_path = "/tmp/test-volumes"
            from app.services.xfs_quota_service import XfsQuotaService

            svc = XfsQuotaService()
            # Bypass the availability check
            svc._xfs_checked = True
            svc._xfs_available = True
            yield svc
            # Cleanup temp file
            if os.path.exists(svc.projects_file):
                os.unlink(svc.projects_file)

    def test_full_quota_lifecycle(self, service):
        """Set, verify, and remove a quota — simulating xfs_quota responses."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service.projects_file = os.path.join(tmpdir, "projects")
            vol_path = os.path.join(tmpdir, "vol1", "_data")
            os.makedirs(vol_path, exist_ok=True)

            # Mock _get_volume_path to return our test path
            with mock.patch.object(service, "_get_volume_path", return_value=vol_path):
                # Mock _find_mountpoint
                with mock.patch.object(service, "_find_mountpoint", return_value=tmpdir):
                    call_log = []

                    def mock_run(cmd, **kwargs):
                        """Simulate xfs_quota and xfs_io commands."""
                        call_log.append(" ".join(cmd))
                        m = mock.MagicMock()
                        m.returncode = 0
                        m.stderr = ""

                        if "xfs_io" in cmd:
                            m.stdout = ""
                        elif "project -s" in " ".join(cmd):
                            m.stdout = "Setting up project... done"
                        elif "limit -p" in " ".join(cmd) and "bhard=" in " ".join(cmd):
                            m.stdout = ""
                        elif "report -p" in " ".join(cmd):
                            # Simulate xfs_quota -N output
                            m.stdout = "#10000    1048576   5242880   5242880   00 [--------]"
                        elif "limit -p bhard=0" in " ".join(cmd):
                            m.stdout = ""
                        else:
                            m.stdout = ""
                        return m

                    with mock.patch("subprocess.run", side_effect=mock_run):
                        # 1. Set quota
                        result = service.set_quota("vol1", 5 * 1024**3)
                        assert result is True
                        assert any("project -s" in c for c in call_log)
                        assert any("limit -p bhard=" in c for c in call_log)
                        # Verify -D flag is passed for custom projects file
                        assert any("-D" in c for c in call_log)

                        # 2. Verify project file was written
                        expected_pid = str(service._project_id("vol1"))
                        with open(service.projects_file) as f:
                            projects = f.read()
                        assert f"{expected_pid}:" in projects
                        assert vol_path in projects

                        # 3. Get usage
                        usage = service.get_quota_usage("vol1")
                        assert usage is not None
                        assert usage["used_bytes"] == 1048576
                        assert usage["hard_limit_bytes"] == 5242880

                        # 4. Remove quota
                        result = service.remove_quota("vol1")
                        assert result is True
                        assert any("limit -p bhard=0" in c for c in call_log)

                        # Verify project entries cleaned up
                        with open(service.projects_file) as f:
                            assert expected_pid not in f.read()

    def test_quota_set_fails_when_project_setup_errors(self, service):
        """Should return False if xfs_quota project setup fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service.projects_file = os.path.join(tmpdir, "projects")
            vol_path = os.path.join(tmpdir, "vol2", "_data")
            os.makedirs(vol_path, exist_ok=True)

            with mock.patch.object(service, "_get_volume_path", return_value=vol_path):
                with mock.patch.object(service, "_find_mountpoint", return_value=tmpdir):

                    def mock_run(cmd, **kwargs):
                        m = mock.MagicMock()
                        if "project -s" in " ".join(cmd):
                            m.returncode = 1
                            m.stderr = "xfs_quota: cannot setup path: No such file or directory"
                        else:
                            m.returncode = 0
                            m.stderr = ""
                        m.stdout = ""
                        return m

                    with mock.patch("subprocess.run", side_effect=mock_run):
                        result = service.set_quota("vol2", 10 * 1024**3)
                        assert result is False

    def test_quota_set_fails_when_limit_command_errors(self, service):
        """Should return False if xfs_quota limit command fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service.projects_file = os.path.join(tmpdir, "projects")
            vol_path = os.path.join(tmpdir, "vol3", "_data")
            os.makedirs(vol_path, exist_ok=True)

            with mock.patch.object(service, "_get_volume_path", return_value=vol_path):
                with mock.patch.object(service, "_find_mountpoint", return_value=tmpdir):

                    def mock_run(cmd, **kwargs):
                        m = mock.MagicMock()
                        if "limit -p" in " ".join(cmd) and "bhard=" in " ".join(cmd):
                            m.returncode = 1
                            m.stderr = "xfs_quota: cannot set limit: Invalid argument"
                        else:
                            m.returncode = 0
                            m.stderr = ""
                        m.stdout = ""
                        return m

                    with mock.patch("subprocess.run", side_effect=mock_run):
                        result = service.set_quota("vol3", 10 * 1024**3)
                        assert result is False

    def test_get_quota_usage_handles_various_output_formats(self, service):
        """Should parse different xfs_quota -N output formats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service.projects_file = os.path.join(tmpdir, "projects")

            with mock.patch.object(service, "_get_volume_path", return_value="/fake/path"):
                with mock.patch.object(service, "_find_mountpoint", return_value=tmpdir):
                    test_cases = [
                        # (stdout, expected_used, expected_hard)
                        ("#10000    1048576   5242880   5242880   00 [--------]", 1048576, 5242880),
                        ("10000     2097152   10485760  10485760  00", 2097152, 10485760),
                        ("#10000    0         none      5242880   00", 0, 5242880),
                        ("#10000    0         0         0         00", 0, 0),
                    ]

                    for stdout, expected_used, expected_hard in test_cases:

                        def mock_run(cmd, **kwargs):
                            m = mock.MagicMock()
                            m.returncode = 0
                            m.stdout = stdout
                            m.stderr = ""
                            return m

                        with mock.patch("subprocess.run", side_effect=mock_run):
                            usage = service.get_quota_usage("vol-format-test")
                            assert usage is not None, f"Failed to parse: {stdout}"
                            assert usage["used_bytes"] == expected_used
                            assert usage["hard_limit_bytes"] == expected_hard
