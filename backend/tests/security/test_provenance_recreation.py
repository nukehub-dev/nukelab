# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Manifest content grants no image, quota, mount or cross-owner authority."""

import secrets
import uuid
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, update

from app.api.auth import get_password_hash
from app.models.api_token import ApiToken
from app.models.environment_revision import EnvironmentRevision
from app.models.server import Server
from app.models.server_launch_record import ServerLaunchRecord
from app.models.server_queue import ServerQueue
from app.models.volume import Volume
from tests.api.servers.conftest import server_api_runtime as server_api_runtime
from tests.api.servers.test_server_provenance import (
    add_portable_revision,
    manifest_recreation,
    portable_manifest,
    recorded,
    recreation,
)
from tests.api.servers.test_servers_launch_boundary import auth
from tests.api.servers.test_servers_launch_boundary import launch_api as launch_api


@pytest.fixture(autouse=True)
def provenance_runtime(monkeypatch, server_api_runtime):
    acquire = AsyncMock(return_value=server_api_runtime)
    monkeypatch.setattr("app.api.server_provenance.get_driver", acquire)
    return acquire


async def token(db, owner_id, scopes):
    value = "nukelab_" + secrets.token_urlsafe(32)
    db.add(
        ApiToken(
            user_id=owner_id,
            name="Provenance scope",
            token_hash=get_password_hash(value),
            token_prefix=value[:16],
            scopes=scopes,
            is_active=True,
        )
    )
    await db.commit()
    return auth(value)


@pytest.mark.asyncio
async def test_owner_scopes_and_cross_owner_jwt_are_both_enforced(
    client, user_token, db_session, admin_user, launch_api, provenance_runtime
):
    admin_id = admin_user.id
    sid, history = await recorded(client, user_token, launch_api)
    read = await token(db_session, launch_api.owner_id, ["servers:read"])
    manage = await token(db_session, launch_api.owner_id, ["servers:manage"])
    wrong = await token(db_session, launch_api.owner_id, ["volumes:read"])
    readable = await client.get(f"/api/servers/{sid}/provenance", headers=read)
    assert readable.status_code == 200
    assert readable.json()["can_recreate"] is False
    assert readable.json()["recreation_reason_code"] == "insufficient_scope"
    assert "no-store" in readable.headers["cache-control"]
    assert (
        await client.get(f"/api/servers/{sid}/environment-manifest", headers=wrong)
    ).status_code == 403
    assert (
        await client.get("/api/servers/provenance-capabilities", headers=wrong)
    ).status_code == 403
    body = {"source_launch_id": history["launch_id"]}
    assert (
        await client.post("/api/servers/recreate/validate", headers=read, json=body)
    ).status_code == 403
    assert (
        await client.post("/api/servers/recreate/validate", headers=manage, json=body)
    ).status_code == 403
    combined = await token(db_session, launch_api.owner_id, ["servers:read", "servers:manage"])
    preview = await client.post("/api/servers/recreate/validate", headers=combined, json=body)
    assert preview.status_code == 200
    assert "no-store" in preview.headers["cache-control"]
    other_token = await token(db_session, admin_id, ["servers:read", "servers:manage"])
    foreign = await client.get(
        f"/api/servers/{sid}/provenance",
        headers=other_token,
        params={"reason": "Cannot bypass JWT restriction"},
    )
    assert foreign.status_code == 403
    assert (
        await client.post("/api/servers/recreate/validate", headers=other_token, json=body)
    ).status_code == 404
    provenance_runtime.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,expected",
    [
        ("image", 409),
        ("names", 409),
        ("toolchain_layout", 409),
        ("privileged", 422),
        ("environment_values", 422),
        ("host_mount", 422),
        ("version", 422),
        ("oversized", 422),
        ("reserved_requirement", 422),
    ],
)
async def test_untrusted_manifest_changes_fail_without_launch_or_storage_side_effects(
    client,
    user_token,
    db_session,
    launch_api,
    provenance_runtime,
    server_api_runtime,
    change,
    expected,
):
    _, history = await recorded(client, user_token, launch_api)
    manifest = deepcopy(history["manifest"])
    if change == "image":
        manifest["runtime"]["local_id"] = "sha256:" + "f" * 64
    elif change == "names":
        manifest["environment_variable_names"] = ["UNAPPROVED"]
    elif change == "toolchain_layout":
        manifest["toolchain_mounts"] = ["/other"]
    elif change == "privileged":
        manifest["privileged"] = True
    elif change == "environment_values":
        manifest["environment_variables"] = {"TOKEN": "not-allowed"}
    elif change == "host_mount":
        manifest["volume_requirements"][0]["volume_id"] = "/var/run/docker.sock"
    elif change == "version":
        manifest["schema_version"] = "nukelab.environment/v9"
    elif change == "oversized":
        manifest["template_label"] = "a" * 65537
    else:
        manifest["volume_requirements"][0]["mount_path"] = "/proc"
    body = recreation(history, launch_api)
    del body["source_launch_id"]
    body["manifest"] = manifest
    before = [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Server, Volume, ServerQueue, ServerLaunchRecord)
    ]
    result = await client.post("/api/servers/recreate", headers=auth(user_token), json=body)
    assert result.status_code == expected, result.text
    assert [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Server, Volume, ServerQueue, ServerLaunchRecord)
    ] == before
    assert server_api_runtime.create_container.await_count == 1
    provenance_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_imported_resource_descriptions_cannot_override_current_plan(
    client, user_token, db_session, launch_api
):
    _, history = await recorded(client, user_token, launch_api)
    body = recreation(history, launch_api)
    del body["source_launch_id"]
    body["manifest"] = deepcopy(history["manifest"])
    body["manifest"]["resources"]["cpu"] = 9999.0
    response = await client.post("/api/servers/recreate", headers=auth(user_token), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["allocated_cpu"] == 1
    server = await db_session.get(Server, uuid.UUID(response.json()["id"]))
    assert server.allocated_cpu == 1


@pytest.mark.asyncio
async def test_preview_is_not_authorization_for_later_submit(
    client, user_token, db_session, launch_api, provenance_runtime
):
    _, history = await recorded(client, user_token, launch_api)
    preview = await client.post(
        "/api/servers/recreate/validate",
        headers=auth(user_token),
        json={"source_launch_id": history["launch_id"]},
    )
    assert preview.status_code == 200
    revision = await db_session.get(
        EnvironmentRevision, uuid.UUID(history["manifest"]["revision_id"])
    )
    revision.revoked = True
    await db_session.commit()
    result = await client.post(
        "/api/servers/recreate",
        headers=auth(user_token),
        json=recreation(history, launch_api),
    )
    assert result.status_code == 409 and result.json()["detail"]["code"] == "revision_unavailable"
    provenance_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_reserved_destinations_remain_readable_but_not_recreatable(
    client, user_token, db_session, launch_api, provenance_runtime
):
    sid, history = await recorded(client, user_token, launch_api)
    old = deepcopy(history["manifest"])
    old["volume_requirements"][0]["mount_path"] = "/proc"
    await db_session.execute(
        update(ServerLaunchRecord)
        .where(ServerLaunchRecord.id == uuid.UUID(history["launch_id"]))
        .values(manifest=old)
    )
    await db_session.commit()
    read = await client.get(f"/api/servers/{sid}/provenance", headers=auth(user_token))
    assert read.status_code == 200 and not read.json()["can_recreate"]
    assert read.json()["recreation_reason_code"] == "invalid_volume_requirement"
    exported = await client.get(
        f"/api/servers/{sid}/environment-manifest", headers=auth(user_token)
    )
    assert exported.status_code == 200 and exported.json() == old
    preview = await client.post(
        "/api/servers/recreate/validate",
        headers=auth(user_token),
        json={"source_launch_id": history["launch_id"]},
    )
    assert preview.status_code == 422
    provenance_runtime.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,expected,code",
    [
        ("credits", 402, "insufficient_credits"),
        ("quota", 429, "quota_exceeded"),
        ("foreign_volume", 403, "volume_unavailable"),
        ("artifact_missing", 409, "artifact_missing"),
    ],
)
async def test_recreation_uses_current_admission_policy_and_never_falls_back_to_new_tag(
    client,
    user_token,
    db_session,
    launch_api,
    server_api_runtime,
    failure,
    expected,
    code,
):
    from app.models.resource_quota import ResourceQuota
    from app.models.user import User

    _, history = await recorded(client, user_token, launch_api)
    body = recreation(history, launch_api)
    if failure == "credits":
        (await db_session.get(User, launch_api.owner_id)).nuke_balance = 0
    elif failure == "quota":
        quota = await db_session.scalar(
            select(ResourceQuota).where(ResourceQuota.user_id == launch_api.owner_id)
        )
        quota.max_cpu_total = 1
    elif failure == "foreign_volume":
        body["volume_mounts"][0]["volume_id"] = str(uuid.uuid4())
    else:
        server_api_runtime.image_exists.return_value = False
    await db_session.commit()
    before = [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Server, Volume, ServerQueue)
    ]
    response = await client.post("/api/servers/recreate", headers=auth(user_token), json=body)
    assert response.status_code == expected, response.text
    assert response.json()["detail"]["code"] == code
    assert [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Server, Volume, ServerQueue)
    ] == before
    server_api_runtime.pull_image.assert_not_awaited()
    assert server_api_runtime.create_container.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing", "path", "mode", "extra", "order"])
async def test_explicit_bindings_must_match_normalized_requirements_without_side_effects(
    client, user_token, db_session, launch_api, provenance_runtime, server_api_runtime, change
):
    body = launch_api.body()
    body["volume_mounts"][0]["max_size_bytes"] = 512 * 1024**2
    body["volume_mounts"].append(
        {
            "volume_id": "",
            "mount_path": "/data",
            "mode": "read_only",
            "max_size_bytes": 512 * 1024**2,
        }
    )
    created = await client.post("/api/servers/", headers=auth(user_token), json=body)
    assert created.status_code == 200, created.text
    sid = created.json()["id"]
    history = (await client.get(f"/api/servers/{sid}/provenance", headers=auth(user_token))).json()
    request = recreation(history, launch_api)
    request["volume_mounts"] = deepcopy(body["volume_mounts"])
    if change == "missing":
        request["volume_mounts"].pop()
    elif change == "path":
        request["volume_mounts"][1]["mount_path"] = "/other"
    elif change == "mode":
        request["volume_mounts"][1]["mode"] = "read_write"
    elif change == "extra":
        request["volume_mounts"].append(
            {"volume_id": "", "mount_path": "/extra", "mode": "read_only", "max_size_bytes": 1}
        )
    else:
        request["volume_mounts"].reverse()
    before = [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Server, Volume, ServerQueue, ServerLaunchRecord)
    ]
    result = await client.post("/api/servers/recreate", headers=auth(user_token), json=request)
    assert result.status_code == 422, result.text
    assert result.json()["detail"]["code"] == "volume_bindings_mismatch"
    assert [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Server, Volume, ServerQueue, ServerLaunchRecord)
    ] == before
    provenance_runtime.assert_not_awaited()
    assert server_api_runtime.create_container.await_count == 1


@pytest.mark.asyncio
async def test_preview_requires_read_permission_in_addition_to_write_permission(
    client, user_token, launch_api, provenance_runtime
):
    from app.core.permissions import Permission
    from app.core.roles import ROLE_PERMISSIONS, _rebuild_expansion_cache

    _, history = await recorded(client, user_token, launch_api)
    previous = list(ROLE_PERMISSIONS["user"])
    try:
        ROLE_PERMISSIONS["user"] = [Permission.SERVERS_WRITE_OWN]
        _rebuild_expansion_cache()
        result = await client.post(
            "/api/servers/recreate/validate",
            headers=auth(user_token),
            json={"source_launch_id": history["launch_id"]},
        )
        assert result.status_code == 403
    finally:
        ROLE_PERMISSIONS["user"] = previous
        _rebuild_expansion_cache()
    provenance_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_manage_scope_can_submit_without_reading_source_metadata(
    client, user_token, db_session, launch_api
):
    sid, history = await recorded(client, user_token, launch_api)
    manage = await token(db_session, launch_api.owner_id, ["servers:manage"])
    assert (await client.get(f"/api/servers/{sid}/provenance", headers=manage)).status_code == 403
    result = await client.post(
        "/api/servers/recreate", headers=manage, json=recreation(history, launch_api)
    )
    assert result.status_code == 200, result.text
    assert result.json()["user_id"] == str(launch_api.owner_id)


@pytest.mark.asyncio
async def test_portable_manifest_cannot_match_an_environment_the_actor_cannot_use(
    client, user_token, db_session, launch_api, provenance_runtime, server_api_runtime
):
    from app.models.environment_template import EnvironmentTemplate

    template = await db_session.get(EnvironmentTemplate, launch_api.environment_id)
    destination = await add_portable_revision(db_session, template, local_id="sha256:" + "f" * 64)
    template.is_public = False
    await db_session.commit()
    exported = portable_manifest(destination.portable_fingerprint, username=launch_api.username)
    body = manifest_recreation(exported, launch_api)

    preview = await client.post(
        "/api/servers/recreate/validate",
        headers=auth(user_token),
        json={"manifest": body["manifest"]},
    )
    assert preview.status_code == 409
    assert preview.json()["detail"]["code"] == "revision_unavailable"
    assert template.name not in preview.text
    assert str(template.id) not in preview.text
    result = await client.post("/api/servers/recreate", headers=auth(user_token), json=body)
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "revision_unavailable"
    provenance_runtime.assert_not_awaited()
    server_api_runtime.create_container.assert_not_awaited()
