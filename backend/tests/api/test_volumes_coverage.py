# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Additional coverage tests for app.api.volumes.

Targets branches not exercised by the existing volume test modules:
- list_volume_files: unreadable directory entries, page clamping
- delete_volume_file: non-EROFS OSError handler, volume 404
- download_volume_file: volume 404, media-type fallback
- update_volume: destructive status change with zero active mounts
- get_volume: public volume read by non-owner
"""

import errno
import uuid as uuid_mod
from unittest import mock

import pytest

from app.models.volume import Volume


@pytest.fixture(autouse=True)
def mock_docker_client():
    """Mock Docker container client to avoid real volume operations."""
    mock_vol = mock.AsyncMock()
    mock_vol.delete = mock.AsyncMock()

    mock_volumes = mock.AsyncMock()
    mock_volumes.create = mock.AsyncMock(return_value=mock_vol)
    mock_volumes.get = mock.AsyncMock(return_value=mock_vol)

    mock_client = mock.AsyncMock()
    mock_client.volumes = mock_volumes
    mock_client.close = mock.AsyncMock()

    mock_container_client = mock.AsyncMock()
    mock_container_client.client = mock_client
    mock_container_client.list_containers = mock.AsyncMock(return_value=[])
    mock_container_client.create_container = mock.AsyncMock(return_value=mock.Mock(id="mock-cid"))
    mock_container_client.start_container = mock.AsyncMock()
    mock_container_client.get_container_logs = mock.AsyncMock(return_value="mock logs")

    with mock.patch(
        "app.services.volume_service.get_container_client", return_value=mock_container_client
    ):
        yield


@pytest.fixture
def auth(user_token):
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def admin_auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


async def _make_volume(db_session, owner_id, name=None, **kwargs):
    vol = Volume(
        name=name or f"cov-vol-{uuid_mod.uuid4().hex[:8]}",
        display_name=kwargs.pop("display_name", "Coverage Volume"),
        owner_id=owner_id,
        size_bytes=0,
        status="active",
        **kwargs,
    )
    db_session.add(vol)
    await db_session.commit()
    await db_session.refresh(vol)
    return vol


class TestListVolumeFilesEdgeCases:
    """Edge branches in list_volume_files."""

    @pytest.mark.asyncio
    async def test_list_files_skips_unstatable_entries(
        self, client, auth, test_user, db_session, tmp_path
    ):
        """Entries whose stat() fails (e.g. dangling symlink) are skipped."""
        vol = await _make_volume(db_session, test_user.id)
        base = tmp_path / vol.name / "_data"
        base.mkdir(parents=True)
        (base / "good.txt").write_text("ok")
        (base / "broken-link").symlink_to(base / "does-not-exist")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(f"/api/volumes/{vol.id}/files", headers=auth)

        assert response.status_code == 200
        data = response.json()
        names = [item["name"] for item in data["items"]]
        assert "good.txt" in names
        assert "broken-link" not in names
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_files_page_clamped_to_one(
        self, client, auth, test_user, db_session, tmp_path
    ):
        """A page number below 1 is clamped to the first page."""
        vol = await _make_volume(db_session, test_user.id)
        base = tmp_path / vol.name / "_data"
        base.mkdir(parents=True)
        (base / "a.txt").write_text("x")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{vol.id}/files?page=0&page_size=10", headers=auth
            )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_files_sort_by_modified_ascending(
        self, client, auth, test_user, db_session, tmp_path
    ):
        """Sort by modified ascending returns items oldest-first."""
        import os
        import time

        vol = await _make_volume(db_session, test_user.id)
        base = tmp_path / vol.name / "_data"
        base.mkdir(parents=True)
        old = base / "old.txt"
        new = base / "new.txt"
        old.write_text("old")
        new.write_text("new")
        now = time.time()
        os.utime(old, (now - 100, now - 100))
        os.utime(new, (now, now))

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{vol.id}/files?sort_by=modified&sort_order=asc", headers=auth
            )

        assert response.status_code == 200
        names = [item["name"] for item in response.json()["items"]]
        assert names.index("old.txt") < names.index("new.txt")

    @pytest.mark.asyncio
    async def test_list_files_sort_by_size_directories_first_on_tie(
        self, client, auth, test_user, db_session, tmp_path
    ):
        """Sort by size treats directories as size 0 and breaks ties by name."""
        vol = await _make_volume(db_session, test_user.id)
        base = tmp_path / vol.name / "_data"
        base.mkdir(parents=True)
        (base / "adir").mkdir()
        (base / "big.txt").write_text("xxxxx")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{vol.id}/files?sort_by=size&sort_order=asc", headers=auth
            )

        assert response.status_code == 200
        names = [item["name"] for item in response.json()["items"]]
        assert names == ["adir", "big.txt"]


class TestDeleteVolumeFileEdgeCases:
    """Edge branches in delete_volume_file."""

    @pytest.mark.asyncio
    async def test_delete_file_volume_not_found(self, client, auth):
        """Deleting a file in a non-existent volume returns 404."""
        response = await client.delete(
            f"/api/volumes/{uuid_mod.uuid4()}/files?path=foo.txt", headers=auth
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_file_oserror_non_erofs_returns_500(
        self, client, auth, test_user, db_session, tmp_path
    ):
        """An OSError other than read-only-fs maps to a 500."""
        vol = await _make_volume(db_session, test_user.id)
        base = tmp_path / vol.name / "_data"
        base.mkdir(parents=True)
        (base / "foo.txt").write_text("hello")

        def raise_eacces(*a, **k):
            raise OSError(errno.EACCES, "Permission denied")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            with mock.patch("pathlib.Path.unlink", side_effect=raise_eacces):
                response = await client.delete(
                    f"/api/volumes/{vol.id}/files?path=foo.txt", headers=auth
                )

        assert response.status_code == 500
        assert "failed to delete" in response.json()["detail"].lower()


class TestDownloadVolumeFileEdgeCases:
    """Edge branches in download_volume_file."""

    @pytest.mark.asyncio
    async def test_download_volume_not_found(self, client, auth):
        """Downloading from a non-existent volume returns 404."""
        response = await client.get(
            f"/api/volumes/{uuid_mod.uuid4()}/download?path=foo.txt", headers=auth
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_download_unknown_extension_uses_octet_stream(
        self, client, auth, test_user, db_session, tmp_path
    ):
        """Files with no guessable media type fall back to octet-stream."""
        vol = await _make_volume(db_session, test_user.id)
        base = tmp_path / vol.name / "_data"
        base.mkdir(parents=True)
        (base / "datafile").write_text("raw bytes")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{vol.id}/download?path=datafile", headers=auth
            )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.content == b"raw bytes"

    @pytest.mark.asyncio
    async def test_download_known_extension_media_type(
        self, client, auth, test_user, db_session, tmp_path
    ):
        """Files with a known extension get the guessed media type."""
        vol = await _make_volume(db_session, test_user.id)
        base = tmp_path / vol.name / "_data"
        base.mkdir(parents=True)
        (base / "notes.txt").write_text("plain text")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{vol.id}/download?path=notes.txt", headers=auth
            )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")


class TestUpdateVolumeMountGuard:
    """Destructive status guard when no active mounts exist."""

    @pytest.mark.asyncio
    async def test_archive_volume_without_mounts_succeeds(
        self, client, auth, test_user, db_session
    ):
        """Archiving a volume with no running-server mounts is allowed."""
        vol = await _make_volume(db_session, test_user.id)

        response = await client.put(
            f"/api/volumes/{vol.id}", headers=auth, json={"status": "archived"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "archived"

    @pytest.mark.asyncio
    async def test_delete_status_volume_with_stopped_server_mount_succeeds(
        self, client, auth, test_user, db_session
    ):
        """A mount by a stopped server does not block destructive status changes."""
        from app.models.server import Server
        from app.models.server_volume import ServerVolume

        vol = await _make_volume(db_session, test_user.id)
        server = Server(name="cov-stopped-server", user_id=test_user.id, status="stopped")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        db_session.add(ServerVolume(server_id=server.id, volume_id=vol.id, mount_path="/data"))
        await db_session.commit()

        response = await client.put(
            f"/api/volumes/{vol.id}", headers=auth, json={"status": "deleting"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "deleting"


class TestGetVolumeAccess:
    """Access-check branches in get_volume."""

    @pytest.mark.asyncio
    async def test_non_owner_can_read_public_volume(
        self, client, auth, admin_user, db_session
    ):
        """A non-owner can read a public volume without admin rights."""
        vol = await _make_volume(db_session, admin_user.id, visibility="public")

        response = await client.get(f"/api/volumes/{vol.id}", headers=auth)

        assert response.status_code == 200
        assert response.json()["id"] == str(vol.id)


class TestDeleteVolumeDetails:
    """Delete-volume branches not covered elsewhere."""

    @pytest.mark.asyncio
    async def test_delete_volume_falls_back_to_name_in_notification(
        self, client, auth, test_user, db_session
    ):
        """When display_name is empty, the notification uses the volume name."""
        vol = await _make_volume(db_session, test_user.id, display_name="")

        with mock.patch("app.api.volumes.NotificationService") as mock_notif_cls:
            mock_notif = mock_notif_cls.return_value
            mock_notif.volume_deleted = mock.AsyncMock()

            response = await client.delete(f"/api/volumes/{vol.id}", headers=auth)

        assert response.status_code == 200
        mock_notif.volume_deleted.assert_awaited_once()
        kwargs = mock_notif.volume_deleted.await_args.kwargs
        assert kwargs["volume_name"] == vol.name


class TestRefreshVolumeSizeAccess:
    """Access branches in refresh_volume_size."""

    @pytest.mark.asyncio
    async def test_non_owner_can_refresh_public_volume(
        self, client, auth, admin_user, db_session
    ):
        """Public volumes grant read_only access, enough for refresh-size."""
        vol = await _make_volume(db_session, admin_user.id, visibility="public")

        with mock.patch(
            "app.api.volumes.VolumeService.update_volume_size",
            new_callable=mock.AsyncMock,
            return_value=4096,
        ):
            response = await client.post(f"/api/volumes/{vol.id}/refresh-size", headers=auth)

        assert response.status_code == 200
        assert response.json()["size_bytes"] == 4096
