"""Tests for ContainerClient."""

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
        assert client._parse_memory("512m") == 512 * 1024 ** 2

    def test_parse_gigabytes(self, client):
        assert client._parse_memory("2g") == 2 * 1024 ** 3

    def test_parse_plain_number(self, client):
        assert client._parse_memory("1024") == 1024

    def test_parse_float(self, client):
        assert client._parse_memory("1.5g") == int(1.5 * 1024 ** 3)


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
