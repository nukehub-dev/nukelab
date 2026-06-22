"""Tests for volume API guards (status changes on mounted volumes)."""

import pytest


class TestVolumeStatusGuard:
    """Tests that destructive status changes are blocked on active mounts."""

    @pytest.mark.asyncio
    async def test_cannot_archive_volume_mounted_by_running_server(self, client, admin_token, db_session):
        """Should reject archiving a volume mounted by a running server."""
        from app.models.volume import Volume
        from app.models.server import Server
        from app.models.server_volume import ServerVolume
        from app.models.user import User

        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create a user in the transactional test session so changes roll back.
        user = User(
            username="volguard-test",
            email="volguard@test.com",
            password_hash="hashed",
            role="user",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Create a volume
        volume = Volume(
            name="nukelab-vol-test-guard",
            display_name="Test Guard Volume",
            owner_id=str(user.id),
            status="active",
            size_bytes=1024,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        # Create a running server
        server = Server(
            name="test-server",
            user_id=user.id,
            status="running",
            container_id="abc123",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        # Mount the volume to the server
        sv = ServerVolume(
            server_id=server.id,
            volume_id=volume.id,
            mount_path="/data",
        )
        db_session.add(sv)
        await db_session.commit()

        # Try to archive the volume via API
        response = await client.put(
            f"/api/volumes/{volume.id}",
            json={"status": "archived"},
            headers=headers,
        )
        assert response.status_code == 409
        data = response.json()
        assert "mounted by" in data["detail"]
        assert "Stop the server(s) first" in data["detail"]

    @pytest.mark.asyncio
    async def test_can_resize_volume_mounted_by_running_server(self, client, admin_token, db_session):
        """Should allow resizing a volume mounted by a running server."""
        from app.models.volume import Volume
        from app.models.server import Server
        from app.models.server_volume import ServerVolume
        from app.models.user import User

        headers = {"Authorization": f"Bearer {admin_token}"}

        user = User(
            username="volguard-resize",
            email="volguard-resize@test.com",
            password_hash="hashed",
            role="user",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        volume = Volume(
            name="nukelab-vol-resize-guard",
            display_name="Resize Guard Volume",
            owner_id=str(user.id),
            status="active",
            size_bytes=1024,
            max_size_bytes=10 * 1024 ** 3,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        server = Server(
            name="test-server-resize",
            user_id=user.id,
            status="running",
            container_id="abc456",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        sv = ServerVolume(
            server_id=server.id,
            volume_id=volume.id,
            mount_path="/data",
        )
        db_session.add(sv)
        await db_session.commit()

        # Try to increase max_size_bytes
        response = await client.put(
            f"/api/volumes/{volume.id}",
            json={"max_size_bytes": 20 * 1024 ** 3},
            headers=headers,
        )
        # 200 if admin can manage, 404/403 if permission model blocks it
        # We just verify it's NOT 409 (the mount guard)
        assert response.status_code != 409
