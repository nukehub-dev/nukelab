# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Home-directory sharing warnings survive lifecycle edits and server deletion."""

import pytest

from app.models.server import Server
from app.models.volume import Volume
from tests.api.servers.conftest import server_api_runtime as server_api_runtime
from tests.api.servers.test_servers_launch_boundary import auth
from tests.api.servers.test_servers_launch_boundary import launch_api as launch_api


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "stopped"])
async def test_edited_home_volume_keeps_privacy_warning_after_server_deleted(
    client, user_token, admin_token, db_session, launch_api, status
):
    created = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    assert created.status_code == 200, created.text
    server_id = created.json()["id"]
    if status == "stopped":
        assert (
            await client.post(f"/api/servers/{server_id}/stop", headers=auth(user_token))
        ).status_code == 200
    volume = Volume(
        name="selected-home",
        display_name="Selected home",
        owner_id=launch_api.owner_id,
        status="active",
        visibility="private",
        size_bytes=0,
        max_size_bytes=1024**3,
    )
    db_session.add(volume)
    await db_session.commit()
    volume_id = volume.id
    response = await client.patch(
        f"/api/servers/{server_id}",
        headers=auth(admin_token),
        json={
            "reason": "Owner requested home selection",
            "volume_mounts": [
                {
                    "volume_id": str(volume_id),
                    "mount_path": f"/home/{launch_api.username}",
                    "mode": "read_write",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert (
        await client.delete(f"/api/servers/{server_id}", headers=auth(user_token))
    ).status_code == 200
    await db_session.refresh(volume)
    assert volume.to_dict()["is_home_volume"] is True
    assert volume.labels["was_home_volume"] is True
    if status == "running":
        assert volume.last_mounted_at is not None


@pytest.mark.asyncio
async def test_legacy_resume_records_home_mount_usage(client, user_token, db_session, launch_api):
    volume = Volume(
        name="legacy-home",
        display_name="Legacy home",
        owner_id=launch_api.owner_id,
        status="active",
        visibility="private",
        size_bytes=1,
        max_size_bytes=1024**3,
    )
    db_session.add(volume)
    await db_session.flush()
    server = Server(
        name="legacy-resume",
        user_id=launch_api.owner_id,
        status="stopped",
        container_id="legacy-runtime",
        volume_id=volume.id,
        allocated_cpu=1,
        allocated_memory="1g",
        allocated_disk="2g",
    )
    db_session.add(server)
    await db_session.commit()
    server_id, volume_id = server.id, volume.id
    result = await client.post(f"/api/servers/{server_id}/start", headers=auth(user_token))
    assert result.status_code == 200, result.text
    await db_session.refresh(volume)
    assert volume.id == volume_id and volume.last_mounted_at is not None
    assert volume.labels["was_home_volume"] is True
