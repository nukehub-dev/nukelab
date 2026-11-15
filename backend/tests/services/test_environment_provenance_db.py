# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""PostgreSQL persistence regressions for approval and launch history."""

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


async def create_template(db):
    name = "environment-" + uuid4().hex
    template = EnvironmentTemplate(
        name=name,
        slug=name,
        image="workspace:latest",
        is_active=True,
        environment_variables={"TOKEN": "private-value"},
    )
    db.add(template)
    await db.flush()
    return template


async def capture(db, template, authorize=None):
    service = EnvironmentRevisionService(db, authorize or AsyncMock())
    revision = await service.capture(
        template.id,
        expected_template_fingerprint=fingerprint(template_configuration(template)),
        runtime=runtime_identity(),
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
