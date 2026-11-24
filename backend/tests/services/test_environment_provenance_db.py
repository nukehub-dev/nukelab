# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""PostgreSQL persistence regressions for approval and launch history."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_launch_record import ServerLaunchRecord
from app.schemas.environment_manifest import ImageIdentity, ManifestResources
from app.services.environment_revision_service import (
    ConfigurationChanged,
    EnvironmentRevisionService,
    RevisionAmbiguous,
    RevisionUnavailable,
    fingerprint,
    template_configuration,
)
from app.services.server_provenance_service import ServerProvenanceService, build_manifest


def runtime_identity():
    return ImageIdentity(
        requested_reference="workspace:latest",
        local_id="sha256:" + "a" * 64,
        os="linux",
        architecture="amd64",
    )


def verified_runtime_identity(*, local_id="sha256:" + "a" * 64):
    digest = "sha256:" + "b" * 64
    return ImageIdentity(
        requested_reference="workspace:latest",
        local_id=local_id,
        repository_digests=[f"registry/workspace@{digest}"],
        os="linux",
        architecture="amd64",
        registry_verified=True,
        verified_reference=f"registry/workspace@{digest}",
        manifest_digest=digest,
        index_digest="sha256:" + "d" * 64,
        descriptor_media_type="application/vnd.oci.image.manifest.v1+json",
    )


def exported_manifest(*, portable_fingerprint, runtime=None, label="Origin environment"):
    source = SimpleNamespace(
        id=uuid4(),
        fingerprint="c" * 64,
        portable_fingerprint=portable_fingerprint,
        runtime_identity=(runtime or verified_runtime_identity()).model_dump(mode="json"),
        toolchain_identity=None,
        configuration={"tool_mounts": [], "environment_variables": {}},
    )
    return build_manifest(
        source,
        template_label=label,
        resources=ManifestResources(cpu=1.0, memory_mib=2048, disk_mib=10240),
    )


async def create_template(db, **changes):
    name = "environment-" + uuid4().hex
    values = {
        "name": name,
        "slug": name,
        "image": "workspace:latest",
        "is_active": True,
        "environment_variables": {"TOKEN": "private-value"},
    }
    template = EnvironmentTemplate(**(values | changes))
    db.add(template)
    await db.flush()
    return template


async def capture(db, template, authorize=None, runtime=None):
    service = EnvironmentRevisionService(db, authorize or AsyncMock())
    revision = await service.capture(
        template.id,
        expected_template_fingerprint=fingerprint(template_configuration(template)),
        runtime=runtime or runtime_identity(),
    )
    return service, revision


@pytest.mark.asyncio
async def test_revision_capture_reuses_approval_without_duplicate_rows(db_session):
    template = await create_template(db_session)
    authorize = AsyncMock()
    _, first = await capture(db_session, template, authorize)
    _, second = await capture(db_session, template, authorize)
    assert first.id == second.id
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(EnvironmentRevision)
            .where(EnvironmentRevision.template_id == template.id)
        )
    ).scalar_one() == 1
    assert authorize.await_count == 2


@pytest.mark.asyncio
async def test_revision_capture_refreshes_template_changed_after_resolution(db_session):
    template = await create_template(db_session)
    expected = fingerprint(template_configuration(template))
    # Preserve the stale ORM identity-map object, as an external approval edit would.
    await db_session.execute(
        update(EnvironmentTemplate)
        .where(EnvironmentTemplate.id == template.id)
        .values(image="workspace:changed")
        .execution_options(synchronize_session=False)
    )
    service = EnvironmentRevisionService(db_session, AsyncMock())
    with pytest.raises(ConfigurationChanged):
        await service.capture(
            template.id, expected_template_fingerprint=expected, runtime=runtime_identity()
        )
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(EnvironmentRevision)
            .where(EnvironmentRevision.template_id == template.id)
        )
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_revision_configuration_cannot_be_replaced_after_capture(db_session):
    template = await create_template(db_session)
    _, revision = await capture(db_session, template)
    revision_id = revision.id
    original = revision.configuration
    with pytest.raises(ValueError, match="immutable"):
        async with db_session.begin_nested():
            revision.configuration = {"image": "attacker:latest"}
            await db_session.flush()
    revision = await db_session.get(EnvironmentRevision, revision_id)
    await db_session.refresh(revision)
    assert revision.configuration == original


@pytest.mark.asyncio
async def test_revocation_preserves_history_and_blocks_recreation(db_session):
    template = await create_template(db_session)
    revisions, revision = await capture(db_session, template)
    exported = build_manifest(
        revision,
        template_label=template.name,
        resources=ManifestResources(cpu=1.0, memory_mib=2048, disk_mib=10240),
    )
    revision.revoked = True
    await db_session.flush()
    with pytest.raises(RevisionUnavailable):
        await revisions.require_available(revision.id)
    with pytest.raises(RevisionUnavailable):
        await ServerProvenanceService(db_session, revisions).validate_recreation(
            exported.model_dump_json()
        )
    assert (
        await db_session.get(EnvironmentRevision, revision.id)
    ).fingerprint == exported.revision_fingerprint


@pytest.mark.asyncio
async def test_current_authorization_is_checked_for_historical_revision(db_session):
    template = await create_template(db_session)
    _, revision = await capture(db_session, template)
    denied = AsyncMock(side_effect=PermissionError("Access revoked"))
    with pytest.raises(PermissionError):
        await EnvironmentRevisionService(db_session, denied).require_available(revision.id)
    denied.assert_awaited_once()


@pytest.mark.asyncio
async def test_launch_record_redelivery_reuses_identity_and_is_append_only(db_session, test_user):
    template = await create_template(db_session)
    revisions, revision = await capture(db_session, template)
    server = Server(name="server-" + uuid4().hex, user_id=test_user.id, status="running")
    db_session.add(server)
    await db_session.flush()
    exported = build_manifest(
        revision,
        template_label=template.name,
        resources=ManifestResources(cpu=1.0, memory_mib=2048, disk_mib=10240),
    )
    service = ServerProvenanceService(db_session, revisions)
    operation_id = uuid4()
    arguments = {
        "operation_id": operation_id,
        "server_id": server.id,
        "owner_id": test_user.id,
        "generation": 1,
        "manifest": exported,
        "actual_runtime": runtime_identity(),
        "actual_toolchain": None,
    }
    first = await service.record_launch(**arguments)
    second = await service.record_launch(**arguments)
    assert first.id == second.id == operation_id
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(ServerLaunchRecord)
            .where(ServerLaunchRecord.server_id == server.id)
        )
    ).scalar_one() == 1
    assert "private-value" not in str(first.manifest)
    with pytest.raises(ValueError, match="identity cannot be reused"):
        await service.record_launch(**(arguments | {"generation": 2}))
    with pytest.raises(ValueError, match="append-only"):
        async with db_session.begin_nested():
            first.generation = 2
            await db_session.flush()
    first = await db_session.get(ServerLaunchRecord, operation_id)
    await db_session.refresh(first)
    assert first.generation == 1


@pytest.mark.asyncio
async def test_portable_manifest_matches_a_second_template_by_fingerprint_only(db_session):
    origin_template = await create_template(db_session, name="origin-" + uuid4().hex)
    _, origin = await capture(
        db_session,
        origin_template,
        runtime=verified_runtime_identity(local_id="sha256:" + "a" * 64),
    )
    exported = exported_manifest(
        portable_fingerprint=origin.portable_fingerprint,
        label="Origin label",
    )
    portable_fingerprint = origin.portable_fingerprint
    origin_id = origin.id
    await db_session.delete(origin)
    await db_session.flush()

    destination_template = await create_template(db_session, name="destination-" + uuid4().hex)
    _, destination = await capture(
        db_session,
        destination_template,
        runtime=verified_runtime_identity(local_id="sha256:" + "f" * 64),
    )

    assert destination.id != origin_id
    assert destination.portable_fingerprint == portable_fingerprint
    assert destination.runtime_identity["local_id"] != exported.runtime.local_id
    service = ServerProvenanceService(
        db_session,
        EnvironmentRevisionService(db_session, AsyncMock()),
        can_use_template=AsyncMock(return_value=True),
    )
    selected = await service.validate_recreation(exported.model_dump_json())
    assert selected.id == destination.id


@pytest.mark.asyncio
async def test_portable_manifest_with_multiple_templates_is_ambiguous(db_session):
    first_template = await create_template(db_session)
    second_template = await create_template(db_session)
    _, first = await capture(
        db_session,
        first_template,
        runtime=verified_runtime_identity(local_id="sha256:" + "a" * 64),
    )
    _, second = await capture(
        db_session,
        second_template,
        runtime=verified_runtime_identity(local_id="sha256:" + "f" * 64),
    )
    assert first.portable_fingerprint == second.portable_fingerprint

    exported = exported_manifest(portable_fingerprint=first.portable_fingerprint)
    service = ServerProvenanceService(
        db_session,
        EnvironmentRevisionService(db_session, AsyncMock()),
        can_use_template=AsyncMock(return_value=True),
    )
    with pytest.raises(RevisionAmbiguous) as error:
        await service.validate_recreation(exported.model_dump_json())
    assert error.value.code == "revision_ambiguous"


@pytest.mark.asyncio
async def test_portable_manifest_without_matching_revision_is_unavailable(db_session):
    exported = exported_manifest(portable_fingerprint="e" * 64)
    service = ServerProvenanceService(
        db_session,
        EnvironmentRevisionService(db_session, AsyncMock()),
        can_use_template=AsyncMock(return_value=True),
    )
    with pytest.raises(RevisionUnavailable) as error:
        await service.validate_recreation(exported.model_dump_json())
    assert error.value.code == "revision_unavailable"


@pytest.mark.asyncio
async def test_portable_manifest_never_matches_a_revoked_revision(db_session):
    template = await create_template(db_session)
    _, revision = await capture(db_session, template, runtime=verified_runtime_identity())
    portable_fingerprint = revision.portable_fingerprint
    exported = exported_manifest(portable_fingerprint=portable_fingerprint)
    revision.revoked = True
    await db_session.flush()

    service = ServerProvenanceService(
        db_session,
        EnvironmentRevisionService(db_session, AsyncMock()),
        can_use_template=AsyncMock(return_value=True),
    )
    with pytest.raises(RevisionUnavailable) as error:
        await service.validate_recreation(exported.model_dump_json())
    assert error.value.code == "revision_unavailable"


@pytest.mark.asyncio
async def test_portable_manifest_chooses_the_newest_revision_of_one_template(db_session):
    template = await create_template(db_session)
    portable_fingerprint = "e" * 64
    older_id = uuid4()
    newer_id = uuid4()
    db_session.add_all(
        [
            EnvironmentRevision(
                id=older_id,
                template_id=template.id,
                fingerprint="1" * 64,
                template_fingerprint="2" * 64,
                portable_fingerprint=portable_fingerprint,
                configuration={"tool_mounts": [], "environment_variables": {}},
                runtime_identity=verified_runtime_identity().model_dump(mode="json"),
                created_at=datetime(2026, 1, 1, 12),
            ),
            EnvironmentRevision(
                id=newer_id,
                template_id=template.id,
                fingerprint="3" * 64,
                template_fingerprint="4" * 64,
                portable_fingerprint=portable_fingerprint,
                configuration={"tool_mounts": [], "environment_variables": {}},
                runtime_identity=verified_runtime_identity().model_dump(mode="json"),
                created_at=datetime(2026, 1, 2, 12),
            ),
        ]
    )
    await db_session.flush()

    service = ServerProvenanceService(
        db_session,
        EnvironmentRevisionService(db_session, AsyncMock()),
        can_use_template=AsyncMock(return_value=True),
    )
    selected = await service.validate_recreation(
        exported_manifest(portable_fingerprint=portable_fingerprint).model_dump_json()
    )
    assert selected.id == newer_id


@pytest.mark.asyncio
async def test_unauthorized_portable_templates_are_omitted_not_disclosed(db_session):
    allowed_template = await create_template(db_session)
    hidden_template = await create_template(db_session)
    _, allowed = await capture(
        db_session,
        allowed_template,
        runtime=verified_runtime_identity(local_id="sha256:" + "a" * 64),
    )
    _, hidden = await capture(
        db_session,
        hidden_template,
        runtime=verified_runtime_identity(local_id="sha256:" + "f" * 64),
    )
    assert allowed.portable_fingerprint == hidden.portable_fingerprint
    exported = exported_manifest(portable_fingerprint=allowed.portable_fingerprint)

    async def allowed_only(template):
        return template.id == allowed_template.id

    service = ServerProvenanceService(
        db_session,
        EnvironmentRevisionService(db_session, AsyncMock()),
        can_use_template=allowed_only,
    )
    selected = await service.validate_recreation(exported.model_dump_json())
    assert selected.id == allowed.id

    async def deny_all(template):
        return False

    denied = ServerProvenanceService(
        db_session,
        EnvironmentRevisionService(db_session, AsyncMock()),
        can_use_template=deny_all,
    )
    with pytest.raises(RevisionUnavailable) as error:
        await denied.validate_recreation(exported.model_dump_json())
    assert error.value.code == "revision_unavailable"
    assert hidden_template.name not in str(error.value)


@pytest.mark.asyncio
async def test_inactive_portable_templates_are_not_matched(db_session):
    template = await create_template(db_session)
    _, revision = await capture(db_session, template, runtime=verified_runtime_identity())
    exported = exported_manifest(portable_fingerprint=revision.portable_fingerprint)
    template.is_active = False
    await db_session.flush()

    service = ServerProvenanceService(
        db_session,
        EnvironmentRevisionService(db_session, AsyncMock()),
        can_use_template=AsyncMock(return_value=True),
    )
    with pytest.raises(RevisionUnavailable) as error:
        await service.validate_recreation(exported.model_dump_json())
    assert error.value.code == "revision_unavailable"
