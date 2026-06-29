"""Container runtime security regression tests.

These tests verify that user containers are spawned with appropriate security
options and cannot easily escape or access host resources.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_container_client(captured: dict):
    """Build a mocked ContainerClient that captures spawn-time config."""

    async def fake_create_container(**kwargs):
        captured["create_kwargs"] = kwargs
        mock_container = MagicMock()
        mock_container.id = "mock-cid"
        return mock_container

    mock_client = MagicMock()
    mock_client.volumes = MagicMock()
    mock_client.volumes.get = AsyncMock(side_effect=Exception("not found"))
    mock_client.volumes.create = AsyncMock()
    mock_client.images = MagicMock()
    mock_client.images.get = AsyncMock(side_effect=Exception("not found"))

    mock_container_client = MagicMock()
    mock_container_client.client = mock_client
    mock_container_client.pull_image = AsyncMock()
    mock_container_client.create_container = AsyncMock(side_effect=fake_create_container)
    mock_container_client.start_container = AsyncMock()
    mock_container_client.wait_for_container_ready = AsyncMock(return_value=True)
    mock_container_client.get_container_info = AsyncMock(
        return_value={"State": {"Status": "running"}}
    )

    return mock_container_client


class TestContainerSecurityOptions:
    """Verify container security configuration at spawn time."""

    @pytest.mark.asyncio
    async def test_spawn_does_not_mount_docker_socket(self, db_session, test_user):
        """User containers should never mount the Docker socket."""
        from app.container.spawner import spawner
        from app.models.environment_template import EnvironmentTemplate
        from app.models.server_plan import ServerPlan

        plan = ServerPlan(
            name="No Socket Plan",
            slug="no-socket-plan",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=1,
            is_active=True,
            visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="No Socket Env",
            slug="no-socket-env",
            image="hello-world",
            is_active=True,
            is_public=True,
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        captured = {}
        mock_container_client = _make_mock_container_client(captured)

        with patch.object(spawner, "_get_container_client", return_value=mock_container_client):
            await spawner.spawn(
                user_id=str(test_user.id),
                username=test_user.username,
                server_name="no-socket-server",
                environment=env.slug,
                environment_id=str(env.id),
                image=env.image,
                cpu=plan.cpu_limit,
                memory=plan.memory_limit,
                disk=plan.disk_limit,
            )

        create_kwargs = captured.get("create_kwargs", {})
        volumes = create_kwargs.get("volumes", {})
        binds = create_kwargs.get("binds", [])

        # Volumes dict keys are host volume names; values are bind paths/modes.
        for host_volume in volumes.keys():
            assert "/var/run/docker.sock" not in host_volume, (
                "Docker socket mounted in user container"
            )
            assert "docker.sock" not in host_volume, "Docker socket path mounted in user container"

        for bind in binds:
            assert "/var/run/docker.sock" not in bind, "Docker socket mounted in user container"
            assert "docker.sock" not in bind, "Docker socket path mounted in user container"

    @pytest.mark.asyncio
    async def test_spawn_uses_isolated_network(self, db_session, test_user):
        """User containers should use the configured isolated Docker network."""
        from app.config import settings
        from app.container.spawner import spawner
        from app.models.environment_template import EnvironmentTemplate
        from app.models.server_plan import ServerPlan

        plan = ServerPlan(
            name="Network Plan",
            slug="network-plan",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=1,
            is_active=True,
            visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Network Env",
            slug="network-env",
            image="hello-world",
            is_active=True,
            is_public=True,
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        captured = {}
        mock_container_client = _make_mock_container_client(captured)

        with patch.object(spawner, "_get_container_client", return_value=mock_container_client):
            await spawner.spawn(
                user_id=str(test_user.id),
                username=test_user.username,
                server_name="network-server",
                environment=env.slug,
                environment_id=str(env.id),
                image=env.image,
                cpu=plan.cpu_limit,
                memory=plan.memory_limit,
                disk=plan.disk_limit,
            )

        create_kwargs = captured.get("create_kwargs", {})
        network = create_kwargs.get("network")
        assert network == settings.docker_network, (
            f"Container not on expected isolated network: {network} != {settings.docker_network}"
        )


class TestContainerHardening:
    """Tests for container hardening controls.

    These tests document expected production-hardening controls. If they fail,
    the finding should be recorded in docs/PENETRATION-TEST-FINDINGS.md.
    """

    @pytest.fixture
    def hardened_settings(self):
        """Patch settings to force container hardening on."""
        from app.config import settings

        original = {
            "container_hardening_enabled": settings.container_hardening_enabled,
            "container_user": settings.container_user,
            "container_uid": settings.container_uid,
            "container_gid": settings.container_gid,
            "container_drop_all_capabilities": settings.container_drop_all_capabilities,
            "container_readonly_rootfs": settings.container_readonly_rootfs,
            "container_no_new_privileges": settings.container_no_new_privileges,
            "container_readonly_tmpfs_paths": list(settings.container_readonly_tmpfs_paths),
        }
        settings.container_hardening_enabled = True
        settings.container_user = "nukelab"
        settings.container_uid = 1000
        settings.container_gid = 1000
        settings.container_drop_all_capabilities = True
        settings.container_readonly_rootfs = True
        settings.container_no_new_privileges = True
        settings.container_readonly_tmpfs_paths = [
            "/tmp",
            "/var/tmp",
            "/var/run",
            "/var/log/nginx",
            "/var/cache/nginx",
        ]
        yield settings
        for key, value in original.items():
            setattr(settings, key, value)

    @pytest.mark.asyncio
    async def test_container_runs_as_non_root(self, hardened_settings):
        """User containers should run as a non-root user."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())
        client._cpu_lib_volume_ready = False
        client._lxcfs_support = False

        await client.create_container(name="test", image="hello-world")

        call_args = client.client.containers.create.call_args
        config = call_args[0][0]
        assert config["HostConfig"]["User"] == "1000:1000", (
            f"Container not running as expected non-root user: {config['HostConfig'].get('User')}"
        )

    @pytest.mark.asyncio
    async def test_container_drops_all_capabilities(self, hardened_settings):
        """User containers should drop all Linux capabilities."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())
        client._cpu_lib_volume_ready = False
        client._lxcfs_support = False

        await client.create_container(name="test", image="hello-world")

        call_args = client.client.containers.create.call_args
        config = call_args[0][0]
        assert config["HostConfig"].get("CapDrop") == ["ALL"], (
            f"Container did not drop all capabilities: {config['HostConfig'].get('CapDrop')}"
        )

    @pytest.mark.asyncio
    async def test_container_has_read_only_root_filesystem(self, hardened_settings):
        """User containers should have a read-only root filesystem."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())
        client._cpu_lib_volume_ready = False
        client._lxcfs_support = False

        await client.create_container(name="test", image="hello-world")

        call_args = client.client.containers.create.call_args
        config = call_args[0][0]
        assert config["HostConfig"].get("ReadonlyRootfs") is True, (
            "Container root filesystem is not read-only"
        )
        tmpfs = config["HostConfig"].get("Tmpfs", {})
        for path in hardened_settings.container_readonly_tmpfs_paths:
            assert path in tmpfs, f"Missing tmpfs mount for read-only rootfs: {path}"

    @pytest.mark.asyncio
    async def test_container_has_no_new_privileges(self, hardened_settings):
        """User containers should have NoNewPrivileges enabled."""
        from app.container.client import ContainerClient

        client = ContainerClient()
        client.client = MagicMock()
        client.client.containers = MagicMock()
        client.client.containers.create = AsyncMock(return_value=MagicMock())
        client._cpu_lib_volume_ready = False
        client._lxcfs_support = False

        await client.create_container(name="test", image="hello-world")

        call_args = client.client.containers.create.call_args
        config = call_args[0][0]
        assert "no-new-privileges:true" in config["HostConfig"].get("SecurityOpt", []), (
            "Container does not have no-new-privileges security option"
        )


class TestContainerNetworkIsolation:
    """Verify network isolation between user containers and system services."""

    @pytest.mark.skip(
        reason="Requires live container runtime; run manually in isolated environment"
    )
    def test_user_container_cannot_reach_backend_api(self):
        """From inside a user container, the FastAPI backend should not be reachable."""
        pass

    @pytest.mark.skip(
        reason="Requires live container runtime; run manually in isolated environment"
    )
    def test_user_container_cannot_reach_redis(self):
        """From inside a user container, Redis should not be reachable."""
        pass

    @pytest.mark.skip(
        reason="Requires live container runtime; run manually in isolated environment"
    )
    def test_user_container_cannot_reach_postgres(self):
        """From inside a user container, PostgreSQL should not be reachable."""
        pass
