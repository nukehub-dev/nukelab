# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admin environment revision list, verify, and revoke behavior."""

import hashlib
import uuid
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.api import environment_revisions
from app.models.activity_log import ActivityLog
from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.schemas.environment_manifest import ImageIdentity
from app.services.environment_revision_service import fingerprint, template_configuration
from app.services.registry_client import RegistryError, VerifiedImage
from app.services.registry_image_service import RegistryResolution

pytestmark = pytest.mark.asyncio


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def unique_fingerprint():
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


async def create_template(db, **overrides):
    name = "environment-" + uuid.uuid4().hex
    values = {
        "name": name,
        "slug": name,
        "image": "registry.example/workspace:latest",
        "is_active": True,
        "environment_variables": {"API_TOKEN": "private-value"},
        "packages": ["numpy==2.1.0"],
        "ports": [8080],
    }
    values.update(overrides)
    template = EnvironmentTemplate(**values)
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def add_revision(
    db,
    template,
    *,
    revision_fingerprint=None,
    template_fingerprint=None,
    portable_fingerprint=None,
    configuration=None,
    runtime_identity=None,
    toolchain_identity=None,
    revoked=False,
    created_at=None,
):
    revision = EnvironmentRevision(
        template_id=template.id,
        fingerprint=revision_fingerprint or unique_fingerprint(),
        template_fingerprint=template_fingerprint or unique_fingerprint(),
        portable_fingerprint=portable_fingerprint,
        configuration=configuration if configuration is not None else {},
        runtime_identity=(
            runtime_identity
            if runtime_identity is not None
            else {
                "requested_reference": template.image,
                "local_id": "sha256:" + "a" * 64,
                "os": "linux",
                "architecture": "amd64",
            }
        ),
        toolchain_identity=toolchain_identity,
        revoked=revoked,
        created_at=created_at,
    )
    db.add(revision)
    await db.commit()
    await db.refresh(revision)
    return revision


def verified_artifact(
    reference,
    *,
    repository,
    manifest_char="b",
    index_char="c",
    local_char="a",
    os_name="linux",
    architecture="amd64",
    variant=None,
):
    digest = "sha256:" + manifest_char * 64
    verified_reference = f"{repository}@{digest}"
    verified = VerifiedImage(
        requested_reference=reference,
        verified_reference=verified_reference,
        manifest_digest=digest,
        index_digest="sha256:" + index_char * 64,
        descriptor_media_type="application/vnd.oci.image.manifest.v1+json",
        os=os_name,
        architecture=architecture,
        variant=variant,
    )
    identity = ImageIdentity(
        requested_reference=reference,
        local_id="sha256:" + local_char * 64,
        repository_digests=[verified_reference],
        os=os_name,
        architecture=architecture,
        registry_verified=True,
        verified_reference=verified_reference,
        manifest_digest=digest,
        index_digest=verified.index_digest,
        descriptor_media_type=verified.descriptor_media_type,
        variant=variant,
    )
    return verified, identity


class FakeRegistry:
    def __init__(self, resolutions):
        self.resolutions = resolutions
        self.calls = []

    async def resolve(self, reference, *, policy=None, pull=False):
        self.calls.append((reference, policy, pull))
        value = self.resolutions[reference]
        if isinstance(value, Exception):
            raise value
        return RegistryResolution(
            policy="require",
            state="verified",
            verified=value,
            fallback_reason=None,
            pull_requested=False,
        )


class FakeArtifacts:
    def __init__(self, identities):
        self.identities = identities
        self.calls = []

    async def ensure_local(self, verified):
        self.calls.append(verified)
        value = self.identities[verified.requested_reference]
        if isinstance(value, Exception):
            raise value
        return value


def patch_registry(monkeypatch, registry, artifacts):
    async def _registry():
        return registry

    async def _artifacts():
        return artifacts

    monkeypatch.setattr(environment_revisions, "_registry_service", _registry)
    monkeypatch.setattr(environment_revisions, "_artifact_service", _artifacts)


async def revision_count(db, template_id):
    return (
        await db.scalar(
            select(func.count())
            .select_from(EnvironmentRevision)
            .where(EnvironmentRevision.template_id == template_id)
        )
        or 0
    )


async def audit_rows(db, action):
    return (
        (
            await db.execute(
                select(ActivityLog)
                .where(ActivityLog.action == action)
                .order_by(ActivityLog.created_at, ActivityLog.id)
            )
        )
        .scalars()
        .all()
    )


async def test_list_returns_sanitized_metadata_newest_first_including_revoked(
    client, admin_token, db_session
):
    template = await create_template(
        db_session,
        image="registry.internal/private/workspace:latest",
        tool_image="registry.internal/private/tools:latest",
        packages=["numpy==2.1.0", "scipy"],
        ports=[8080, "9090"],
        tool_mounts=["/opt/nuke"],
        environment_variables={"API_TOKEN": "private-value", "MODE": "production"},
        volumes=[{"mount_path": "/data", "mode": "read_write"}],
    )
    unverified = ImageIdentity(
        requested_reference=template.image,
        local_id="sha256:" + "d" * 64,
        repository_digests=["registry.unverified.internal/private@" + "sha256:" + "e" * 64],
        os="linux",
        architecture="amd64",
    )
    verified, verified_identity = verified_artifact(
        template.image,
        repository="registry.verified.example/workspace",
        manifest_char="f",
        index_char="1",
        local_char="2",
    )
    older = await add_revision(
        db_session,
        template,
        configuration=template_configuration(template),
        runtime_identity=unverified.model_dump(mode="json"),
        created_at=datetime(2026, 1, 1, 12),
    )
    newer = await add_revision(
        db_session,
        template,
        configuration=template_configuration(template),
        runtime_identity=verified_identity.model_dump(mode="json"),
        portable_fingerprint="9" * 64,
        revoked=True,
        created_at=datetime(2026, 1, 2, 12),
    )

    response = await client.get(
        f"/api/environments/{template.id}/revisions", headers=auth(admin_token)
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"] == {"limit": 50, "offset": 0, "total": 2, "has_more": False}
    assert [item["id"] for item in payload["items"]] == [str(newer.id), str(older.id)]

    verified_item = payload["items"][0]
    assert verified_item["portability"] == "registry_verified"
    assert verified_item["portable_fingerprint"] == "9" * 64
    assert verified_item["revoked"] is True
    assert verified_item["runtime"]["manifest_digest"] == verified.manifest_digest
    assert verified_item["runtime"]["index_digest"] == verified.index_digest
    assert verified_item["runtime"]["verified_reference"] == verified.verified_reference
    assert verified_item["runtime"]["os"] == "linux"
    assert verified_item["runtime"]["architecture"] == "amd64"

    local_item = payload["items"][1]
    assert local_item["portability"] == "local_only"
    assert local_item["portable_fingerprint"] is None
    assert local_item["revoked"] is False
    assert local_item["runtime"]["registry_verified"] is False
    assert local_item["runtime"]["verified_reference"] is None
    assert local_item["runtime"]["manifest_digest"] is None
    assert local_item["configuration"]["packages"] == ["numpy==2.1.0", "scipy"]
    assert local_item["configuration"]["ports"] == ["8080", "9090"]
    assert local_item["configuration"]["tool_mounts"] == ["/opt/nuke"]
    assert local_item["configuration"]["environment_variable_names"] == ["API_TOKEN", "MODE"]
    assert local_item["configuration"]["volumes"] == [{"mount_path": "/data", "mode": "read_write"}]
    assert "local_only_artifact" in local_item["limitations"]

    raw = response.text
    assert "private-value" not in raw
    assert "production" not in raw
    assert "sha256:" + "d" * 64 not in raw
    assert "registry.unverified.internal/private" not in raw


async def test_list_reports_bounded_limitations_for_unreducible_configuration(
    client, admin_token, db_session
):
    template = await create_template(
        db_session,
        environment_variables={"GOOD": "secret"},
        packages=["numpy==2.1.0"],
        ports=[8080],
        volumes=["/host/path:/data"],
    )
    revision = await add_revision(
        db_session,
        template,
        configuration=template_configuration(template),
    )

    response = await client.get(
        f"/api/environments/{template.id}/revisions", headers=auth(admin_token)
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == str(revision.id)
    assert item["configuration"]["volumes"] == []
    assert "volume_configuration_local_only" in item["limitations"]
    assert "/host/path" not in response.text
    assert "secret" not in response.text


async def test_list_pagination_is_bounded_and_deterministic(client, admin_token, db_session):
    template = await create_template(db_session)
    revisions = [
        await add_revision(
            db_session,
            template,
            created_at=datetime(2026, 1, day, 12),
        )
        for day in (1, 2, 3)
    ]

    response = await client.get(
        f"/api/environments/{template.id}/revisions?limit=1&offset=1",
        headers=auth(admin_token),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"] == {"limit": 1, "offset": 1, "total": 3, "has_more": True}
    assert payload["items"][0]["id"] == str(revisions[1].id)

    assert (
        await client.get(
            f"/api/environments/{template.id}/revisions?limit=101", headers=auth(admin_token)
        )
    ).status_code == 422
    assert (
        await client.get(
            f"/api/environments/{template.id}/revisions?offset=-1", headers=auth(admin_token)
        )
    ).status_code == 422


async def test_list_missing_environment_is_404_and_other_template_rows_are_omitted(
    client, admin_token, db_session
):
    missing = await client.get(
        f"/api/environments/{uuid.uuid4()}/revisions", headers=auth(admin_token)
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "environment_not_found"}

    first = await create_template(db_session, name="first", slug="first-revisions")
    second = await create_template(db_session, name="second", slug="second-revisions")
    first_revision = await add_revision(db_session, first)
    await add_revision(db_session, second)

    response = await client.get(
        f"/api/environments/{first.id}/revisions", headers=auth(admin_token)
    )
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [str(first_revision.id)]
    assert {item["template_id"] for item in payload["items"]} == {str(first.id)}
    assert "second-revisions" not in response.text


async def test_verify_rejects_inactive_template_before_registry_io(
    client, admin_token, db_session, monkeypatch
):
    template = await create_template(db_session, is_active=False)
    verified, identity = verified_artifact(template.image, repository="registry.example/workspace")
    registry = FakeRegistry({template.image: verified})
    artifacts = FakeArtifacts({template.image: identity})
    artifact_factory_calls = 0

    async def _registry():
        return registry

    async def _artifacts():
        nonlocal artifact_factory_calls
        artifact_factory_calls += 1
        return artifacts

    monkeypatch.setattr(environment_revisions, "_registry_service", _registry)
    monkeypatch.setattr(environment_revisions, "_artifact_service", _artifacts)

    response = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=auth(admin_token),
        json={"reason": "verify inactive template"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "template_inactive"}
    assert registry.calls == []
    assert artifacts.calls == []
    assert artifact_factory_calls == 0
    assert await revision_count(db_session, template.id) == 0


async def test_verify_captures_registry_verified_revision_with_portable_fingerprint(
    client, admin_token, admin_user, db_session, monkeypatch
):
    template = await create_template(
        db_session,
        image="registry.example/workspace:latest",
        tool_image="registry.example/tools:latest",
        packages=["numpy==2.1.0", "scipy"],
        ports=[8080],
        environment_variables={"SECRET": "do-not-leak"},
        volumes=[{"mount_path": "/data", "mode": "read_write"}],
    )
    runtime_verified, runtime_identity = verified_artifact(
        template.image,
        repository="registry.example/workspace",
        manifest_char="b",
        index_char="c",
        local_char="d",
        variant="v2",
    )
    tool_verified, tool_identity = verified_artifact(
        template.tool_image,
        repository="registry.example/tools",
        manifest_char="e",
        index_char="f",
        local_char="1",
    )
    registry = FakeRegistry(
        {
            template.image: runtime_verified,
            template.tool_image: tool_verified,
        }
    )
    artifacts = FakeArtifacts(
        {
            template.image: runtime_identity,
            template.tool_image: tool_identity,
        }
    )
    patch_registry(monkeypatch, registry, artifacts)

    response = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=auth(admin_token),
        json={"reason": "verify current approved artifacts"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["portability"] == "registry_verified"
    assert len(data["portable_fingerprint"]) == 64
    assert data["runtime"]["manifest_digest"] == runtime_verified.manifest_digest
    assert data["runtime"]["variant"] == "v2"
    assert data["toolchain"]["manifest_digest"] == tool_verified.manifest_digest
    assert data["configuration"]["environment_variable_names"] == ["SECRET"]
    assert data["configuration"]["tool_mounts"] == ["/opt/nuke"]
    assert "do-not-leak" not in response.text
    assert runtime_identity.local_id not in response.text

    assert registry.calls == [
        (template.image, "require", False),
        (template.tool_image, "require", False),
    ]
    assert [call.requested_reference for call in artifacts.calls] == [
        template.image,
        template.tool_image,
    ]

    stored = (
        await db_session.execute(
            select(EnvironmentRevision).where(EnvironmentRevision.template_id == template.id)
        )
    ).scalar_one()
    assert stored.revoked is False
    assert stored.runtime_identity["registry_verified"] is True
    assert stored.portable_fingerprint is not None
    assert stored.configuration["environment_variables"] == {"SECRET": "do-not-leak"}

    logs = await audit_rows(db_session, "environment.revision.verify")
    assert len(logs) == 1
    assert logs[0].actor_id == admin_user.id
    details = logs[0].details
    assert details["reason"] == "verify current approved artifacts"
    assert details["template_id"] == str(template.id)
    assert details["revision_id"] == data["id"]
    assert details["portability"] == "registry_verified"
    assert details["runtime_manifest_digest"] == runtime_verified.manifest_digest
    assert details["toolchain_manifest_digest"] == tool_verified.manifest_digest


async def test_verify_with_unreducible_volumes_reports_local_only_limitation(
    client, admin_token, db_session, monkeypatch
):
    template = await create_template(db_session, volumes=["/host/path:/data"])
    verified, identity = verified_artifact(template.image, repository="registry.example/workspace")
    patch_registry(
        monkeypatch,
        FakeRegistry({template.image: verified}),
        FakeArtifacts({template.image: identity}),
    )

    response = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=auth(admin_token),
        json={"reason": "verify with docker short syntax volume"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["portability"] == "local_only"
    assert data["portable_fingerprint"] is None
    assert data["configuration"]["volumes"] == []
    assert "volume_configuration_local_only" in data["limitations"]
    assert "/host/path" not in response.text
    stored = (
        await db_session.execute(
            select(EnvironmentRevision).where(EnvironmentRevision.template_id == template.id)
        )
    ).scalar_one()
    assert stored.portable_fingerprint is None


async def test_verify_reuses_matching_active_revision(client, admin_token, db_session, monkeypatch):
    template = await create_template(db_session)
    verified, identity = verified_artifact(template.image, repository="registry.example/workspace")
    patch_registry(
        monkeypatch,
        FakeRegistry({template.image: verified}),
        FakeArtifacts({template.image: identity}),
    )
    configuration = template_configuration(template)
    revision_fingerprint = fingerprint(
        {
            "configuration": configuration,
            "runtime": identity.model_dump(mode="json"),
            "toolchain": None,
        }
    )
    existing = await add_revision(
        db_session,
        template,
        revision_fingerprint=revision_fingerprint,
        template_fingerprint=fingerprint(configuration),
        configuration=configuration,
        runtime_identity=identity.model_dump(mode="json"),
    )

    response = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=auth(admin_token),
        json={"reason": "verify already approved artifacts"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(existing.id)
    assert await revision_count(db_session, template.id) == 1


async def test_verify_after_revoke_creates_new_active_revision_with_same_fingerprint(
    client, admin_token, db_session, monkeypatch
):
    template = await create_template(db_session)
    verified, identity = verified_artifact(template.image, repository="registry.example/workspace")
    patch_registry(
        monkeypatch,
        FakeRegistry({template.image: verified}),
        FakeArtifacts({template.image: identity}),
    )
    configuration = template_configuration(template)
    revision_fingerprint = fingerprint(
        {
            "configuration": configuration,
            "runtime": identity.model_dump(mode="json"),
            "toolchain": None,
        }
    )
    revoked = await add_revision(
        db_session,
        template,
        revision_fingerprint=revision_fingerprint,
        template_fingerprint=fingerprint(configuration),
        configuration=configuration,
        runtime_identity=identity.model_dump(mode="json"),
        revoked=True,
    )

    response = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=auth(admin_token),
        json={"reason": "re-approve after revoke"},
    )

    assert response.status_code == 200
    replacement_id = response.json()["data"]["id"]
    assert replacement_id != str(revoked.id)
    assert await revision_count(db_session, template.id) == 2
    rows = (
        (
            await db_session.execute(
                select(EnvironmentRevision)
                .where(EnvironmentRevision.template_id == template.id)
                .order_by(EnvironmentRevision.created_at, EnvironmentRevision.id)
            )
        )
        .scalars()
        .all()
    )
    old = next(row for row in rows if row.id == revoked.id)
    new = next(row for row in rows if str(row.id) == replacement_id)
    assert old.revoked is True
    assert new.revoked is False
    assert new.fingerprint == old.fingerprint


async def test_verify_rejects_local_id_reference_without_registry_call(
    client, admin_token, db_session, monkeypatch
):
    local_id = "sha256:" + "a" * 64
    template = await create_template(db_session, image=local_id)
    registry = FakeRegistry({})
    artifacts = FakeArtifacts({})
    factory_calls = 0

    async def _registry():
        nonlocal factory_calls
        factory_calls += 1
        return registry

    async def _artifacts():
        nonlocal factory_calls
        factory_calls += 1
        return artifacts

    monkeypatch.setattr(environment_revisions, "_registry_service", _registry)
    monkeypatch.setattr(environment_revisions, "_artifact_service", _artifacts)

    response = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=auth(admin_token),
        json={"reason": "local id cannot be verified"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "revision_unavailable"}
    assert factory_calls == 0
    assert registry.calls == []
    assert artifacts.calls == []
    assert await revision_count(db_session, template.id) == 0


@pytest.mark.parametrize(
    ("code", "expected_status", "source"),
    [
        ("registry_auth_failed", 503, "registry"),
        ("registry_unreachable", 503, "registry"),
        ("platform_unavailable", 409, "registry"),
        ("artifact_missing", 409, "artifact"),
        ("artifact_mismatch", 409, "artifact"),
    ],
)
async def test_verify_maps_registry_and_artifact_failures(
    client, admin_token, db_session, monkeypatch, code, expected_status, source
):
    template = await create_template(db_session)
    verified, identity = verified_artifact(template.image, repository="registry.example/workspace")
    error = RegistryError(code, "test failure")
    if source == "registry":
        registry = FakeRegistry({template.image: error})
        artifacts = FakeArtifacts({template.image: identity})
    else:
        registry = FakeRegistry({template.image: verified})
        artifacts = FakeArtifacts({template.image: error})
    patch_registry(monkeypatch, registry, artifacts)

    response = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=auth(admin_token),
        json={"reason": "verify failure mapping"},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == {"code": code}
    assert await revision_count(db_session, template.id) == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"reason": ""},
        {"reason": "   "},
        {"reason": "reason", "force": True},
    ],
)
async def test_verify_request_rejects_missing_invalid_or_extra_fields(
    client, admin_token, db_session, body
):
    template = await create_template(db_session)

    response = await client.post(
        f"/api/environments/{template.id}/verify-artifacts",
        headers=auth(admin_token),
        json=body,
    )

    assert response.status_code == 422
    assert await revision_count(db_session, template.id) == 0


async def test_revoke_is_idempotent_and_audits_actor_and_reason(
    client, admin_token, admin_user, db_session
):
    template = await create_template(db_session)
    revision = await add_revision(db_session, template)
    await add_revision(db_session, template)

    first = await client.post(
        f"/api/admin/environment-revisions/{revision.id}/revoke",
        headers=auth(admin_token),
        json={"reason": "unsafe artifact"},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["data"]["revoked"] is True
    assert payload["template_has_selectable_revision"] is True
    assert payload["selectable_revision_count"] == 1
    assert payload["already_revoked"] is False

    second = await client.post(
        f"/api/admin/environment-revisions/{revision.id}/revoke",
        headers=auth(admin_token),
        json={"reason": "repeat request"},
    )
    assert second.status_code == 200
    assert second.json()["already_revoked"] is True
    assert second.json()["selectable_revision_count"] == 1
    assert second.json()["data"]["revoked"] is True

    rows = await audit_rows(db_session, "environment.revision.revoke")
    assert len(rows) == 2
    assert {row.details["outcome"] for row in rows} == {"revoked", "already_revoked"}
    assert all(row.actor_id == admin_user.id for row in rows)
    applied = next(row for row in rows if row.details["outcome"] == "revoked")
    assert applied.details["reason"] == "unsafe artifact"
    assert applied.details["template_id"] == str(template.id)
    assert applied.details["revision_id"] == str(revision.id)


async def test_revoke_last_revision_requires_confirmation_and_creates_no_replacement(
    client, admin_token, db_session
):
    template = await create_template(db_session)
    revision = await add_revision(db_session, template)

    refused = await client.post(
        f"/api/admin/environment-revisions/{revision.id}/revoke",
        headers=auth(admin_token),
        json={"reason": "remove last approval"},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "last_revision_confirmation_required",
        "selectable_revision_count": 0,
        "replacement_available": False,
    }
    stored = await db_session.get(EnvironmentRevision, revision.id, populate_existing=True)
    assert stored.revoked is False
    assert await revision_count(db_session, template.id) == 1

    confirmed = await client.post(
        f"/api/admin/environment-revisions/{revision.id}/revoke",
        headers=auth(admin_token),
        json={"reason": "confirm remove last approval", "confirm_last_revision": True},
    )
    assert confirmed.status_code == 200
    payload = confirmed.json()
    assert payload["data"]["revoked"] is True
    assert payload["template_has_selectable_revision"] is False
    assert payload["selectable_revision_count"] == 0
    assert await revision_count(db_session, template.id) == 1

    rows = await audit_rows(db_session, "environment.revision.revoke")
    assert {row.details["outcome"] for row in rows} == {
        "last_revision_confirmation_required",
        "revoked",
    }
    applied = next(row for row in rows if row.details["outcome"] == "revoked")
    assert applied.details["confirm_last_revision"] is True
    assert applied.details["template_has_selectable_revision"] is False


async def test_revoke_already_revoked_last_revision_needs_no_confirmation(
    client, admin_token, db_session
):
    template = await create_template(db_session)
    revision = await add_revision(db_session, template, revoked=True)

    response = await client.post(
        f"/api/admin/environment-revisions/{revision.id}/revoke",
        headers=auth(admin_token),
        json={"reason": "already revoked"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["already_revoked"] is True
    assert payload["template_has_selectable_revision"] is False
    assert payload["selectable_revision_count"] == 0
    rows = await audit_rows(db_session, "environment.revision.revoke")
    assert [row.details["outcome"] for row in rows] == ["already_revoked"]


async def test_revoke_missing_revision_is_404_and_audited(client, admin_token, db_session):
    revision_id = uuid.uuid4()

    response = await client.post(
        f"/api/admin/environment-revisions/{revision_id}/revoke",
        headers=auth(admin_token),
        json={"reason": "missing revision probe"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "revision_not_found"}
    rows = await audit_rows(db_session, "environment.revision.revoke")
    assert len(rows) == 1
    assert rows[0].target_id == revision_id
    assert rows[0].details["outcome"] == "not_found"
    assert rows[0].details["reason"] == "missing revision probe"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"reason": ""},
        {"reason": "reason", "force": True},
        {"reason": "reason", "confirm_last_revision": "yes"},
    ],
)
async def test_revoke_request_rejects_missing_invalid_or_extra_fields(
    client, admin_token, db_session, body
):
    template = await create_template(db_session)
    revision = await add_revision(db_session, template)

    response = await client.post(
        f"/api/admin/environment-revisions/{revision.id}/revoke",
        headers=auth(admin_token),
        json=body,
    )

    assert response.status_code == 422
    stored = await db_session.get(EnvironmentRevision, revision.id, populate_existing=True)
    assert stored.revoked is False


async def test_revocation_has_no_unrevoke_route(client, admin_token, db_session):
    template = await create_template(db_session)
    revision = await add_revision(db_session, template, revoked=True)

    response = await client.post(
        f"/api/admin/environment-revisions/{revision.id}/unrevoke",
        headers=auth(admin_token),
        json={"reason": "attempt unrevoke"},
    )

    assert response.status_code in (404, 405)
    stored = await db_session.get(EnvironmentRevision, revision.id, populate_existing=True)
    assert stored.revoked is True
