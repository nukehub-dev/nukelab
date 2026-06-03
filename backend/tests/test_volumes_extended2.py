"""Extended tests for volumes.py — covering gaps in error handling and file browser."""

import os
import pytest
import pytest_asyncio
import uuid as uuid_mod
from unittest import mock
from pathlib import Path

from app.models.volume import Volume
from app.models.server_volume import ServerVolume
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_volume(db_session, test_user):
    """Create a volume for testing."""
    vol = Volume(
        name=f"test-vol-{uuid_mod.uuid4().hex[:8]}",
        display_name="Test Volume",
        owner_id=test_user.id,
        size_bytes=1024,
        max_size_bytes=10737418240,
        status="active",
    )
    db_session.add(vol)
    await db_session.commit()
    await db_session.refresh(vol)
    return vol


# ─────────────────────────────────────────────────────────────
# POST / — create_volume gaps
# ─────────────────────────────────────────────────────────────

class TestCreateVolumeGaps:
    """Tests for create_volume error branches."""

    @pytest.mark.asyncio
    async def test_create_volume_quota_denied(self, client, user_token, db_session):
        """Quota check failure should return 422."""
        with mock.patch("app.api.volumes.QuotaService") as mock_quota_cls:
            mock_quota = mock_quota_cls.return_value
            mock_quota.check_volume_creation_allowed = mock.AsyncMock(
                return_value={"allowed": False, "reason": "Quota exceeded"}
            )

            response = await client.post(
                "/api/volumes/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"display_name": "Too Big", "max_size_bytes": 999999999999},
            )

        assert response.status_code == 422
        assert "quota exceeded" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_volume_notification_called(self, client, user_token, db_session):
        """Notification service should be called after successful creation."""
        from app.models.volume import Volume as VolModel

        mock_vol = VolModel(
            name="notified-vol",
            display_name="Notified Volume",
            owner_id=uuid_mod.uuid4(),
            size_bytes=0,
            max_size_bytes=10737418240,
            status="active",
        )

        with mock.patch("app.api.volumes.QuotaService") as mock_quota_cls:
            mock_quota = mock_quota_cls.return_value
            mock_quota.check_volume_creation_allowed = mock.AsyncMock(
                return_value={"allowed": True}
            )
            with mock.patch("app.api.volumes.VolumeService") as mock_svc_cls:
                mock_svc = mock_svc_cls.return_value
                mock_svc.create_volume = mock.AsyncMock(return_value=mock_vol)
                with mock.patch("app.api.volumes.NotificationService") as mock_notif_cls:
                    mock_notif = mock_notif_cls.return_value
                    mock_notif.volume_created = mock.AsyncMock()

                    response = await client.post(
                        "/api/volumes/",
                        headers={"Authorization": f"Bearer {user_token}"},
                        json={"display_name": "Notified Volume"},
                    )

        assert response.status_code == 201
        mock_notif.volume_created.assert_awaited_once()


# ─────────────────────────────────────────────────────────────
# GET /{id} — get_volume gaps
# ─────────────────────────────────────────────────────────────

class TestGetVolumeGaps:
    """Tests for get_volume error branches."""

    @pytest.mark.asyncio
    async def test_get_volume_not_found(self, client, user_token):
        """Non-existent volume should return 404."""
        response = await client.get(
            f"/api/volumes/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_volume_admin_override(self, client, admin_token, test_volume):
        """Admin should be able to access any volume."""
        response = await client.get(
            f"/api/volumes/{test_volume.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(test_volume.id)


# ─────────────────────────────────────────────────────────────
# PUT /{id} — update_volume gaps
# ─────────────────────────────────────────────────────────────

class TestUpdateVolumeGaps:
    """Tests for update_volume error branches."""

    @pytest.mark.asyncio
    async def test_update_volume_not_found(self, client, user_token):
        """Non-existent volume should return 404."""
        response = await client.put(
            f"/api/volumes/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"display_name": "New Name"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_volume_admin_override(self, client, admin_token, test_volume):
        """Admin should be able to update any volume."""
        response = await client.put(
            f"/api/volumes/{test_volume.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"display_name": "Admin Renamed"},
        )
        assert response.status_code == 200
        assert response.json()["display_name"] == "Admin Renamed"


# ─────────────────────────────────────────────────────────────
# DELETE /{id} — delete_volume gaps
# ─────────────────────────────────────────────────────────────

class TestDeleteVolumeGaps:
    """Tests for delete_volume error branches."""

    @pytest.mark.asyncio
    async def test_delete_volume_not_found(self, client, user_token):
        """Non-existent volume should return 404."""
        response = await client.delete(
            f"/api/volumes/{uuid_mod.uuid4()}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_volume_value_error(self, client, user_token, test_volume):
        """ValueError from delete_volume should return 400."""
        with mock.patch("app.api.volumes.VolumeService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_volume = mock.AsyncMock(return_value=test_volume)
            mock_svc.delete_volume = mock.AsyncMock(side_effect=ValueError("still mounted"))

            response = await client.delete(
                f"/api/volumes/{test_volume.id}",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 400
        assert "try again" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_volume_service_returns_false(self, client, user_token, test_volume):
        """delete_volume returning False should return 500."""
        with mock.patch("app.api.volumes.VolumeService") as mock_svc_cls:
            mock_svc = mock_svc_cls.return_value
            mock_svc.get_volume = mock.AsyncMock(return_value=test_volume)
            mock_svc.delete_volume = mock.AsyncMock(return_value=False)

            response = await client.delete(
                f"/api/volumes/{test_volume.id}",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 500
        assert "failed" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_volume_notification_called(self, client, user_token, test_volume):
        """Notification service should be called after successful deletion."""
        with mock.patch("app.api.volumes.NotificationService") as mock_notif_cls:
            mock_notif = mock_notif_cls.return_value
            mock_notif.volume_deleted = mock.AsyncMock()

            response = await client.delete(
                f"/api/volumes/{test_volume.id}",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        mock_notif.volume_deleted.assert_awaited_once()


# ─────────────────────────────────────────────────────────────
# File browser — success paths
# ─────────────────────────────────────────────────────────────

class TestVolumeFileBrowserSuccess:
    """Tests for file browser success paths."""

    @pytest.mark.asyncio
    async def test_list_files_directory(self, client, user_token, test_volume, tmp_path):
        """Should list files and directories."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)
        (base / "file1.txt").write_text("hello")
        (base / "subdir").mkdir()
        (base / "subdir" / "nested.txt").write_text("world")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{test_volume.id}/files",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "directory"
        names = {item["name"] for item in data["items"]}
        assert "file1.txt" in names
        assert "subdir" in names

    @pytest.mark.asyncio
    async def test_list_files_single_file(self, client, user_token, test_volume, tmp_path):
        """Should return file info when path points to a single file."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)
        (base / "single.txt").write_text("content")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{test_volume.id}/files?path=single.txt",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "file"
        assert data["name"] == "single.txt"
        assert data["size"] == len("content")

    @pytest.mark.asyncio
    async def test_list_files_search(self, client, user_token, test_volume, tmp_path):
        """Should filter items by search query."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)
        (base / "alpha.txt").write_text("a")
        (base / "beta.txt").write_text("b")
        (base / "gamma.txt").write_text("c")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{test_volume.id}/files?search=alp",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "alpha.txt"

    @pytest.mark.asyncio
    async def test_list_files_sort_by_size(self, client, user_token, test_volume, tmp_path):
        """Should sort items by size."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)
        (base / "small.txt").write_text("x")
        (base / "large.txt").write_text("xxx")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{test_volume.id}/files?sort_by=size&sort_order=desc",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        names = [item["name"] for item in data["items"]]
        assert names.index("large.txt") < names.index("small.txt")

    @pytest.mark.asyncio
    async def test_list_files_pagination(self, client, user_token, test_volume, tmp_path):
        """Should paginate results."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)
        for i in range(5):
            (base / f"file{i}.txt").write_text(str(i))

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{test_volume.id}/files?page=1&page_size=2",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["total_pages"] == 3

    @pytest.mark.asyncio
    async def test_delete_file_success(self, client, user_token, test_volume, tmp_path):
        """Should delete a file."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)
        target = base / "to_delete.txt"
        target.write_text("bye")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.delete(
                f"/api/volumes/{test_volume.id}/files?path=to_delete.txt",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_delete_directory_success(self, client, user_token, test_volume, tmp_path):
        """Should delete a directory recursively."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)
        (base / "to_delete").mkdir()
        (base / "to_delete" / "inner.txt").write_text("bye")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.delete(
                f"/api/volumes/{test_volume.id}/files?path=to_delete",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        assert not (base / "to_delete").exists()

    @pytest.mark.asyncio
    async def test_download_file_success(self, client, user_token, test_volume, tmp_path):
        """Should download a file."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)
        (base / "download.txt").write_text("file content here")

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{test_volume.id}/download?path=download.txt",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        assert response.content == b"file content here"


# ─────────────────────────────────────────────────────────────
# File browser — error paths
# ─────────────────────────────────────────────────────────────

class TestVolumeFileBrowserErrors:
    """Tests for file browser error paths."""

    @pytest.mark.asyncio
    async def test_list_files_path_not_found(self, client, user_token, test_volume, tmp_path):
        """Should return 404 when path does not exist."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{test_volume.id}/files?path=nonexistent",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 404
        assert "path not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_file_volume_root(self, client, user_token, test_volume, tmp_path):
        """Should return 403 when trying to delete volume root."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.delete(
                f"/api/volumes/{test_volume.id}/files?path=",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 403
        assert "cannot delete volume root" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_file_not_found(self, client, user_token, test_volume, tmp_path):
        """Should return 404 when file does not exist."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.delete(
                f"/api/volumes/{test_volume.id}/files?path=missing.txt",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 404
        assert "path not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_download_directory_returns_404(self, client, user_token, test_volume, tmp_path):
        """Should return 404 when trying to download a directory."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)
        (base / "subdir").mkdir()

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{test_volume.id}/download?path=subdir",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 404
        assert "file not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_download_file_not_found(self, client, user_token, test_volume, tmp_path):
        """Should return 404 when file does not exist."""
        base = tmp_path / test_volume.name / "_data"
        base.mkdir(parents=True)

        with mock.patch("app.api.volumes.VOLUME_STORAGE_PATH", str(tmp_path)):
            response = await client.get(
                f"/api/volumes/{test_volume.id}/download?path=missing.txt",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 404
        assert "file not found" in response.json()["detail"].lower()
