# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Provenance transport preserves saved identity and uses ordinary admission."""

import hashlib
import uuid
from types import SimpleNamespace
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
from app.schemas.environment_manifest import (
    ImageIdentity,
    ManifestResources,
    VolumeRequirement,
)
from app.services.environment_revision_service import fingerprint, template_configuration
from app.services.portable_environment import portable_environment_identity
from app.services.server_provenance_service import build_manifest
from tests.api.servers.test_servers_launch_boundary import auth
from tests.api.servers.test_servers_launch_boundary import launch_api as launch_api

PORTABLE_DIGEST = "sha256:" + "b" * 64


def verified_identity(*, local_id):
    return ImageIdentity(
        requested_reference="approved:latest",
        local_id=local_id,
        repository_digests=[f"registry.example/approved@{PORTABLE_DIGEST}"],
        os="linux",
        architecture="amd64",
        registry_verified=True,
        verified_reference=f"registry.example/approved@{PORTABLE_DIGEST}",
        manifest_digest=PORTABLE_DIGEST,
        index_digest="sha256:" + "d" * 64,
        descriptor_media_type="application/vnd.oci.image.manifest.v1+json",
    )


def portable_fingerprint(template):
    runtime = verified_identity(local_id="sha256:" + "a" * 64)
    return portable_environment_identity(
        template_configuration(template), runtime, None
    ).fingerprint


async def add_portable_revision(db_session, template, *, local_id):
    configuration = template_configuration(template)
    runtime = verified_identity(local_id=local_id)
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint=hashlib.sha256(f"{local_id}:{uuid.uuid4().hex}".encode()).hexdigest(),
        template_fingerprint=fingerprint(configuration),
        portable_fingerprint=portable_environment_identity(
            configuration, runtime, None
        ).fingerprint,
        configuration=configuration,
        runtime_identity=runtime.model_dump(mode="json"),
    )
    db_session.add(revision)
    await db_session.flush()
    return revision


def portable_manifest(fingerprint, *, username, local_id="sha256:" + "e" * 64):
    source = SimpleNamespace(
        id=uuid.uuid4(),
        fingerprint="c" * 64,
        portable_fingerprint=fingerprint,
        runtime_identity=verified_identity(local_id=local_id).model_dump(mode="json"),
        toolchain_identity=None,
        configuration={"tool_mounts": [], "environment_variables": {}},
    )
    return build_manifest(
        source,
        template_label="Origin installation environment",
        resources=ManifestResources(cpu=1.0, memory_mib=2048, disk_mib=10240),
        volumes=[
            VolumeRequirement(purpose="home", mount_path=f"/home/{username}", mode="read_write")
        ],
    )


def manifest_recreation(exported, launch_api, *, name="cross-install"):
    return {
        "manifest": exported.model_dump(mode="json"),
        "name": name,
        "plan_id": str(launch_api.plan_id),
        "volume_mounts": launch_api.body()["volume_mounts"],
    }


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


@pytest.mark.asyncio
async def test_portable_manifest_recreates_with_the_destination_revision(
    client, user_token, db_session, launch_api, server_api_runtime, monkeypatch
):
    template = await db_session.get(EnvironmentTemplate, launch_api.environment_id)
    destination = await add_portable_revision(db_session, template, local_id="sha256:" + "f" * 64)
    destination_identity = ImageIdentity.model_validate(destination.runtime_identity)
    monkeypatch.setattr(
        "app.services.server_launch_service.RegistryArtifactService.from_settings",
        lambda driver: SimpleNamespace(ensure_local=AsyncMock(return_value=destination_identity)),
    )
    exported = portable_manifest(
        destination.portable_fingerprint,
        username=launch_api.username,
        local_id="sha256:" + "e" * 64,
    )
    await db_session.commit()

    response = await client.post(
        "/api/servers/recreate",
        headers=auth(user_token),
        json=manifest_recreation(exported, launch_api),
    )
    assert response.status_code == 200, response.text
    assert response.json()["environment_id"] == str(template.id)
    assert server_api_runtime.create_container.call_args.kwargs["image"] == (
        destination_identity.local_id
    )
    assert server_api_runtime.create_container.call_args.kwargs["image"] != (
        exported.runtime.local_id
    )


@pytest.mark.asyncio
async def test_portable_manifest_preview_and_submit_recheck_current_approval(
    client, user_token, db_session, launch_api, provenance_runtime
):
    template = await db_session.get(EnvironmentTemplate, launch_api.environment_id)
    destination = await add_portable_revision(db_session, template, local_id="sha256:" + "f" * 64)
    exported = portable_manifest(destination.portable_fingerprint, username=launch_api.username)
    await db_session.commit()

    preview = await client.post(
        "/api/servers/recreate/validate",
        headers=auth(user_token),
        json={"manifest": exported.model_dump(mode="json")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["environment_label"] == template.name

    destination.revoked = True
    await db_session.commit()
    result = await client.post(
        "/api/servers/recreate",
        headers=auth(user_token),
        json=manifest_recreation(exported, launch_api),
    )
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "revision_unavailable"
    provenance_runtime.assert_not_awaited()


@pytest.mark.asyncio
async def test_portable_manifest_ambiguity_and_unavailability_are_distinct(
    client, user_token, db_session, launch_api, provenance_runtime
):
    template = await db_session.get(EnvironmentTemplate, launch_api.environment_id)
    await add_portable_revision(db_session, template, local_id="sha256:" + "f" * 64)
    second_template = EnvironmentTemplate(
        name="Second HTTP environment",
        slug="second-http-environment",
        image="approved:latest",
        is_active=True,
        is_public=True,
    )
    db_session.add(second_template)
    await db_session.flush()
    await add_portable_revision(db_session, second_template, local_id="sha256:" + "9" * 64)
    fingerprint = portable_fingerprint(template)
    await db_session.commit()

    ambiguous = await client.post(
        "/api/servers/recreate/validate",
        headers=auth(user_token),
        json={
            "manifest": portable_manifest(fingerprint, username=launch_api.username).model_dump(
                mode="json"
            )
        },
    )
    assert ambiguous.status_code == 409
    assert ambiguous.json()["detail"]["code"] == "revision_ambiguous"

    unavailable = await client.post(
        "/api/servers/recreate/validate",
        headers=auth(user_token),
        json={
            "manifest": portable_manifest("0" * 64, username=launch_api.username).model_dump(
                mode="json"
            )
        },
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "revision_unavailable"
    provenance_runtime.assert_not_awaited()
