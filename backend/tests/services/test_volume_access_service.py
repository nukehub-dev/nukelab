# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for VolumeAccessService."""

import uuid

import pytest

from app.models.shared_workspace import SharedWorkspace, WorkspaceMember
from app.models.volume import Volume
from app.models.workspace_volume import WorkspaceVolume
from app.services.volume_access_service import VolumeAccessService


@pytest.fixture
def service(db_session):
    return VolumeAccessService(db_session)


class TestCanAccessVolume:
    @pytest.mark.asyncio
    async def test_owner_has_rw_access(self, service, db_session, test_user):
        vol = Volume(name="vol1", display_name="Vol 1", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        assert await service.can_access_volume(str(vol.id), str(test_user.id), "read_write") is True
        assert await service.can_access_volume(str(vol.id), str(test_user.id), "read_only") is True

    @pytest.mark.asyncio
    async def test_non_owner_no_access(self, service, db_session, test_user, admin_user):
        vol = Volume(name="vol1", display_name="Vol 1", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        assert (
            await service.can_access_volume(str(vol.id), str(test_user.id), "read_write") is False
        )

    @pytest.mark.asyncio
    async def test_public_volume_read_only(self, service, db_session, admin_user):
        vol = Volume(
            name="pub",
            display_name="Pub",
            owner_id=admin_user.id,
            size_bytes=0,
            visibility="public",
        )
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        assert await service.can_access_volume(str(vol.id), str(uuid.uuid4()), "read_only") is True
        assert (
            await service.can_access_volume(str(vol.id), str(uuid.uuid4()), "read_write") is False
        )

    @pytest.mark.asyncio
    async def test_workspace_owner_gets_volume_role(
        self, service, db_session, test_user, admin_user
    ):
        ws = SharedWorkspace(name="ws", owner_id=test_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        vol = Volume(name="v", display_name="V", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        wv = WorkspaceVolume(workspace_id=ws.id, volume_id=vol.id, role="read_write")
        db_session.add(wv)
        await db_session.commit()

        assert await service.can_access_volume(str(vol.id), str(test_user.id), "read_write") is True

    @pytest.mark.asyncio
    async def test_workspace_member_rw(self, service, db_session, test_user, admin_user):
        ws = SharedWorkspace(name="ws", owner_id=admin_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        vol = Volume(name="v", display_name="V", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        wv = WorkspaceVolume(workspace_id=ws.id, volume_id=vol.id, role="read_write")
        db_session.add(wv)
        await db_session.commit()

        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="read_write")
        db_session.add(member)
        await db_session.commit()

        assert await service.can_access_volume(str(vol.id), str(test_user.id), "read_write") is True

    @pytest.mark.asyncio
    async def test_workspace_member_ro_when_volume_ro(
        self, service, db_session, test_user, admin_user
    ):
        ws = SharedWorkspace(name="ws", owner_id=admin_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        vol = Volume(name="v", display_name="V", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        wv = WorkspaceVolume(workspace_id=ws.id, volume_id=vol.id, role="read_only")
        db_session.add(wv)
        await db_session.commit()

        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="read_write")
        db_session.add(member)
        await db_session.commit()

        assert (
            await service.can_access_volume(str(vol.id), str(test_user.id), "read_write") is False
        )
        assert await service.can_access_volume(str(vol.id), str(test_user.id), "read_only") is True

    @pytest.mark.asyncio
    async def test_workspace_member_ro_when_member_ro(
        self, service, db_session, test_user, admin_user
    ):
        ws = SharedWorkspace(name="ws", owner_id=admin_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        vol = Volume(name="v", display_name="V", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        wv = WorkspaceVolume(workspace_id=ws.id, volume_id=vol.id, role="read_write")
        db_session.add(wv)
        await db_session.commit()

        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="read_only")
        db_session.add(member)
        await db_session.commit()

        assert (
            await service.can_access_volume(str(vol.id), str(test_user.id), "read_write") is False
        )
        assert await service.can_access_volume(str(vol.id), str(test_user.id), "read_only") is True

    @pytest.mark.asyncio
    async def test_missing_volume_returns_false(self, service):
        assert await service.can_access_volume(str(uuid.uuid4()), str(uuid.uuid4())) is False


class TestCanManageVolume:
    @pytest.mark.asyncio
    async def test_owner_can_manage(self, service, db_session, test_user):
        vol = Volume(name="v", display_name="V", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        assert await service.can_manage_volume(str(vol.id), str(test_user.id)) is True

    @pytest.mark.asyncio
    async def test_non_owner_cannot_manage(self, service, db_session, test_user, admin_user):
        vol = Volume(name="v", display_name="V", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        assert await service.can_manage_volume(str(vol.id), str(test_user.id)) is False


class TestMostRestrictive:
    def test_none_returns_other(self, service):
        assert service._most_restrictive(None, "read_write") == "read_write"
        assert service._most_restrictive("read_write", None) == "read_write"

    def test_read_only_wins(self, service):
        assert service._most_restrictive("read_write", "read_only") == "read_only"
        assert service._most_restrictive("read_only", "read_write") == "read_only"

    def test_both_rw(self, service):
        assert service._most_restrictive("read_write", "read_write") == "read_write"

    def test_both_ro(self, service):
        assert service._most_restrictive("read_only", "read_only") == "read_only"


class TestComputeEffectiveAccess:
    def test_personal_and_workspace(self, service):
        assert service._compute_effective_access("read_write", "read_only") == "read_only"
        assert service._compute_effective_access("read_write", "read_write") == "read_write"

    def test_only_personal(self, service):
        assert service._compute_effective_access("read_write", None) == "read_write"

    def test_only_workspace(self, service):
        assert service._compute_effective_access(None, "read_only") == "read_only"

    def test_no_access(self, service):
        assert service._compute_effective_access(None, None) is None


class TestGetAccessibleVolumeIds:
    @pytest.mark.asyncio
    async def test_includes_owned_volumes(self, service, db_session, test_user):
        vol = Volume(name="v", display_name="V", owner_id=test_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        ids = await service.get_accessible_volume_ids(str(test_user.id))
        assert str(vol.id) in ids

    @pytest.mark.asyncio
    async def test_includes_workspace_volumes(self, service, db_session, test_user, admin_user):
        ws = SharedWorkspace(name="ws", owner_id=admin_user.id)
        db_session.add(ws)
        await db_session.commit()
        await db_session.refresh(ws)

        vol = Volume(name="v", display_name="V", owner_id=admin_user.id, size_bytes=0)
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        wv = WorkspaceVolume(workspace_id=ws.id, volume_id=vol.id, role="read_write")
        db_session.add(wv)
        await db_session.commit()

        # Add test_user as a workspace member so the join finds it
        member = WorkspaceMember(workspace_id=ws.id, user_id=test_user.id, role="read_write")
        db_session.add(member)
        await db_session.commit()

        ids = await service.get_accessible_volume_ids(str(test_user.id))
        assert str(vol.id) in ids

    @pytest.mark.asyncio
    async def test_includes_public_for_read_only(self, service, db_session, admin_user):
        vol = Volume(
            name="pub",
            display_name="Pub",
            owner_id=admin_user.id,
            size_bytes=0,
            visibility="public",
        )
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        ids = await service.get_accessible_volume_ids(str(uuid.uuid4()), mode="read_only")
        assert str(vol.id) in ids

    @pytest.mark.asyncio
    async def test_excludes_public_for_rw(self, service, db_session, admin_user):
        vol = Volume(
            name="pub",
            display_name="Pub",
            owner_id=admin_user.id,
            size_bytes=0,
            visibility="public",
        )
        db_session.add(vol)
        await db_session.commit()
        await db_session.refresh(vol)

        ids = await service.get_accessible_volume_ids(str(uuid.uuid4()), mode="read_write")
        assert str(vol.id) not in ids
