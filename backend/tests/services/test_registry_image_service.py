# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import base64
import hashlib
import json

import httpx
import pytest

from app.config import Settings
from app.services.registry_client import (
    REGISTRY_ARTIFACT_MISMATCH,
    REGISTRY_ARTIFACT_MISSING,
    REGISTRY_AUTH_FAILED,
    REGISTRY_PLATFORM_UNAVAILABLE,
    REGISTRY_REFERENCE_INVALID,
    REGISTRY_UNREACHABLE,
    Platform,
    RegistryError,
    VerifiedImage,
)
from app.services.registry_config import RegistryCredentialProvider
from app.services.registry_image_service import (
    RegistryImageService,
    RegistryResolution,
    RegistryResolverSpec,
)

DIGEST = "sha256:" + "a" * 64
REFERENCE = "ghcr.io/demo/app:1.0"
VERIFIED = VerifiedImage(
    requested_reference=REFERENCE,
    verified_reference=f"ghcr.io/demo/app@{DIGEST}",
    manifest_digest=DIGEST,
    index_digest=None,
    descriptor_media_type="application/vnd.oci.image.manifest.v1+json",
    os="linux",
    architecture="amd64",
    variant=None,
)

OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"


class _FakeResolver:
    def __init__(self, verified: VerifiedImage | None = None, error: RegistryError | None = None):
        self.verified = verified
        self.error = error
        self.calls: list[str] = []

    async def resolve(self, reference: str) -> VerifiedImage:
        self.calls.append(reference)
        if self.error is not None:
            raise self.error
        assert self.verified is not None
        return self.verified


class _RecordingFactory:
    def __init__(self, resolver: _FakeResolver):
        self.resolver = resolver
        self.specs: list[RegistryResolverSpec] = []

    def __call__(self, spec: RegistryResolverSpec) -> _FakeResolver:
        self.specs.append(spec)
        return self.resolver


def _service(**overrides) -> RegistryImageService:
    options = {"verification_policy": "off", "pull_policy": "on_demand"}
    options.update(overrides)
    return RegistryImageService(**options)


def _write_credentials(path, username: str, password: str) -> None:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    path.write_text(
        json.dumps({"auths": {"ghcr.io": {"auth": encoded}}}),
        encoding="utf-8",
    )


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _json_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _mock_registry():
    config_body = _json_bytes({"os": "linux", "architecture": "amd64"})
    config_digest = _digest(config_body)
    manifest_body = _json_bytes(
        {
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST,
            "config": {
                "mediaType": OCI_CONFIG,
                "digest": config_digest,
                "size": len(config_body),
            },
            "layers": [],
        }
    )
    manifest_digest = _digest(manifest_body)
    index_body = _json_bytes(
        {
            "schemaVersion": 2,
            "mediaType": OCI_INDEX,
            "manifests": [
                {
                    "mediaType": OCI_MANIFEST,
                    "digest": manifest_digest,
                    "size": len(manifest_body),
                    "platform": {"os": "linux", "architecture": "amd64"},
                }
            ],
        }
    )
    index_digest = _digest(index_body)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v2/demo/app/manifests/1.0":
            return httpx.Response(
                200,
                headers={"Content-Type": OCI_INDEX, "Docker-Content-Digest": index_digest},
                content=index_body,
            )
        if path == f"/v2/demo/app/manifests/{manifest_digest}":
            return httpx.Response(
                200,
                headers={
                    "Content-Type": OCI_MANIFEST,
                    "Docker-Content-Digest": manifest_digest,
                },
                content=manifest_body,
            )
        if path == f"/v2/demo/app/blobs/{config_digest}":
            return httpx.Response(200, content=config_body)
        return httpx.Response(404)

    return handler, manifest_digest, index_digest


class TestPolicies:
    async def test_off_skips_without_registry_io(self):
        resolver = _FakeResolver(VERIFIED)
        factory = _RecordingFactory(resolver)
        service = _service(verification_policy="off", resolver_factory=factory)

        result = await service.resolve(REFERENCE)

        assert result == RegistryResolution(
            policy="off",
            state="skipped",
            verified=None,
            fallback_reason=None,
            pull_requested=False,
        )
        assert factory.specs == []
        assert resolver.calls == []

    async def test_off_records_a_pull_request_without_pulling(self):
        factory = _RecordingFactory(_FakeResolver(VERIFIED))
        service = _service(verification_policy="off", resolver_factory=factory)

        result = await service.resolve(REFERENCE, pull=True)

        assert result.state == "skipped"
        assert result.pull_requested is True
        assert factory.specs == []

    async def test_prefer_resolves_and_records_the_verified_identity(self):
        resolver = _FakeResolver(VERIFIED)
        factory = _RecordingFactory(resolver)
        service = _service(
            verification_policy="prefer",
            allowed_hosts=frozenset({"ghcr.io"}),
            platform=Platform("linux", "arm64"),
            resolver_factory=factory,
        )

        result = await service.resolve(REFERENCE)

        assert result.policy == "prefer"
        assert result.state == "verified"
        assert result.verified == VERIFIED
        assert result.fallback_reason is None
        assert result.pull_requested is False
        assert resolver.calls == [REFERENCE]
        assert factory.specs[0].registry == "ghcr.io"
        assert factory.specs[0].allowed_hosts == frozenset({"ghcr.io"})
        assert factory.specs[0].platform == Platform("linux", "arm64")
        assert factory.specs[0].credentials is None

    async def test_default_resolver_input_uses_the_local_platform(self):
        factory = _RecordingFactory(_FakeResolver(VERIFIED))
        service = _service(verification_policy="prefer", resolver_factory=factory)

        await service.resolve(REFERENCE)

        assert isinstance(factory.specs[0].platform, Platform)

    @pytest.mark.parametrize(
        "code",
        [
            REGISTRY_REFERENCE_INVALID,
            REGISTRY_UNREACHABLE,
            REGISTRY_AUTH_FAILED,
            REGISTRY_PLATFORM_UNAVAILABLE,
            REGISTRY_ARTIFACT_MISMATCH,
            REGISTRY_ARTIFACT_MISSING,
        ],
    )
    async def test_prefer_returns_a_stable_fallback_code_without_retrying(self, code):
        resolver = _FakeResolver(error=RegistryError(code, "registry failure"))
        service = _service(
            verification_policy="prefer",
            resolver_factory=_RecordingFactory(resolver),
        )

        result = await service.resolve(REFERENCE)

        assert result.policy == "prefer"
        assert result.state == "fallback"
        assert result.verified is None
        assert result.fallback_reason == code
        assert len(resolver.calls) == 1

    async def test_require_propagates_the_registry_error(self):
        resolver = _FakeResolver(error=RegistryError(REGISTRY_AUTH_FAILED, "auth failed"))
        service = _service(
            verification_policy="prefer",
            resolver_factory=_RecordingFactory(resolver),
        )

        with pytest.raises(RegistryError) as exc_info:
            await service.resolve(REFERENCE, policy="require")

        assert exc_info.value.code == REGISTRY_AUTH_FAILED
        assert len(resolver.calls) == 1

    async def test_explicit_require_verification_works_when_launch_policy_is_off(self):
        resolver = _FakeResolver(VERIFIED)
        factory = _RecordingFactory(resolver)
        service = _service(verification_policy="off", resolver_factory=factory)

        result = await service.resolve(REFERENCE, policy="require")

        assert result.policy == "require"
        assert result.state == "verified"
        assert result.verified == VERIFIED
        assert resolver.calls == [REFERENCE]
        assert len(factory.specs) == 1

    async def test_prefer_records_a_requested_pull_without_performing_it(self):
        service = _service(
            verification_policy="prefer",
            resolver_factory=_RecordingFactory(_FakeResolver(VERIFIED)),
        )

        result = await service.resolve(REFERENCE, pull=True)

        assert result.state == "verified"
        assert result.pull_requested is True


class TestConfiguration:
    async def test_invalid_explicit_policy_is_rejected(self):
        service = _service(verification_policy="prefer")

        with pytest.raises(ValueError, match="verification policy"):
            await service.resolve(REFERENCE, policy="sometimes")

    def test_invalid_constructor_policies_are_rejected(self):
        with pytest.raises(ValueError, match="verification policy"):
            RegistryImageService(verification_policy="sometimes")

        with pytest.raises(ValueError, match="pull policy"):
            RegistryImageService(pull_policy="sometimes")

    def test_malformed_allowed_hosts_fail_when_building_from_settings(self):
        configured = Settings(
            registry_verification_policy="prefer",
            registry_allowed_hosts="https://ghcr.io",
            registry_credentials_file="",
        )

        with pytest.raises(ValueError, match="REGISTRY_ALLOWED_HOSTS"):
            RegistryImageService.from_settings(configured)

    async def test_from_settings_builds_the_default_resolver(self):
        handler, manifest_digest, index_digest = _mock_registry()
        configured = Settings(
            registry_verification_policy="prefer",
            registry_pull_policy="on_demand",
            registry_allowed_hosts="ghcr.io",
            registry_credentials_file="",
        )
        service = RegistryImageService.from_settings(
            configured,
            transport=httpx.MockTransport(handler),
            platform=Platform("linux", "amd64"),
        )

        result = await service.resolve(REFERENCE)

        assert result.state == "verified"
        assert result.verified is not None
        assert result.verified.manifest_digest == manifest_digest
        assert result.verified.index_digest == index_digest
        assert result.verified.verified_reference == f"ghcr.io/demo/app@{manifest_digest}"
        assert result.verified.os == "linux"
        assert result.verified.architecture == "amd64"


class TestCredentialSelection:
    async def test_credentials_are_scoped_to_the_referenced_registry(self, tmp_path):
        path = tmp_path / "config.json"
        _write_credentials(path, "alice", "super-secret-password")
        provider = RegistryCredentialProvider(str(path))
        factory = _RecordingFactory(_FakeResolver(VERIFIED))
        service = _service(
            verification_policy="prefer",
            credentials=provider,
            resolver_factory=factory,
        )

        result = await service.resolve(REFERENCE)
        await service.resolve("registry.example.com/demo/app:1.0")

        assert factory.specs[0].credentials is not None
        assert factory.specs[0].credentials.username == "alice"
        assert factory.specs[1].credentials is None
        assert "super-secret-password" not in repr(result)
        assert "super-secret-password" not in repr(factory.specs[0])
