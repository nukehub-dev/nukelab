# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the container driver factory and DockerDriver boundary behavior.

Covers runtime selection (factory), DockerError → ContainerDriverError
mapping, and the driver-only wrapper methods that replaced raw aiodocker
access in spawner/services (volumes, images, stats, exec).
"""

from unittest import mock

import aiodocker
import pytest

from app.config import settings
from app.container import factory
from app.container.docker_driver import DockerDriver
from app.container.driver import ContainerDriverError


@pytest.fixture
def reset_factory(monkeypatch):
    """Reset the factory singleton around each test."""
    monkeypatch.setattr(factory, "_driver", None)
    yield
    monkeypatch.setattr(factory, "_driver", None)


class TestFactory:
    """Runtime selection via CONTAINER_RUNTIME."""

    @pytest.mark.asyncio
    async def test_default_runtime_returns_docker_driver_singleton(self, reset_factory):
        with mock.patch("aiodocker.Docker"):
            driver1 = await factory.get_driver()
            driver2 = await factory.get_driver()
        assert isinstance(driver1, DockerDriver)
        assert driver1 is driver2

    @pytest.mark.asyncio
    async def test_fresh_driver_returns_new_instance_per_call(self, reset_factory):
        with mock.patch("aiodocker.Docker"):
            driver1 = await factory.get_fresh_driver()
            driver2 = await factory.get_fresh_driver()
        assert isinstance(driver1, DockerDriver)
        assert driver1 is not driver2
        assert driver1.client is not None

    @pytest.mark.asyncio
    async def test_unknown_runtime_raises_clear_error(self, reset_factory, monkeypatch):
        monkeypatch.setattr(settings, "container_runtime", "kubernetes")
        with pytest.raises(ContainerDriverError, match="Unknown CONTAINER_RUNTIME"):
            await factory.get_driver()

    @pytest.mark.asyncio
    async def test_fresh_driver_unknown_runtime_raises(self, reset_factory, monkeypatch):
        monkeypatch.setattr(settings, "container_runtime", "podman")
        with pytest.raises(ContainerDriverError, match="Unknown CONTAINER_RUNTIME"):
            await factory.get_fresh_driver()


class TestErrorMapping:
    """aiodocker DockerError is re-raised as ContainerDriverError."""

    @pytest.mark.asyncio
    async def test_create_volume_maps_docker_error(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        driver.client.volumes.create = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=409, data={"message": "volume exists"})
        )

        with pytest.raises(ContainerDriverError) as exc_info:
            await driver.create_volume("vol-1", labels={"a": "b"})

        assert exc_info.value.message == "volume exists"
        assert exc_info.value.status == 409

    @pytest.mark.asyncio
    async def test_get_container_info_maps_docker_error(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        driver.client.containers.get = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=404, data={"message": "not found"})
        )

        with pytest.raises(ContainerDriverError) as exc_info:
            await driver.get_container_info("cid")

        assert exc_info.value.status == 404

    @pytest.mark.asyncio
    async def test_start_container_maps_docker_error(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        driver.client.containers.get = mock.AsyncMock(
            side_effect=aiodocker.DockerError(status=404, data={"message": "gone"})
        )

        with pytest.raises(ContainerDriverError):
            await driver.start_container("cid")


class TestDriverWrapperMethods:
    """Wrapper methods that replaced raw aiodocker access outside the driver."""

    @pytest.mark.asyncio
    async def test_ensure_volume_skips_create_when_present(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        driver.client.volumes.get = mock.AsyncMock(return_value=mock.AsyncMock())

        await driver.ensure_volume("vol-1", labels={"nukelab.managed": "true"})

        driver.client.volumes.get.assert_awaited_once_with("vol-1")
        driver.client.volumes.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ensure_volume_creates_when_missing(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        driver.client.volumes.get = mock.AsyncMock(side_effect=Exception("not found"))

        await driver.ensure_volume("new-vol", labels={"nukelab.managed": "true"})

        driver.client.volumes.create.assert_awaited_once_with(
            {"Name": "new-vol", "Labels": {"nukelab.managed": "true"}}
        )

    @pytest.mark.asyncio
    async def test_image_exists(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        driver.client.images.get = mock.AsyncMock(return_value=mock.AsyncMock())
        assert await driver.image_exists("img:latest") is True

        driver.client.images.get = mock.AsyncMock(side_effect=Exception("not found"))
        assert await driver.image_exists("img:latest") is False

    @pytest.mark.asyncio
    async def test_get_container_by_name(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.id = "cid-1"
        driver.client.containers.get = mock.AsyncMock(return_value=mock_container)
        assert await driver.get_container_by_name("name-1") == "cid-1"

        driver.client.containers.get = mock.AsyncMock(side_effect=Exception("not found"))
        assert await driver.get_container_by_name("name-1") is None

    @pytest.mark.asyncio
    async def test_get_container_stats_normalizes_list(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.stats = mock.AsyncMock(return_value=[{"cpu_stats": {"online_cpus": 2}}])
        driver.client.containers.get = mock.AsyncMock(return_value=mock_container)

        stats = await driver.get_container_stats("cid")
        assert stats == {"cpu_stats": {"online_cpus": 2}}

    @pytest.mark.asyncio
    async def test_get_container_status_maps_state(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.show = mock.AsyncMock(
            return_value={"State": {"Running": True, "Paused": False}}
        )
        driver.client.containers.get = mock.AsyncMock(return_value=mock_container)
        assert await driver.get_container_status("cid") == "running"

        mock_container.show = mock.AsyncMock(
            return_value={"State": {"Running": False, "Paused": True}}
        )
        assert await driver.get_container_status("cid") == "paused"

        mock_container.show = mock.AsyncMock(
            return_value={"State": {"Running": False, "Paused": False}}
        )
        assert await driver.get_container_status("cid") == "stopped"

    @pytest.mark.asyncio
    async def test_list_containers_returns_inspect_dicts(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_container.show = mock.AsyncMock(
            return_value={"Id": "cid-1", "Config": {"Labels": {"nukelab.server.id": "srv-1"}}}
        )
        driver.client.containers.list = mock.AsyncMock(return_value=[mock_container])

        containers = await driver.list_containers(filters={"status": ["running"]})
        assert containers == [{"Id": "cid-1", "Config": {"Labels": {"nukelab.server.id": "srv-1"}}}]

    @pytest.mark.asyncio
    async def test_exec_in_container_detach_returns_empty(self):
        driver = DockerDriver()
        driver.client = mock.AsyncMock()
        mock_container = mock.AsyncMock()
        mock_exec = mock.AsyncMock()
        mock_container.exec = mock.AsyncMock(return_value=mock_exec)
        driver.client.containers.get = mock.AsyncMock(return_value=mock_container)

        output = await driver.exec_in_container(
            "cid", ["chmod", "777", "/data"], user="root", detach=True
        )

        assert output == ""
        mock_container.exec.assert_awaited_once_with(["chmod", "777", "/data"], user="root")
        mock_exec.start.assert_awaited_once_with(detach=True)
