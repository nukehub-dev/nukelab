# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import hashlib
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.container.driver import ContainerDriverError
from app.services.volume_recovery_runtime import RuntimeRecoveryError, VolumeRecoveryRuntime

IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    driver = AsyncMock()
    driver.image_exists.return_value = True
    driver.resolve_image.return_value = {"local_id": IMAGE}
    driver.list_containers.return_value = []
    driver.get_container_by_name.return_value = None
    driver.create_recovery_helper.return_value = "helper-id"
    driver.wait_recovery_helper.return_value = 0
    driver.get_volume.return_value = {
        "Name": "source",
        "Mountpoint": "/var/lib/docker/volumes/source/_data",
    }
    value = VolumeRecoveryRuntime(driver, storage_root=tmp_path, host_root="/trusted/backups")
    monkeypatch.setattr(value, "_storage", lambda: tmp_path)

    def directory(relative, *, create=False):
        path = tmp_path / relative
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.exists():
            raise FileNotFoundError
        return path

    monkeypatch.setattr(value, "_directory", directory)
    return value


def operation():
    return tuple(str(uuid4()) for _ in range(3))


def exited(runtime, ids):
    runtime.driver.get_container_info.return_value = {
        "Image": IMAGE,
        "Config": {"Labels": runtime._labels(*ids)},
        "State": {"Running": False, "Status": "exited"},
    }


@pytest.mark.asyncio
async def test_capture_uses_pinned_identity_readonly_mount_and_proves_exit(runtime, monkeypatch):
    ids = operation()
    exited(runtime, ids)
    payload = b"compressed fixture"
    metadata = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "compressed_bytes": len(payload),
        "logical_bytes": 4,
        "member_count": 1,
    }

    async def completed(*args, **kwargs):
        (runtime.storage_root / "backups" / ids[2] / "archive.tar.gz").write_bytes(payload)
        return 0

    runtime.driver.wait_recovery_helper.side_effect = completed
    monkeypatch.setattr(runtime, "_metadata", lambda *args: metadata)
    result = await runtime.capture(ids[0], ids[1], "source", ids[2], max_logical_bytes=1024)
    config = runtime.driver.create_recovery_helper.call_args.kwargs
    assert config["image"] == IMAGE
    assert config["name"] == "nukelab-recovery-" + ids[0]
    assert config["mounts"][1] == {
        "Type": "volume",
        "Source": "source",
        "Target": "/source",
        "ReadOnly": True,
    }
    assert config["mounts"][0]["Source"] == "/trusted/backups/backups/" + ids[2]
    assert result["executor_terminated"] is True
    runtime.driver.delete_container.assert_awaited_once_with("helper-id", force=False)
    runtime.driver.create_volume.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [{"Id": "old"}, {}])
async def test_existing_helper_is_never_adopted(runtime, existing):
    runtime.driver.get_container_by_name.return_value = existing
    with pytest.raises(RuntimeRecoveryError) as caught:
        await runtime.capture(*operation()[:2], "source", str(uuid4()), max_logical_bytes=1024)
    assert caught.value.code == "recovery_required"
    assert not caught.value.executor_terminated
    runtime.driver.create_recovery_helper.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_create_response_retains_artifacts_and_unknown_guard(runtime):
    ids = operation()
    runtime.driver.create_recovery_helper.side_effect = ContainerDriverError("lost response")
    with pytest.raises(RuntimeRecoveryError) as caught:
        await runtime.capture(ids[0], ids[1], "source", ids[2], max_logical_bytes=1024)
    assert not caught.value.executor_terminated
    assert not caught.value.artifacts_removed
    assert (runtime.storage_root / "backups" / ids[2] / "intent.json").exists()
    runtime.driver.delete_container.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_releases_only_after_owned_helper_stops(runtime):
    ids = operation()
    exited(runtime, ids)
    runtime.driver.wait_recovery_helper.side_effect = TimeoutError
    with pytest.raises(RuntimeRecoveryError) as caught:
        await runtime.capture(ids[0], ids[1], "source", ids[2], max_logical_bytes=1024)
    assert caught.value.executor_terminated and caught.value.artifacts_removed
    assert not (runtime.storage_root / "backups" / ids[2]).exists()


@pytest.mark.asyncio
async def test_foreign_helper_cannot_be_stopped_or_cleaned(runtime):
    ids = operation()
    runtime.driver.wait_recovery_helper.side_effect = TimeoutError
    runtime.driver.get_container_info.return_value = {
        "Image": IMAGE,
        "Config": {"Labels": {}},
        "State": {"Running": True},
    }
    with pytest.raises(RuntimeRecoveryError) as caught:
        await runtime.capture(ids[0], ids[1], "source", ids[2], max_logical_bytes=1024)
    assert not caught.value.executor_terminated
    runtime.driver.stop_container.assert_not_awaited()
    runtime.driver.delete_container.assert_not_awaited()
    assert (runtime.storage_root / "backups" / ids[2]).exists()


@pytest.mark.asyncio
async def test_stopped_unmanaged_attachment_blocks_capture(runtime):
    runtime.driver.list_containers.return_value = [{"Id": "unmanaged"}]
    runtime.driver.get_container_info.return_value = {
        "Mounts": [{"Type": "volume", "Name": "source"}],
        "State": {"Running": False},
    }
    with pytest.raises(RuntimeRecoveryError, match="volume_attached"):
        await runtime.assert_detached("source")
    runtime.driver.list_containers.assert_awaited_once_with(all=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("info", [None, {}, {"Mounts": None}, {"Mounts": [None]}])
async def test_unknown_attachment_inspection_fails_closed(runtime, info):
    runtime.driver.list_containers.return_value = [{"Id": "container"}]
    runtime.driver.get_container_info.return_value = info
    with pytest.raises(RuntimeRecoveryError, match="runtime_inspection_unavailable"):
        await runtime.assert_detached("source")


@pytest.mark.asyncio
async def test_existing_restore_volume_is_never_reused(runtime):
    ids = operation()
    (runtime.storage_root / "backups" / ids[2]).mkdir(parents=True)
    with pytest.raises(RuntimeRecoveryError) as caught:
        await runtime.restore(ids[0], ids[1], "source", ids[2], "b" * 64, max_logical_bytes=1024)
    assert not caught.value.executor_terminated
    runtime.driver.create_volume.assert_not_awaited()
    runtime.driver.create_recovery_helper.assert_not_awaited()


@pytest.mark.asyncio
async def test_restore_creates_labelled_volume_before_mounting(runtime, monkeypatch):
    ids = operation()
    (runtime.storage_root / "backups" / ids[2]).mkdir(parents=True)
    runtime.driver.get_volume.side_effect = [
        None,
        None,
        {"Name": "source", "Labels": runtime._labels(*ids)},
    ]
    exited(runtime, ids)
    metadata = {"sha256": "b" * 64, "compressed_bytes": 20, "logical_bytes": 4, "member_count": 1}
    monkeypatch.setattr(runtime, "_metadata", lambda *args: metadata)
    result = await runtime.restore(
        ids[0], ids[1], "source", ids[2], "b" * 64, max_logical_bytes=1024
    )
    runtime.driver.create_volume.assert_awaited_once_with("source", labels=runtime._labels(*ids))
    assert result["executor_terminated"]
    assert not (runtime.storage_root / "backups" / ids[2] / "operations" / ids[0]).exists()
    assert (runtime.storage_root / "backups" / ids[2]).exists()


@pytest.mark.asyncio
async def test_delete_refuses_live_or_stopped_helper_artifact_bind(runtime):
    backup = str(uuid4())
    path = runtime.storage_root / "backups" / backup
    path.mkdir(parents=True)
    runtime.driver.list_containers.return_value = [
        {
            "Mounts": [
                {"Type": "bind", "Source": "/trusted/backups/backups/" + backup + "/operations/op"}
            ]
        }
    ]
    with pytest.raises(RuntimeRecoveryError, match="artifact_busy"):
        await runtime.delete_artifact(backup)
    assert path.exists()


@pytest.mark.asyncio
async def test_delete_ignores_platform_storage_root_bind(runtime):
    backup = str(uuid4())
    path = runtime.storage_root / "backups" / backup
    path.mkdir(parents=True)
    runtime.driver.list_containers.return_value = [
        {
            "Id": "backend-container",
            "Mounts": [{"Type": "bind", "Source": "/trusted/backups"}],
        }
    ]
    runtime.driver.get_container_info.return_value = {
        "Config": {"Labels": {"com.docker.compose.service": "backend"}}
    }
    await runtime.delete_artifact(backup)
    assert not path.exists()


@pytest.mark.asyncio
async def test_delete_unknown_inspection_preserves_artifacts(runtime):
    backup = str(uuid4())
    path = runtime.storage_root / "backups" / backup
    path.mkdir(parents=True)
    runtime.driver.list_containers.side_effect = ContainerDriverError("offline")
    with pytest.raises(RuntimeRecoveryError, match="artifact_cleanup_failed"):
        await runtime.delete_artifact(backup)
    assert path.exists()


@pytest.mark.asyncio
async def test_local_helper_absence_never_pulls(runtime):
    runtime.driver.image_exists.return_value = False
    with pytest.raises(RuntimeRecoveryError, match="helper_unavailable"):
        await runtime.check_helper()
    runtime.driver.pull_image.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        "/var/lib/docker/volumes/source/_data",
        "/var/lib/docker/volumes/source/_data/subdir",
        "/var/lib/docker/volumes/source",
        "/var/lib/docker/volumes",
        "//var/lib/docker/volumes/source/_data",
    ],
)
async def test_unmanaged_bind_alias_blocks_detached_volume(runtime, source):
    runtime.driver.list_containers.return_value = [{"Id": "unmanaged-stopped"}]
    runtime.driver.get_container_info.return_value = {
        "Mounts": [{"Type": "bind", "Source": source, "RW": False}],
        "State": {"Running": False},
    }
    with pytest.raises(RuntimeRecoveryError, match="volume_attached"):
        await runtime.assert_detached("source")


@pytest.mark.asyncio
async def test_platform_storage_root_bind_does_not_mark_child_volume_attached(runtime):
    runtime.driver.list_containers.return_value = [{"Id": "backend"}]
    runtime.driver.get_container_info.return_value = {
        "Config": {"Labels": {"com.docker.compose.service": "backend"}},
        "Mounts": [{"Type": "bind", "Source": "/var/lib/docker/volumes"}],
    }
    await runtime.assert_detached("source")


@pytest.mark.asyncio
async def test_unrelated_bind_and_tmpfs_allow_detached_volume(runtime):
    runtime.driver.list_containers.return_value = [{"Id": "unmanaged"}]
    runtime.driver.get_container_info.return_value = {
        "Mounts": [
            {"Type": "bind", "Source": "/var/lib/docker/volumes/source-other/_data"},
            {"Type": "tmpfs"},
            {"Type": "volume", "Name": "other"},
        ]
    }
    await runtime.assert_detached("source")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mount",
    [
        {"Type": "bind"},
        {"Type": "bind", "Source": "relative/path"},
        {"Type": "bind", "Source": "/absolute/../alias"},
        {"Type": "bind", "Source": "/absolute\x00/path"},
        {"Type": "volume"},
        {"Type": "unknown", "Source": "/some/path"},
        {},
    ],
)
async def test_unresolved_mount_identity_fails_closed(runtime, mount):
    runtime.driver.list_containers.return_value = [{"Id": "unmanaged"}]
    runtime.driver.get_container_info.return_value = {"Mounts": [mount]}
    with pytest.raises(RuntimeRecoveryError, match="runtime_inspection_unavailable"):
        await runtime.assert_detached("source")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "volume",
    [
        {"Name": "different", "Mountpoint": "/known"},
        {"Name": "source"},
        {"Name": "source", "Mountpoint": "relative"},
        {"Name": "source", "Mountpoint": "/unsafe/../path"},
        {"Name": "source", "Mountpoint": 1},
    ],
)
async def test_unknown_volume_mountpoint_cannot_exclude_bind_alias(runtime, volume):
    runtime.driver.get_volume.return_value = volume
    runtime.driver.list_containers.return_value = [{"Id": "unmanaged"}]
    runtime.driver.get_container_info.return_value = {
        "Mounts": [{"Type": "bind", "Source": "/otherwise/unrelated"}]
    }
    with pytest.raises(RuntimeRecoveryError, match="runtime_inspection_unavailable"):
        await runtime.assert_detached("source")


@pytest.mark.asyncio
async def test_absent_new_restore_volume_has_no_existing_bind_alias(runtime):
    runtime.driver.get_volume.return_value = None
    runtime.driver.list_containers.return_value = [{"Id": "unmanaged"}]
    runtime.driver.get_container_info.return_value = {
        "Mounts": [{"Type": "bind", "Source": "/otherwise/unrelated"}]
    }
    await runtime.assert_detached("source")


def mapped_owner(monkeypatch, *, uid=65532, gid=65532):
    """Model daemon-visible platform ownership without requiring host chown."""
    from types import SimpleNamespace

    from app.services import volume_recovery_runtime as module

    original = module.Path.lstat

    def lstat(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        return SimpleNamespace(
            st_mode=value.st_mode,
            st_uid=uid,
            st_gid=gid,
            st_size=value.st_size,
        )

    monkeypatch.setattr(module.Path, "lstat", lstat)


def test_storage_roots_require_configuration(monkeypatch):
    from app.services.volume_recovery_runtime import settings

    monkeypatch.setattr(settings, "volume_backup_storage_path", "")
    monkeypatch.setattr(settings, "volume_backup_host_path", "")
    value = VolumeRecoveryRuntime(AsyncMock())
    with pytest.raises(RuntimeRecoveryError, match="storage_unconfigured") as caught:
        value.available_bytes()
    assert caught.value.executor_terminated


@pytest.mark.parametrize(
    "root,host", [("relative", "/host"), ("/private/../escape", "/host"), ("/private", "relative")]
)
def test_storage_roots_require_absolute_paths(root, host):
    value = VolumeRecoveryRuntime(AsyncMock(), storage_root=root, host_root=host)
    with pytest.raises(RuntimeRecoveryError, match="storage_unavailable"):
        value._storage()


@pytest.mark.parametrize(
    "uid,gid,mode", [(1000, 65532, 0o700), (65532, 1000, 0o700), (65532, 65532, 0o755)]
)
def test_storage_rejects_foreign_ownership_and_shared_mode(tmp_path, monkeypatch, uid, gid, mode):
    mapped_owner(monkeypatch, uid=uid, gid=gid)
    tmp_path.chmod(mode)
    value = VolumeRecoveryRuntime(AsyncMock(), storage_root=tmp_path, host_root="/host")
    with pytest.raises(RuntimeRecoveryError, match="storage_unavailable"):
        value._storage()


def test_storage_rejects_symlink_root(tmp_path, monkeypatch):
    mapped_owner(monkeypatch)
    target = tmp_path / "real"
    target.mkdir(mode=0o700)
    link = tmp_path / "alias"
    link.symlink_to(target, target_is_directory=True)
    value = VolumeRecoveryRuntime(AsyncMock(), storage_root=link, host_root="/host")
    with pytest.raises(RuntimeRecoveryError, match="storage_unavailable"):
        value._storage()


def test_private_directory_rejects_linked_component(tmp_path, monkeypatch):
    mapped_owner(monkeypatch)
    target = tmp_path / "real"
    target.mkdir(mode=0o700)
    (tmp_path / "backups").symlink_to(target, target_is_directory=True)
    value = VolumeRecoveryRuntime(AsyncMock(), storage_root=tmp_path, host_root="/host")
    with pytest.raises(RuntimeRecoveryError, match="storage_unavailable"):
        value._directory("backups/" + str(uuid4()), create=True)
    assert list(target.iterdir()) == []


def test_private_directory_rejects_traversal(tmp_path, monkeypatch):
    mapped_owner(monkeypatch)
    value = VolumeRecoveryRuntime(AsyncMock(), storage_root=tmp_path, host_root="/host")
    with pytest.raises(RuntimeRecoveryError, match="invalid_operation"):
        value._directory("../outside", create=True)


def test_private_directory_creates_owned_components_and_reports_free_space(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.services import volume_recovery_runtime as module

    mapped_owner(monkeypatch)
    # Creation identity is modelled independently of the current test-process UID.
    monkeypatch.setattr(module.os, "getuid", lambda: 1000)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=123456))
    value = VolumeRecoveryRuntime(AsyncMock(), storage_root=tmp_path, host_root="/host")
    relative = "backups/" + str(uuid4())
    directory = value._directory(relative, create=True)
    assert directory == tmp_path / relative
    assert directory.stat().st_mode & 0o077 == 0
    assert value._directory(relative, create=True) == directory
    assert value.available_bytes() == 123456


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("operation_id", str(uuid4())),
        ("fencing_token", str(uuid4())),
        ("backup_id", str(uuid4())),
        ("action", "restore"),
        ("compressed_bytes", True),
        ("logical_bytes", -1),
        ("member_count", 100001),
        ("sha256", "not-a-sha256"),
    ],
)
def test_completion_requires_exact_fence_and_bounded_integer_metadata(
    runtime, monkeypatch, field, replacement
):
    import json

    mapped_owner(monkeypatch)
    ids = operation()
    result = {
        "operation_id": ids[0],
        "fencing_token": ids[1],
        "backup_id": ids[2],
        "action": "capture",
        "compressed_bytes": 10,
        "logical_bytes": 4,
        "member_count": 1,
        "sha256": "a" * 64,
    }
    result[field] = replacement
    (runtime.storage_root / "completion.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="invalid completion"):
        runtime._metadata(runtime.storage_root, *ids, "capture", runtime._limits(1024))


@pytest.mark.parametrize("kind", ["symlink", "too_large", "foreign_owner"])
def test_completion_requires_small_regular_owned_file(runtime, monkeypatch, kind):
    mapped_owner(monkeypatch, uid=1000 if kind == "foreign_owner" else 65532)
    path = runtime.storage_root / "completion.json"
    if kind == "symlink":
        target = runtime.storage_root / "other"
        target.write_text("{}")
        path.symlink_to(target)
    else:
        path.write_text("x" * (8193 if kind == "too_large" else 2))
    with pytest.raises(ValueError, match="invalid completion"):
        runtime._metadata(runtime.storage_root, *operation(), "capture", runtime._limits(1024))


def test_completion_exposes_only_verified_numeric_metadata(runtime, monkeypatch):
    import json

    mapped_owner(monkeypatch)
    ids = operation()
    result = {
        "operation_id": ids[0],
        "fencing_token": ids[1],
        "backup_id": ids[2],
        "action": "capture",
        "compressed_bytes": 10,
        "logical_bytes": 4,
        "member_count": 1,
        "sha256": "a" * 64,
        "unexpected_secret": "/private/host/path",
    }
    (runtime.storage_root / "completion.json").write_text(json.dumps(result))
    public = runtime._metadata(runtime.storage_root, *ids, "capture", runtime._limits(1024))
    assert set(public) == {"compressed_bytes", "logical_bytes", "member_count", "sha256"}


@pytest.mark.parametrize("maximum", [0, -1, True, 2**80])
def test_runtime_limits_reject_invalid_or_unbounded_values(runtime, maximum):
    with pytest.raises(RuntimeRecoveryError, match="invalid_operation"):
        runtime._limits(maximum)
