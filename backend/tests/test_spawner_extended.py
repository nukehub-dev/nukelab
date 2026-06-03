"""Tests for app.container.spawner.ServerSpawner methods."""

import pytest
import uuid as uuid_mod
from unittest import mock

from app.container.spawner import ServerSpawner, spawner
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
    client.stop_container = mock.AsyncMock()
    client.delete_container = mock.AsyncMock()
    client.get_container_info = mock.AsyncMock(return_value={
        "State": {"Running": True, "Paused": False}
    })

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
        fresh_spawner.container_client.delete_container.assert_awaited_once_with("cid-123", force=True)

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

    @pytest.mark.asyncio
    async def test_spawn_with_provided_image(self, fresh_spawner):
        """spawn should use provided image."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            server = await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
                image="custom:latest",
            )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        assert call_kwargs["image"] == "custom:latest"

    @pytest.mark.asyncio
    async def test_spawn_image_fallback_on_pull_failure(self, fresh_spawner):
        """spawn should fallback to nukelab-dev:latest when image inspect and pull both fail."""
        fresh_spawner.container_client.client.images.get = mock.AsyncMock(
            side_effect=Exception("not found")
        )
        fresh_spawner.container_client.pull_image = mock.AsyncMock(
            side_effect=Exception("pull failed")
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            server = await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
            )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        assert call_kwargs["image"] == "nukelab-dev:latest"

    @pytest.mark.asyncio
    async def test_spawn_image_pull_when_not_local(self, fresh_spawner):
        """spawn should pull image when not found locally."""
        fresh_spawner.container_client.client.images.get = mock.AsyncMock(
            side_effect=Exception("not found")
        )

        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            server = await fresh_spawner.spawn(
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
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            server = await fresh_spawner.spawn(
                user_id=str(uuid_mod.uuid4()),
                username="testuser",
                server_name="srv1",
                env_vars={"FOO": "bar"},
            )

        call_kwargs = fresh_spawner.container_client.create_container.await_args.kwargs
        env = call_kwargs["env"]
        assert env["FOO"] == "bar"
        assert env["NUKELAB_USERNAME"] == "testuser"

    @pytest.mark.asyncio
    async def test_spawn_with_volume_mounts_no_vol_id(self, fresh_spawner):
        """spawn with volume_mounts lacking volume_id should generate default volume name."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            server = await fresh_spawner.spawn(
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
            server = await fresh_spawner.spawn(
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

        mock_warn.assert_called_once()
        assert "Could not fix permissions" in mock_warn.call_args[0][0]

    @pytest.mark.asyncio
    async def test_spawn_with_auth_volume(self, fresh_spawner):
        """spawn should mount auth volume when server_auth_enabled."""
        with mock.patch("app.container.spawner.settings.public_url", "http://test"):
            with mock.patch("app.container.spawner.settings.server_auth_enabled", True):
                with mock.patch("app.container.spawner.settings.server_auth_public_key_path", "/key.pem"):
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
        assert "nukelab-secrets" in vols
        assert vols["nukelab-secrets"]["bind"] == "/etc/nukelab/auth"
        assert vols["nukelab-secrets"]["mode"] == "ro"
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
        assert "nukelab-secrets" not in vols


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
        mock_container.delete.assert_awaited_once_with(force=True)

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
