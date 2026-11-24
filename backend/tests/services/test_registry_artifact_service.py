# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Exact platform-digest proof, bounded pulls, and per-digest lock behavior."""

import asyncio
import contextlib
import hashlib
import secrets
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.container.driver import ContainerDriverError, ImageResolutionError
from app.schemas.environment_manifest import ImageIdentity
from app.services.registry_artifact_service import (
    PULL_LOCK_NAMESPACE,
    PostgresDigestPullLock,
    RegistryArtifactService,
    pull_lock_key,
)
from app.services.registry_client import (
    REGISTRY_ARTIFACT_MISMATCH,
    REGISTRY_ARTIFACT_MISSING,
    REGISTRY_AUTH_FAILED,
    REGISTRY_UNREACHABLE,
    RegistryError,
    VerifiedImage,
)

DIGEST = "sha256:" + "1" * 64
INDEX_DIGEST = "sha256:" + "2" * 64
OTHER_DIGEST = "sha256:" + "3" * 64
LOCAL_ID = "sha256:" + "a" * 64
REPOSITORY = "registry.example.com/team/runtime"
VERIFIED_REFERENCE = f"{REPOSITORY}@{DIGEST}"
MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"


def verified_image(**changes) -> VerifiedImage:
    values = {
        "requested_reference": f"{REPOSITORY}:approved",
        "verified_reference": VERIFIED_REFERENCE,
        "manifest_digest": DIGEST,
        "index_digest": INDEX_DIGEST,
        "descriptor_media_type": MANIFEST_MEDIA_TYPE,
        "os": "linux",
        "architecture": "amd64",
        "variant": None,
    }
    return VerifiedImage(**(values | changes))


def local_image(**changes) -> dict:
    values = {
        "requested_reference": VERIFIED_REFERENCE,
        "local_id": LOCAL_ID,
        "repository_digests": [f"{REPOSITORY}@{DIGEST}"],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }
    return values | changes


class FakeDriver:
    """Minimal driver whose local state only changes after a successful pull."""

    def __init__(
        self,
        *,
        local: object = None,
        after_pull: object = None,
        pull_error: BaseException | None = None,
    ) -> None:
        self.local = local
        self.after_pull = after_pull
        self.pull_error = pull_error
        self.pulled = False
        self.resolve_calls: list[str] = []
        self.pull_calls: list[str] = []

    async def resolve_image(self, image: str) -> dict:
        self.resolve_calls.append(image)
        value = self.after_pull if self.pulled else self.local
        if isinstance(value, BaseException):
            raise value
        return value

    async def pull_image_by_digest(self, reference: str) -> None:
        self.pull_calls.append(reference)
        if self.pull_error is not None:
            raise self.pull_error
        self.pulled = True


class RecordingLock:
    def __init__(self) -> None:
        self.held: list[str] = []

    @asynccontextmanager
    async def hold(self, digest: str):
        self.held.append(digest)
        yield


def make_service(
    driver: FakeDriver,
    *,
    policy: str = "on_demand",
) -> tuple[RegistryArtifactService, RecordingLock]:
    recording = RecordingLock()
    service = RegistryArtifactService(
        driver=driver,
        pull_policy=policy,
        lock_factory=lambda: recording,
    )
    return service, recording


def assert_registry_error(exc_info, code: str) -> None:
    assert exc_info.value.code == code
    assert exc_info.value.message
    assert "private" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_exact_platform_digest_present_is_proof_without_pull():
    driver = FakeDriver(local=local_image())
    service, lock = make_service(driver)

    identity = await service.ensure_local(verified_image())

    assert isinstance(identity, ImageIdentity)
    assert identity.requested_reference == f"{REPOSITORY}:approved"
    assert identity.local_id == LOCAL_ID
    assert identity.repository_digests == [f"{REPOSITORY}@{DIGEST}"]
    assert identity.os == "linux"
    assert identity.architecture == "amd64"
    assert identity.registry_verified is True
    assert identity.verified_reference == VERIFIED_REFERENCE
    assert identity.manifest_digest == DIGEST
    assert identity.index_digest == INDEX_DIGEST
    assert identity.descriptor_media_type == MANIFEST_MEDIA_TYPE
    assert identity.variant is None
    assert driver.resolve_calls == [VERIFIED_REFERENCE]
    assert driver.pull_calls == []
    assert lock.held == []


@pytest.mark.asyncio
async def test_tag_pulled_index_digest_triggers_exact_platform_pull():
    driver = FakeDriver(
        local=local_image(repository_digests=[f"{REPOSITORY}@{INDEX_DIGEST}"]),
        after_pull=local_image(),
    )
    service, lock = make_service(driver)

    identity = await service.ensure_local(verified_image())

    assert driver.pull_calls == [VERIFIED_REFERENCE]
    assert lock.held == [DIGEST]
    assert driver.resolve_calls == [VERIFIED_REFERENCE, VERIFIED_REFERENCE, VERIFIED_REFERENCE]
    assert identity.registry_verified is True
    assert identity.repository_digests == [f"{REPOSITORY}@{DIGEST}"]


@pytest.mark.asyncio
async def test_preload_only_missing_artifact_never_pulls_or_waits():
    driver = FakeDriver(local=None)
    service, lock = make_service(driver, policy="preload_only")

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, REGISTRY_ARTIFACT_MISSING)
    assert driver.pull_calls == []
    assert lock.held == []


@pytest.mark.asyncio
async def test_preload_only_platform_mismatch_is_mismatch_without_pull():
    driver = FakeDriver(local=local_image(architecture="arm64"))
    service, lock = make_service(driver, policy="preload_only")

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, REGISTRY_ARTIFACT_MISMATCH)
    assert driver.pull_calls == []
    assert lock.held == []


@pytest.mark.asyncio
async def test_repository_digest_for_another_repository_is_not_proof():
    driver = FakeDriver(
        local=local_image(repository_digests=[f"registry.example.com/other/runtime@{DIGEST}"]),
        after_pull=local_image(),
    )
    service, _ = make_service(driver)

    identity = await service.ensure_local(verified_image())

    assert driver.pull_calls == [VERIFIED_REFERENCE]
    assert identity.registry_verified is True


@pytest.mark.asyncio
async def test_same_digest_from_a_different_repository_does_not_prove_local_artifact():
    driver = FakeDriver(local=local_image(repository_digests=[f"other/image@{DIGEST}"]))
    service, lock = make_service(driver, policy="preload_only")

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, REGISTRY_ARTIFACT_MISSING)
    assert driver.pull_calls == []
    assert lock.held == []


@pytest.mark.asyncio
async def test_platform_mismatch_after_pull_is_artifact_mismatch():
    driver = FakeDriver(
        local=local_image(os="windows"),
        after_pull=local_image(os="windows"),
    )
    service, lock = make_service(driver)

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, REGISTRY_ARTIFACT_MISMATCH)
    assert driver.pull_calls == [VERIFIED_REFERENCE]
    assert lock.held == [DIGEST]


@pytest.mark.asyncio
async def test_pull_success_without_exact_digest_never_returns_verified_identity():
    driver = FakeDriver(
        local=None,
        after_pull=local_image(repository_digests=[f"{REPOSITORY}@{INDEX_DIGEST}"]),
    )
    service, lock = make_service(driver)

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, REGISTRY_ARTIFACT_MISMATCH)
    assert driver.pull_calls == [VERIFIED_REFERENCE]
    assert lock.held == [DIGEST]


@pytest.mark.asyncio
async def test_partial_pull_that_removes_local_artifact_never_returns_identity():
    driver = FakeDriver(local=local_image(), after_pull=ImageResolutionError("artifact_missing"))
    driver.pulled = True
    service, _ = make_service(driver)

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, REGISTRY_ARTIFACT_MISMATCH)


@pytest.mark.parametrize(
    "error, code",
    [
        (ContainerDriverError("private runtime diagnostic", status=404), REGISTRY_ARTIFACT_MISSING),
        (ContainerDriverError("private runtime diagnostic", status=410), REGISTRY_ARTIFACT_MISSING),
        (ContainerDriverError("private runtime diagnostic", status=401), REGISTRY_AUTH_FAILED),
        (ContainerDriverError("private runtime diagnostic", status=403), REGISTRY_AUTH_FAILED),
        (ContainerDriverError("private runtime diagnostic", status=500), REGISTRY_UNREACHABLE),
        (ContainerDriverError("private runtime diagnostic"), REGISTRY_UNREACHABLE),
        (ImageResolutionError("invalid_digest_reference"), REGISTRY_ARTIFACT_MISMATCH),
        (ImageResolutionError("artifact_mismatch"), REGISTRY_ARTIFACT_MISMATCH),
    ],
)
@pytest.mark.asyncio
async def test_pull_failure_maps_to_bounded_registry_codes(error, code):
    driver = FakeDriver(pull_error=error)
    service, _ = make_service(driver)

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, code)


@pytest.mark.asyncio
async def test_pull_timeout_is_bounded_and_never_verified():
    class SlowPullDriver(FakeDriver):
        async def pull_image_by_digest(self, reference: str) -> None:
            self.pull_calls.append(reference)
            await asyncio.sleep(1)

    driver = SlowPullDriver(local=None)
    lock = RecordingLock()
    service = RegistryArtifactService(
        driver=driver,
        pull_policy="on_demand",
        lock_factory=lambda: lock,
        pull_timeout_seconds=0.01,
    )

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, REGISTRY_UNREACHABLE)
    assert driver.pull_calls == [VERIFIED_REFERENCE]
    assert lock.held == [DIGEST]


@pytest.mark.asyncio
async def test_lock_database_unavailable_fails_closed_without_pull():
    driver = FakeDriver(local=None)

    class UnavailableLock:
        @asynccontextmanager
        async def hold(self, digest: str):
            raise RegistryError(REGISTRY_UNREACHABLE, "Registry pull lock is unavailable.")
            yield

    service = RegistryArtifactService(
        driver=driver,
        pull_policy="on_demand",
        lock_factory=UnavailableLock,
    )

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, REGISTRY_UNREACHABLE)
    assert driver.pull_calls == []


@pytest.mark.asyncio
async def test_lock_factory_failure_fails_closed_without_pull():
    driver = FakeDriver(local=None)

    def broken_factory():
        raise RuntimeError("private database diagnostic")

    service = RegistryArtifactService(
        driver=driver,
        pull_policy="on_demand",
        lock_factory=broken_factory,
    )

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified_image())

    assert_registry_error(failure, REGISTRY_UNREACHABLE)
    assert driver.pull_calls == []


@pytest.mark.asyncio
async def test_proof_is_rechecked_after_acquiring_the_lock():
    driver = FakeDriver(local=None)

    class PublishingLock:
        @asynccontextmanager
        async def hold(self, digest: str):
            driver.local = local_image()
            yield

    service = RegistryArtifactService(
        driver=driver,
        pull_policy="on_demand",
        lock_factory=PublishingLock,
    )

    identity = await service.ensure_local(verified_image())

    assert identity.registry_verified is True
    assert driver.pull_calls == []


@pytest.mark.parametrize(
    "local_reference",
    [
        "alpine@sha256:" + "4" * 64,
        "docker.io/library/alpine@sha256:" + "4" * 64,
        "index.docker.io/library/alpine@sha256:" + "4" * 64,
        "registry-1.docker.io/library/alpine@sha256:" + "4" * 64,
    ],
)
@pytest.mark.asyncio
async def test_docker_hub_aliases_normalize_for_local_proof(local_reference):
    digest = "sha256:" + "4" * 64
    driver = FakeDriver(local=local_image(repository_digests=[local_reference]))
    service, lock = make_service(driver)
    verified = verified_image(
        requested_reference="docker.io/library/alpine:3.20",
        verified_reference=f"docker.io/library/alpine@{digest}",
        manifest_digest=digest,
        index_digest=None,
    )

    identity = await service.ensure_local(verified)

    assert identity.registry_verified is True
    assert driver.pull_calls == []
    assert lock.held == []


@pytest.mark.asyncio
async def test_docker_hub_alias_does_not_prove_a_different_repository():
    digest = "sha256:" + "4" * 64
    driver = FakeDriver(local=local_image(repository_digests=[f"docker.io/other/alpine@{digest}"]))
    service, lock = make_service(driver, policy="preload_only")
    verified = verified_image(
        requested_reference="alpine:3.20",
        verified_reference=f"docker.io/library/alpine@{digest}",
        manifest_digest=digest,
        index_digest=None,
    )

    with pytest.raises(RegistryError) as failure:
        await service.ensure_local(verified)

    assert_registry_error(failure, REGISTRY_ARTIFACT_MISSING)
    assert driver.pull_calls == []
    assert lock.held == []


def test_pull_lock_key_is_stable_signed_and_digest_specific():
    key = pull_lock_key(DIGEST)
    assert key == pull_lock_key(DIGEST)
    assert key != pull_lock_key(OTHER_DIGEST)
    assert -(2**63) <= key < 2**63
    material = f"{PULL_LOCK_NAMESPACE}{DIGEST}".encode()
    assert key == int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)


def test_pull_lock_key_rejects_malformed_digest():
    with pytest.raises(ValueError):
        pull_lock_key("sha256:short")


@pytest_asyncio.fixture
async def lock_engine():
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


def fresh_digest() -> str:
    return "sha256:" + secrets.token_hex(32)


@pytest.mark.asyncio
async def test_default_lock_engine_uses_the_direct_database_url(monkeypatch):
    monkeypatch.setattr(settings, "pgbouncer_enabled", True)
    monkeypatch.setattr(
        settings,
        "database_pgbouncer_url",
        "postgresql+asyncpg://pooled@pgbouncer:6432/nukelab",
    )
    lock = PostgresDigestPullLock()
    engine = lock._create_engine()
    try:
        assert engine.url.render_as_string(hide_password=False) == settings.database_url
        assert "pgbouncer" not in str(engine.url)
    finally:
        await engine.dispose()


def lock_for(engine, **changes) -> PostgresDigestPullLock:
    options = {"poll_interval_seconds": 0.02} | changes
    return PostgresDigestPullLock(
        engine_factory=lambda: engine,
        **options,
    )


@pytest.mark.asyncio
async def test_same_digest_calls_serialize_on_the_advisory_lock(lock_engine):
    digest = fresh_digest()
    acquired = asyncio.Event()
    first = lock_for(lock_engine)
    second = lock_for(lock_engine)

    async def wait_for_same_digest():
        async with second.hold(digest):
            acquired.set()

    task = None
    try:
        async with first.hold(digest):
            task = asyncio.create_task(wait_for_same_digest())
            await asyncio.sleep(0.2)
            assert not acquired.is_set()
        await asyncio.wait_for(task, timeout=5)
        assert acquired.is_set()
    finally:
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_different_digest_does_not_block(lock_engine):
    first = lock_for(lock_engine)
    second = lock_for(lock_engine)

    async with first.hold(fresh_digest()):
        async with asyncio.timeout(2):
            async with second.hold(fresh_digest()):
                pass


@pytest.mark.asyncio
async def test_lock_release_is_explicit_on_success(lock_engine):
    class RecordingConnection:
        def __init__(self, connection):
            self._connection = connection
            self.statements: list[str] = []
            self.closed = False

        async def execution_options(self, **options):
            await self._connection.execution_options(**options)
            return self

        async def execute(self, statement, parameters=None):
            self.statements.append(str(statement))
            return await self._connection.execute(statement, parameters)

        async def close(self):
            self.closed = True
            await self._connection.close()

    class RecordingEngine:
        def __init__(self, engine):
            self._engine = engine
            self.connections: list[RecordingConnection] = []

        async def connect(self):
            connection = RecordingConnection(await self._engine.connect())
            self.connections.append(connection)
            return connection

    recording_engine = RecordingEngine(lock_engine)
    lock = PostgresDigestPullLock(
        engine_factory=lambda: recording_engine,
        poll_interval_seconds=0.02,
    )

    async with lock.hold(fresh_digest()):
        pass

    connection = recording_engine.connections[0]
    assert connection.closed is True
    assert any("pg_try_advisory_lock" in statement for statement in connection.statements)
    assert any("pg_advisory_unlock" in statement for statement in connection.statements)


@pytest.mark.asyncio
async def test_connection_loss_releases_the_session_lock(lock_engine):
    digest = fresh_digest()
    captured = []

    class CapturingEngine:
        async def connect(self):
            connection = await lock_engine.connect()
            captured.append(connection)
            return connection

    lock = PostgresDigestPullLock(
        engine_factory=CapturingEngine,
        poll_interval_seconds=0.02,
    )

    async with lock.hold(digest):
        held_connection = captured[0]
        backend_pid = (await held_connection.execute(text("SELECT pg_backend_pid()"))).scalar()
        async with lock_engine.connect() as terminator:
            await terminator.execute(
                text("SELECT pg_terminate_backend(:pid)"),
                {"pid": backend_pid},
            )

    async with asyncio.timeout(5):
        async with lock.hold(digest):
            pass


@pytest.mark.asyncio
async def test_lock_wait_is_bounded(lock_engine):
    digest = fresh_digest()
    first = lock_for(lock_engine)
    second = lock_for(lock_engine, timeout_seconds=0.05, poll_interval_seconds=0.01)

    async with first.hold(digest):
        with pytest.raises(RegistryError) as failure:
            async with second.hold(digest):
                pass

    assert_registry_error(failure, REGISTRY_UNREACHABLE)


class PublishingDriver:
    """Publish the exact digest once, after a short pull."""

    def __init__(self) -> None:
        self.published = False
        self.pull_count = 0
        self.active_pulls = 0
        self.pull_started = asyncio.Event()

    async def resolve_image(self, image: str) -> dict:
        if not self.published:
            raise ImageResolutionError("artifact_missing")
        return local_image()

    async def pull_image_by_digest(self, reference: str) -> None:
        self.pull_count += 1
        self.active_pulls += 1
        assert self.active_pulls == 1
        self.pull_started.set()
        try:
            await asyncio.sleep(0.2)
            self.published = True
        finally:
            self.active_pulls -= 1


@pytest.mark.asyncio
async def test_concurrent_same_digest_pulls_serialize_and_recheck_proof(lock_engine):
    driver = PublishingDriver()

    def make_locked_service() -> RegistryArtifactService:
        return RegistryArtifactService(
            driver=driver,
            pull_policy="on_demand",
            lock_factory=lambda: lock_for(lock_engine),
        )

    first = asyncio.create_task(make_locked_service().ensure_local(verified_image()))
    second = None
    try:
        await asyncio.wait_for(driver.pull_started.wait(), timeout=5)
        second = asyncio.create_task(make_locked_service().ensure_local(verified_image()))
        first_identity, second_identity = await asyncio.gather(first, second)
    finally:
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    assert driver.pull_count == 1
    assert first_identity.registry_verified is True
    assert second_identity.registry_verified is True
    assert first_identity.local_id == second_identity.local_id == LOCAL_ID


def test_pull_policy_and_lock_timing_validation():
    from app.services.registry_artifact_service import _validate_pull_policy

    assert _validate_pull_policy("on_demand") == "on_demand"
    assert _validate_pull_policy("preload_only") == "preload_only"
    with pytest.raises(ValueError, match="pull policy"):
        _validate_pull_policy("always")
    with pytest.raises(ValueError, match="Lock timing"):
        PostgresDigestPullLock(timeout_seconds=0)
    with pytest.raises(ValueError, match="Lock timing"):
        PostgresDigestPullLock(poll_interval_seconds=0)

    service = RegistryArtifactService(driver=FakeDriver(), pull_policy="preload_only")
    assert service.pull_policy == "preload_only"


def test_canonical_reference_requires_an_exact_manifest_digest():
    from types import SimpleNamespace

    from app.services.registry_artifact_service import _canonical_reference

    parsed = _canonical_reference(verified_image())
    assert parsed.registry == "registry.example.com"
    assert parsed.repository == "team/runtime"
    assert parsed.reference == DIGEST

    with pytest.raises(RegistryError) as invalid:
        _canonical_reference(
            SimpleNamespace(verified_reference="bad reference", manifest_digest=DIGEST)
        )
    assert invalid.value.code == REGISTRY_ARTIFACT_MISMATCH

    with pytest.raises(RegistryError) as mismatch:
        _canonical_reference(
            SimpleNamespace(verified_reference=VERIFIED_REFERENCE, manifest_digest=OTHER_DIGEST)
        )
    assert mismatch.value.code == REGISTRY_ARTIFACT_MISMATCH


def test_repository_digest_proof_skips_untrusted_entries():
    from app.services.registry_artifact_service import _has_repository_digest
    from app.services.registry_client import parse_reference

    canonical = parse_reference(VERIFIED_REFERENCE)
    assert _has_repository_digest([VERIFIED_REFERENCE], canonical, DIGEST) is True
    assert _has_repository_digest("not-a-list", canonical, DIGEST) is False
    assert _has_repository_digest([None, 1, ""], canonical, DIGEST) is False
    assert _has_repository_digest(["bad reference"], canonical, DIGEST) is False
    assert _has_repository_digest([f"{REPOSITORY}@{OTHER_DIGEST}"], canonical, DIGEST) is False
    assert (
        _has_repository_digest([f"other.example.com/team/runtime@{DIGEST}"], canonical, DIGEST)
        is False
    )


def test_local_identity_conversion_rejects_invalid_metadata():
    from app.services.registry_artifact_service import (
        _identity_from_local,
        _platform_matches,
    )

    verified = verified_image()
    assert _platform_matches(local_image(), verified) is True
    assert _platform_matches({"os": None, "architecture": "amd64"}, verified) is False

    with pytest.raises(RegistryError) as invalid:
        _identity_from_local(verified, {"local_id": None, "os": "linux", "architecture": "amd64"})
    assert invalid.value.code == REGISTRY_ARTIFACT_MISMATCH
