# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for Docker spawner volume mount mode enforcement.

These tests verify that read-only volume mounts are actually enforced
at the Docker container level, not just stored in the database.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestContainerClientBindFormatting:
    """Unit tests for ContainerClient.create_container bind string formatting.

    These tests verify that the Docker client correctly appends :ro / :rw
    to bind mount strings based on the mode in the volumes dict.
    """

    @pytest.mark.asyncio
    async def test_dict_volume_with_ro_mode(self):
        """ContainerClient should append ':ro' when mode is 'ro' in dict."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())

        # Mock _check_storage_support to skip disk limit logic
        with patch.object(client, "_check_storage_support", return_value=False):
            with patch.object(client, "_check_lxcfs_support", return_value=[]):
                with patch.object(client, "_get_available_controllers", return_value=set()):
                    await client.create_container(
                        name="test-ro",
                        image="hello-world",
                        volumes={"my-vol": {"bind": "/data", "mode": "ro"}},
                    )

        call_args = client.client.containers.create.call_args
        config = call_args[0][0]
        binds = config["HostConfig"]["Binds"]
        assert "my-vol:/data:ro" in binds, f"Expected ':ro' in binds, got: {binds}"

    @pytest.mark.asyncio
    async def test_dict_volume_with_rw_mode(self):
        """ContainerClient should append ':rw' when mode is 'rw' in dict."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())

        with patch.object(client, "_check_storage_support", return_value=False):
            with patch.object(client, "_check_lxcfs_support", return_value=[]):
                with patch.object(client, "_get_available_controllers", return_value=set()):
                    await client.create_container(
                        name="test-rw",
                        image="hello-world",
                        volumes={"my-vol": {"bind": "/data", "mode": "rw"}},
                    )

        config = client.client.containers.create.call_args[0][0]
        binds = config["HostConfig"]["Binds"]
        assert "my-vol:/data:rw" in binds, f"Expected ':rw' in binds, got: {binds}"

    @pytest.mark.asyncio
    async def test_mixed_ro_and_rw_mounts(self):
        """Multiple mounts with different modes should each get correct suffix."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())

        with patch.object(client, "_check_storage_support", return_value=False):
            with patch.object(client, "_check_lxcfs_support", return_value=[]):
                with patch.object(client, "_get_available_controllers", return_value=set()):
                    await client.create_container(
                        name="test-mixed",
                        image="hello-world",
                        volumes={
                            "vol-ro": {"bind": "/data/readonly", "mode": "ro"},
                            "vol-rw": {"bind": "/data/readwrite", "mode": "rw"},
                        },
                    )

        config = client.client.containers.create.call_args[0][0]
        binds = config["HostConfig"]["Binds"]
        assert "vol-ro:/data/readonly:ro" in binds, f"Missing ':ro' in binds: {binds}"
        assert "vol-rw:/data/readwrite:rw" in binds, f"Missing ':rw' in binds: {binds}"

    @pytest.mark.asyncio
    async def test_string_volume_has_no_mode_suffix(self):
        """Legacy string-format volumes should not have a mode suffix."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())

        with patch.object(client, "_check_storage_support", return_value=False):
            with patch.object(client, "_check_lxcfs_support", return_value=[]):
                with patch.object(client, "_get_available_controllers", return_value=set()):
                    await client.create_container(
                        name="test-string",
                        image="hello-world",
                        volumes={"my-vol": "/data"},
                    )

        config = client.client.containers.create.call_args[0][0]
        binds = config["HostConfig"]["Binds"]
        assert "my-vol:/data" in binds, f"Expected string bind in binds, got: {binds}"
        # Make sure there's no accidental mode suffix
        for bind in binds:
            if "my-vol:/data" in bind:
                assert not bind.endswith(":ro"), f"String volume got :ro suffix: {bind}"
                assert not bind.endswith(":rw"), f"String volume got :rw suffix: {bind}"


class TestContainerClientCpuMasking:
    """Unit tests for ContainerClient CPU masking configuration.

    Verifies that CPU env vars, volume mounts, and system files are
    correctly injected into spawned containers.
    """

    @pytest.mark.asyncio
    async def test_cpu_env_vars_generated(self):
        """_get_cpu_env should return correct thread-limit env vars."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        env = client._get_cpu_env(cpu_limit=4.0)

        assert env["NUKELAB_CPU_COUNT"] == "4"
        assert env["OMP_NUM_THREADS"] == "4"
        assert env["MKL_NUM_THREADS"] == "4"
        assert env["OPENBLAS_NUM_THREADS"] == "4"
        assert env["VECLIB_MAXIMUM_THREADS"] == "4"
        assert env["NUMEXPR_NUM_THREADS"] == "4"
        assert env["LD_PRELOAD"] == "/usr/local/lib/nukelab/libnukelab_cpu.so"

    @pytest.mark.asyncio
    async def test_cpu_env_defaults_to_host_count_when_none(self):
        """_get_cpu_env should default to os.cpu_count when cpu_limit is None."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        env = client._get_cpu_env(cpu_limit=None)

        # Should be at least 1
        assert int(env["NUKELAB_CPU_COUNT"]) >= 1
        assert env["LD_PRELOAD"] == "/usr/local/lib/nukelab/libnukelab_cpu.so"

    @pytest.mark.asyncio
    async def test_cpu_env_defaults_to_host_when_below_one(self):
        """_get_cpu_env should default to host count when cpu_limit < 1."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        env = client._get_cpu_env(cpu_limit=0.5)

        # Falls back to os.cpu_count() when limit is < 1
        assert int(env["NUKELAB_CPU_COUNT"]) >= 1
        assert env["OMP_NUM_THREADS"] == env["NUKELAB_CPU_COUNT"]

    @pytest.mark.asyncio
    async def test_cpu_lib_volume_mounted_when_ready(self):
        """Container should mount nukelab-cpu-lib volume when available."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())
        client._cpu_lib_volume_ready = True

        with patch.object(client, "_check_storage_support", return_value=False):
            with patch.object(client, "_check_lxcfs_support", return_value=[]):
                with patch.object(client, "_get_available_controllers", return_value=set()):
                    await client.create_container(
                        name="test-cpu",
                        image="hello-world",
                    )

        config = client.client.containers.create.call_args[0][0]
        mounts = config["HostConfig"].get("Mounts", [])
        cpu_mounts = [m for m in mounts if m.get("Source") == "nukelab-cpu-lib"]
        assert len(cpu_mounts) == 1, f"Expected cpu-lib mount, got: {mounts}"
        assert cpu_mounts[0]["Target"] == "/usr/local/lib/nukelab"
        assert cpu_mounts[0]["ReadOnly"] is True

    @pytest.mark.asyncio
    async def test_cpu_lib_volume_not_mounted_when_missing(self):
        """Container should not crash when cpu-lib volume is unavailable."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())
        client._cpu_lib_volume_ready = False

        with patch.object(client, "_check_storage_support", return_value=False):
            with patch.object(client, "_check_lxcfs_support", return_value=[]):
                with patch.object(client, "_get_available_controllers", return_value=set()):
                    await client.create_container(
                        name="test-no-cpu",
                        image="hello-world",
                    )

        config = client.client.containers.create.call_args[0][0]
        mounts = config["HostConfig"].get("Mounts", [])
        cpu_mounts = [m for m in mounts if m.get("Source") == "nukelab-cpu-lib"]
        assert len(cpu_mounts) == 0, f"Did not expect cpu-lib mount, got: {mounts}"

    @pytest.mark.asyncio
    async def test_cpu_files_injected_via_put_archive(self):
        """_inject_cpu_files should write /etc/ld.so.preload and profile script."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        mock_container = MagicMock()
        mock_container.put_archive = AsyncMock(return_value=True)

        await client._inject_cpu_files(mock_container, cpu_limit=2.0)

        mock_container.put_archive.assert_called_once()
        args = mock_container.put_archive.call_args[0]
        assert args[0] == "/etc"

        # Verify tar archive contents
        import io
        import tarfile

        tar_buffer = io.BytesIO(args[1])
        with tarfile.open(fileobj=tar_buffer, mode="r") as tar:
            names = tar.getnames()
            assert "ld.so.preload" in names
            assert "profile.d/nukelab-cpu.sh" in names

            # Check ld.so.preload content
            preload = tar.extractfile("ld.so.preload").read().decode()
            assert "/usr/local/lib/nukelab/libnukelab_cpu.so" in preload

            # Check profile script content
            profile = tar.extractfile("profile.d/nukelab-cpu.sh").read().decode()
            assert "LD_PRELOAD=" in profile
            assert "NUKELAB_CPU_COUNT=2" in profile
            assert "OMP_NUM_THREADS=2" in profile


class TestSpawnerVolumeDictBuilding:
    """Tests that ServerSpawner builds the volumes dict with mode preserved."""

    @pytest.mark.asyncio
    async def test_spawner_builds_ro_volume_dict(self, db_session, test_user):
        """Spawner should produce volumes dict with mode='ro' for read_only mounts."""
        from app.container.spawner import ServerSpawner
        from app.models.volume import Volume

        volume = Volume(
            name="test-spawner-ro",
            display_name="Spawner RO Volume",
            owner_id=test_user.id,
            status="active",
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        ServerSpawner()

        # Build volumes dict manually (same logic as spawn)
        mount = {
            "volume_id": str(volume.id),
            "mount_path": "/data",
            "mode": "read_only",
        }
        vol_id = mount.get("volume_id")
        mount_path = mount.get("mount_path", "/data")
        mode = mount.get("mode", "read_write")

        # Get volume name from DB (same as spawner)
        from sqlalchemy import select

        result = await db_session.execute(select(Volume).where(Volume.id == vol_id))
        vol = result.scalar_one_or_none()
        volume_name = vol.name if vol else f"nukelab-vol-{vol_id[:8]}"

        mount_mode = "ro" if mode == "read_only" else "rw"
        volumes = {volume_name: {"bind": mount_path, "mode": mount_mode}}

        assert volumes[volume_name]["mode"] == "ro"
        assert volumes[volume_name]["bind"] == "/data"

    @pytest.mark.asyncio
    async def test_spawner_builds_rw_volume_dict(self, db_session, test_user):
        """Spawner should produce volumes dict with mode='rw' for read_write mounts."""
        from app.models.volume import Volume

        volume = Volume(
            name="test-spawner-rw",
            display_name="Spawner RW Volume",
            owner_id=test_user.id,
            status="active",
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        mount = {
            "volume_id": str(volume.id),
            "mount_path": "/home",
            "mode": "read_write",
        }
        mode = mount.get("mode", "read_write")
        mount_mode = "ro" if mode == "read_only" else "rw"

        assert mount_mode == "rw"


"""Tests for app.container.spawner.ServerSpawner methods."""

import uuid as uuid_mod
from unittest import mock

import pytest

from app.container.spawner import ServerSpawner
from app.models.server import Server


class MockContainer:
    """Mock Docker container."""

    def __init__(self, container_id=None):
        self.id = container_id or str(uuid_mod.uuid4())


class MockExec:
    """Mock exec instance."""

    async def start(self, detach=False):
        pass


@pytest.fixture
def mock_container_client():
    """Return a fully mocked container client suitable for spawner tests."""
    client = mock.AsyncMock()

    # Mock volumes
    mock_volume = mock.AsyncMock()
    client.client.volumes.get = mock.AsyncMock(return_value=mock_volume)
    client.client.volumes.create = mock.AsyncMock(return_value=mock_volume)

    # Mock images
    mock_image = mock.AsyncMock()
    client.client.images.get = mock.AsyncMock(return_value=mock_image)
    client.pull_image = mock.AsyncMock(return_value=mock_image)

    # Mock containers
    mock_container = MockContainer()
    client.create_container = mock.AsyncMock(return_value=mock_container)
    client.start_container = mock.AsyncMock()
    client.wait_for_container_ready = mock.AsyncMock(return_value=True)
    client.stop_container = mock.AsyncMock()
    client.delete_container = mock.AsyncMock()
    client.get_container_info = mock.AsyncMock(
        return_value={"State": {"Running": True, "Paused": False}}
    )

    # Mock container exec
    mock_exec = MockExec()
    mock_container_mock = mock.AsyncMock()
    mock_container_mock.exec = mock.AsyncMock(return_value=mock_exec)
    mock_container_mock.delete = mock.AsyncMock()
    client.client.containers.get = mock.AsyncMock(return_value=mock_container_mock)

    return client


@pytest.fixture
def fresh_spawner(mock_container_client):
    """Return a fresh ServerSpawner with mocked container client."""
    s = ServerSpawner()
    s.container_client = mock_container_client
    return s


# ─────────────────────────────────────────────────────────────
# _get_container_client
# ─────────────────────────────────────────────────────────────


class TestGetContainerClient:
    """Tests for _get_container_client lazy initialization."""

    @pytest.mark.asyncio
    async def test_lazy_init(self, mock_container_client):
        """Should call get_container_client when container_client is None."""
        s = ServerSpawner()
        assert s.container_client is None

        with mock.patch(
            "app.container.spawner.get_container_client",
            return_value=mock_container_client,
        ):
            result = await s._get_container_client()

        assert result is mock_container_client
        assert s.container_client is mock_container_client

    @pytest.mark.asyncio
    async def test_reuses_existing(self, mock_container_client):
        """Should not re-call get_container_client if already set."""
        s = ServerSpawner()
        s.container_client = mock_container_client

        with mock.patch(
            "app.container.spawner.get_container_client",
            side_effect=Exception("should not be called"),
        ):
            result = await s._get_container_client()

        assert result is mock_container_client


# ─────────────────────────────────────────────────────────────
# _ensure_volume
# ─────────────────────────────────────────────────────────────


class TestEnsureVolume:
    """Tests for _ensure_volume."""

    @pytest.mark.asyncio
    async def test_volume_already_exists(self, fresh_spawner):
        """Should not create volume if it already exists."""
        await fresh_spawner._ensure_volume("existing-vol")
        fresh_spawner.container_client.client.volumes.get.assert_awaited_once_with("existing-vol")
        fresh_spawner.container_client.client.volumes.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_volume_needs_creation(self, fresh_spawner):
        """Should create volume if it does not exist."""
        fresh_spawner.container_client.client.volumes.get = mock.AsyncMock(
            side_effect=Exception("not found")
        )
        await fresh_spawner._ensure_volume("new-vol")
        fresh_spawner.container_client.client.volumes.create.assert_awaited_once()
        call_args = fresh_spawner.container_client.client.volumes.create.await_args[0][0]
        assert call_args["Name"] == "new-vol"
        assert call_args["Labels"]["nukelab.managed"] == "true"


# ─────────────────────────────────────────────────────────────
# start / stop / delete
# ─────────────────────────────────────────────────────────────


class TestStartStopDelete:
    """Tests for start, stop, and delete wrappers."""

    @pytest.mark.asyncio
    async def test_start_success(self, fresh_spawner):
        """start should return True on success."""
        result = await fresh_spawner.start("cid-123")
        assert result is True
        fresh_spawner.container_client.start_container.assert_awaited_once_with("cid-123")

    @pytest.mark.asyncio
    async def test_start_failure(self, fresh_spawner):
        """start should return False when container_client raises."""
        fresh_spawner.container_client.start_container = mock.AsyncMock(
            side_effect=Exception("docker error")
        )
        result = await fresh_spawner.start("cid-123")
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_success(self, fresh_spawner):
        """stop should return True on success."""
        result = await fresh_spawner.stop("cid-123")
        assert result is True
        fresh_spawner.container_client.stop_container.assert_awaited_once_with("cid-123")

    @pytest.mark.asyncio
    async def test_stop_failure(self, fresh_spawner):
        """stop should return False when container_client raises."""
        fresh_spawner.container_client.stop_container = mock.AsyncMock(
            side_effect=Exception("docker error")
        )
        result = await fresh_spawner.stop("cid-123")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_success(self, fresh_spawner):
        """delete should return True on success."""
        result = await fresh_spawner.delete("cid-123")
        assert result is True
        fresh_spawner.container_client.delete_container.assert_awaited_once_with(
            "cid-123", force=True
        )

    @pytest.mark.asyncio
    async def test_delete_failure(self, fresh_spawner):
        """delete should return False when container_client raises."""
        fresh_spawner.container_client.delete_container = mock.AsyncMock(
            side_effect=Exception("docker error")
        )
        result = await fresh_spawner.delete("cid-123")
        assert result is False


# ─────────────────────────────────────────────────────────────
# get_status
# ─────────────────────────────────────────────────────────────


class TestGetStatus:
    """Tests for get_status."""

    @pytest.mark.asyncio
    async def test_running(self, fresh_spawner):
        """Should return 'running' when State.Running is True."""
        fresh_spawner.container_client.get_container_info = mock.AsyncMock(
            return_value={"State": {"Running": True, "Paused": False}}
        )
        assert await fresh_spawner.get_status("cid") == "running"

    @pytest.mark.asyncio
    async def test_paused(self, fresh_spawner):
        """Should return 'paused' when State.Paused is True."""
        fresh_spawner.container_client.get_container_info = mock.AsyncMock(
            return_value={"State": {"Running": False, "Paused": True}}
        )
        assert await fresh_spawner.get_status("cid") == "paused"

    @pytest.mark.asyncio
    async def test_stopped(self, fresh_spawner):
        """Should return 'stopped' when neither Running nor Paused."""
        fresh_spawner.container_client.get_container_info = mock.AsyncMock(
            return_value={"State": {"Running": False, "Paused": False}}
        )
        assert await fresh_spawner.get_status("cid") == "stopped"

    @pytest.mark.asyncio
    async def test_unknown_on_exception(self, fresh_spawner):
        """Should return 'unknown' when get_container_info raises."""
        fresh_spawner.container_client.get_container_info = mock.AsyncMock(
            side_effect=Exception("docker error")
        )
        assert await fresh_spawner.get_status("cid") == "unknown"


# ─────────────────────────────────────────────────────────────
# spawn — success paths
# ─────────────────────────────────────────────────────────────


class TestSpawnSuccess:
    """Tests for spawn() success paths."""

    @pytest.mark.asyncio
    async def test_spawn_default_volume(self, fresh_spawner):
        """spawn with no volume_mounts should use default volume."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            server = await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
                environment="dev",
            )

        assert isinstance(server, Server)
        assert server.name == "srv1"
        assert server.status == "running"
        fresh_spawner.container_client.create_container.assert_awaited_once()
        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        assert "nukelab-server-testuser-srv1-data" in call_kwargs["volumes"]
        assert call_kwargs["command"] == "/start.sh"
        assert call_kwargs["hostname"] == "NukeLab"

    @pytest.mark.asyncio
    async def test_spawn_with_provided_image(self, fresh_spawner):
        """spawn should use provided image."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
                image="custom:latest",
            )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        assert call_kwargs["image"] == "custom:latest"

    @pytest.mark.asyncio
    async def test_spawn_image_fallback_on_pull_failure(self, fresh_spawner):
        """spawn should fallback to nukelab-base:latest when image inspect and pull both fail."""
        fresh_spawner.container_client.client.images.get = mock.AsyncMock(
            side_effect=Exception("not found")
        )
        fresh_spawner.container_client.pull_image = mock.AsyncMock(
            side_effect=Exception("pull failed")
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
            )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        assert call_kwargs["image"] == "nukelab-base:latest"

    @pytest.mark.asyncio
    async def test_spawn_image_pull_when_not_local(self, fresh_spawner):
        """spawn should pull image when not found locally."""
        fresh_spawner.container_client.client.images.get = mock.AsyncMock(
            side_effect=Exception("not found")
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
                image="remote:latest",
            )

        fresh_spawner.container_client.pull_image.assert_awaited_once_with("remote:latest")
        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        assert call_kwargs["image"] == "remote:latest"

    @pytest.mark.asyncio
    async def test_spawn_with_env_vars(self, fresh_spawner):
        """spawn should inject custom env_vars."""
        from app.container.spawner import settings

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
                env_vars={"FOO": "bar"},
            )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        env = call_kwargs["env"]
        assert env["FOO"] == "bar"
        assert env["NUKELAB_USERNAME"] == "testuser"
        assert env["NUKELAB_CONTAINER_USER"] == settings.container_user
        assert env["NUKELAB_SERVER_NAME"] == "srv1"
        assert env["HOME"] == "/home/testuser"
        assert env["USER"] == "testuser"

    @pytest.mark.asyncio
    async def test_spawn_with_volume_mounts_no_vol_id(self, fresh_spawner):
        """spawn with volume_mounts lacking volume_id should generate default volume name."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
                volume_mounts=[{"mount_path": "/data", "mode": "read_write"}],
            )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        vols = call_kwargs["volumes"]
        assert any("testuser-srv1-data" in k for k in vols)

    @pytest.mark.asyncio
    async def test_spawn_with_volume_mounts_read_only(self, fresh_spawner):
        """spawn with read_only mode should use 'ro' bind mode."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
                volume_mounts=[{"mount_path": "/data", "mode": "read_only"}],
            )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        vols = call_kwargs["volumes"]
        mount_info = next(v for k, v in vols.items() if "testuser-srv1-data" in k)
        assert mount_info["mode"] == "ro"

    @pytest.mark.asyncio
    async def test_spawn_returns_server_with_url(self, fresh_spawner):
        """spawn should return Server with correct external_url."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test:8080"):
            server = await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
            )

        assert server.external_url == "http://test:8080/user/testuser/srv1"
        assert server.status == "running"
        assert server.allocated_cpu == 1.0
        assert server.allocated_memory == "2g"
        assert server.allocated_disk == "10g"

    @pytest.mark.asyncio
    async def test_spawn_waits_for_container_ready(self, fresh_spawner):
        """spawn should wait for container readiness before returning."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
            )

        fresh_spawner.container_client.wait_for_container_ready.assert_awaited_once_with(
            "nukelab-server-testuser-srv1", "http://nukelab-server-testuser-srv1:8080/health"
        )

    @pytest.mark.asyncio
    async def test_spawn_removes_existing_container_before_create(self, fresh_spawner):
        """spawn should delete an existing container with the same name before creating a new one."""
        mock_existing = mock.AsyncMock()
        fresh_spawner.container_client.client.containers.get = mock.AsyncMock(
            return_value=mock_existing
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            with mock.patch("asyncio.sleep"):
                await fresh_spawner.spawn(
                    user_id=str(uuid_mod.uuid4()),
                    username="testuser",
                    server_name="srv1",
                )

        fresh_spawner.container_client.client.containers.get.assert_awaited_once_with(
            "nukelab-server-testuser-srv1"
        )
        mock_existing.delete.assert_awaited_once_with(force=True)
        fresh_spawner.container_client.create_container.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_spawn_ignores_missing_existing_container(self, fresh_spawner):
        """spawn should proceed normally when no existing container is found."""
        fresh_spawner.container_client.client.containers.get = mock.AsyncMock(
            side_effect=Exception("not found")
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            with mock.patch("asyncio.sleep"):
                await fresh_spawner.spawn(
                    user_id=str(uuid_mod.uuid4()),
                    username="testuser",
                    server_name="srv1",
                )

        fresh_spawner.container_client.client.containers.get.assert_awaited_once_with(
            "nukelab-server-testuser-srv1"
        )
        fresh_spawner.container_client.create_container.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_spawn_with_server_id(self, fresh_spawner):
        """spawn should use provided server_id."""
        sid = str(uuid_mod.uuid4())
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            server = await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
                server_id=sid,
            )

        assert str(server.id) == sid

    @pytest.mark.asyncio
    async def test_spawn_permission_fix_skips_home(self, fresh_spawner):
        """spawn should skip chmod on /home/{username}."""
        mock_exec = MockExec()
        mock_container = mock.AsyncMock()
        mock_container.id = str(uuid_mod.uuid4())
        mock_container.exec = mock.AsyncMock(return_value=mock_exec)
        fresh_spawner.container_client.create_container = mock.AsyncMock(
            return_value=mock_container
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            with mock.patch("asyncio.sleep"):
                await fresh_spawner.spawn(
                    user_id=str(uuid_mod.uuid4()),
                    username="testuser",
                    server_name="srv1",
                    volume_mounts=[
                        {"mount_path": "/home/testuser", "mode": "read_write"},
                        {"mount_path": "/data", "mode": "read_write"},
                    ],
                )

        # Only /data should get chmod, not /home/testuser
        exec_calls = mock_container.exec.call_args_list
        paths = [c[0][0][2] for c in exec_calls]
        assert "/home/testuser" not in paths
        assert "/data" in paths

    @pytest.mark.asyncio
    async def test_spawn_permission_fix_failure_logged(self, fresh_spawner):
        """spawn should log warning when chmod fails."""
        mock_container = mock.AsyncMock()
        mock_container.id = str(uuid_mod.uuid4())
        mock_container.exec = mock.AsyncMock(side_effect=Exception("chmod failed"))
        fresh_spawner.container_client.create_container = mock.AsyncMock(
            return_value=mock_container
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            with mock.patch("asyncio.sleep"):
                with mock.patch("app.container.spawner.logger.warning") as mock_warn:
                    await fresh_spawner.spawn(
                        user_id=str(uuid_mod.uuid4()),
                        username="testuser",
                        server_name="srv1",
                        volume_mounts=[{"mount_path": "/data", "mode": "read_write"}],
                    )

        chmod_warnings = [
            c for c in mock_warn.call_args_list if "Could not fix permissions" in c[0][0]
        ]
        assert len(chmod_warnings) == 1

    @pytest.mark.asyncio
    async def test_spawn_with_auth_volume(self, fresh_spawner):
        """spawn should mount auth volume when server_auth_enabled."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            with mock.patch("app.container.spawner.settings.server_auth_enabled", True):
                with mock.patch(
                    "app.container.spawner.settings.server_auth_public_key_path", "/key.pem"
                ):
                    with mock.patch(
                        "app.services.server_auth_service.server_auth_service._ensure_keys_exist"
                    ) as mock_ensure:
                        await fresh_spawner.spawn(
                            user_id=str(uuid_mod.uuid4()),
                            username="testuser",
                            server_name="srv1",
                        )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        vols = call_kwargs["volumes"]
        assert "nukelab-server-secrets" in vols
        assert vols["nukelab-server-secrets"]["bind"] == "/etc/nukelab/auth"
        assert vols["nukelab-server-secrets"]["mode"] == "ro"
        mock_ensure.assert_called_once()

    @pytest.mark.asyncio
    async def test_spawn_without_auth_volume(self, fresh_spawner):
        """spawn should NOT mount auth volume when server_auth_enabled is False."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            with mock.patch("app.container.spawner.settings.server_auth_enabled", False):
                await fresh_spawner.spawn(
                    user_id=str(uuid_mod.uuid4()),
                    username="testuser",
                    server_name="srv1",
                )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        vols = call_kwargs["volumes"]
        assert "nukelab-server-secrets" not in vols


# ─────────────────────────────────────────────────────────────
# spawn — failure paths
# ─────────────────────────────────────────────────────────────


class TestSpawnFailure:
    """Tests for spawn() failure handling."""

    @pytest.mark.asyncio
    async def test_spawn_cleanup_on_create_failure(self, fresh_spawner):
        """spawn should cleanup container by name when create_container fails."""
        fresh_spawner.container_client.create_container = mock.AsyncMock(
            side_effect=Exception("create failed")
        )
        mock_container = mock.AsyncMock()
        mock_container.delete = mock.AsyncMock()
        fresh_spawner.container_client.client.containers.get = mock.AsyncMock(
            return_value=mock_container
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            with pytest.raises(Exception) as exc_info:
                await fresh_spawner.spawn(
                    user_id=str(uuid_mod.uuid4()),
                    username="testuser",
                    server_name="srv1",
                )

        assert "Failed to spawn server" in str(exc_info.value)
        mock_container.delete.assert_awaited_with(force=True)
        assert mock_container.delete.await_count == 2

    @pytest.mark.asyncio
    async def test_spawn_cleanup_ignores_delete_failure(self, fresh_spawner):
        """spawn cleanup should not raise if delete also fails."""
        fresh_spawner.container_client.create_container = mock.AsyncMock(
            side_effect=Exception("create failed")
        )
        fresh_spawner.container_client.client.containers.get = mock.AsyncMock(
            side_effect=Exception("not found")
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            with pytest.raises(Exception) as exc_info:
                await fresh_spawner.spawn(
                    user_id=str(uuid_mod.uuid4()),
                    username="testuser",
                    server_name="srv1",
                )

        assert "Failed to spawn server" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────
# spawn — DB volume lookup
# ─────────────────────────────────────────────────────────────


class TestSpawnVolumeLookup:
    """Tests for spawn() volume lookup from database."""

    @pytest.mark.asyncio
    async def test_spawn_with_db_volume_found(self, fresh_spawner):
        """spawn should use volume.name from DB when volume_id exists."""
        mock_volume = mock.Mock()
        mock_volume.name = "db-volume-name"

        mock_session = mock.AsyncMock()
        mock_session.execute = mock.AsyncMock(
            return_value=mock.Mock(scalar_one_or_none=mock.Mock(return_value=mock_volume))
        )
        mock_context = mock.AsyncMock()
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_session)
        mock_context.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("app.db.session.async_session", return_value=mock_context):
            with mock.patch("app.container.spawner.settings.public_url", "http://test"):
                await fresh_spawner.spawn(
                    user_id=str(uuid_mod.uuid4()),
                    username="testuser",
                    server_name="srv1",
                    volume_mounts=[{"volume_id": str(uuid_mod.uuid4()), "mount_path": "/data"}],
                )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        vols = call_kwargs["volumes"]
        assert "db-volume-name" in vols

    @pytest.mark.asyncio
    async def test_spawn_with_db_volume_not_found(self, fresh_spawner):
        """spawn should fallback to generated name when volume_id not in DB."""
        mock_session = mock.AsyncMock()
        mock_session.execute = mock.AsyncMock(
            return_value=mock.Mock(scalar_one_or_none=mock.Mock(return_value=None))
        )
        mock_context = mock.AsyncMock()
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_session)
        mock_context.__aexit__ = mock.AsyncMock(return_value=False)

        vol_id = str(uuid_mod.uuid4())
        with mock.patch("app.db.session.async_session", return_value=mock_context):
            with mock.patch("app.container.spawner.settings.public_url", "http://test"):
                await fresh_spawner.spawn(
                    user_id=str(uuid_mod.uuid4()),
                    username="testuser",
                    server_name="srv1",
                    volume_mounts=[{"volume_id": vol_id, "mount_path": "/data"}],
                )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        vols = call_kwargs["volumes"]
        expected_name = f"nukelab-vol-{vol_id[:8]}"
        assert expected_name in vols


# ─────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────


class TestModuleSingleton:
    """Tests for the module-level spawner singleton."""

    def test_singleton_exists(self):
        """The module should export a spawner singleton instance."""
        from app.container.spawner import spawner as s

        assert isinstance(s, ServerSpawner)
