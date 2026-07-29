# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for NVIDIA GPU support.

Covers container DeviceRequests payloads (Podman CDI and Docker nvidia
driver), the GPU disabled guard, spawner wiring of gpu/allocated_gpu, quota
GPU accounting, and the nvidia-smi CSV parser.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.container.client import ContainerClient
from app.services.metrics_collector import parse_nvidia_smi_csv

PODMAN_VERSION_INFO = {
    "Platform": {"Name": "linux/amd64/fedora"},
    "Components": [{"Name": "Podman Engine", "Version": "6.0.1"}],
}
DOCKER_VERSION_INFO = {
    "Platform": {"Name": "Docker Engine - Community"},
    "Components": [{"Name": "Engine", "Version": "24.0.7"}],
    "Version": "24.0.7",
}


def _make_container_client(podman: bool):
    """Build a ContainerClient with a mocked aiodocker backend.

    Returns (client, containers_create_mock) so tests can inspect the config
    dict passed to containers.create.
    """
    mock_container = MagicMock()
    mock_container.id = "mock-cid"
    mock_container.put_archive = AsyncMock()

    mock_docker = MagicMock()
    mock_docker.version = AsyncMock(
        return_value=PODMAN_VERSION_INFO if podman else DOCKER_VERSION_INFO
    )
    mock_docker.containers = MagicMock()
    mock_docker.containers.create = AsyncMock(return_value=mock_container)
    mock_docker.volumes = MagicMock()
    mock_docker.volumes.get = AsyncMock(side_effect=Exception("not found"))

    client = ContainerClient()
    client.client = mock_docker
    return client, mock_docker.containers.create


class TestCreateContainerGpu:
    """DeviceRequests payload emitted by create_container."""

    @pytest.mark.asyncio
    async def test_podman_uses_cdi_device_request(self, monkeypatch):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        client, create_mock = _make_container_client(podman=True)

        await client.create_container(name="gpu-test", image="img:latest", gpu_limit=1)

        config = create_mock.call_args.args[0]
        device_requests = config["HostConfig"]["DeviceRequests"]
        assert device_requests == [
            {
                "Driver": "cdi",
                "DeviceIDs": [settings.gpu_cdi_device],
                "Capabilities": [["gpu"]],
            }
        ]

    @pytest.mark.asyncio
    async def test_docker_uses_nvidia_driver_device_request(self, monkeypatch):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        client, create_mock = _make_container_client(podman=False)

        await client.create_container(name="gpu-test", image="img:latest", gpu_limit=2)

        config = create_mock.call_args.args[0]
        device_requests = config["HostConfig"]["DeviceRequests"]
        assert device_requests == [
            {
                "Driver": "nvidia",
                "Count": 2,
                "Capabilities": [["gpu", "compute", "utility"]],
            }
        ]

    @pytest.mark.asyncio
    async def test_gpu_requested_but_disabled_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "gpu_enabled", False)
        client, create_mock = _make_container_client(podman=True)

        with pytest.raises(ValueError, match="GPU_ENABLED"):
            await client.create_container(name="gpu-test", image="img:latest", gpu_limit=1)

        create_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_gpu_request_means_no_device_requests(self, monkeypatch):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        client, create_mock = _make_container_client(podman=True)

        await client.create_container(name="plain-test", image="img:latest")

        config = create_mock.call_args.args[0]
        assert "DeviceRequests" not in config["HostConfig"]

    @pytest.mark.asyncio
    async def test_podman_uses_explicit_device_ids_when_given(self, monkeypatch):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        client, create_mock = _make_container_client(podman=True)

        await client.create_container(
            name="gpu-test",
            image="img:latest",
            gpu_limit=1,
            gpu_devices=["nvidia.com/gpu=1"],
        )

        config = create_mock.call_args.args[0]
        device_requests = config["HostConfig"]["DeviceRequests"]
        assert device_requests == [
            {
                "Driver": "cdi",
                "DeviceIDs": ["nvidia.com/gpu=1"],
                "Capabilities": [["gpu"]],
            }
        ]

    @pytest.mark.asyncio
    async def test_docker_converts_cdi_names_to_plain_indices(self, monkeypatch):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        client, create_mock = _make_container_client(podman=False)

        await client.create_container(
            name="gpu-test",
            image="img:latest",
            gpu_limit=2,
            gpu_devices=["nvidia.com/gpu=0", "nvidia.com/gpu=1"],
        )

        config = create_mock.call_args.args[0]
        device_requests = config["HostConfig"]["DeviceRequests"]
        assert device_requests == [
            {
                "Driver": "nvidia",
                "DeviceIDs": ["0", "1"],
                "Capabilities": [["gpu", "compute", "utility"]],
            }
        ]


class TestSpawnerGpu:
    """Spawner forwards gpu to create_container and records allocated_gpu."""

    @staticmethod
    def _make_mock_container_client(captured: dict):
        async def fake_create_container(**kwargs):
            captured["create_kwargs"] = kwargs
            return "mock-cid"

        mock_container_client = MagicMock()
        mock_container_client.ensure_volume = AsyncMock()
        mock_container_client.image_exists = AsyncMock(return_value=True)
        mock_container_client.get_container_by_name = AsyncMock(return_value=None)
        mock_container_client.create_container = AsyncMock(side_effect=fake_create_container)
        mock_container_client.start_container = AsyncMock()
        mock_container_client.exec_in_container = AsyncMock(return_value="")
        mock_container_client.wait_for_container_ready = AsyncMock(return_value=True)

        return mock_container_client

    @pytest.mark.asyncio
    async def test_spawn_forwards_gpu_and_sets_allocated_gpu(
        self, db_session, test_user, monkeypatch
    ):
        from app.container.spawner import spawner

        monkeypatch.setattr(settings, "gpu_enabled", True)

        captured = {}
        mock_container_client = self._make_mock_container_client(captured)

        with patch.object(spawner, "_get_container_client", return_value=mock_container_client):
            server = await spawner.spawn(
                user_id=str(test_user.id),
                username=test_user.username,
                server_name="gpu-server",
                environment="dev",
                image="img:latest",
                cpu=2.0,
                memory="4g",
                disk="20g",
                gpu=1,
            )

        assert captured["create_kwargs"]["gpu_limit"] == 1
        assert captured["create_kwargs"]["gpu_devices"] is None
        assert server.allocated_gpu == 1

    @pytest.mark.asyncio
    async def test_spawn_forwards_gpu_devices(self, db_session, test_user, monkeypatch):
        from app.container.spawner import spawner

        monkeypatch.setattr(settings, "gpu_enabled", True)

        captured = {}
        mock_container_client = self._make_mock_container_client(captured)

        with patch.object(spawner, "_get_container_client", return_value=mock_container_client):
            await spawner.spawn(
                user_id=str(test_user.id),
                username=test_user.username,
                server_name="gpu-server",
                environment="dev",
                image="img:latest",
                cpu=2.0,
                memory="4g",
                disk="20g",
                gpu=1,
                gpu_devices=["nvidia.com/gpu=0"],
            )

        assert captured["create_kwargs"]["gpu_limit"] == 1
        assert captured["create_kwargs"]["gpu_devices"] == ["nvidia.com/gpu=0"]

    @pytest.mark.asyncio
    async def test_spawn_gpu_requested_but_disabled_raises(self, monkeypatch):
        from app.container.spawner import spawner

        monkeypatch.setattr(settings, "gpu_enabled", False)

        with pytest.raises(Exception, match="GPU_ENABLED"):
            await spawner.spawn(
                user_id="00000000-0000-0000-0000-000000000000",
                username="someone",
                server_name="gpu-server",
                gpu=1,
            )


class TestQuotaGpuAccounting:
    """recalculate_usage sums allocated_gpu across active servers."""

    @pytest.mark.asyncio
    async def test_recalculate_usage_sums_allocated_gpu(self, db_session, test_user):
        from app.models.server import Server
        from app.services.quota_service import QuotaService

        db_session.add_all(
            [
                Server(
                    name="gpu-srv-1",
                    user_id=test_user.id,
                    status="running",
                    allocated_gpu=1,
                ),
                Server(
                    name="gpu-srv-2",
                    user_id=test_user.id,
                    status="running",
                    allocated_gpu=2,
                ),
                # Stopped servers must not count toward usage.
                Server(
                    name="gpu-srv-stopped",
                    user_id=test_user.id,
                    status="stopped",
                    allocated_gpu=5,
                ),
            ]
        )
        await db_session.commit()

        service = QuotaService(db_session)
        quota = await service.recalculate_usage(str(test_user.id))
        assert quota.usage_gpu == 3


class TestParseNvidiaSmiCsv:
    """Pure parser for nvidia-smi CSV output."""

    def test_valid_output(self):
        result = parse_nvidia_smi_csv("12, 1024, 8192, 55\n")
        assert result == {
            "gpu_percent": 12.0,
            "gpu_memory_used": 1024,
            "gpu_memory_total": 8192,
            "gpu_temperature": 55.0,
        }

    def test_multi_gpu_output_uses_first_row(self):
        result = parse_nvidia_smi_csv("90, 4096, 24576, 71\n5, 128, 24576, 40\n")
        assert result is not None
        assert result["gpu_percent"] == 90.0
        assert result["gpu_memory_total"] == 24576

    def test_garbage_returns_none(self):
        assert parse_nvidia_smi_csv("not,a,csv,line") is None
        assert parse_nvidia_smi_csv("nvidia-smi: command not found") is None

    def test_empty_returns_none(self):
        assert parse_nvidia_smi_csv("") is None
        assert parse_nvidia_smi_csv("   \n  ") is None
