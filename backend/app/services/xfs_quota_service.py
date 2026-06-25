"""XFS project quota integration for kernel-enforced volume size limits.

Provides real-time disk enforcement by assigning a unique XFS project ID to each
volume directory and setting a hard byte limit. Works alongside the periodic
du-based enforcement task (which serves as fallback on non-XFS filesystems).

Requirements:
    - Host filesystem must be XFS mounted with prjquota
    - xfsprogs installed on host (xfs_quota, xfs_io)
    - Container must have CAP_SYS_ADMIN or run privileged to run xfs_quota

Setup on host:
    mount -o remount,prjquota /var/lib/docker/volumes
    # or in fstab:
    /dev/sdXn /var/lib/docker/volumes xfs defaults,prjquota 0 0
"""

import hashlib
import os
import subprocess

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class XfsQuotaService:
    """Manage XFS project quotas for volume directories."""

    def __init__(self):
        self.enabled = settings.xfs_quota_enabled
        self.project_id_start = settings.xfs_project_id_start
        self.projects_file = settings.xfs_projects_file
        self._xfs_checked = False
        self._xfs_available = False

    def _is_xfs(self, path: str) -> bool:
        """Check if the given path resides on an XFS filesystem."""
        try:
            result = subprocess.run(
                ["stat", "-f", "-c", "%T", path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0 and "xfs" in result.stdout.lower()
        except Exception:
            return False

    def _has_cap_sys_admin(self) -> bool:
        """Check if we have CAP_SYS_ADMIN (required for xfs_quota)."""
        try:
            result = subprocess.run(
                ["xfs_quota", "-x", "-c", "state", "/"],
                capture_output=True,
                timeout=5,
            )
            return not (result.returncode != 0 and "permission" in result.stderr.lower())
        except Exception:
            return False

    def _xfs_quota_available(self) -> bool:
        """Check if xfs_quota binary is available and the volume path is on XFS."""
        if self._xfs_checked:
            return self._xfs_available

        try:
            result = subprocess.run(
                ["which", "xfs_quota"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                self._xfs_checked = True
                self._xfs_available = False
                return False
        except Exception:
            self._xfs_checked = True
            self._xfs_available = False
            return False

        check_path = settings.volume_storage_path or "/var/lib/docker/volumes"
        is_xfs = self._is_xfs(check_path)

        if not is_xfs:
            self._xfs_checked = True
            self._xfs_available = False
            logger.warning(
                "XFS project quotas not available: path %s is not XFS",
                check_path,
            )
            return False

        has_cap = self._has_cap_sys_admin()
        self._xfs_available = has_cap
        self._xfs_checked = True

        if has_cap:
            logger.info("XFS project quotas available on %s", check_path)
        else:
            logger.warning(
                "XFS project quotas not available: xfs_quota found but "
                "CAP_SYS_ADMIN missing (run container privileged or add cap)"
            )

        return self._xfs_available

    def _get_volume_path(self, volume_name: str) -> str | None:
        """Resolve the host filesystem path for a named volume."""
        candidates = []

        if settings.volume_storage_path:
            candidates.append(os.path.join(settings.volume_storage_path, volume_name, "_data"))

        candidates.append(f"/var/lib/docker/volumes/{volume_name}/_data")
        candidates.append(f"/var/lib/containers/storage/volumes/{volume_name}/_data")
        candidates.append(
            f"{os.path.expanduser('~')}/.local/share/containers/storage/volumes/{volume_name}/_data"
        )

        for path in candidates:
            if os.path.exists(os.path.dirname(path)):
                return path

        return candidates[0] if candidates else None

    def _find_mountpoint(self, path: str) -> str:
        """Find the filesystem mountpoint for a given path."""
        path = os.path.abspath(path)
        if not os.path.exists(path):
            while path and not os.path.exists(path):
                path = os.path.dirname(path)
            if not path:
                return "/"

        st = os.lstat(path)
        current_dev = st.st_dev

        while True:
            parent = os.path.dirname(path)
            if parent == path:
                return path
            try:
                parent_dev = os.lstat(parent).st_dev
            except OSError:
                return path
            if parent_dev != current_dev:
                return path
            path = parent

    def _project_id(self, volume_name: str) -> int:
        """Deterministically generate a unique project ID for a volume.

        Uses MD5 (not Python's randomized hash()) so IDs are stable
        across process restarts.
        """
        h = int(hashlib.md5(volume_name.encode("utf-8")).hexdigest(), 16)
        return self.project_id_start + (h % 1_000_000)

    def _write_project_entry(self, project_id: int, volume_path: str) -> bool:
        """Append or update the project definition in the custom projects file.

        Returns False if the file cannot be written.
        """
        projects_file = self.projects_file

        parent = os.path.dirname(projects_file)
        if parent and not os.path.exists(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError:
                logger.error("Cannot create directory %s for XFS project files", parent)
                return False

        if os.path.exists(projects_file) and not os.access(projects_file, os.W_OK):
            logger.error("XFS project file %s is not writable", projects_file)
            return False
        if parent and not os.access(parent, os.W_OK):
            logger.error("XFS project directory %s is not writable", parent)
            return False

        _update_line(projects_file, f"{project_id}:{volume_path}")
        return True

    def _remove_project_entry(self, project_id: int) -> None:
        """Remove a project definition from the custom projects file."""
        _remove_line(self.projects_file, f"{project_id}:")

    def _run_xfs_quota(self, *commands: str, mountpoint: str) -> subprocess.CompletedProcess:
        """Run xfs_quota with -D pointing to our custom projects file."""
        cmd = [
            "xfs_quota",
            "-x",
            "-D",
            self.projects_file,
            "-c",
            " ".join(commands),
            mountpoint,
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def set_quota(self, volume_name: str, bytes_limit: int) -> bool:
        """Apply an XFS project quota hard limit to a volume directory.

        Returns True if quota was set, False if XFS is unavailable or failed.
        Logs errors but never raises — callers should check the return value.
        """
        if not self.enabled:
            return False
        if not self._xfs_quota_available():
            return False

        volume_path = self._get_volume_path(volume_name)
        if not volume_path:
            logger.warning("Cannot resolve host path for volume %s", volume_name)
            return False

        try:
            os.makedirs(volume_path, exist_ok=True)
        except OSError as e:
            logger.error("Cannot create volume directory %s: %s", volume_path, e)
            return False

        project_id = self._project_id(volume_name)
        mountpoint = self._find_mountpoint(volume_path)

        if not self._write_project_entry(project_id, volume_path):
            logger.error("Cannot write XFS project files for %s", volume_name)
            return False

        # Set project inheritance flag on the directory
        try:
            subprocess.run(
                ["xfs_io", "-c", "chattr +P", volume_path],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception as e:
            logger.warning("xfs_io chattr +P failed for %s: %s", volume_name, e)

        # Initialize the project in xfs_quota (numeric ID + path)
        result = self._run_xfs_quota(
            f"project -s -p {volume_path} {project_id}",
            mountpoint=mountpoint,
        )
        if result.returncode != 0:
            logger.error(
                "xfs_quota project setup failed for %s (mount=%s): %s",
                volume_name,
                mountpoint,
                result.stderr.strip(),
            )
            return False

        # Set hard byte limit
        result = self._run_xfs_quota(
            f"limit -p bhard={bytes_limit} {project_id}",
            mountpoint=mountpoint,
        )
        if result.returncode != 0:
            logger.error(
                "xfs_quota limit failed for %s (mount=%s): %s",
                volume_name,
                mountpoint,
                result.stderr.strip(),
            )
            return False

        logger.info(
            "XFS quota set: volume=%s project=%s mount=%s limit=%s bytes",
            volume_name,
            project_id,
            mountpoint,
            bytes_limit,
        )
        return True

    def remove_quota(self, volume_name: str) -> bool:
        """Remove the XFS project quota for a volume."""
        if not self.enabled:
            return False
        if not self._xfs_quota_available():
            return False

        volume_path = self._get_volume_path(volume_name)
        if not volume_path:
            return False

        project_id = self._project_id(volume_name)
        mountpoint = self._find_mountpoint(volume_path)

        result = self._run_xfs_quota(
            f"limit -p bhard=0 {project_id}",
            mountpoint=mountpoint,
        )
        if result.returncode != 0:
            logger.warning(
                "xfs_quota clear failed for %s: %s",
                volume_name,
                result.stderr.strip(),
            )

        self._remove_project_entry(project_id)
        logger.info("XFS quota removed: volume=%s", volume_name)
        return True

    def update_quota(self, volume_name: str, bytes_limit: int) -> bool:
        """Update an existing XFS project quota limit."""
        return self.set_quota(volume_name, bytes_limit)

    def get_quota_usage(self, volume_name: str) -> dict | None:
        """Return current usage and limit for a volume's project quota."""
        if not self.enabled or not self._xfs_quota_available():
            return None

        volume_path = self._get_volume_path(volume_name)
        if not volume_path:
            return None

        project_id = self._project_id(volume_name)
        mountpoint = self._find_mountpoint(volume_path)

        result = self._run_xfs_quota(
            f"report -p -b -N -L {project_id} -U {project_id}",
            mountpoint=mountpoint,
        )
        if result.returncode != 0:
            return None

        lines = result.stdout.strip().splitlines()
        for line in lines:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    used = _parse_quota_value(parts[1])
                    soft = _parse_quota_value(parts[2])
                    hard = _parse_quota_value(parts[3])
                    if used is not None and hard is not None:
                        return {
                            "used_bytes": used,
                            "soft_limit_bytes": soft,
                            "hard_limit_bytes": hard,
                        }
                except ValueError:
                    continue
        return None


def _parse_quota_value(value: str) -> int | None:
    """Parse a quota value from xfs_quota output."""
    if value.lower() in ("none", "0", "-"):
        return 0
    try:
        return int(value)
    except ValueError:
        return None


def _update_line(filepath: str, line_prefix: str) -> None:
    """Upsert a line in a text file (matched by prefix before ':')."""
    key = line_prefix.split(":", 1)[0]
    lines = []
    found = False

    if os.path.exists(filepath):
        with open(filepath) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith(key + ":"):
                    lines.append(line_prefix + "\n")
                    found = True
                else:
                    lines.append(line)

    if not found:
        lines.append(line_prefix + "\n")

    with open(filepath, "w") as f:
        f.writelines(lines)


def _remove_line(filepath: str, prefix: str) -> None:
    """Remove lines starting with the given prefix from a text file."""
    if not os.path.exists(filepath):
        return

    with open(filepath) as f:
        lines = f.readlines()

    with open(filepath, "w") as f:
        for line in lines:
            if not line.strip().startswith(prefix):
                f.write(line)


# Singleton
xfs_quota_service = XfsQuotaService()
