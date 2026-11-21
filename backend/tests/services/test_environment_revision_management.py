# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Active revision reuse, portable identity persistence, and re-approval."""

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.environment_revision import EnvironmentRevision
from app.models.environment_template import EnvironmentTemplate
from app.schemas.environment_manifest import ImageIdentity
from app.services.environment_revision_service import (
    EnvironmentRevisionService,
    RevisionUnavailable,
    fingerprint,
    template_configuration,
)
from app.services.portable_environment import portable_environment_identity


def runtime_identity(*, verified: bool = False, **changes):
    values = {
        "requested_reference": "workspace:latest",
        "local_id": "sha256:" + "a" * 64,
        "os": "linux",
        "architecture": "amd64",
    }
    if verified:
        values |= {
            "repository_digests": ["registry/workspace@sha256:" + "b" * 64],
            "registry_verified": True,
            "verified_reference": "registry/workspace@sha256:" + "b" * 64,
            "manifest_digest": "sha256:" + "b" * 64,
            "index_digest": "sha256:" + "c" * 64,
            "descriptor_media_type": "application/vnd.oci.image.manifest.v1+json",
        }
    values |= changes
    return ImageIdentity(**values)


async def create_template(db, **changes):
    name = "environment-" + uuid4().hex
    values = {
        "name": name,
        "slug": name,
        "image": "workspace:latest",
        "is_active": True,
        "environment_variables": {"TOKEN": "private-value"},
        "packages": ["numpy==2.1.0"],
    }
    values |= changes
    template = EnvironmentTemplate(**values)
    db.add(template)
    await db.flush()
    return template


def service_for(db, authorize=None):
    return EnvironmentRevisionService(db, authorize or AsyncMock())


async def capture(db, template, runtime=None, **changes):
    service = service_for(db)
    revision = await service.capture(
        template.id,
        expected_template_fingerprint=fingerprint(template_configuration(template)),
        runtime=runtime or runtime_identity(),
        **changes,
    )
    return service, revision


async def revision_count(db, template_id):
    return (
        await db.execute(
            select(func.count())
            .select_from(EnvironmentRevision)
            .where(EnvironmentRevision.template_id == template_id)
        )
    ).scalar_one()


def stored_revision(
    template,
    revision_id,
    *,
    template_fingerprint,
    fingerprint_value,
    created_at,
    revoked=False,
):
    return EnvironmentRevision(
        id=revision_id,
        template_id=template.id,
        fingerprint=fingerprint_value,
        template_fingerprint=template_fingerprint,
        configuration={},
        runtime_identity={},
        revoked=revoked,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_find_active_revision_selects_newest_active_and_ignores_revoked(db_session):
    template = await create_template(db_session)
    template_fingerprint = fingerprint(template_configuration(template))
    older_id = UUID("00000000-0000-4000-8000-000000000001")
    newer_id = UUID("00000000-0000-4000-8000-000000000002")
    revoked_id = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    db_session.add_all(
        [
            stored_revision(
                template,
                older_id,
                template_fingerprint=template_fingerprint,
                fingerprint_value="a" * 64,
                created_at=datetime(2026, 1, 1, 12),
            ),
            stored_revision(
                template,
                newer_id,
                template_fingerprint=template_fingerprint,
                fingerprint_value="b" * 64,
                created_at=datetime(2026, 1, 2, 12),
            ),
            stored_revision(
                template,
                revoked_id,
                template_fingerprint=template_fingerprint,
                fingerprint_value="c" * 64,
                created_at=datetime(2026, 1, 3, 12),
                revoked=True,
            ),
        ]
    )
    await db_session.flush()

    service = service_for(db_session)
    selected = await service.find_active_revision(template.id, template_fingerprint)

    assert selected is not None
    assert selected.id == newer_id
    assert selected.revoked is False


@pytest.mark.asyncio
async def test_find_active_revision_breaks_created_at_ties_by_id(db_session):
    template = await create_template(db_session)
    template_fingerprint = fingerprint(template_configuration(template))
    lower_id = UUID("00000000-0000-4000-8000-000000000001")
    higher_id = UUID("00000000-0000-4000-8000-000000000002")
    created_at = datetime(2026, 1, 1, 12)
    db_session.add_all(
        [
            stored_revision(
                template,
                higher_id,
                template_fingerprint=template_fingerprint,
                fingerprint_value="b" * 64,
                created_at=created_at,
            ),
            stored_revision(
                template,
                lower_id,
                template_fingerprint=template_fingerprint,
                fingerprint_value="a" * 64,
                created_at=created_at,
            ),
        ]
    )
    await db_session.flush()

    selected = await service_for(db_session).find_active_revision(template.id, template_fingerprint)

    assert selected is not None
    assert selected.id == higher_id


@pytest.mark.asyncio
async def test_find_active_revision_filters_current_template_fingerprint(db_session):
    template = await create_template(db_session)
    _, revision = await capture(db_session, template)

    service = service_for(db_session)
    assert await service.find_active_revision(template.id, "0" * 64) is None
    selected = await service.find_active_revision(template.id, revision.template_fingerprint)
    assert selected is not None
    assert selected.id == revision.id


@pytest.mark.asyncio
async def test_capture_reuses_the_active_revision_instead_of_inserting(db_session):
    template = await create_template(db_session)
    _, first = await capture(db_session, template)
    _, second = await capture(db_session, template)

    assert first.id == second.id
    assert await revision_count(db_session, template.id) == 1


@pytest.mark.asyncio
async def test_capture_refuses_a_revoked_only_approval(db_session):
    template = await create_template(db_session)
    _, revision = await capture(db_session, template)
    revision.revoked = True
    await db_session.flush()

    with pytest.raises(RevisionUnavailable):
        await capture(db_session, template)

    assert await revision_count(db_session, template.id) == 1


@pytest.mark.asyncio
async def test_capture_reapproval_creates_a_new_active_revision_for_same_fingerprint(
    db_session,
):
    template = await create_template(db_session)
    _, revoked = await capture(db_session, template)
    revoked.revoked = True
    await db_session.flush()

    _, replacement = await capture(db_session, template, allow_reapproval=True)

    assert replacement.id != revoked.id
    assert replacement.fingerprint == revoked.fingerprint
    assert replacement.revoked is False
    assert revoked.revoked is True
    assert await revision_count(db_session, template.id) == 2


@pytest.mark.asyncio
async def test_capture_persists_portable_fingerprint_for_verified_identity(db_session):
    template = await create_template(db_session)
    runtime = runtime_identity(verified=True)

    _, revision = await capture(db_session, template, runtime=runtime)

    expected = portable_environment_identity(template_configuration(template), runtime, None)
    assert revision.portable_fingerprint == expected.fingerprint
    assert len(revision.portable_fingerprint) == 64


@pytest.mark.asyncio
async def test_capture_keeps_local_only_identity_without_a_portable_fingerprint(db_session):
    template = await create_template(db_session)

    _, revision = await capture(db_session, template, runtime=runtime_identity())

    assert revision.portable_fingerprint is None
    assert revision.runtime_identity["registry_verified"] is False


@pytest.mark.asyncio
async def test_capture_keeps_unsupported_volume_configuration_local_only(db_session):
    template = await create_template(db_session, volumes=["/data:/data"])
    runtime = runtime_identity(verified=True)

    _, revision = await capture(db_session, template, runtime=runtime)

    assert revision.portable_fingerprint is None
    assert revision.runtime_identity["registry_verified"] is True


@pytest.mark.asyncio
async def test_capture_recovers_from_a_concurrent_active_fingerprint_insert(
    db_session, monkeypatch
):
    template = await create_template(db_session)
    _, winner = await capture(db_session, template)
    service = service_for(db_session)

    lookup = service._active_revision_by_fingerprint
    lookups = 0

    async def miss_lookup_once(template_id, revision_fingerprint):
        nonlocal lookups
        lookups += 1
        if lookups == 1:
            return None
        return await lookup(template_id, revision_fingerprint)

    monkeypatch.setattr(service, "_active_revision_by_fingerprint", miss_lookup_once)
    flush = db_session.flush
    failures = 0

    async def fail_flush_once(*args, **kwargs):
        nonlocal failures
        if failures == 0:
            failures += 1
            raise IntegrityError("INSERT", {}, Exception("duplicate key value"))
        return await flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_flush_once)

    result = await service.capture(
        template.id,
        expected_template_fingerprint=fingerprint(template_configuration(template)),
        runtime=runtime_identity(),
    )

    assert result.id == winner.id
    assert failures == 1
    assert lookups == 2
    await db_session.flush()
    assert await revision_count(db_session, template.id) == 1
