# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for VolumeService."""

import uuid
from unittest import mock

import pytest
from sqlalchemy import select

from app.models.server import Server
from app.models.server_volume import ServerVolume
from app.models.shared_workspace import SharedWorkspace
from app.models.user import User
from app.models.volume import Volume
from app.models.workspace_volume import WorkspaceVolume
from app.services.volume_service import VolumeService


@pytest.fixture
def vol_service(db_session):
    return VolumeService(db_session)


class TestVolumeServiceHelpers:
    """Tests for pure helper methods."""

    def test_parse_memory_bytes(self, vol_service):
        assert vol_service._parse_memory("100") == 100
        assert vol_service._parse_memory("100b") == 100

    def test_parse_memory_kb(self, vol_service):
        assert vol_service._parse_memory("10k") == 10 * 1024

    def test_parse_memory_mb(self, vol_service):
        assert vol_service._parse_memory("5m") == 5 * 1024**2

    def test_parse_memory_gb(self, vol_service):
        assert vol_service._parse_memory("2g") == 2 * 1024**3

    def test_parse_memory_tb(self, vol_service):
        assert vol_service._parse_memory("1t") == 1 * 1024**4

    def test_human_size_bytes(self, vol_service):
        assert vol_service._human_size(500) == "500.0 B"

    def test_human_size_kb(self, vol_service):
        assert vol_service._human_size(1536) == "1.5 KB"

    def test_human_size_mb(self, vol_service):
        result = vol_service._human_size(2 * 1024**2)
        assert "MB" in result

    def test_get_volume_storage_paths(self, vol_service):
        paths = vol_service._get_volume_storage_paths("test-vol")
        assert isinstance(paths, list)
        assert len(paths) > 0
        assert any("test-vol" in p for p in paths)


class TestVolumeServiceCreate:
    """Tests for create_volume."""

    @pytest.mark.asyncio
    async def test_create_volume(self, db_session, vol_service, test_user):
        with mock.patch("app.services.volume_service.get_container_client") as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_vol = mock.AsyncMock()
            mock_client.client.volumes.create = mock.AsyncMock(return_value=mock_vol)
            mock_get_client.return_value = mock_client

            volume = await vol_service.create_volume(
                name="test-vol-1",
                display_name="Test Volume 1",
                owner_id=str(test_user.id),
                max_size_bytes=1024**3,
                description="A test volume",
                visibility="private",
            )

        assert volume.name == "test-vol-1"
        assert volume.display_name == "Test Volume 1"
        assert str(volume.owner_id) == str(test_user.id)
        assert volume.status == "active"
        assert volume.visibility == "private"

    @pytest.mark.asyncio
    async def test_create_volume_public(self, db_session, vol_service, test_user):
        with mock.patch("app.services.volume_service.get_container_client") as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_client.client.volumes.create = mock.AsyncMock()
            mock_get_client.return_value = mock_client

            volume = await vol_service.create_volume(
                name="public-vol",
                display_name="Public Volume",
                owner_id=str(test_user.id),
                visibility="public",
            )

        assert volume.visibility == "public"


class TestVolumeServiceGet:
    """Tests for get_volume and get_volume_by_name."""

    @pytest.mark.asyncio
    async def test_get_volume_found(self, db_session, vol_service, test_user):
        vol = Volume(name="gv1", display_name="Get Vol 1", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        result = await vol_service.get_volume(str(vol.id))
        assert result is not None
        assert result.name == "gv1"

    @pytest.mark.asyncio
    async def test_get_volume_not_found(self, vol_service):
        result = await vol_service.get_volume(str(uuid.uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_volume_by_name(self, db_session, vol_service, test_user):
        vol = Volume(name="by-name-vol", display_name="By Name", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()

        result = await vol_service.get_volume_by_name("by-name-vol")
        assert result is not None
        assert result.display_name == "By Name"

    @pytest.mark.asyncio
    async def test_get_volume_by_name_not_found(self, vol_service):
        result = await vol_service.get_volume_by_name("nonexistent")
        assert result is None


class TestVolumeServiceList:
    """Tests for list_volumes and list_all_volumes."""

    @pytest.mark.asyncio
    async def test_list_volumes_owned(self, db_session, vol_service, test_user):
        vol = Volume(
            name="owned", display_name="Owned", owner_id=test_user.id, visibility="private"
        )
        db_session.add(vol)
        await db_session.commit()

        result = await vol_service.list_volumes(str(test_user.id))
        assert len(result) == 1
        assert result[0].name == "owned"

    @pytest.mark.asyncio
    async def test_list_volumes_public(self, db_session, vol_service, test_user):
        other = User(username="pubowner", email="po@test.com", role="user")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)

        vol = Volume(name="pub", display_name="Public", owner_id=other.id, visibility="public")
        db_session.add(vol)
        await db_session.commit()

        result = await vol_service.list_volumes(str(test_user.id))
        assert len(result) == 1
        assert result[0].name == "pub"

    @pytest.mark.asyncio
    async def test_list_volumes_workspace(self, db_session, vol_service, test_user):
        ws = SharedWorkspace(name="ws-vol", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        vol = Volume(name="ws-v", display_name="WS Volume", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        wv = WorkspaceVolume(workspace_id=ws.id, volume_id=vol.id)
        db_session.add(wv)
        await db_session.commit()

        result = await vol_service.list_volumes(str(test_user.id))
        names = {v.name for v in result}
        assert "ws-v" in names

    @pytest.mark.asyncio
    async def test_list_all_volumes_basic(self, db_session, vol_service, test_user):
        vol = Volume(name="admin-vol", display_name="Admin Vol", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()

        result = await vol_service.list_all_volumes()
        assert result["total"] == 1
        assert len(result["volumes"]) == 1
        assert result["page"] == 1

    @pytest.mark.asyncio
    async def test_list_all_volumes_pagination(self, db_session, vol_service, test_user):
        for i in range(5):
            db_session.add(Volume(name=f"p{i}", display_name=f"Page {i}", owner_id=test_user.id))
        await db_session.commit()

        result = await vol_service.list_all_volumes(page=1, limit=3)
        assert result["total"] == 5
        assert len(result["volumes"]) == 3

    @pytest.mark.asyncio
    async def test_list_all_volumes_search(self, db_session, vol_service, test_user):
        db_session.add(Volume(name="find-me", display_name="Find Me", owner_id=test_user.id))
        db_session.add(Volume(name="other", display_name="Other", owner_id=test_user.id))
        await db_session.commit()

        result = await vol_service.list_all_volumes(search="find")
        assert result["total"] == 1
        assert result["volumes"][0]["name"] == "find-me"

    @pytest.mark.asyncio
    async def test_list_all_volumes_status_filter(self, db_session, vol_service, test_user):
        db_session.add(
            Volume(name="active-v", display_name="Active", owner_id=test_user.id, status="active")
        )
        db_session.add(
            Volume(
                name="archived-v", display_name="Archived", owner_id=test_user.id, status="archived"
            )
        )
        await db_session.commit()

        result = await vol_service.list_all_volumes(status="active")
        assert result["total"] == 1
        assert result["volumes"][0]["name"] == "active-v"

    @pytest.mark.asyncio
    async def test_list_all_volumes_visibility_filter(self, db_session, vol_service, test_user):
        db_session.add(
            Volume(name="priv", display_name="Private", owner_id=test_user.id, visibility="private")
        )
        db_session.add(
            Volume(name="pub2", display_name="Public", owner_id=test_user.id, visibility="public")
        )
        await db_session.commit()

        result = await vol_service.list_all_volumes(visibility="public")
        assert result["total"] == 1
        assert result["volumes"][0]["name"] == "pub2"

    @pytest.mark.asyncio
    async def test_list_all_volumes_owner_filter(self, db_session, vol_service, test_user):
        from app.models.user import User

        other = User(username="other2", email="o2@test.com", role="user")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)

        db_session.add(Volume(name="mine", display_name="Mine", owner_id=test_user.id))
        db_session.add(Volume(name="theirs", display_name="Theirs", owner_id=other.id))
        await db_session.commit()

        result = await vol_service.list_all_volumes(owner_id=str(test_user.id))
        assert result["total"] == 1
        assert result["volumes"][0]["name"] == "mine"

    @pytest.mark.asyncio
    async def test_list_all_volumes_sort_by_name(self, db_session, vol_service, test_user):
        db_session.add(Volume(name="z", display_name="Z", owner_id=test_user.id))
        db_session.add(Volume(name="a", display_name="A", owner_id=test_user.id))
        await db_session.commit()

        result = await vol_service.list_all_volumes(sort_by="name", sort_order="asc")
        assert result["volumes"][0]["name"] == "a"


class TestVolumeServiceUpdate:
    """Tests for update_volume and validate_max_size."""

    @pytest.mark.asyncio
    async def test_update_volume(self, db_session, vol_service, test_user):
        vol = Volume(name="uv1", display_name="UV1", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        result = await vol_service.update_volume(
            str(vol.id),
            display_name="Updated",
            description="New desc",
            visibility="public",
            max_size_bytes=2048,
            status="archived",
        )
        assert result.display_name == "Updated"
        assert result.description == "New desc"
        assert result.visibility == "public"
        assert result.max_size_bytes == 2048
        assert result.status == "archived"

    @pytest.mark.asyncio
    async def test_update_volume_not_found(self, vol_service):
        result = await vol_service.update_volume(str(uuid.uuid4()), display_name="X")
        assert result is None

    def test_validate_max_size_ok(self, vol_service):
        vol = Volume(name="v1", display_name="V1")
        vol.size_bytes = 100
        vol_service.validate_max_size(vol, 200)

    def test_validate_max_size_rejects_shrink(self, vol_service):
        vol = Volume(name="v1", display_name="V1")
        vol.size_bytes = 200
        with pytest.raises(ValueError, match="Cannot set volume limit"):
            vol_service.validate_max_size(vol, 100)

    def test_validate_max_size_none(self, vol_service):
        vol = Volume(name="v1", display_name="V1")
        vol.size_bytes = 100
        vol_service.validate_max_size(vol, None)


class TestVolumeServiceDelete:
    """Tests for delete_volume."""

    @pytest.mark.asyncio
    async def test_delete_volume(self, db_session, vol_service, test_user):
        vol = Volume(name="del-vol", display_name="Delete Me", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch("app.services.volume_service.get_container_client") as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_docker_vol = mock.AsyncMock()
            mock_client.client.volumes.get = mock.AsyncMock(return_value=mock_docker_vol)
            mock_get_client.return_value = mock_client

            result = await vol_service.delete_volume(str(vol.id))

        assert result is True
        # Verify DB record deleted
        db_result = await db_session.execute(select(Volume).where(Volume.id == vol.id))
        assert db_result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_volume_not_found(self, vol_service):
        result = await vol_service.delete_volume(str(uuid.uuid4()))
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_volume_mounted_raises(self, db_session, vol_service, test_user):
        vol = Volume(name="mounted-vol", display_name="Mounted", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        server = Server(name="srv-mount", user_id=test_user.id, status="running")
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        sv = ServerVolume(server_id=server.id, volume_id=vol.id)
        db_session.add(sv)
        await db_session.commit()

        with pytest.raises(ValueError, match="still mounted"):
            await vol_service.delete_volume(str(vol.id))


class TestVolumeServiceQuota:
    """Tests for check_volumes_quota batch quota check."""

    @pytest.mark.asyncio
    async def test_check_quota_allowed(self, db_session, vol_service, test_user):
        vol = Volume(name="q-ok", display_name="Quota OK", owner_id=test_user.id, size_bytes=100)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch.object(vol_service, "get_volume_size", return_value=None):
            result = await vol_service.check_volumes_quota([str(vol.id)], "10g")

        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_check_quota_exceeded(self, db_session, vol_service, test_user):
        vol = Volume(name="q-bad", display_name="Quota Bad", owner_id=test_user.id, size_bytes=200)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        with mock.patch.object(vol_service, "get_volume_size", return_value=None):
            result = await vol_service.check_volumes_quota([str(vol.id)], "1b")

        assert result["allowed"] is False
        assert "exceeds" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_quota_volume_not_found(self, vol_service):
        result = await vol_service.check_volumes_quota([str(uuid.uuid4())], "10g")
        assert result["allowed"] is False
        assert "not found" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_aggregate_allowed(self, db_session, vol_service, test_user):
        vol1 = Volume(name="agg1", display_name="Agg1", owner_id=test_user.id, size_bytes=100)
        vol2 = Volume(name="agg2", display_name="Agg2", owner_id=test_user.id, size_bytes=100)
        db_session.add_all([vol1, vol2])
        await db_session.commit()
        await db_session.refresh(vol1)
        await db_session.refresh(vol2)

        with mock.patch.object(vol_service, "get_volume_size", return_value=None):
            result = await vol_service.check_volumes_quota([str(vol1.id), str(vol2.id)], "10g")

        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_check_aggregate_exceeded(self, db_session, vol_service, test_user):
        vol1 = Volume(name="agg3", display_name="Agg3", owner_id=test_user.id, size_bytes=200)
        vol2 = Volume(name="agg4", display_name="Agg4", owner_id=test_user.id, size_bytes=200)
        db_session.add_all([vol1, vol2])
        await db_session.commit()
        await db_session.refresh(vol1)
        await db_session.refresh(vol2)

        with mock.patch.object(vol_service, "get_volume_size", return_value=None):
            result = await vol_service.check_volumes_quota([str(vol1.id), str(vol2.id)], "1b")

        assert result["allowed"] is False
        assert "exceeds" in result["reason"]

    @pytest.mark.asyncio
    async def test_check_aggregate_missing_volume(self, db_session, vol_service, test_user):
        vol = Volume(name="agg5", display_name="Agg5", owner_id=test_user.id, size_bytes=100)
        db_session.add(vol)
        await db_session.commit()

        with mock.patch.object(vol_service, "get_volume_size", return_value=None):
            result = await vol_service.check_volumes_quota([str(vol.id), str(uuid.uuid4())], "10g")

        assert result["allowed"] is False
        assert "not found" in result["reason"]


class TestVolumeServiceRecordMount:
    """Tests for record_mount and mark_home_volume."""

    @pytest.mark.asyncio
    async def test_record_mount(self, db_session, vol_service, test_user):
        vol = Volume(name="rm-vol", display_name="RM", owner_id=test_user.id)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        await vol_service.record_mount(str(vol.id))
        assert vol.last_mounted_at is not None

    @pytest.mark.asyncio
    async def test_mark_home_volume(self, db_session, vol_service, test_user):
        vol = Volume(name="hm-vol", display_name="HM", owner_id=test_user.id, labels={})
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        await vol_service.mark_home_volume(str(vol.id))
        assert vol.labels.get("was_home_volume") is True

    @pytest.mark.asyncio
    async def test_mark_home_volume_idempotent(self, db_session, vol_service, test_user):
        vol = Volume(
            name="hm2-vol",
            display_name="HM2",
            owner_id=test_user.id,
            labels={"was_home_volume": True},
        )
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        await vol_service.mark_home_volume(str(vol.id))
        assert vol.labels.get("was_home_volume") is True
