# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Provenance transport preserves saved identity and uses ordinary admission."""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models.activity_log import ActivityLog
from app.models.credit_transaction import CreditTransaction
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_queue import ServerQueue
from app.models.volume import Volume
from tests.api.servers.test_servers_launch_boundary import auth
from tests.api.servers.test_servers_launch_boundary import launch_api as launch_api


@pytest.fixture(autouse=True)
def provenance_runtime(monkeypatch, server_api_runtime):
    acquire = AsyncMock(return_value=server_api_runtime)
    monkeypatch.setattr("app.api.server_provenance.get_driver", acquire)
    return acquire


async def recorded(client, user_token, launch_api):
    response = await client.post("/api/servers/", headers=auth(user_token), json=launch_api.body())
    assert response.status_code == 200, response.text
    sid = response.json()["id"]
    history = await client.get(f"/api/servers/{sid}/provenance", headers=auth(user_token))
    assert history.status_code == 200, history.text
    return sid, history.json()


def recreation(history, launch_api, *, name="recreated"):
    return {
        "source_launch_id": history["launch_id"],
        "name": name,
        "plan_id": str(launch_api.plan_id),
        "volume_mounts": launch_api.body()["volume_mounts"],
    }


@pytest.mark.asyncio
async def test_saved_history_and_export_are_redacted_and_survive_revocation(
    client, user_token, db_session, launch_api, provenance_runtime
):
    template = await db_session.get(EnvironmentTemplate, launch_api.environment_id)
    template.environment_variables = {"API_TOKEN": "private-token-not-exported"}
    await db_session.commit()
    sid, data = await recorded(client, user_token, launch_api)
    assert data["state"] == "recorded" and data["generation"] == 1 and data["captured_at"]
    assert data["actual_runtime"]["local_id"] == data["manifest"]["runtime"]["local_id"]
    assert data["manifest"]["environment_variable_names"] == ["API_TOKEN"]
    assert data["manifest"]["portability"] == "local_only"
    assert data["can_recreate"] is True
    revision = await db_session.get(EnvironmentRevision, uuid.UUID(data["manifest"]["revision_id"]))
    revision.revoked = True
    template.image = "new:tag"
    await db_session.commit()
    history = await client.get(f"/api/servers/{sid}/provenance", headers=auth(user_token))
    assert history.status_code == 200
    assert history.json()["manifest"] == data["manifest"]
    assert history.json()["can_recreate"] is False
    assert history.json()["recreation_reason_code"] == "revision_unavailable"
    exported = await client.get(
        f"/api/servers/{sid}/environment-manifest", headers=auth(user_token)
    )
    assert exported.status_code == 200 and exported.json() == data["manifest"]
    assert "attachment" in exported.headers["content-disposition"]
    assert "no-store" in exported.headers["cache-control"]
    assert "private-token-not-exported" not in exported.text + history.text
    provenance_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_server_is_unrecorded_and_has_no_fabricated_export(
    client, user_token, db_session, launch_api, provenance_runtime
):
    server = Server(name="legacy-unrecorded", user_id=launch_api.owner_id, status="stopped")
    db_session.add(server)
    await db_session.commit()
    sid = str(server.id)
    response = await client.get(f"/api/servers/{sid}/provenance", headers=auth(user_token))
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "unrecorded" and data["manifest"] is None
    assert data["launch_id"] is None and data["actual_runtime"] is None
    assert not data["can_recreate"] and data["recreation_reason_code"] == "unrecorded"
    exported = await client.get(
        f"/api/servers/{sid}/environment-manifest", headers=auth(user_token)
    )
    assert exported.status_code == 409 and exported.json()["detail"]["code"] == "unrecorded"
    provenance_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_owner_history_requires_reason_and_audits_but_source_is_not_owned(
    client, user_token, admin_token, db_session, launch_api
):
    sid, _ = await recorded(client, user_token, launch_api)
    denied = await client.get(f"/api/servers/{sid}/provenance", headers=auth(admin_token))
    assert denied.status_code == 400
    response = await client.get(
        f"/api/servers/{sid}/provenance",
        headers=auth(admin_token),
        params={"reason": "Support review"},
    )
    assert response.status_code == 200, response.text
    assert not response.json()["can_recreate"]
    assert response.json()["recreation_reason_code"] == "source_not_owned"
    row = await db_session.scalar(
        select(ActivityLog).where(ActivityLog.action == "server.provenance.read")
    )
    assert row is not None and str(row.target_id) == sid


@pytest.mark.asyncio
async def test_preview_has_no_launch_or_storage_effects_and_keeps_data_path(
    client, user_token, db_session, launch_api, provenance_runtime, server_api_runtime
):
    body = launch_api.body()
    body["volume_mounts"][0]["mount_path"] = "/data"
    created = await client.post("/api/servers/", headers=auth(user_token), json=body)
    sid = created.json()["id"]
    history = (await client.get(f"/api/servers/{sid}/provenance", headers=auth(user_token))).json()
    counts = [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Server, Volume, CreditTransaction, ServerQueue)
    ]
    calls = server_api_runtime.create_container.await_count
    response = await client.post(
        "/api/servers/recreate/validate",
        headers=auth(user_token),
        json={"source_launch_id": history["launch_id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["volume_requirements"][0]["mount_path"] == "/data"
    assert response.json()["environment_label"] == "HTTP environment"
    assert [
        await db_session.scalar(select(func.count()).select_from(model))
        for model in (Server, Volume, CreditTransaction, ServerQueue)
    ] == counts
    assert server_api_runtime.create_container.await_count == calls
    provenance_runtime.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [False, True])
async def test_recreation_keeps_captured_artifact_after_template_change_and_uses_explicit_new_volume(
    client, user_token, db_session, launch_api, server_api_runtime, monkeypatch, queued
):
    sid, history = await recorded(client, user_token, launch_api)
    old_image = server_api_runtime.create_container.call_args.kwargs["image"]
    original = await db_session.get(Server, uuid.UUID(sid))
    source_volume_id = original.volume_id
    template = await db_session.get(EnvironmentTemplate, launch_api.environment_id)
    template.image = "approved:changed"
    await db_session.commit()
    if queued:
        monkeypatch.setattr(settings, "resource_pool_cpu", 1)
    response = await client.post(
        "/api/servers/recreate",
        headers=auth(user_token),
        json=recreation(history, launch_api),
    )
    assert response.status_code == (202 if queued else 200), response.text
    if queued:
        queue = await db_session.get(ServerQueue, uuid.UUID(response.json()["queue_id"]))
        assert str(queue.revision_id) == history["manifest"]["revision_id"]
        assert queue.request_payload["volume_mounts"][0]["volume_id"] == ""
        assert server_api_runtime.create_container.await_count == 1
    else:
        current = await db_session.get(Server, uuid.UUID(response.json()["id"]))
        assert current.volume_id != source_volume_id
        assert server_api_runtime.create_container.call_args.kwargs["image"] == old_image
        assert server_api_runtime.create_container.await_count == 2
    assert await db_session.scalar(select(func.count()).select_from(CreditTransaction)) == 0


@pytest.mark.asyncio
async def test_export_can_select_the_displayed_historical_generation(
    client, user_token, db_session, launch_api
):
    sid, first = await recorded(client, user_token, launch_api)
    restarted = await client.post(f"/api/servers/{sid}/restart", headers=auth(user_token))
    assert restarted.status_code == 200, restarted.text
    latest = await client.get(f"/api/servers/{sid}/provenance", headers=auth(user_token))
    assert latest.json()["generation"] == 2
    older = await client.get(
        f"/api/servers/{sid}/provenance",
        headers=auth(user_token),
        params={"launch_id": first["launch_id"]},
    )
    assert older.json()["generation"] == 1
    exported = await client.get(
        f"/api/servers/{sid}/environment-manifest",
        headers=auth(user_token),
        params={"launch_id": first["launch_id"]},
    )
    assert exported.status_code == 200 and exported.json() == first["manifest"]
    missing = await client.get(
        f"/api/servers/{sid}/environment-manifest",
        headers=auth(user_token),
        params={"launch_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 404
