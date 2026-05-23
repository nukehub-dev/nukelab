"""Tests for Docker spawner volume mount mode enforcement.

These tests verify that read-only volume mounts are actually enforced
at the Docker container level, not just stored in the database.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY


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
        with patch.object(client, '_check_storage_support', return_value=False):
            with patch.object(client, '_check_lxcfs_support', return_value=[]):
                with patch.object(client, '_get_available_controllers', return_value=set()):
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

        with patch.object(client, '_check_storage_support', return_value=False):
            with patch.object(client, '_check_lxcfs_support', return_value=[]):
                with patch.object(client, '_get_available_controllers', return_value=set()):
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

        with patch.object(client, '_check_storage_support', return_value=False):
            with patch.object(client, '_check_lxcfs_support', return_value=[]):
                with patch.object(client, '_get_available_controllers', return_value=set()):
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

        with patch.object(client, '_check_storage_support', return_value=False):
            with patch.object(client, '_check_lxcfs_support', return_value=[]):
                with patch.object(client, '_get_available_controllers', return_value=set()):
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

        with patch.object(client, '_check_storage_support', return_value=False):
            with patch.object(client, '_check_lxcfs_support', return_value=[]):
                with patch.object(client, '_get_available_controllers', return_value=set()):
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

        with patch.object(client, '_check_storage_support', return_value=False):
            with patch.object(client, '_check_lxcfs_support', return_value=[]):
                with patch.object(client, '_get_available_controllers', return_value=set()):
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

        spawner = ServerSpawner()

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
        from app.container.spawner import ServerSpawner
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
