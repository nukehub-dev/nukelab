"""Tests for ContainerClient."""

import io
import pytest
from unittest import mock

from app.container.client import ContainerClient, get_container_client, get_fresh_container_client


class TestParseMemory:
    @pytest.fixture
    def client(self):
        return ContainerClient()

    def test_parse_bytes(self, client):
        assert client._parse_memory("1024b") == 1024

    def test_parse_kilobytes(self, client):
        assert client._parse_memory("4k") == 4 * 1024

    def test_parse_megabytes(self, client):
        assert client._parse_memory("512m") == 512 * 1024**2

    def test_parse_gigabytes(self, client):
        assert client._parse_memory("2g") == 2 * 1024**3

    def test_parse_plain_number(self, client):
        assert client._parse_memory("1024") == 1024

    def test_parse_float(self, client):
        assert client._parse_memory("1.5g") == int(1.5 * 1024**3)


class TestGetCpuEnv:
    @pytest.fixture
    def client(self):
        return ContainerClient()

    def test_cpu_env_with_limit(self, client):
        env = client._get_cpu_env(4.0)
        assert env["OMP_NUM_THREADS"] == "4"
        assert env["MKL_NUM_THREADS"] == "4"
        assert env["NUKELAB_CPU_COUNT"] == "4"
        assert "LD_PRELOAD" in env

    def test_cpu_env_without_limit(self, client):
        with mock.patch("os.cpu_count", return_value=8):
            env = client._get_cpu_env(None)
            assert env["OMP_NUM_THREADS"] == "8"

    def test_cpu_env_zero_limit(self, client):
        with mock.patch("os.cpu_count", return_value=4):
            env = client._get_cpu_env(0)
            assert env["OMP_NUM_THREADS"] == "4"


class TestGetLxcfsMounts:
    @pytest.fixture
    def client(self):
        return ContainerClient()

    def test_no_lxcfs_support_returns_empty(self, client):
        client._lxcfs_support = False
        assert client._get_lxcfs_mounts() == []

    def test_lxcfs_support_returns_mounts(self, client):
        client._lxcfs_support = True
        with mock.patch("os.path.exists", return_value=True):
            mounts = client._get_lxcfs_mounts()
            assert len(mounts) > 0
            assert all(m.startswith("/var/lib/lxcfs") for m in mounts)

    def test_lxcfs_support_missing_files_skipped(self, client):
        client._lxcfs_support = True
        with mock.patch("os.path.exists", return_value=False):
            mounts = client._get_lxcfs_mounts()
            assert mounts == []


class TestConnectAndClose:
    @pytest.mark.asyncio
    async def test_connect_sets_client(self):
        client = ContainerClient()
        with mock.patch("aiodocker.Docker") as MockDocker:
            await client.connect()
            assert client.client is not None
            MockDocker.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_clears_client(self):
        client = ContainerClient()
        mock_docker = mock.AsyncMock()
        client.client = mock_docker
        await client.close()
        mock_docker.close.assert_awaited_once()


class TestGetContainerClient:
    @pytest.mark.asyncio
    async def test_get_container_client_connects_when_not_connected(self):
        with mock.patch("app.container.client.container_client") as mock_client:
            mock_client.client = None
            mock_client.connect = mock.AsyncMock()
            result = await get_container_client()
            mock_client.connect.assert_awaited_once()
            assert result == mock_client

    @pytest.mark.asyncio
    async def test_get_container_client_reuses_existing(self):
        with mock.patch("app.container.client.container_client") as mock_client:
            mock_client.client = mock.Mock()
            mock_client.connect = mock.AsyncMock()
            result = await get_container_client()
            mock_client.connect.assert_not_awaited()
            assert result == mock_client

    @pytest.mark.asyncio
    async def test_get_fresh_container_client(self):
        with mock.patch("aiodocker.Docker"):
            client = await get_fresh_container_client()
            assert isinstance(client, ContainerClient)
            assert client.client is not None


class TestPullImage:
    @pytest.mark.asyncio
    async def test_pull_image(self):
        client = ContainerClient()
        client.client = mock.AsyncMock()
        await client.pull_image("nginx:latest")
        client.client.images.pull.assert_awaited_once_with("nginx:latest")


class TestGetAvailableControllers:
    @pytest.mark.asyncio
    async def test_caches_result(self):
        client = ContainerClient()
        client._available_cgroup_controllers = {"cpu", "memory"}
        result = await client._get_available_controllers()
        assert result == {"cpu", "memory"}

    @pytest.mark.asyncio
    async def test_reads_cgroup_files(self):
        client = ContainerClient()

        def fake_exists(path):
            return path in (
                "/sys/fs/cgroup/cgroup.controllers",
                "/sys/fs/cgroup/cgroup.subtree_control",
            )

        def fake_open(path, *args, **kwargs):
            if path == "/sys/fs/cgroup/cgroup.controllers":
                return mock.mock_open(read_data="cpu memory\n")()
            if path == "/sys/fs/cgroup/cgroup.subtree_control":
                return mock.mock_open(read_data="io pids\n")()
            raise FileNotFoundError(path)

        with (
            mock.patch("os.path.exists", side_effect=fake_exists),
            mock.patch("builtins.open", side_effect=fake_open),
        ):
            result = await client._get_available_controllers()
            assert result == {"cpu", "memory", "io", "pids"}
            assert client._available_cgroup_controllers == {"cpu", "memory", "io", "pids"}

    @pytest.mark.asyncio
    async def test_no_cgroup_files(self):
        client = ContainerClient()
        with mock.patch("os.path.exists", return_value=False):
            result = await client._get_available_controllers()
            assert result == set()

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        client = ContainerClient()
        with mock.patch("os.path.exists", side_effect=PermissionError("nope")):
            result = await client._get_available_controllers()
            assert result == set()


class TestCheckLxcfsSupport:
    @pytest.mark.asyncio
    async def test_caches_result(self):
        client = ContainerClient()
        client._lxcfs_support = True
        result = await client._check_lxcfs_support()
        assert result is True

    @pytest.mark.asyncio
    async def test_missing_lxcfs_file(self):
        client = ContainerClient()
        with mock.patch("os.path.exists", return_value=False):
            result = await client._check_lxcfs_support()
            assert result is False
            assert client._lxcfs_support is False

    @pytest.mark.asyncio
    async def test_lxcfs_available(self):
        client = ContainerClient()
        with mock.patch("os.path.exists", return_value=True):
            result = await client._check_lxcfs_support()
            assert result is True
            assert client._lxcfs_support is True


class TestEnsureCpuLibVolume:
    @pytest.mark.asyncio
    async def test_already_ready(self):
        client = ContainerClient()
        client._cpu_lib_volume_ready = True
        client.client = mock.AsyncMock()
        await client._ensure_cpu_lib_volume()
        client.client.volumes.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_volume_exists(self):
        client = ContainerClient()
        client.client = mock.AsyncMock()
        await client._ensure_cpu_lib_volume()
        client.client.volumes.get.assert_awaited_once_with("nukelab-cpu-lib")
        assert client._cpu_lib_volume_ready is True

    @pytest.mark.asyncio
    async def test_volume_missing(self):
        client = ContainerClient()
        client.client = mock.AsyncMock()
        client.client.volumes.get.side_effect = Exception("not found")
        await client._ensure_cpu_lib_volume()
        assert client._cpu_lib_volume_ready is False


class TestCheckStorageSupport:
    @pytest.mark.asyncio
    async def test_caches_result(self):
        client = ContainerClient()
        client._storage_support = True
        result = await client._check_storage_support()
        assert result is True

    @pytest.mark.asyncio
    async def test_image_exists_and_storage_supported(self):
        client = ContainerClient()
        client.client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        result = await client._check_storage_support()
        assert result is True
        mock_container.delete.assert_awaited_once_with(force=True)

    @pytest.mark.asyncio
    async def test_image_needs_pull(self):
        client = ContainerClient()
        client.client = mock.AsyncMock()
        client.client.images.get.side_effect = Exception("not found")
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        result = await client._check_storage_support()
        assert result is True
        client.client.images.pull.assert_awaited_once_with("busybox:latest")

    @pytest.mark.asyncio
    async def test_pull_fails(self):
        client = ContainerClient()
        client.client = mock.AsyncMock()
        client.client.images.get.side_effect = Exception("not found")
        client.client.images.pull.side_effect = Exception("network error")
        result = await client._check_storage_support()
        assert result is False

    @pytest.mark.asyncio
    async def test_container_create_fails(self):
        client = ContainerClient()
        client.client = mock.AsyncMock()
        client.client.containers.create.side_effect = Exception("driver error")
        result = await client._check_storage_support()
        assert result is False


class TestCreateContainer:
    @pytest.fixture
    def client(self):
        c = ContainerClient()
        c.client = mock.AsyncMock()
        return c

    @pytest.mark.asyncio
    async def test_minimal_create(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
        ):
            result = await client.create_container("test-1", "nginx:latest")
            assert result == mock_container
            client.client.containers.create.assert_awaited_once()
            config = client.client.containers.create.call_args[0][0]
            assert config["Image"] == "nginx:latest"

    @pytest.mark.asyncio
    async def test_with_ports(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
        ):
            await client.create_container("test-1", "nginx:latest", ports={"80": "8080"})
            config = client.client.containers.create.call_args[0][0]
            assert config["ExposedPorts"] == {"80/tcp": {}}
            assert config["HostConfig"]["PortBindings"] == {"80/tcp": [{"HostPort": "8080"}]}

    @pytest.mark.asyncio
    async def test_with_volumes_old_format(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
        ):
            await client.create_container("test-1", "nginx:latest", volumes={"/host": "/container"})
            config = client.client.containers.create.call_args[0][0]
            assert "/host:/container" in config["HostConfig"]["Binds"]

    @pytest.mark.asyncio
    async def test_with_volumes_new_format(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
        ):
            await client.create_container(
                "test-1", "nginx:latest", volumes={"/host": {"bind": "/container", "mode": "rw"}}
            )
            config = client.client.containers.create.call_args[0][0]
            assert "/host:/container:rw" in config["HostConfig"]["Binds"]

    @pytest.mark.asyncio
    async def test_with_cpu_limit_and_controllers(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value={"cpu", "cpuset"}),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
            mock.patch("os.cpu_count", return_value=8),
        ):
            await client.create_container("test-1", "nginx:latest", cpu_limit=2.0)
            config = client.client.containers.create.call_args[0][0]
            assert config["HostConfig"]["NanoCpus"] == int(2.0 * 1e9)
            assert config["HostConfig"]["CpusetCpus"] == "0,1"

    @pytest.mark.asyncio
    async def test_with_cpu_limit_missing_controllers(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
        ):
            await client.create_container("test-1", "nginx:latest", cpu_limit=2.0)
            config = client.client.containers.create.call_args[0][0]
            assert "NanoCpus" not in config["HostConfig"]
            assert "CpusetCpus" not in config["HostConfig"]

    @pytest.mark.asyncio
    async def test_with_memory_limit(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value={"memory"}),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
        ):
            await client.create_container("test-1", "nginx:latest", memory_limit="512m")
            config = client.client.containers.create.call_args[0][0]
            assert config["HostConfig"]["Memory"] == 512 * 1024**2
            assert config["HostConfig"]["MemorySwap"] == 512 * 1024**2

    @pytest.mark.asyncio
    async def test_with_memory_limit_missing_controller(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
        ):
            await client.create_container("test-1", "nginx:latest", memory_limit="512m")
            config = client.client.containers.create.call_args[0][0]
            assert "Memory" not in config["HostConfig"]

    @pytest.mark.asyncio
    async def test_with_disk_limit_supported(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
            mock.patch.object(client, "_check_storage_support", return_value=True),
        ):
            await client.create_container("test-1", "nginx:latest", disk_limit="10m")
            config = client.client.containers.create.call_args[0][0]
            assert config["HostConfig"]["StorageOpt"]["size"] == f"{10 * 1024**2}b"

    @pytest.mark.asyncio
    async def test_with_disk_limit_not_supported(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
            mock.patch.object(client, "_check_storage_support", return_value=False),
        ):
            await client.create_container("test-1", "nginx:latest", disk_limit="10m")
            config = client.client.containers.create.call_args[0][0]
            assert "StorageOpt" not in config["HostConfig"]

    @pytest.mark.asyncio
    async def test_lxcfs_mounts_added(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        client._lxcfs_support = True
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
            mock.patch("os.path.exists", return_value=True),
        ):
            await client.create_container("test-1", "nginx:latest")
            config = client.client.containers.create.call_args[0][0]
            binds = config["HostConfig"].get("Binds", [])
            assert any("lxcfs" in b for b in binds)

    @pytest.mark.asyncio
    async def test_cpu_lib_volume_mounted(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        client._cpu_lib_volume_ready = True
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
        ):
            await client.create_container("test-1", "nginx:latest")
            config = client.client.containers.create.call_args[0][0]
            mounts = config["HostConfig"].get("Mounts", [])
            assert any(m["Source"] == "nukelab-cpu-lib" for m in mounts)

    @pytest.mark.asyncio
    async def test_injects_cpu_files(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
        ):
            await client.create_container("test-1", "nginx:latest", cpu_limit=2.0)
            mock_container.put_archive.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_with_command_and_env_and_labels(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.create = mock.AsyncMock(return_value=mock_container)
        with (
            mock.patch.object(client, "_get_available_controllers", return_value=set()),
            mock.patch.object(client, "_check_lxcfs_support", return_value=False),
            mock.patch.object(client, "_ensure_cpu_lib_volume"),
        ):
            await client.create_container(
                "test-1",
                "nginx:latest",
                command="sleep 30",
                env={"FOO": "bar"},
                labels={"app": "test"},
            )
            config = client.client.containers.create.call_args[0][0]
            assert config["Cmd"] == ["sleep", "30"]
            assert any("FOO=bar" in e for e in config["Env"])
            assert config["Labels"] == {"app": "test"}


class TestContainerLifecycle:
    @pytest.fixture
    def client(self):
        c = ContainerClient()
        c.client = mock.AsyncMock()
        return c

    @pytest.mark.asyncio
    async def test_start_container(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.get = mock.AsyncMock(return_value=mock_container)
        await client.start_container("abc123")
        mock_container.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_container(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.get = mock.AsyncMock(return_value=mock_container)
        await client.stop_container("abc123", timeout=10)
        mock_container.stop.assert_awaited_once_with(timeout=10)

    @pytest.mark.asyncio
    async def test_stop_container_graceful_on_error(self, client):
        client.client.containers.get.side_effect = Exception("not found")
        await client.stop_container("abc123")

    @pytest.mark.asyncio
    async def test_delete_container(self, client):
        mock_container = mock.AsyncMock()
        client.client.containers.get = mock.AsyncMock(return_value=mock_container)
        await client.delete_container("abc123", force=True)
        mock_container.delete.assert_awaited_once_with(force=True)

    @pytest.mark.asyncio
    async def test_delete_container_graceful_on_error(self, client):
        client.client.containers.get.side_effect = Exception("not found")
        await client.delete_container("abc123")

    @pytest.mark.asyncio
    async def test_get_container_info(self, client):
        mock_container = mock.AsyncMock()
        mock_container.show = mock.AsyncMock(return_value={"Id": "abc"})
        client.client.containers.get = mock.AsyncMock(return_value=mock_container)
        result = await client.get_container_info("abc123")
        assert result == {"Id": "abc"}

    @pytest.mark.asyncio
    async def test_version(self, client):
        client.client.version = mock.AsyncMock(return_value={"Version": "20.10"})
        result = await client.version()
        assert result == {"Version": "20.10"}

    @pytest.mark.asyncio
    async def test_list_containers(self, client):
        client.client.containers.list = mock.AsyncMock(return_value=[])
        result = await client.list_containers()
        assert result == []
        client.client.containers.list.assert_awaited_once_with(filters=None)

    @pytest.mark.asyncio
    async def test_list_containers_with_filters(self, client):
        client.client.containers.list = mock.AsyncMock(return_value=[])
        await client.list_containers(filters={"label": ["app=test"]})
        client.client.containers.list.assert_awaited_once_with(filters={"label": ["app=test"]})


class TestContainerLogs:
    @pytest.fixture
    def client(self):
        c = ContainerClient()
        c.client = mock.AsyncMock()
        return c

    @pytest.mark.asyncio
    async def test_get_logs_list_response(self, client):
        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value=["line1\n", "line2\n"])
        client.client.containers.get = mock.AsyncMock(return_value=mock_container)
        result = await client.get_container_logs("abc123")
        assert result == "line1\nline2\n"

    @pytest.mark.asyncio
    async def test_get_logs_string_response(self, client):
        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value="raw logs")
        client.client.containers.get = mock.AsyncMock(return_value=mock_container)
        result = await client.get_container_logs("abc123")
        assert result == "raw logs"

    @pytest.mark.asyncio
    async def test_get_logs_with_since(self, client):
        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value=[])
        client.client.containers.get = mock.AsyncMock(return_value=mock_container)
        await client.get_container_logs("abc123", since=1234567890)
        _, kwargs = mock_container.log.call_args
        assert kwargs["since"] == 1234567890

    @pytest.mark.asyncio
    async def test_stream_logs(self, client):
        mock_container = mock.AsyncMock()
        mock_container.log = mock.AsyncMock(return_value=["line1\n"])
        client.client.containers.get = mock.AsyncMock(return_value=mock_container)
        result = await client.stream_container_logs("abc123", tail=50)
        assert result == ["line1\n"]
        _, kwargs = mock_container.log.call_args
        assert kwargs["follow"] is True


class TestInjectCpuFiles:
    @pytest.fixture
    def client(self):
        c = ContainerClient()
        c.client = mock.AsyncMock()
        return c

    @pytest.mark.asyncio
    async def test_inject_cpu_files(self, client):
        mock_container = mock.AsyncMock()
        await client._inject_cpu_files(mock_container, cpu_limit=4.0)
        mock_container.put_archive.assert_awaited_once()
        _, data_bytes = mock_container.put_archive.call_args[0]
        assert isinstance(data_bytes, bytes)

    @pytest.mark.asyncio
    async def test_inject_cpu_files_no_limit(self, client):
        mock_container = mock.AsyncMock()
        with mock.patch("os.cpu_count", return_value=2):
            await client._inject_cpu_files(mock_container, cpu_limit=None)
        mock_container.put_archive.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_inject_cpu_files_failure(self, client):
        mock_container = mock.AsyncMock()
        mock_container.put_archive.side_effect = Exception("permission denied")
        await client._inject_cpu_files(mock_container, cpu_limit=2.0)
        mock_container.put_archive.assert_awaited_once()
