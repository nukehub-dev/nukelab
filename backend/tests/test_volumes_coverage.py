"""Coverage-focused tests for volumes.py gaps."""

import pytest
import os
import tempfile
import errno
from pathlib import Path
from unittest import mock

from app.models.volume import Volume
from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.workspace_volume import WorkspaceVolume


class TestVolumeAccessControl:
    """403 + admin override for endpoints beyond GET/PUT."""

    @pytest.mark.asyncio
    async def test_refresh_size_non_owner_forbidden(self, client, user_token, test_user, admin_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.post(
            f"/api/volumes/{vol.id}/refresh-size",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_refresh_size_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.api.volumes.VolumeService.update_volume_size", return_value=1024):
            response = await client.post(
                f"/api/volumes/{vol.id}/refresh-size",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_files_non_owner_forbidden(self, client, user_token, test_user, admin_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.get(
            f"/api/volumes/{vol.id}/files",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_files_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                os.makedirs(os.path.join(tmpdir, vol.name, "_data"))
                response = await client.get(
                    f"/api/volumes/{vol.id}/files",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_file_non_owner_forbidden(self, client, user_token, test_user, admin_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.delete(
            f"/api/volumes/{vol.id}/files?path=foo.txt",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_file_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                file_path = os.path.join(data_dir, "foo.txt")
                with open(file_path, "w") as f:
                    f.write("hello")

                response = await client.delete(
                    f"/api/volumes/{vol.id}/files?path=foo.txt",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_download_non_owner_forbidden(self, client, user_token, test_user, admin_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.get(
            f"/api/volumes/{vol.id}/download?path=foo.txt",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_download_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                file_path = os.path.join(data_dir, "foo.txt")
                with open(file_path, "w") as f:
                    f.write("hello")

                response = await client.get(
                    f"/api/volumes/{vol.id}/download?path=foo.txt",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_volume_non_owner_forbidden(self, client, user_token, test_user, admin_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.delete(
            f"/api/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_volume_admin_override(self, client, admin_token, test_user, db_session):
        vol = Volume(name="vol1", display_name="Vol1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.api.volumes.VolumeService.delete_volume", return_value=True):
            response = await client.delete(
                f"/api/volumes/{vol.id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
        assert response.status_code == 200


class TestListVolumeFilesSorting:
    """Sort branches in list_volume_files."""

    @pytest.fixture
    def _setup_volume_and_files(self, test_user, db_session):
        vol = Volume(name="vol-sort", display_name="Vol Sort", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        db_session.commit()
        return vol

    @pytest.mark.asyncio
    async def test_sort_by_modified(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-sort", display_name="Vol Sort", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                for name in ["a.txt", "b.txt"]:
                    with open(os.path.join(data_dir, name), "w") as f:
                        f.write("x")

                response = await client.get(
                    f"/api/volumes/{vol.id}/files?sort_by=modified&sort_order=desc",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
                assert response.status_code == 200
                data = response.json()
                assert data["type"] == "directory"

    @pytest.mark.asyncio
    async def test_sort_by_name_desc(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-sort", display_name="Vol Sort", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                for name in ["a.txt", "b.txt"]:
                    with open(os.path.join(data_dir, name), "w") as f:
                        f.write("x")

                response = await client.get(
                    f"/api/volumes/{vol.id}/files?sort_by=name&sort_order=desc",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
                assert response.status_code == 200
                data = response.json()
                names = [i["name"] for i in data["items"]]
                assert names == sorted(names, reverse=True)

    @pytest.mark.asyncio
    async def test_sort_by_invalid(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-sort", display_name="Vol Sort", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                with open(os.path.join(data_dir, "a.txt"), "w") as f:
                    f.write("x")

                response = await client.get(
                    f"/api/volumes/{vol.id}/files?sort_by=invalid",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
                assert response.status_code == 200


class TestListVolumeFilesPagination:
    """Pagination edge cases."""

    @pytest.mark.asyncio
    async def test_empty_directory(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-empty", display_name="Vol Empty", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                os.makedirs(os.path.join(tmpdir, vol.name, "_data"), exist_ok=True)
                response = await client.get(
                    f"/api/volumes/{vol.id}/files",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
                assert response.status_code == 200
                data = response.json()
                assert data["total"] == 0
                assert data["total_pages"] == 1

    @pytest.mark.asyncio
    async def test_page_beyond_total(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-page", display_name="Vol Page", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                with open(os.path.join(data_dir, "a.txt"), "w") as f:
                    f.write("x")

                response = await client.get(
                    f"/api/volumes/{vol.id}/files?page=100&page_size=10",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
                assert response.status_code == 200
                data = response.json()
                assert data["page"] == 1


class TestDeleteVolumeFileErrors:
    """Exception handlers in delete_volume_file."""

    @pytest.mark.asyncio
    async def test_delete_read_only_filesystem(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-ro", display_name="Vol RO", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                file_path = os.path.join(data_dir, "foo.txt")
                with open(file_path, "w") as f:
                    f.write("hello")

                def raise_readonly(*a, **k):
                    e = OSError(errno.EROFS, "Read-only file system")
                    raise e

                with mock.patch("pathlib.Path.unlink", side_effect=raise_readonly):
                    response = await client.delete(
                        f"/api/volumes/{vol.id}/files?path=foo.txt",
                        headers={"Authorization": f"Bearer {user_token}"}
                    )
                assert response.status_code == 403
                assert "read-only" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_generic_exception(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-err", display_name="Vol Err", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                file_path = os.path.join(data_dir, "foo.txt")
                with open(file_path, "w") as f:
                    f.write("hello")

                with mock.patch("pathlib.Path.unlink", side_effect=RuntimeError("boom")):
                    response = await client.delete(
                        f"/api/volumes/{vol.id}/files?path=foo.txt",
                        headers={"Authorization": f"Bearer {user_token}"}
                    )
                assert response.status_code == 500


class TestDownloadVolumeFileErrors:
    """Exception handler in download_volume_file."""

    @pytest.mark.asyncio
    async def test_download_generic_exception(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-dl", display_name="Vol DL", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", tmpdir):
                data_dir = os.path.join(tmpdir, vol.name, "_data")
                os.makedirs(data_dir, exist_ok=True)
                with open(os.path.join(data_dir, "foo.txt"), "w") as f:
                    f.write("hello")

                with mock.patch("fastapi.responses.FileResponse.__init__", side_effect=RuntimeError("boom")):
                    response = await client.get(
                        f"/api/volumes/{vol.id}/download?path=foo.txt",
                        headers={"Authorization": f"Bearer {user_token}"}
                    )
                assert response.status_code == 500


class TestListVolumeFilesGenericException:
    """Generic exception handler in list_volume_files."""

    @pytest.mark.asyncio
    async def test_list_files_generic_exception(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-list", display_name="Vol List", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch("app.api.volumes._get_volume_base_path", side_effect=RuntimeError("boom")):
            response = await client.get(
                f"/api/volumes/{vol.id}/files",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 500


class TestUpdateVolumeFields:
    """Update description, visibility, status."""

    @pytest.mark.asyncio
    async def test_update_volume_description_visibility_status(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-up", display_name="Vol Up", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()

        response = await client.put(
            f"/api/volumes/{vol.id}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "description": "New desc",
                "visibility": "public",
                "status": "active"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "New desc"
        assert data["visibility"] == "public"
        assert data["status"] == "active"


class TestListVolumesWorkspaceAssociations:
    """Workspace associations truthy path."""

    @pytest.mark.asyncio
    async def test_list_volumes_with_workspace(self, client, user_token, test_user, db_session):
        vol = Volume(name="vol-ws", display_name="Vol WS", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.flush()

        ws = SharedWorkspace(name="test-ws", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.flush()

        assoc = WorkspaceVolume(workspace_id=ws.id, volume_id=vol.id)
        db_session.add(assoc)
        await db_session.commit()

        response = await client.get(
            "/api/volumes/",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        vol_data = next(v for v in data["volumes"] if v["id"] == str(vol.id))
        assert vol_data["workspace_count"] == 1


class TestCreateVolumeNotificationFallback:
    """Notification fallback when display_name is empty."""

    @pytest.mark.asyncio
    async def test_create_volume_fallback_name(self, client, user_token):
        with mock.patch("app.api.volumes.QuotaService.check_volume_creation_allowed", return_value={"allowed": True}):
            with mock.patch("app.api.volumes.VolumeService.create_volume") as mock_create:
                vol = Volume(name="vol-fallback", display_name="", owner_id="x", size_bytes=0)
                mock_create.return_value = vol
                response = await client.post(
                    "/api/volumes/",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={"display_name": "", "max_size_bytes": 1024}
                )
                assert response.status_code == 201
