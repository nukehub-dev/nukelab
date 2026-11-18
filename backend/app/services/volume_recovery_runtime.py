# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Trusted helper execution and private UUID artifact paths, never user filesystem paths."""

import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path
from uuid import UUID

from app.config import settings
from app.container.driver import ContainerDriverError
from app.services.volume_archive_service import ArchiveLimits


class RuntimeRecoveryError(ValueError):
    def __init__(self, code, *, executor_terminated=False, artifacts_removed=False):
        self.code = code
        self.executor_terminated = executor_terminated
        self.artifacts_removed = artifacts_removed
        super().__init__(code)


class VolumeRecoveryRuntime:
    def __init__(self, driver, *, storage_root=None, host_root=None, helper_image=None):
        self.driver = driver
        self.storage_root = (
            Path(storage_root or settings.volume_backup_storage_path)
            if (storage_root or settings.volume_backup_storage_path)
            else None
        )
        self.host_root = (
            Path(host_root or settings.volume_backup_host_path)
            if (host_root or settings.volume_backup_host_path)
            else None
        )
        self.helper_image = helper_image or settings.volume_backup_helper_image
        self.timeout = settings.volume_backup_timeout_seconds
        self.image = None

    def _storage(self):
        if self.storage_root is None or self.host_root is None:
            raise RuntimeRecoveryError("storage_unconfigured", executor_terminated=True)
        for path in (self.storage_root, self.host_root):
            if not path.is_absolute() or ".." in path.parts:
                raise RuntimeRecoveryError("storage_unavailable", executor_terminated=True)
        try:
            value = self.storage_root.lstat()
            if (
                not stat.S_ISDIR(value.st_mode)
                or value.st_uid != 65532
                or value.st_gid != 65532
                or value.st_mode & 0o077
                or not os.access(self.storage_root, os.W_OK | os.X_OK)
            ):
                raise OSError("private storage required")
        except OSError:
            raise RuntimeRecoveryError("storage_unavailable", executor_terminated=True) from None
        return self.storage_root

    def available_bytes(self):
        try:
            return shutil.disk_usage(self._storage()).free
        except OSError:
            raise RuntimeRecoveryError("storage_unavailable", executor_terminated=True) from None

    async def check_helper(self):
        self._storage()
        try:
            if not await self.driver.image_exists(self.helper_image):
                raise RuntimeRecoveryError("helper_unavailable", executor_terminated=True)
            identity = await self.driver.resolve_image(self.helper_image)
            image = identity.get("local_id")
            if not isinstance(image, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
                raise RuntimeRecoveryError("helper_unavailable", executor_terminated=True)
            self.image = image
            return image
        except RuntimeRecoveryError:
            raise
        except Exception:
            raise RuntimeRecoveryError("helper_unavailable", executor_terminated=True) from None

    @staticmethod
    def _platform_container(info):
        """Trusted orchestration containers may bind the private storage root."""
        labels = (info.get("Config") or {}).get("Labels") or {}
        return labels.get("com.docker.compose.service") in {
            "backend",
            "celery-worker",
            "celery-beat",
            "backend-test",
        }

    async def assert_detached(self, volume_name):
        try:
            volume = await self.driver.get_volume(volume_name)
            if volume is not None and (
                not isinstance(volume, dict) or volume.get("Name") != volume_name
            ):
                raise ValueError("inspection unavailable")
            mountpoint = volume.get("Mountpoint") if volume is not None else None
            if mountpoint is not None:
                if (
                    not isinstance(mountpoint, str)
                    or not Path(mountpoint).is_absolute()
                    or ".." in Path(mountpoint).parts
                    or "\x00" in mountpoint
                ):
                    raise ValueError("inspection unavailable")
                mountpoint = Path("/" + mountpoint.lstrip("/"))
            containers = await self.driver.list_containers(all=True)
            if not isinstance(containers, list):
                raise ValueError("inspection unavailable")
            for container in containers:
                if not isinstance(container, dict) or not isinstance(container.get("Id"), str):
                    raise ValueError("inspection unavailable")
                info = await self.driver.get_container_info(container["Id"])
                # Platform services bind the whole storage root (for example,
                # VOLUME_STORAGE_PATH equals the daemon's volume root). They
                # are trusted orchestration containers, not user workloads,
                # and their parent-path bind must not mark every child volume
                # as attached.
                if self._platform_container(info):
                    continue
                mounts = info.get("Mounts")
                if not isinstance(mounts, list):
                    raise ValueError("inspection unavailable")
                for mount in mounts:
                    if not isinstance(mount, dict):
                        raise ValueError("inspection unavailable")
                    kind = mount.get("Type")
                    if kind == "volume":
                        if not isinstance(mount.get("Name"), str) or not mount["Name"]:
                            raise ValueError("inspection unavailable")
                        if mount["Name"] == volume_name:
                            raise RuntimeRecoveryError("volume_attached", executor_terminated=True)
                    elif kind == "bind":
                        source = mount.get("Source")
                        if (
                            not isinstance(source, str)
                            or not Path(source).is_absolute()
                            or ".." in Path(source).parts
                            or "\x00" in source
                            or (volume is not None and mountpoint is None)
                        ):
                            raise ValueError("inspection unavailable")
                        source = Path("/" + source.lstrip("/"))
                        if mountpoint is not None and (
                            source == mountpoint
                            or source in mountpoint.parents
                            or mountpoint in source.parents
                        ):
                            raise RuntimeRecoveryError("volume_attached", executor_terminated=True)
                    elif kind != "tmpfs":
                        raise ValueError("inspection unavailable")
        except RuntimeRecoveryError:
            raise
        except Exception:
            raise RuntimeRecoveryError(
                "runtime_inspection_unavailable", executor_terminated=True
            ) from None

    @staticmethod
    def _uuid(value):
        try:
            return str(UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            raise RuntimeRecoveryError("invalid_operation", executor_terminated=True) from None

    def _directory(self, relative, *, create=False):
        current = self._storage()
        for component in Path(relative).parts:
            if component in ("", ".", "..") or "/" in component:
                raise RuntimeRecoveryError("invalid_operation", executor_terminated=True)
            current = current / component
            if create:
                try:
                    current.mkdir(mode=0o700)
                    if os.getuid() == 0:
                        os.chown(current, 65532, 65532)
                except FileExistsError:
                    pass
            value = current.lstat()
            if (
                not stat.S_ISDIR(value.st_mode)
                or value.st_uid != 65532
                or value.st_gid != 65532
                or value.st_mode & 0o077
            ):
                raise RuntimeRecoveryError("storage_unavailable", executor_terminated=True)
        return current

    def _host(self, relative):
        return str(self.host_root / relative)

    def _limits(self, maximum):
        if (
            type(maximum) is not int
            or maximum <= 0
            or maximum > settings.volume_backup_max_logical_bytes
        ):
            raise RuntimeRecoveryError("invalid_operation", executor_terminated=True)
        raw = maximum + settings.volume_backup_max_members * 4096 + 8 * 1024**2
        return ArchiveLimits(
            max_compressed_bytes=raw,
            max_tar_bytes=raw,
            max_file_bytes=maximum,
            max_logical_bytes=maximum,
            max_members=settings.volume_backup_max_members,
            timeout_seconds=self.timeout,
            max_expansion_ratio=10000,
        )

    @staticmethod
    def _labels(operation, fence, backup):
        return {
            "nukelab.managed": "true",
            "nukelab.recovery.operation": operation,
            "nukelab.recovery.fence": fence,
            "nukelab.recovery.backup": backup,
        }

    async def _info(self, identity):
        try:
            return await self.driver.get_container_info(identity)
        except ContainerDriverError as error:
            if error.status == 404:
                return None
            raise

    def _owned(self, info, labels):
        return bool(
            info
            and info.get("Image") == self.image
            and all(
                (info.get("Config", {}).get("Labels") or {}).get(key) == value
                for key, value in labels.items()
            )
        )

    async def _terminated(self, identity, labels, *, stop=False):
        try:
            info = await self._info(identity)
            if info is None:
                return True
            if not self._owned(info, labels):
                return False
            state = info.get("State") or {}
            if state.get("Running") is True and stop:
                await self.driver.stop_container(identity, timeout=10)
                info = await self._info(identity)
                if info is None:
                    return True
                if not self._owned(info, labels):
                    return False
                state = info.get("State") or {}
            return state.get("Running") is False and state.get("Status") in ("exited", "dead")
        except Exception:
            return False

    def _metadata(self, work, operation, fence, backup, action, limits):
        path = work / "completion.json"
        value = path.lstat()
        if not stat.S_ISREG(value.st_mode) or value.st_size > 8192 or value.st_uid != 65532:
            raise ValueError("invalid completion")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding="utf-8") as source:
            result = json.load(source)
        if not isinstance(result, dict) or any(
            result.get(key) != expected
            for key, expected in {
                "operation_id": operation,
                "fencing_token": fence,
                "backup_id": backup,
                "action": action,
            }.items()
        ):
            raise ValueError("invalid completion")
        for key, maximum in {
            "compressed_bytes": limits.max_compressed_bytes,
            "logical_bytes": limits.max_logical_bytes,
            "member_count": limits.max_members,
        }.items():
            if type(result.get(key)) is not int or not 0 <= result[key] <= maximum:
                raise ValueError("invalid completion")
        if not isinstance(result.get("sha256"), str) or not re.fullmatch(
            r"[a-f0-9]{64}", result["sha256"]
        ):
            raise ValueError("invalid completion")
        return {
            key: result[key]
            for key in ("sha256", "compressed_bytes", "logical_bytes", "member_count")
        }

    async def _execute(
        self, operation_id, fencing_token, volume_name, backup_id, *, maximum, action, checksum=None
    ):
        operation, fence, backup = map(self._uuid, (operation_id, fencing_token, backup_id))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", volume_name):
            raise RuntimeRecoveryError("invalid_operation", executor_terminated=True)
        limits = self._limits(maximum)
        # A previous executor can still be alive even when its helper has exited.
        # Only explicit executor reconciliation may adopt an existing operation.
        try:
            existing = await self.driver.get_container_by_name("nukelab-recovery-" + operation)
        except Exception:
            raise RuntimeRecoveryError("recovery_required") from None
        if existing is not None:
            raise RuntimeRecoveryError("recovery_required")
        await self.check_helper()
        await self.assert_detached(volume_name)
        relative = Path("backups") / backup
        try:
            backup_dir = self._directory(relative, create=action == "capture")
            if action == "capture":
                work = backup_dir
            else:
                work = self._directory(relative / "operations" / operation, create=True)
            marker = work / "intent.json"
            intent = {
                "operation_id": operation,
                "fencing_token": fence,
                "backup_id": backup,
                "action": action,
            }
            try:
                with marker.open("x", encoding="utf-8") as output:
                    json.dump(intent, output, sort_keys=True)
                if os.getuid() == 0:
                    os.chown(marker, 65532, 65532)
            except FileExistsError:
                if (
                    marker.is_symlink()
                    or marker.stat().st_size > 8192
                    or json.loads(marker.read_text()) != intent
                ):
                    raise RuntimeRecoveryError("artifact_conflict", executor_terminated=True)
        except RuntimeRecoveryError:
            raise
        except (OSError, ValueError):
            raise RuntimeRecoveryError("storage_unavailable", executor_terminated=True) from None
        labels = self._labels(operation, fence, backup)
        mounts = [
            {
                "Type": "bind",
                "Source": self._host(work.relative_to(self.storage_root)),
                "Target": "/artifact",
                "ReadOnly": False,
            },
            {
                "Type": "volume",
                "Source": volume_name,
                "Target": "/source" if action == "capture" else "/target",
                "ReadOnly": action == "capture",
            },
        ]
        if action == "restore":
            if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
                raise RuntimeRecoveryError("artifact_corrupt", executor_terminated=True)
            mounts.append(
                {
                    "Type": "bind",
                    "Source": self._host(relative),
                    "Target": "/archive",
                    "ReadOnly": True,
                }
            )
        command = [action, operation, fence, backup, json.dumps(vars(limits), sort_keys=True)]
        if checksum:
            command.append(checksum)
        identity = None
        claimed = False
        try:
            volume = await self.driver.get_volume(volume_name)
            if action == "capture":
                if not isinstance(volume, dict) or volume.get("Name") != volume_name:
                    raise RuntimeRecoveryError("volume_missing", executor_terminated=True)
            else:
                # Docker mounts create absent volumes implicitly and reuse existing
                # names. Neither behavior establishes fresh destination ownership.
                if volume is not None:
                    raise RuntimeRecoveryError("recovery_required")
                await self.driver.create_volume(volume_name, labels=labels)
                volume = await self.driver.get_volume(volume_name)
                if (
                    not isinstance(volume, dict)
                    or volume.get("Name") != volume_name
                    or not isinstance(volume.get("Labels"), dict)
                    or any(volume["Labels"].get(key) != value for key, value in labels.items())
                ):
                    raise RuntimeRecoveryError("recovery_required")
            try:
                identity = await self.driver.create_recovery_helper(
                    name="nukelab-recovery-" + operation,
                    image=self.image,
                    command=command,
                    mounts=mounts,
                    labels=labels,
                    limits={"memory_bytes": 1024**3},
                )
                claimed = True
            except ContainerDriverError:
                # A lost create response cannot prove that the helper never started.
                raise RuntimeRecoveryError("recovery_required") from None
            if claimed:
                await self.driver.start_container(identity)
                exit_code = await self.driver.wait_recovery_helper(identity, timeout=self.timeout)
                if exit_code != 0:
                    raise RuntimeRecoveryError("helper_failed")
            if not await self._terminated(identity, labels):
                raise RuntimeRecoveryError("recovery_required")
            result = self._metadata(work, operation, fence, backup, action, limits)
            if action == "capture":
                digest = hashlib.sha256()
                archive_path = backup_dir / "archive.tar.gz"
                descriptor = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as source:
                    info = os.fstat(source.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != 65532:
                        raise RuntimeRecoveryError("artifact_corrupt")
                    for chunk in iter(lambda: source.read(65536), b""):
                        digest.update(chunk)
                if (
                    digest.hexdigest() != result["sha256"]
                    or info.st_size != result["compressed_bytes"]
                ):
                    raise RuntimeRecoveryError("artifact_corrupt")
            elif result["sha256"] != checksum:
                raise RuntimeRecoveryError("artifact_corrupt")
            await self.driver.delete_container(identity, force=False)
            if action == "restore":
                shutil.rmtree(work)
            return {
                **result,
                "helper_identity": identity,
                "executor_terminated": True,
                "artifacts_removed": True,
            }
        except BaseException as error:
            proven = False
            if identity is not None and claimed:
                proven = await self._terminated(identity, labels, stop=True)
            # No ID means create outcome is unknown, even if a lookup is absent.
            removed = False
            if proven:
                try:
                    if identity:
                        await self.driver.delete_container(identity, force=False)
                    shutil.rmtree(work)
                    removed = True
                except OSError:
                    pass
                except Exception:
                    pass
            if not isinstance(error, Exception):
                raise
            raise RuntimeRecoveryError(
                "helper_failed" if proven else "recovery_required",
                executor_terminated=proven,
                artifacts_removed=removed,
            ) from None

    async def capture(
        self, operation_id, fencing_token, volume_name, backup_id, *, max_logical_bytes
    ):
        return await self._execute(
            operation_id,
            fencing_token,
            volume_name,
            backup_id,
            maximum=max_logical_bytes,
            action="capture",
        )

    async def restore(
        self,
        operation_id,
        fencing_token,
        volume_name,
        backup_id,
        expected_sha256,
        *,
        max_logical_bytes,
    ):
        return await self._execute(
            operation_id,
            fencing_token,
            volume_name,
            backup_id,
            maximum=max_logical_bytes,
            action="restore",
            checksum=expected_sha256,
        )

    async def delete_artifact(self, backup_id):
        backup = self._uuid(backup_id)
        relative = Path("backups") / backup
        try:
            directory = self._directory(relative)
        except FileNotFoundError:
            return
        host = Path(self._host(relative))
        try:
            for info in await self.driver.list_containers(all=True):
                if not isinstance(info, dict):
                    raise ValueError("inspection unavailable")
                details = info
                if isinstance(info.get("Id"), str):
                    details = await self.driver.get_container_info(info["Id"])
                if self._platform_container(details):
                    continue
                mounts = info.get("Mounts")
                if not isinstance(mounts, list):
                    raise ValueError("inspection unavailable")
                for mount in mounts:
                    if mount.get("Type") == "bind":
                        source = Path(mount.get("Source", ""))
                        if source == host or host in source.parents or source in host.parents:
                            raise RuntimeRecoveryError("artifact_busy", executor_terminated=True)
            shutil.rmtree(directory)
        except RuntimeRecoveryError:
            raise
        except Exception:
            raise RuntimeRecoveryError(
                "artifact_cleanup_failed", executor_terminated=True
            ) from None
