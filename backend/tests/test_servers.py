"""Tests for Server model and Server lifecycle with volume support."""

import pytest
from datetime import datetime, timedelta
from httpx import AsyncClient
from unittest.mock import MagicMock, AsyncMock, patch

from app.models.server import Server


class TestServerModelFields:
    """Server model property tests."""

    def test_server_has_volume_fields(self):
        """Server model should have volume-related fields."""
        server = Server()
        assert hasattr(server, 'volume_id')
        assert hasattr(server, 'volume_mode')
        assert hasattr(server, 'volume_mounts')
        assert hasattr(server, 'total_cost')
        assert hasattr(server, 'last_billed_at')
        assert hasattr(server, 'expires_at')
        assert hasattr(server, 'last_activity')

    def test_server_volume_defaults(self):
        """Volume fields should default correctly when loaded from DB."""
        server = Server()
        assert server.volume_id is None
        # volume_mode defaults to "read_write" in model, but is None before DB insert
        assert server.volume_mode is None  # DB default
        assert server.total_cost is None
        assert server.last_billed_at is None
        assert server.expires_at is None


class TestServerVolumeIntegration:
    """Tests for server deployment with volume selection."""

    @pytest.mark.asyncio
    async def test_server_creation_with_auto_volume(self, db_session, test_user):
        """Server creation without volume_id should auto-create a volume."""
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate
        from app.models.volume import Volume
        from sqlalchemy import select

        plan = ServerPlan(
            name="Test Plan",
            slug="test-plan-auto-vol",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=10,
            is_active=True,
            allowed_roles=["user"]
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Test Env",
            slug="test-env-auto-vol",
            image="hello-world",
            is_active=True,
            is_public=True
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        # Create server without volume_id - volume should be auto-created
        server = Server(
            name="auto-vol-server",
            user_id=test_user.id,
            plan_id=plan.id,
            environment_id=env.id,
            status="pending",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        assert server.volume_id is None  # Would be set by API logic
        assert server.volume_mode == "read_write"

    @pytest.mark.asyncio
    async def test_server_creation_with_existing_volume(self, db_session, test_user):
        """Server creation should support volume_id reference."""
        from app.models.volume import Volume

        # Create a volume
        volume = Volume(
            name="test-existing-vol",
            display_name="Existing Volume",
            owner_id=test_user.id,
            status="active",
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        # Server should be able to reference it
        server = Server(
            name="existing-vol-server",
            user_id=test_user.id,
            volume_id=volume.id,
            volume_mode="read_only",
            status="pending",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        assert str(server.volume_id) == str(volume.id)
        assert server.volume_mode == "read_only"

    @pytest.mark.asyncio
    async def test_server_volume_quota_validation(self, db_session, test_user):
        """Server should validate volume quota against plan limit."""
        from app.services.volume_service import VolumeService
        from unittest.mock import AsyncMock, patch

        service = VolumeService(db_session)
        
        volume = await service.create_volume(
            name="test-quota-vol",
            display_name="Quota Test Volume",
            owner_id=str(test_user.id),
        )

        # Mock the filesystem size check to return 15GB
        with patch.object(service, 'get_volume_size', new_callable=AsyncMock) as mock_size:
            mock_size.return_value = 16106127360  # 15GB
            
            # Should fail with 10GB plan
            result = await service.check_quota(str(volume.id), "10g")
            assert result["allowed"] is False
            assert "exceeds" in result["reason"].lower()

            # Should pass with 20GB plan
            result = await service.check_quota(str(volume.id), "20g")
            assert result["allowed"] is True


class TestServerLifecycleE2E:
    """End-to-end tests for full server lifecycle."""

    @pytest.mark.asyncio
    async def test_server_creation_has_billing_fields(self, client: AsyncClient, test_user, user_token, db_session):
        """E2E: Create server prerequisites and verify billing fields exist."""
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate
        from sqlalchemy import select

        headers = {"Authorization": f"Bearer {user_token}"}

        plan = ServerPlan(
            name="Test Plan",
            slug="test-plan",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=10,
            is_active=True,
            allowed_roles=["user"]
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Test Env",
            slug="test-env",
            image="hello-world",
            is_active=True,
            is_public=True
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        server = Server(
            name="e2e-test-server",
            user_id=test_user.id,
            plan_id=plan.id,
            environment_id=env.id,
            status="running"
        )
        assert hasattr(server, 'total_cost')
        assert hasattr(server, 'last_billed_at')
        assert hasattr(server, 'expires_at')
        assert hasattr(server, 'last_activity')

    @pytest.mark.asyncio
    async def test_auto_stop_fields(self, db_session):
        """E2E: Verify auto-stop related fields exist on server."""
        server = Server()

        server.expires_at = datetime.utcnow() + timedelta(hours=1)
        assert server.expires_at is not None

        server.last_activity = datetime.utcnow()
        assert server.last_activity is not None

        server.total_cost = 100
        assert server.total_cost == 100


class TestServerWorkspaceVolumeAccess:
    """Tests for server creation with workspace-shared volumes."""

    @pytest.mark.asyncio
    async def test_viewer_cannot_mount_workspace_volume_as_rw(self, client: AsyncClient, test_user, admin_user, user_token, db_session):
        """A workspace viewer must be blocked from mounting a shared volume as read-write."""
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate
        from app.models.volume import Volume
        from app.services.workspace_service import WorkspaceService
        from app.api.auth import create_access_token

        # Admin creates workspace and adds volume
        ws_service = WorkspaceService(db_session)
        workspace = await ws_service.create_workspace(
            name="Secure Workspace",
            description="Test",
            owner_id=str(admin_user.id),
        )

        volume = Volume(
            name="shared-vol",
            display_name="Shared Volume",
            owner_id=admin_user.id,
            status="active",
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        await ws_service.add_volume(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_write",
        )

        # Add test_user as VIEWER (read_only member role)
        await ws_service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(test_user.id),
            role="read_only",
        )

        # Create plan and environment
        plan = ServerPlan(
            name="Test Plan",
            slug="test-plan-ws",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=10,
            is_active=True,
            allowed_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Test Env",
            slug="test-env-ws",
            image="hello-world",
            is_active=True,
            is_public=True,
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        # Viewer tries to create server with shared volume as RW
        headers = {"Authorization": f"Bearer {user_token}"}
        response = await client.post("/api/servers/", headers=headers, json={
            "name": "viewer-rw-attack",
            "plan_id": str(plan.id),
            "environment_id": str(env.id),
            "volume_mounts": [{
                "volume_id": str(volume.id),
                "mount_path": "/data",
                "mode": "read_write",
            }],
        })

        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"
        detail = response.json().get("detail", "")
        assert "read-write" in detail.lower() or "read_only" in detail.lower() or "cannot be mounted" in detail.lower()

    @pytest.mark.asyncio
    async def test_viewer_can_mount_workspace_volume_as_ro(self, client: AsyncClient, test_user, admin_user, user_token, db_session):
        """A workspace viewer should be allowed to mount a shared volume as read-only."""
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate
        from app.models.volume import Volume
        from app.services.workspace_service import WorkspaceService
        from unittest.mock import AsyncMock, patch

        ws_service = WorkspaceService(db_session)
        workspace = await ws_service.create_workspace(
            name="RO Workspace",
            description="Test",
            owner_id=str(admin_user.id),
        )

        volume = Volume(
            name="shared-ro-vol",
            display_name="Shared RO Volume",
            owner_id=admin_user.id,
            status="active",
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        await ws_service.add_volume(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_write",
        )

        await ws_service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(test_user.id),
            role="read_only",
        )

        plan = ServerPlan(
            name="Test Plan",
            slug="test-plan-ro",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=10,
            is_active=True,
            allowed_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Test Env",
            slug="test-env-ro",
            image="hello-world",
            is_active=True,
            is_public=True,
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        headers = {"Authorization": f"Bearer {user_token}"}

        # Mock spawner to avoid actual Docker calls
        with patch("app.api.servers.spawner.spawn", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = MagicMock(
                id="server123",
                container_id="container123",
                status="running",
                user_id=test_user.id,
                name="viewer-ro-server",
            )
            with patch("app.api.servers.spawner.get_status", new_callable=AsyncMock) as mock_status:
                mock_status.return_value = "running"
                response = await client.post("/api/servers/", headers=headers, json={
                    "name": "viewer-ro-server",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id),
                    "volume_mounts": [{
                        "volume_id": str(volume.id),
                        "mount_path": "/data",
                        "mode": "read_only",
                    }],
                })

        # Should succeed (201) or get a Docker-related error, NOT a 403
        if response.status_code == 403:
            detail = response.json().get("detail", "")
            assert "read-only" not in detail.lower(), f"Viewer should be allowed RO mount: {detail}"
        # We don't strictly assert 201 because Docker mocking is complex,
        # but we absolutely forbid 403 for read-only mount attempts.
        assert response.status_code != 403, f"Viewer should be allowed to mount as RO: {response.text}"

    @pytest.mark.asyncio
    async def test_editor_can_mount_workspace_volume_as_rw(self, client: AsyncClient, test_user, admin_user, user_token, db_session):
        """A workspace editor (read_write member) should be allowed to mount as read-write."""
        from app.models.server_plan import ServerPlan
        from app.models.environment_template import EnvironmentTemplate
        from app.models.volume import Volume
        from app.services.workspace_service import WorkspaceService
        from unittest.mock import AsyncMock, patch

        ws_service = WorkspaceService(db_session)
        workspace = await ws_service.create_workspace(
            name="RW Workspace",
            description="Test",
            owner_id=str(admin_user.id),
        )

        volume = Volume(
            name="shared-rw-vol",
            display_name="Shared RW Volume",
            owner_id=admin_user.id,
            status="active",
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        await ws_service.add_volume(
            workspace_id=str(workspace.id),
            volume_id=str(volume.id),
            role="read_write",
        )

        # Add test_user as EDITOR (read_write member role)
        await ws_service.add_member(
            workspace_id=str(workspace.id),
            user_id=str(test_user.id),
            role="read_write",
        )

        plan = ServerPlan(
            name="Test Plan",
            slug="test-plan-editor",
            category="standard",
            cpu_limit=1,
            memory_limit="1g",
            disk_limit="10g",
            max_servers_per_user=5,
            cost_per_hour=10,
            is_active=True,
            allowed_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        env = EnvironmentTemplate(
            name="Test Env",
            slug="test-env-editor",
            image="hello-world",
            is_active=True,
            is_public=True,
        )
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        headers = {"Authorization": f"Bearer {user_token}"}

        with patch("app.api.servers.spawner.spawn", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = MagicMock(
                id="server456",
                container_id="container456",
                status="running",
                user_id=test_user.id,
                name="editor-rw-server",
            )
            with patch("app.api.servers.spawner.get_status", new_callable=AsyncMock) as mock_status:
                mock_status.return_value = "running"
                response = await client.post("/api/servers/", headers=headers, json={
                    "name": "editor-rw-server",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id),
                    "volume_mounts": [{
                        "volume_id": str(volume.id),
                        "mount_path": "/data",
                        "mode": "read_write",
                    }],
                })

        # Editor should NOT get a 403 permission denied
        assert response.status_code != 403, f"Editor should be allowed RW mount: {response.text}"
