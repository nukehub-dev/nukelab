# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Coverage-gap tests for app.container.docker_driver.

Targets branches not exercised by test_client.py / test_driver.py:
Podman detection, GPU device requests (Docker + Podman/CDI), container
hardening, network aliases/hostname, LD_PRELOAD combination, exec output
streaming, archive writes, volume/image wrappers, and error mapping.
"""

from unittest import mock

import aiodocker
import aiohttp
import pytest

from app.config import settings
from app.container.docker_driver import DockerDriver
from app.container.driver import ContainerDriverError


def _make_driver(
    controllers: set[str] | None = None,
    storage: bool = False,
    lxcfs: bool = False,
    cpu_lib_ready: bool = False,
):
    """Build a DockerDriver with detection caches preset and a mocked client."""
    driver = DockerDriver()
    driver.client = mock.AsyncMock()
    driver._available_cgroup_controllers = controllers if controllers is not None else set()
    driver._storage_support = storage
    driver._lxcfs_support = lxcfs
    driver._cpu_lib_volume_ready = cpu_lib_ready
    if not cpu_lib_ready:
        driver.client.volumes.get = mock.AsyncMock(side_effect=Exception("missing"))
    container = mock.AsyncMock()
    container.id = "cid-1"
    driver.client.containers.create = mock.AsyncMock(return_value=container)
    return driver, container


@pytest.fixture
def hardening_off(monkeypatch):
    monkeypatch.setattr(settings, "container_hardening_enabled", False)


class TestDetectPodman:
    @pytest.mark.asyncio
    async def test_cached_value_returned_without_version_call(self):
        driver, _ = _make_driver()
        driver._is_podman = True
        assert await driver._detect_podman() is True
        driver.client.version.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_detects_podman_from_version_info(self):
        driver, _ = _make_driver()
        driver.client.version = mock.AsyncMock(
            return_value={"Components": [{"Name": "Podman Engine"}]}
        )
        assert await driver.is_podman() is True
        # Second call uses the cache.
        driver.client.version = mock.AsyncMock(side_effect=AssertionError("should be cached"))
        assert await driver.is_podman() is True

    @pytest.mark.asyncio
    async def test_detects_docker_from_version_info(self):
        driver, _ = _make_driver()
        driver.client.version = mock.AsyncMock(return_value={"Components": [{"Name": "Engine"}]})
        assert await driver.is_podman() is False

    @pytest.mark.asyncio
    async def test_version_failure_defaults_to_docker(self):
        driver, _ = _make_driver()
        driver.client.version = mock.AsyncMock(side_effect=Exception("socket gone"))
        assert await driver.is_podman() is False


class TestCreateContainerGpu:
    @pytest.mark.asyncio
    async def test_gpu_requested_but_disabled_raises(self, monkeypatch, hardening_off):
        monkeypatch.setattr(settings, "gpu_enabled", False)
        driver, _ = _make_driver()
        with pytest.raises(ValueError, match="GPU support is disabled"):
            await driver.create_container("gpu-1", "img:latest", gpu_limit=1)

    @pytest.mark.asyncio
    async def test_docker_gpu_uses_nvidia_driver_with_count(self, monkeypatch, hardening_off):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        driver, _ = _make_driver()
        driver._is_podman = False

        await driver.create_container("gpu-1", "img:latest", gpu_limit=2)

        config = driver.client.containers.create.call_args[0][0]
        (request,) = config["HostConfig"]["DeviceRequests"]
        assert request["Driver"] == "nvidia"
        assert request["Count"] == 2
        assert request["Capabilities"] == [["gpu", "compute", "utility"]]
        assert "DeviceIDs" not in request

    @pytest.mark.asyncio
    async def test_docker_gpu_strips_cdi_prefix_from_device_ids(self, monkeypatch, hardening_off):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        driver, _ = _make_driver()
        driver._is_podman = False

        await driver.create_container(
            "gpu-1", "img:latest", gpu_limit=1, gpu_devices=["nvidia.com/gpu=0"]
        )

        config = driver.client.containers.create.call_args[0][0]
        (request,) = config["HostConfig"]["DeviceRequests"]
        assert request["DeviceIDs"] == ["0"]
        assert "Count" not in request

    @pytest.mark.asyncio
    async def test_podman_gpu_uses_cdi_default_device(self, monkeypatch, hardening_off):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        monkeypatch.setattr(settings, "gpu_cdi_device", "nvidia.com/gpu=all")
        driver, _ = _make_driver()
        driver._is_podman = True

        await driver.create_container("gpu-1", "img:latest", gpu_limit=1)

        config = driver.client.containers.create.call_args[0][0]
        (request,) = config["HostConfig"]["DeviceRequests"]
        assert request == {
            "Driver": "cdi",
            "DeviceIDs": ["nvidia.com/gpu=all"],
            "Capabilities": [["gpu"]],
        }

    @pytest.mark.asyncio
    async def test_podman_gpu_uses_explicit_device_ids(self, monkeypatch, hardening_off):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        driver, _ = _make_driver()
        driver._is_podman = True

        await driver.create_container(
            "gpu-1", "img:latest", gpu_limit=1, gpu_devices=["nvidia.com/gpu=1"]
        )

        config = driver.client.containers.create.call_args[0][0]
        (request,) = config["HostConfig"]["DeviceRequests"]
        assert request["DeviceIDs"] == ["nvidia.com/gpu=1"]


class TestCreateContainerHardening:
    @pytest.mark.asyncio
    async def test_hardening_applies_all_options(self, monkeypatch):
        monkeypatch.setattr(settings, "container_hardening_enabled", True)
        monkeypatch.setattr(settings, "container_uid", 65532)
        monkeypatch.setattr(settings, "container_gid", 65532)
        monkeypatch.setattr(settings, "container_drop_all_capabilities", True)
        monkeypatch.setattr(settings, "container_no_new_privileges", True)
        monkeypatch.setattr(settings, "container_readonly_rootfs", True)
        monkeypatch.setattr(settings, "container_readonly_tmpfs_paths", ["/tmp", "/run"])
        driver, _ = _make_driver()

        await driver.create_container("hard-1", "img:latest")

        config = driver.client.containers.create.call_args[0][0]
        host_config = config["HostConfig"]
        assert host_config["User"] == "65532:65532"
        assert config["User"] == "65532:65532"
        assert host_config["CapDrop"] == ["ALL"]
        assert host_config["SecurityOpt"] == ["no-new-privileges:true"]
        assert host_config["ReadonlyRootfs"] is True
        assert host_config["Tmpfs"] == {"/tmp": "mode=1777,size=100m", "/run": "mode=1777,size=100m"}

    @pytest.mark.asyncio
    async def test_hardening_without_readonly_rootfs_omits_tmpfs(self, monkeypatch):
        monkeypatch.setattr(settings, "container_hardening_enabled", True)
        monkeypatch.setattr(settings, "container_drop_all_capabilities", False)
        monkeypatch.setattr(settings, "container_no_new_privileges", False)
        monkeypatch.setattr(settings, "container_readonly_rootfs", False)
        driver, _ = _make_driver()

        await driver.create_container("hard-2", "img:latest")

        host_config = driver.client.containers.create.call_args[0][0]["HostConfig"]
        assert "CapDrop" not in host_config
        assert "SecurityOpt" not in host_config
        assert "ReadonlyRootfs" not in host_config
        assert "Tmpfs" not in host_config


class TestCreateContainerMisc:
    @pytest.mark.asyncio
    async def test_network_aliases_and_hostname(self, monkeypatch, hardening_off):
        monkeypatch.setattr(settings, "docker_network", "nukelab-network")
        driver, _ = _make_driver()

        await driver.create_container(
            "aliased-1",
            "img:latest",
            hostname="srv-host",
            network_aliases=["short-alias"],
        )

        config = driver.client.containers.create.call_args[0][0]
        assert config["Hostname"] == "srv-host"
        assert config["NetworkingConfig"] == {
            "EndpointsConfig": {"nukelab-network": {"Aliases": ["short-alias"]}}
        }

    @pytest.mark.asyncio
    async def test_existing_ld_preload_is_combined(self, hardening_off):
        driver, _ = _make_driver()

        await driver.create_container(
            "env-1", "img:latest", env={"LD_PRELOAD": "/usr/lib/libnss_wrapper.so"}
        )

        config = driver.client.containers.create.call_args[0][0]
        preload_entries = [e for e in config["Env"] if e.startswith("LD_PRELOAD=")]
        assert preload_entries == [
            "LD_PRELOAD=/usr/lib/libnss_wrapper.so:/usr/local/lib/nukelab/libnukelab_cpu.so"
        ]

    @pytest.mark.asyncio
    async def test_unparseable_disk_limit_is_swallowed(self, hardening_off):
        driver, _ = _make_driver(storage=True)

        await driver.create_container("disk-1", "img:latest", disk_limit="bogus")

        config = driver.client.containers.create.call_args[0][0]
        assert "StorageOpt" not in config["HostConfig"]

    @pytest.mark.asyncio
    async def test_docker_error_on_create_is_mapped(self, hardening_off):
        driver, _ = _make_driver()
        driver.client.containers.create = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=409, data={"message": "name in use"})
        )

        with pytest.raises(ContainerDriverError) as exc_info:
            await driver.create_container("dup-1", "img:latest")

        assert exc_info.value.status == 409

    @pytest.mark.asyncio
    async def test_cpu_lib_volume_mounted_when_ready(self, hardening_off):
        driver, _ = _make_driver(cpu_lib_ready=True)

        await driver.create_container("vol-1", "img:latest")

        config = driver.client.containers.create.call_args[0][0]
        assert config["HostConfig"]["Mounts"] == [
            {
                "Type": "volume",
                "Source": DockerDriver.VOLUME_CPU_LIB,
                "Target": DockerDriver.CPU_LIB_TARGET,
                "ReadOnly": True,
            }
        ]

    @pytest.mark.asyncio
    async def test_lxcfs_binds_created_when_no_other_binds(self, monkeypatch, hardening_off):
        driver, _ = _make_driver(lxcfs=True)
        monkeypatch.setattr("app.container.docker_driver.os.path.exists", lambda p: True)

        await driver.create_container("lxcfs-1", "img:latest")

        config = driver.client.containers.create.call_args[0][0]
        assert any(b.startswith("/var/lib/lxcfs/proc/") for b in config["HostConfig"]["Binds"])


class TestExecInContainer:
    @pytest.mark.asyncio
    async def test_non_detach_reads_stream_until_none(self):
        driver, _ = _make_driver()
        mock_container = mock.AsyncMock()
        driver.client.containers.get = mock.AsyncMock(return_value=mock_container)

        msg1 = mock.MagicMock(data=b"hello ")
        msg2 = mock.MagicMock(data=b"world")
        stream = mock.AsyncMock()
        stream.read_out = mock.AsyncMock(side_effect=[msg1, msg2, None])
        stream_cm = mock.AsyncMock()
        stream_cm.__aenter__ = mock.AsyncMock(return_value=stream)
        stream_cm.__aexit__ = mock.AsyncMock(return_value=False)
        mock_exec = mock.AsyncMock()
        mock_exec.start = mock.MagicMock(return_value=stream_cm)
        mock_container.exec = mock.AsyncMock(return_value=mock_exec)

        output = await driver.exec_in_container("cid", ["echo", "hi"])

        assert output == "hello world"
        mock_container.exec.assert_awaited_once_with(["echo", "hi"])

    @pytest.mark.asyncio
    async def test_get_error_is_mapped(self):
        driver, _ = _make_driver()
        driver.client.containers.get = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=404, data={"message": "gone"})
        )
        with pytest.raises(ContainerDriverError):
            await driver.exec_in_container("cid", ["ls"])


class TestPutArchive:
    @pytest.mark.asyncio
    async def test_put_archive_success(self):
        driver, _ = _make_driver()
        mock_container = mock.AsyncMock()
        driver.client.containers.get = mock.AsyncMock(return_value=mock_container)

        await driver.put_archive("cid", "/etc", b"tar-bytes")

        mock_container.put_archive.assert_awaited_once_with("/etc", b"tar-bytes")

    @pytest.mark.asyncio
    async def test_put_archive_maps_error(self):
        driver, _ = _make_driver()
        driver.client.containers.get = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=404, data={"message": "gone"})
        )
        with pytest.raises(ContainerDriverError):
            await driver.put_archive("cid", "/etc", b"tar-bytes")


class TestVolumeAndImageWrappers:
    @pytest.mark.asyncio
    async def test_ensure_volume_maps_create_error_when_missing(self):
        driver, _ = _make_driver()
        driver.client.volumes.get = mock.AsyncMock(side_effect=Exception("missing"))
        driver.client.volumes.create = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=500, data={"message": "daemon error"})
        )
        with pytest.raises(ContainerDriverError) as exc_info:
            await driver.ensure_volume("vol-1")
        assert exc_info.value.status == 500

    @pytest.mark.asyncio
    async def test_create_volume_success(self):
        driver, _ = _make_driver()
        await driver.create_volume("vol-1", labels={"a": "b"})
        driver.client.volumes.create.assert_awaited_once_with(
            {"Name": "vol-1", "Labels": {"a": "b"}}
        )

    @pytest.mark.asyncio
    async def test_get_volume_returns_info_or_none(self):
        driver, _ = _make_driver()
        volume = mock.AsyncMock()
        volume.show = mock.AsyncMock(return_value={"Name": "vol-1"})
        driver.client.volumes.get = mock.AsyncMock(return_value=volume)
        assert await driver.get_volume("vol-1") == {"Name": "vol-1"}

        driver.client.volumes.get = mock.AsyncMock(side_effect=Exception("missing"))
        assert await driver.get_volume("vol-1") is None

    @pytest.mark.asyncio
    async def test_delete_volume_best_effort(self):
        driver, _ = _make_driver()
        volume = mock.AsyncMock()
        driver.client.volumes.get = mock.AsyncMock(return_value=volume)
        await driver.delete_volume("vol-1")
        volume.delete.assert_awaited_once()

        driver.client.volumes.get = mock.AsyncMock(side_effect=Exception("missing"))
        await driver.delete_volume("vol-1")  # must not raise

    @pytest.mark.asyncio
    async def test_list_images_success(self):
        driver, _ = _make_driver()
        driver.client.images.list = mock.AsyncMock(return_value=[{"Id": "img1"}])
        assert await driver.list_images() == [{"Id": "img1"}]

    @pytest.mark.asyncio
    async def test_list_images_maps_error(self):
        driver, _ = _make_driver()
        driver.client.images.list = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=500, data={"message": "daemon error"})
        )
        with pytest.raises(ContainerDriverError):
            await driver.list_images()


class TestErrorMappingGaps:
    @pytest.mark.asyncio
    async def test_pull_image_maps_error(self):
        driver, _ = _make_driver()
        driver.client.images.pull = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=404, data={"message": "no such image"})
        )
        with pytest.raises(ContainerDriverError) as exc_info:
            await driver.pull_image("missing:latest")
        assert exc_info.value.status == 404

    @pytest.mark.asyncio
    async def test_version_maps_error(self):
        driver, _ = _make_driver()
        driver.client.version = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=500, data={"message": "boom"})
        )
        with pytest.raises(ContainerDriverError):
            await driver.version()

    @pytest.mark.asyncio
    async def test_list_containers_maps_error(self):
        driver, _ = _make_driver()
        driver.client.containers.list = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=500, data={"message": "boom"})
        )
        with pytest.raises(ContainerDriverError):
            await driver.list_containers()

    @pytest.mark.asyncio
    async def test_get_container_stats_maps_error(self):
        driver, _ = _make_driver()
        driver.client.containers.get = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=404, data={"message": "gone"})
        )
        with pytest.raises(ContainerDriverError):
            await driver.get_container_stats("cid")

    @pytest.mark.asyncio
    async def test_get_logs_maps_get_error(self):
        driver, _ = _make_driver()
        driver.client.containers.get = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=404, data={"message": "gone"})
        )
        with pytest.raises(ContainerDriverError):
            await driver.get_container_logs("cid")

    @pytest.mark.asyncio
    async def test_stream_logs_maps_get_error(self):
        driver, _ = _make_driver()
        driver.client.containers.get = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=404, data={"message": "gone"})
        )
        with pytest.raises(ContainerDriverError):
            await driver.stream_container_logs("cid")


class TestWaitForContainerReady:
    @pytest.mark.asyncio
    async def test_recovers_from_probe_exception(self):
        class Resp:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        mock_session = mock.AsyncMock(spec=aiohttp.ClientSession)
        mock_session.get.side_effect = [Exception("connection refused"), Resp()]
        fake_cm = mock.AsyncMock()
        fake_cm.__aenter__ = mock.AsyncMock(return_value=mock_session)
        fake_cm.__aexit__ = mock.AsyncMock(return_value=False)

        driver, _ = _make_driver()
        with mock.patch("app.container.docker_driver.aiohttp.ClientSession", return_value=fake_cm):
            result = await driver.wait_for_container_ready(
                "srv", "http://srv:8080/health", timeout=30, interval=0
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_zero_timeout_returns_false_without_probing(self):
        driver, _ = _make_driver()
        with mock.patch("app.container.docker_driver.aiohttp.ClientSession") as session_cls:
            result = await driver.wait_for_container_ready(
                "srv", "http://srv:8080/health", timeout=0
            )

        assert result is False
        session_cls.assert_not_called()
