# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Owner recovery never grants cross-owner authority or leaks host storage paths."""

import secrets
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.api.auth import get_password_hash
from app.models.api_token import ApiToken
from app.models.volume_backup import VolumeBackup
from app.models.volume_operation import VolumeOperation
from app.models.volume_restore import VolumeRestore
from tests.services.test_volume_backup_service import recovery as recovery
from tests.services.test_volume_backup_service import source


def auth(token):
    return {"Authorization": "Bearer " + token}


async def token(db, owner_id, scopes):
    value = "nukelab_" + secrets.token_urlsafe(32)
    db.add(
        ApiToken(
            user_id=owner_id,
            name="Recovery scopes",
            token_hash=get_password_hash(value),
            token_prefix=value[:16],
            scopes=scopes,
            is_active=True,
        )
    )
    await db.commit()
    return auth(value)


@pytest.fixture(autouse=True)
def transport(monkeypatch, recovery):
    async def service(db):
        return recovery

    monkeypatch.setattr("app.api.volume_backups.recovery_service", service)
    dispatch = AsyncMock()
    monkeypatch.setattr("app.api.volume_backups._dispatch", dispatch)
    return dispatch


@pytest.mark.asyncio
async def test_backup_restore_delete_contract_and_private_cache(
    client, user_token, test_user, db_session, recovery, transport
):
    owner = test_user.id
    vid = await source(db_session, owner)
    headers = auth(user_token)
    capabilities = await client.get("/api/volume-backups/capabilities", headers=headers)
    assert capabilities.status_code == 200 and capabilities.json()["enabled"]
    eligible = await client.get(f"/api/volumes/{vid}/backup-eligibility", headers=headers)
    assert eligible.status_code == 200 and eligible.json()["eligible"]
    operation = str(uuid4())
    result = await client.post(
        f"/api/volumes/{vid}/backups",
        headers=headers,
        json={"request_id": operation, "description": "My recovery"},
    )
    assert result.status_code == 202, result.text
    assert result.json()["status"] == "pending"
    assert "no-store" in result.headers["cache-control"]
    transport.assert_awaited_once_with("backup", UUID(operation))
    completed = await recovery.execute_backup(UUID(operation))
    detail = await client.get(f"/api/volume-backups/{operation}", headers=headers)
    assert detail.status_code == 200 and detail.json()["can_restore"]
    assert "backup_path" not in detail.json() and "volume_name" not in detail.json()
    listed = await client.get("/api/volume-backups", headers=headers)
    assert listed.status_code == 200 and listed.json()["total"] == 1
    restored = await client.post(
        f"/api/volume-backups/{operation}/restore",
        headers=headers,
        json={"display_name": "New private copy", "max_size_bytes": 1024**2},
    )
    assert restored.status_code == 202, restored.text
    rid = restored.json()["id"]
    assert restored.json()["destination_volume_id"] != str(vid)
    assert (await client.get(f"/api/volume-restores/{rid}", headers=headers)).status_code == 200
    assert (await client.get("/api/volume-restores", headers=headers)).json()["total"] == 1
    assert (
        await client.delete(f"/api/volume-backups/{completed.id}", headers=headers)
    ).status_code == 409
    await recovery.execute_restore(UUID(rid))
    deleted = await client.delete(f"/api/volume-backups/{operation}", headers=headers)
    assert deleted.status_code == 202 and deleted.json()["status"] == "deleting"
    assert deleted.json()["source_display_name"] == "Private Ω"


@pytest.mark.asyncio
async def test_read_and_manage_scopes_are_separate_and_foreign_metadata_is_hidden(
    client, user_token, admin_token, test_user, db_session, recovery
):
    owner = test_user.id
    vid = await source(db_session, owner)
    pending = await recovery.reserve_backup(owner, vid)
    await recovery.execute_backup(pending.id)
    read = await token(db_session, owner, ["volumes:read"])
    manage = await token(db_session, owner, ["volumes:manage"])
    wrong = await token(db_session, owner, ["servers:read"])
    response = await client.get(f"/api/volume-backups/{pending.id}", headers=read)
    assert response.status_code == 200
    assert response.json()["can_restore"] is False and response.json()["can_delete"] is False
    assert (await client.get("/api/volume-backups", headers=manage)).status_code == 403
    assert (await client.get("/api/volume-backups/capabilities", headers=wrong)).status_code == 403
    assert (
        await client.post(f"/api/volumes/{vid}/backups", headers=read, json={})
    ).status_code == 403
    assert (
        await client.post(
            f"/api/volume-backups/{pending.id}/restore",
            headers=read,
            json={"display_name": "Denied", "max_size_bytes": 1000},
        )
    ).status_code == 403
    assert (
        await client.delete(f"/api/volume-backups/{pending.id}", headers=read)
    ).status_code == 403
    assert (
        await client.delete(f"/api/volume-backups/{pending.id}", headers=manage)
    ).status_code == 403
    assert (
        await client.get(f"/api/volume-backups/{pending.id}", headers=auth(admin_token))
    ).status_code == 404
    assert (await client.get("/api/volume-backups", headers=auth(admin_token))).json()["total"] == 0
    assert (
        await client.post(
            f"/api/volume-backups/{pending.id}/restore",
            headers=auth(admin_token),
            json={"display_name": "Denied", "max_size_bytes": 1000},
        )
    ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["public", "workspace"])
async def test_nonprivate_source_cannot_create_recovery_copy(
    client, user_token, test_user, db_session, recovery, visibility
):
    owner = test_user.id
    vid = await source(db_session, owner)
    from app.models.volume import Volume

    row = await db_session.get(Volume, vid)
    row.visibility = visibility
    await db_session.commit()
    response = await client.post(f"/api/volumes/{vid}/backups", headers=auth(user_token), json={})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "private_volume_required"
    assert await db_session.scalar(select(func.count()).select_from(VolumeBackup)) == 0
    recovery.runtime.capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_archive_paths_and_extra_privileges_are_rejected_without_side_effects(
    client, user_token, test_user, db_session, recovery
):
    vid = await source(db_session, test_user.id)
    headers = auth(user_token)
    bad = await client.post(
        f"/api/volumes/{vid}/backups", headers=headers, json={"backup_path": "/var/run/docker.sock"}
    )
    assert bad.status_code == 422
    for body in (
        {"display_name": "Copy", "max_size_bytes": True},
        {"display_name": "Copy", "max_size_bytes": -1},
        {"display_name": "Copy", "max_size_bytes": 100, "user_id": str(uuid4())},
        {"display_name": "Copy", "max_size_bytes": "100"},
    ):
        assert (
            await client.post(f"/api/volume-backups/{uuid4()}/restore", headers=headers, json=body)
        ).status_code == 422
    assert await db_session.scalar(select(func.count()).select_from(VolumeBackup)) == 0
    assert await db_session.scalar(select(func.count()).select_from(VolumeRestore)) == 0
    assert await db_session.scalar(select(func.count()).select_from(VolumeOperation)) == 0


@pytest.mark.asyncio
async def test_broker_failure_preserves_committed_pending_intent(
    client, user_token, test_user, db_session, recovery, monkeypatch
):
    from app.api.volume_backups import _dispatch

    monkeypatch.setattr("app.api.volume_backups._dispatch", _dispatch)
    monkeypatch.setattr(
        "app.tasks.enqueue_volume_recovery",
        lambda *args: (_ for _ in ()).throw(RuntimeError("broker offline")),
    )
    vid = await source(db_session, test_user.id)
    result = await client.post(f"/api/volumes/{vid}/backups", headers=auth(user_token), json={})
    assert result.status_code == 202, result.text
    pending = await db_session.get(VolumeBackup, UUID(result.json()["id"]))
    assert pending.status == "pending"
    assert (await db_session.get(VolumeOperation, (pending.id, vid))).state == "reserved"
    assert "/" not in result.json()["message"]
