# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import base64
import hashlib
import ipaddress
import json

import httpx
import pytest

from app.services import registry_client
from app.services.registry_client import (
    REGISTRY_ARTIFACT_MISMATCH,
    REGISTRY_ARTIFACT_MISSING,
    REGISTRY_AUTH_FAILED,
    REGISTRY_PLATFORM_UNAVAILABLE,
    REGISTRY_REFERENCE_INVALID,
    REGISTRY_UNREACHABLE,
    Platform,
    RegistryCredentials,
    RegistryError,
    RegistryResolver,
    parse_reference,
)

PUBLIC_HOST = "93.184.216.34"
REALM = f"https://{PUBLIC_HOST}/token"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
DOCKER_INDEX = "application/vnd.docker.distribution.manifest.list.v2+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"

DIGEST_A = "sha256:" + "a" * 64


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _json_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _response(
    body: bytes,
    media_type: str,
    *,
    digest_header: bool | str = True,
) -> httpx.Response:
    headers = {"Content-Type": media_type}
    if digest_header is True:
        headers["Docker-Content-Digest"] = _digest(body)
    elif isinstance(digest_header, str):
        headers["Docker-Content-Digest"] = digest_header
    return httpx.Response(200, headers=headers, content=body)


def _image_manifest(
    *,
    os_name: str = "linux",
    architecture: str = "amd64",
    variant: str | None = None,
    media_type: str = OCI_MANIFEST,
) -> tuple[bytes, str, bytes, str, dict]:
    config = {"os": os_name, "architecture": architecture}
    if variant is not None:
        config["variant"] = variant
    config_body = _json_bytes(config)
    config_digest = _digest(config_body)
    manifest = {
        "schemaVersion": 2,
        "mediaType": media_type,
        "config": {
            "mediaType": OCI_CONFIG,
            "digest": config_digest,
            "size": len(config_body),
        },
        "layers": [],
    }
    manifest_body = _json_bytes(manifest)
    manifest_digest = _digest(manifest_body)
    platform = {"os": os_name, "architecture": architecture}
    if variant is not None:
        platform["variant"] = variant
    descriptor = {
        "mediaType": media_type,
        "digest": manifest_digest,
        "size": len(manifest_body),
        "platform": platform,
    }
    return config_body, config_digest, manifest_body, manifest_digest, descriptor


def _index_body(descriptors: list[dict], media_type: str = OCI_INDEX) -> bytes:
    return _json_bytes(
        {
            "schemaVersion": 2,
            "mediaType": media_type,
            "manifests": descriptors,
        }
    )


def _resolver(
    handler,
    *,
    platform: Platform | None = Platform("linux", "amd64"),
    allowed_hosts: frozenset[str] | None = None,
    credentials: RegistryCredentials | None = None,
) -> RegistryResolver:
    return RegistryResolver(
        transport=httpx.MockTransport(handler),
        credentials=credentials,
        allowed_hosts=allowed_hosts,
        platform=platform,
    )


def _assert_manifest_accept(request: httpx.Request) -> None:
    accept = request.headers["accept"]
    for media_type in (OCI_INDEX, DOCKER_INDEX, OCI_MANIFEST, DOCKER_MANIFEST):
        assert media_type in accept


def _standard_index_handler(
    requests: list[httpx.Request],
    index_body: bytes,
    manifest_body: bytes,
    manifest_digest: str,
    *,
    tag: str = "1.0",
    index_media_type: str = OCI_INDEX,
    manifest_media_type: str = OCI_MANIFEST,
):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == f"/v2/demo/app/manifests/{tag}":
            _assert_manifest_accept(request)
            return _response(index_body, index_media_type)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            _assert_manifest_accept(request)
            return _response(manifest_body, manifest_media_type)
        return httpx.Response(404)

    return handler


# ---------------------------------------------------------------------------
# Reference parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "alpine",
        "docker.io/alpine",
        "docker.io/library/alpine",
        "index.docker.io/library/alpine",
        "registry-1.docker.io/library/alpine",
    ],
)
def test_docker_hub_aliases_normalize_consistently(value: str) -> None:
    reference = parse_reference(value)
    assert reference.registry == "registry-1.docker.io"
    assert reference.repository == "library/alpine"
    assert reference.reference == "latest"
    assert reference.is_digest is False


def test_parse_tag_registry_and_defaults() -> None:
    reference = parse_reference("registry.example.com:5000/team/app:1.2.3")
    assert reference.registry == "registry.example.com:5000"
    assert reference.repository == "team/app"
    assert reference.reference == "1.2.3"
    assert reference.is_digest is False

    defaulted = parse_reference("registry.example.com/team/app")
    assert defaulted.reference == "latest"


def test_parse_digest_and_tag_plus_digest() -> None:
    reference = parse_reference(f"registry.example.com/team/app@{DIGEST_A}")
    assert reference.reference == DIGEST_A
    assert reference.is_digest is True

    tagged = parse_reference(f"registry.example.com/team/app:1.0@{DIGEST_A}")
    assert tagged.repository == "team/app"
    assert tagged.reference == DIGEST_A
    assert tagged.is_digest is True


def test_parse_ipv6_registry_literal() -> None:
    reference = parse_reference("[::1]:5000/team/app:1.0")
    assert reference.registry == "[::1]:5000"
    assert reference.repository == "team/app"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "https://registry.example.com/repo:tag",
        "http://registry.example.com/repo:tag",
        "user:secret@registry.example.com/repo:tag",
        "//registry.example.com/repo",
        "registry\\example.com/repo",
        "a@b@c",
        "registry.example.com/repo:",
        "registry.example.com/repo@",
        "registry.example.com/repo:tag@",
        "registry.example.com/repo@sha256:" + "a" * 63,
        "registry.example.com/repo@sha256:" + "a" * 64 + "x",
        "registry.example.com/repo@sha512:" + "a" * 128,
        "registry.example.com/repo name",
        "registry.example.com/repo:bad tag@sha256:" + "a" * 64,
        "registry.example.com/repo:" + "a" * 129,
        "registry.example.com/Repo",
        "registry.example.com//repo",
        "registry.example.com/repo//sub",
        "registry.example.com/repo\n",
        "registry.example.com/repo ",
        "registry.example.com/repo\t",
        "registry.example.com/repo\x00",
        "registry.example.com/repo\x7f",
        "localhost:5000",
        "registry.example.com:5000",
        "registry.example.com:0/repo",
        "registry.example.com:65536/repo",
        "registry.example.com:abc/repo",
        "registry..example.com/repo",
        "registry_example.com/repo",
        "-registry.example.com/repo",
        "[::ffff:127.0.0.1]/repo",
        "[::1/repo",
        "[not-ipv6]/repo",
        "a" * 501,
    ],
)
def test_parse_rejects_invalid_references(value: str) -> None:
    with pytest.raises(RegistryError) as error:
        parse_reference(value)
    assert error.value.code == REGISTRY_REFERENCE_INVALID
    assert "secret" not in str(error.value)


def test_parse_rejects_oversized_repository() -> None:
    with pytest.raises(RegistryError) as error:
        parse_reference("registry.example.com/" + "a" * 256)
    assert error.value.code == REGISTRY_REFERENCE_INVALID


def test_parse_rejects_references_that_cannot_form_a_verified_identity() -> None:
    host = ".".join(("a" * 60, "b" * 60, "c" * 60, "d" * 20))
    repository = "e" * 240
    value = f"{host}/{repository}"
    assert len(value) <= 500
    assert len(f"{host}/{repository}@sha256:") + 64 > 500

    with pytest.raises(RegistryError) as error:
        parse_reference(value)
    assert error.value.code == REGISTRY_REFERENCE_INVALID


def test_registry_error_rejects_unknown_codes() -> None:
    with pytest.raises(ValueError):
        RegistryError("unexpected_code", "failure")


def test_platform_normalization_and_validation() -> None:
    platform = Platform("Linux", "AMD64", "V8")
    assert platform.os == "linux"
    assert platform.architecture == "amd64"
    assert platform.variant == "v8"

    with pytest.raises(ValueError):
        Platform("", "amd64")
    with pytest.raises(ValueError):
        Platform(123, "amd64")
    for variant in (123, "bad space", "x" * 33):
        with pytest.raises(ValueError):
            Platform("linux", "amd64", variant)


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("", "password"),
        ("user", ""),
        ("user", "bad\npassword"),
        (123, "password"),
        ("user", 123),
        ("u" * 1025, "password"),
        ("user", "p" * 8193),
    ],
)
def test_registry_credentials_validation(username, password) -> None:
    with pytest.raises(ValueError):
        RegistryCredentials(username, password)


def test_credentials_repr_hides_password() -> None:
    credentials = RegistryCredentials("user", "top-secret")
    assert "top-secret" not in repr(credentials)


def test_verified_image_rejects_inconsistent_identity() -> None:
    digest = "sha256:" + "a" * 64
    base = {
        "requested_reference": "registry.example.com/demo/app:1.0",
        "verified_reference": f"registry.example.com/demo/app@{digest}",
        "manifest_digest": digest,
        "index_digest": None,
        "descriptor_media_type": OCI_MANIFEST,
        "os": "linux",
        "architecture": "amd64",
        "variant": None,
    }

    # The base identity is valid.
    registry_client.VerifiedImage(**base)

    for overrides in (
        {"manifest_digest": "invalid"},
        {"index_digest": "invalid"},
        {"verified_reference": "registry.example.com/demo/app@sha256:" + "b" * 64},
        {"requested_reference": ""},
        {"descriptor_media_type": ""},
        {"os": ""},
    ):
        with pytest.raises(ValueError):
            registry_client.VerifiedImage(**{**base, **overrides})


def test_resolver_rejects_invalid_allowed_hosts() -> None:
    with pytest.raises(ValueError):
        RegistryResolver(allowed_hosts=frozenset({"https://registry.example.com"}))
    with pytest.raises(TypeError):
        RegistryResolver(allowed_hosts="registry.example.com")
    with pytest.raises(TypeError):
        RegistryResolver(allowed_hosts=frozenset({123}))


# ---------------------------------------------------------------------------
# Public tag resolution
# ---------------------------------------------------------------------------


async def test_public_tag_resolves_index_to_platform_manifest() -> None:
    config_body, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    arm_config, _, arm_manifest, arm_digest, arm_descriptor = _image_manifest(architecture="arm64")
    del config_body, arm_config
    index_body = _index_body([arm_descriptor, descriptor])
    index_digest = _digest(index_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _standard_index_handler(
            requests,
            index_body,
            manifest_body,
            manifest_digest,
        )
    )
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.requested_reference == f"{PUBLIC_HOST}/demo/app:1.0"
    assert verified.verified_reference == f"{PUBLIC_HOST}/demo/app@{manifest_digest}"
    assert verified.manifest_digest == manifest_digest
    assert verified.index_digest == index_digest
    assert verified.descriptor_media_type == OCI_MANIFEST
    assert (verified.os, verified.architecture, verified.variant) == (
        "linux",
        "amd64",
        None,
    )
    assert "1.0" not in verified.verified_reference
    assert [request.url.path for request in requests] == [
        "/v2/demo/app/manifests/1.0",
        f"/v2/demo/app/manifests/{manifest_digest}",
    ]
    assert arm_digest not in [request.url.path for request in requests]
    assert all("/blobs/" not in request.url.path for request in requests)
    del arm_manifest


async def test_requested_reference_preserves_the_caller_input() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/latest":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, allowed_hosts=frozenset({"127.0.0.1"}))
    verified = await resolver.resolve("127.0.0.1/demo/app")

    assert verified.requested_reference == "127.0.0.1/demo/app"
    assert verified.verified_reference == f"127.0.0.1/demo/app@{manifest_digest}"
    assert requests[0].url.path == "/v2/demo/app/manifests/latest"


async def test_docker_manifest_list_media_types_are_supported() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest(media_type=DOCKER_MANIFEST)
    descriptor["mediaType"] = DOCKER_MANIFEST
    index_body = _index_body([descriptor], media_type=DOCKER_INDEX)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _standard_index_handler(
            requests,
            index_body,
            manifest_body,
            manifest_digest,
            index_media_type=DOCKER_INDEX,
            manifest_media_type=DOCKER_MANIFEST,
        )
    )
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")
    assert verified.descriptor_media_type == DOCKER_MANIFEST
    assert verified.manifest_digest == manifest_digest


async def test_manifest_media_type_falls_back_to_content_type() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    manifest_document = json.loads(manifest_body)
    manifest_document.pop("mediaType")
    manifest_body = _json_bytes(manifest_document)
    manifest_digest = _digest(manifest_body)
    descriptor["digest"] = manifest_digest
    descriptor["size"] = len(manifest_body)

    index_document = json.loads(_index_body([descriptor]))
    index_document.pop("mediaType")
    index_body = _json_bytes(index_document)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler)
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.manifest_digest == manifest_digest
    assert verified.descriptor_media_type == OCI_MANIFEST


async def test_unknown_unknown_attestation_descriptor_is_ignored() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    attestation_descriptor = {
        "mediaType": OCI_MANIFEST,
        "digest": "sha256:" + "b" * 64,
        "size": 100,
        "platform": {"os": "unknown", "architecture": "unknown"},
    }
    index_body = _index_body([attestation_descriptor, descriptor])
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _standard_index_handler(
            requests,
            index_body,
            manifest_body,
            manifest_digest,
        )
    )
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.manifest_digest == manifest_digest
    requested_paths = [request.url.path for request in requests]
    assert f"/v2/demo/app/manifests/{attestation_descriptor['digest']}" not in requested_paths
    assert f"/v2/demo/app/manifests/{manifest_digest}" in requested_paths


# ---------------------------------------------------------------------------
# Digest verification
# ---------------------------------------------------------------------------


async def test_requested_digest_mismatch_is_artifact_mismatch() -> None:
    _, _, manifest_body, manifest_digest, _ = _image_manifest()
    wrong_digest = "sha256:" + "0" * 64
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(manifest_body, OCI_MANIFEST, digest_header=manifest_digest)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{wrong_digest}")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    assert len(requests) == 1


async def test_header_digest_mismatch_is_artifact_mismatch() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(index_body, OCI_INDEX, digest_header="sha256:" + "f" * 64)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    assert len(requests) == 1


async def test_child_body_digest_mismatch_is_artifact_mismatch() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    other_manifest = _image_manifest(architecture="arm64")[2]
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(other_manifest, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    assert len(requests) == 2


async def test_child_header_digest_mismatch_is_artifact_mismatch() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(
                manifest_body,
                OCI_MANIFEST,
                digest_header="sha256:" + "e" * 64,
            )
        return httpx.Response(404)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    assert len(requests) == 2


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
async def test_invalid_manifest_json_is_rejected(body: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": OCI_INDEX}, content=body)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH


async def test_child_response_must_be_an_image_manifest() -> None:
    _, _, manifest_body, manifest_digest, _ = _image_manifest()
    child_index_body = _index_body(
        [
            {
                "mediaType": OCI_MANIFEST,
                "digest": manifest_digest,
                "size": len(manifest_body),
                "platform": {"os": "linux", "architecture": "amd64"},
            }
        ]
    )
    child_index_digest = _digest(child_index_body)
    descriptor = {
        "mediaType": OCI_MANIFEST,
        "digest": child_index_digest,
        "size": len(child_index_body),
        "platform": {"os": "linux", "architecture": "amd64"},
    }
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{child_index_digest}":
            return _response(child_index_body, OCI_INDEX)
        return httpx.Response(404)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    assert len(requests) == 2


async def test_descriptor_media_type_must_match_child_manifest() -> None:
    _, _, docker_manifest, docker_digest, _ = _image_manifest(media_type=DOCKER_MANIFEST)
    descriptor = {
        "mediaType": OCI_MANIFEST,
        "digest": docker_digest,
        "size": len(docker_manifest),
        "platform": {"os": "linux", "architecture": "amd64"},
    }
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{docker_digest}":
            return _response(docker_manifest, DOCKER_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH


async def test_index_with_invalid_descriptor_digest_is_rejected() -> None:
    index_body = _index_body(
        [
            {
                "mediaType": OCI_MANIFEST,
                "digest": "sha256:short",
                "size": 1,
                "platform": {"os": "linux", "architecture": "amd64"},
            }
        ]
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(index_body, OCI_INDEX)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    assert len(requests) == 1


async def test_index_with_non_runnable_descriptor_media_type_is_ignored() -> None:
    index_body = _index_body(
        [
            {
                "mediaType": "application/vnd.example.artifact.v1+json",
                "digest": DIGEST_A,
                "size": 1,
                "platform": {"os": "linux", "architecture": "amd64"},
            }
        ]
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(index_body, OCI_INDEX)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_PLATFORM_UNAVAILABLE
    assert len(requests) == 1


async def test_index_without_manifests_is_rejected() -> None:
    index_body = _json_bytes({"schemaVersion": 2, "mediaType": OCI_INDEX})

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(index_body, OCI_INDEX)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH


async def test_malformed_docker_content_digest_header_is_rejected() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX, digest_header="not-a-digest")
        return httpx.Response(404)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    del manifest_body, manifest_digest


# ---------------------------------------------------------------------------
# Bearer authentication
# ---------------------------------------------------------------------------


async def test_bearer_token_flow_and_token_caching() -> None:
    token = "issued-token-value"
    credentials = RegistryCredentials("user", "secret")
    expected_basic = "Basic " + base64.b64encode(b"user:secret").decode()
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    token_requests = 0
    authorized_requests = 0
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests, authorized_requests
        requests.append(request)
        if request.url.path == "/token":
            token_requests += 1
            assert request.url.params["service"] == "registry.test"
            assert request.url.params["scope"] == "repository:demo/app:pull"
            assert request.headers["authorization"] == expected_basic
            return httpx.Response(200, json={"token": token, "expires_in": 300})
        if request.headers.get("authorization") != f"Bearer {token}":
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        f'Bearer realm="{REALM}",service="registry.test",'
                        'scope="repository:demo/app:pull"'
                    )
                },
            )
        authorized_requests += 1
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, credentials=credentials)
    first = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")
    second = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert first == second
    assert token_requests == 1
    assert authorized_requests == 4
    assert requests[1].headers["authorization"] == expected_basic
    assert all(
        f"Bearer {token}" == request.headers.get("authorization") for request in requests[2:]
    )


async def test_private_registry_without_credentials_fails_auth() -> None:
    token_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/token":
            token_requests += 1
            assert "authorization" not in request.headers
            return httpx.Response(401)
        return httpx.Response(
            401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="{REALM}",service="registry.test",'
                    'scope="repository:demo/app:pull"'
                )
            },
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_AUTH_FAILED
    assert token_requests == 1


async def test_unsupported_auth_challenge_fails_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="registry"'})

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_AUTH_FAILED


async def test_bearer_challenge_without_realm_fails_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            headers={"WWW-Authenticate": 'Bearer service="registry.test"'},
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_AUTH_FAILED


async def test_http_token_realm_fails_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="http://{PUBLIC_HOST}/token",service="registry.test"'
                )
            },
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_AUTH_FAILED


async def test_token_challenge_without_scope_requests_default_pull_scope() -> None:
    token = "issued-token"
    seen_scope: list[str] = []
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            seen_scope.append(request.url.params["scope"])
            return httpx.Response(200, json={"token": token})
        if request.headers.get("authorization") != f"Bearer {token}":
            return httpx.Response(
                401,
                headers={"WWW-Authenticate": (f'bEaReR realm="{REALM}",service="registry.test"')},
            )
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler)
    await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert seen_scope == ["repository:demo/app:pull"]


@pytest.mark.parametrize(
    "token_response",
    [
        httpx.Response(200, json={}),
        httpx.Response(200, json={"token": ""}),
        httpx.Response(200, json={"token": 123}),
        httpx.Response(200, json={"token": "bad token"}),
        httpx.Response(200, json={"token": "x" * 8193}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(403),
        httpx.Response(404),
    ],
)
async def test_invalid_token_responses_fail_auth(token_response: httpx.Response) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return token_response
        return httpx.Response(
            401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="{REALM}",service="registry.test",'
                    'scope="repository:demo/app:pull"'
                )
            },
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_AUTH_FAILED


async def test_token_service_error_maps_to_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(503)
        return httpx.Response(
            401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="{REALM}",service="registry.test",'
                    'scope="repository:demo/app:pull"'
                )
            },
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE


def _basic_header(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


async def test_basic_challenge_with_correct_credentials() -> None:
    credentials = RegistryCredentials("user", "secret")
    expected_basic = _basic_header("user", "secret")
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("authorization") != expected_basic:
            return httpx.Response(
                401,
                headers={"WWW-Authenticate": 'bAsIc realm="Registry Realm"'},
            )
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, credentials=credentials)
    first = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")
    second = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert first == second
    assert first.manifest_digest == manifest_digest
    assert requests[0].headers.get("authorization") is None
    assert all(request.headers.get("authorization") == expected_basic for request in requests[1:])
    assert len(requests) == 5


async def test_basic_challenge_on_child_request_is_handled() -> None:
    credentials = RegistryCredentials("user", "secret")
    expected_basic = _basic_header("user", "secret")
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            if request.headers.get("authorization") != expected_basic:
                return httpx.Response(
                    401,
                    headers={"WWW-Authenticate": 'Basic realm="Registry Realm"'},
                )
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, credentials=credentials)
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.manifest_digest == manifest_digest
    assert requests[0].headers.get("authorization") is None
    assert requests[1].headers.get("authorization") is None
    assert requests[2].headers["authorization"] == expected_basic
    assert len(requests) == 3


async def test_basic_challenge_without_credentials_fails_auth() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            401,
            headers={"WWW-Authenticate": 'Basic realm="registry"'},
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_AUTH_FAILED
    assert len(requests) == 1
    assert requests[0].headers.get("authorization") is None


async def test_basic_challenge_with_wrong_credentials_fails_auth() -> None:
    password = "wrong-secret"
    expected_basic = _basic_header("user", password)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            401,
            headers={"WWW-Authenticate": 'Basic realm="registry"'},
        )

    resolver = _resolver(handler, credentials=RegistryCredentials("user", password))
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_AUTH_FAILED
    assert len(requests) == 2
    assert requests[0].headers.get("authorization") is None
    assert requests[1].headers["authorization"] == expected_basic
    assert password not in str(error.value)
    assert password not in repr(error.value)
    assert expected_basic not in str(error.value)
    assert expected_basic not in repr(error.value)

    # A marked Basic host sends credentials immediately and does not retry
    # forever when the registry rejects them again.
    with pytest.raises(RegistryError) as second_error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert second_error.value.code == REGISTRY_AUTH_FAILED
    assert len(requests) == 3
    assert requests[2].headers["authorization"] == expected_basic
    assert password not in str(second_error.value)
    assert expected_basic not in str(second_error.value)


async def test_token_is_never_exposed_in_auth_errors() -> None:
    token = "secret-token-value"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": token})
        return httpx.Response(
            401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="{REALM}",service="registry.test",'
                    'scope="repository:demo/app:pull"'
                )
            },
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_AUTH_FAILED
    assert token not in str(error.value)
    assert token not in repr(error.value)


async def test_token_cache_respects_bounded_ttl(monkeypatch) -> None:
    token = "cached-token"
    clock = [0.0]
    monkeypatch.setattr(registry_client.time, "monotonic", lambda: clock[0])
    token_requests = 0
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/token":
            token_requests += 1
            return httpx.Response(200, json={"token": token, "expires_in": 300})
        if request.headers.get("authorization") != f"Bearer {token}":
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": (
                        f'Bearer realm="{REALM}",service="registry.test",'
                        'scope="repository:demo/app:pull"'
                    )
                },
            )
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler)
    await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")
    clock[0] = 100.0
    await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")
    clock[0] = 301.0
    await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert token_requests == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 300.0),
        ("60", 60.0),
        (30.5, 30.0),
        (0, 300.0),
        (-1, 300.0),
        (True, 300.0),
        (9999, 300.0),
        ("not-a-number", 300.0),
    ],
)
def test_token_ttl_is_bounded(value: object, expected: float) -> None:
    assert registry_client._token_ttl(value) == expected


def test_local_platform_is_established() -> None:
    platform = registry_client._local_platform()
    assert platform.os
    assert platform.architecture


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        ("x86_64", Platform("linux", "amd64", None)),
        ("aarch64", Platform("linux", "arm64", "v8")),
        ("arm64", Platform("linux", "arm64", "v8")),
        ("armv7l", Platform("linux", "arm", "v7")),
        ("armv6l", Platform("linux", "arm", "v6")),
    ],
)
def test_local_platform_reports_expected_arm_variants(
    monkeypatch,
    machine: str,
    expected: Platform,
) -> None:
    monkeypatch.setattr(registry_client.host_platform, "system", lambda: "Linux")
    monkeypatch.setattr(registry_client.host_platform, "machine", lambda: machine)

    assert registry_client._local_platform() == expected


def test_local_platform_failure_is_platform_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(registry_client.host_platform, "system", lambda: "")
    monkeypatch.setattr(registry_client.host_platform, "machine", lambda: "")

    with pytest.raises(RegistryError) as error:
        registry_client._local_platform()

    assert error.value.code == REGISTRY_PLATFORM_UNAVAILABLE


async def test_resolve_addresses_handles_ip_literals() -> None:
    addresses = await registry_client._resolve_addresses("127.0.0.1", None)
    assert any(str(address) == "127.0.0.1" for address in addresses)


async def test_check_url_host_requires_https_and_no_credentials() -> None:
    resolver = _resolver(lambda request: httpx.Response(500))

    for url in (
        "http://93.184.216.34/v2/",
        "https://user:pass@93.184.216.34/v2/",
        "https://[invalid/v2/",
    ):
        with pytest.raises(RegistryError) as error:
            await resolver._check_url_host(url)
        assert error.value.code == REGISTRY_UNREACHABLE


async def test_hostname_resolving_to_public_address_is_allowed(monkeypatch) -> None:
    async def fake_resolve(host: str, port: int | None):
        assert host == "registry.example.test"
        return [ipaddress.ip_address(PUBLIC_HOST)]

    monkeypatch.setattr(registry_client, "_resolve_addresses", fake_resolve)
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _standard_index_handler(
            requests,
            index_body,
            manifest_body,
            manifest_digest,
        )
    )
    verified = await resolver.resolve("registry.example.test/demo/app:1.0")

    assert verified.verified_reference == (f"registry.example.test/demo/app@{manifest_digest}")


async def test_hostname_resolving_to_private_address_is_denied(monkeypatch) -> None:
    async def fake_resolve(host: str, port: int | None):
        return [ipaddress.ip_address("10.0.0.1")]

    monkeypatch.setattr(registry_client, "_resolve_addresses", fake_resolve)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve("registry.example.test/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE
    assert requests == []


# ---------------------------------------------------------------------------
# Platform selection
# ---------------------------------------------------------------------------


async def test_platform_unavailable_when_no_descriptor_matches() -> None:
    _, _, arm_manifest, arm_digest, arm_descriptor = _image_manifest(architecture="arm64")
    index_body = _index_body([arm_descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(index_body, OCI_INDEX)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_PLATFORM_UNAVAILABLE
    assert all(f"/manifests/{arm_digest}" not in request.url.path for request in requests)
    del arm_manifest


async def test_multiple_exact_platform_matches_fail_closed() -> None:
    _, _, _, digest_a, descriptor_a = _image_manifest()
    _, _, manifest_b, _, descriptor_b = _image_manifest()
    manifest_b_document = json.loads(manifest_b)
    manifest_b_document["layers"] = [
        {
            "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
            "digest": DIGEST_A,
            "size": 1,
        }
    ]
    manifest_b = _json_bytes(manifest_b_document)
    digest_b = _digest(manifest_b)
    descriptor_b["digest"] = digest_b
    descriptor_b["size"] = len(manifest_b)
    index_body = _index_body([descriptor_a, descriptor_b])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(index_body, OCI_INDEX)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    assert len(requests) == 1
    assert digest_a != digest_b


async def test_variant_is_part_of_platform_selection() -> None:
    _, _, v6_manifest, v6_digest, v6_descriptor = _image_manifest(architecture="arm", variant="v6")
    _, _, v7_manifest, v7_digest, v7_descriptor = _image_manifest(architecture="arm", variant="v7")
    index_body = _index_body([v6_descriptor, v7_descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{v7_digest}":
            return _response(v7_manifest, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, platform=Platform("linux", "arm", "v7"))
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.variant == "v7"
    assert verified.manifest_digest == v7_digest
    requested_paths = [request.url.path for request in requests]
    assert f"/v2/demo/app/manifests/{v7_digest}" in requested_paths
    assert f"/v2/demo/app/manifests/{v6_digest}" not in requested_paths
    del v6_manifest


async def test_arm64_v8_exact_variant_is_selected() -> None:
    _, _, v8_manifest, v8_digest, v8_descriptor = _image_manifest(
        architecture="arm64", variant="v8"
    )
    _, _, generic_manifest, generic_digest, generic_descriptor = _image_manifest(
        architecture="arm64"
    )
    index_body = _index_body([generic_descriptor, v8_descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{v8_digest}":
            return _response(v8_manifest, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, platform=Platform("linux", "arm64", "v8"))
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.variant == "v8"
    assert verified.manifest_digest == v8_digest
    requested_paths = [request.url.path for request in requests]
    assert f"/v2/demo/app/manifests/{v8_digest}" in requested_paths
    assert f"/v2/demo/app/manifests/{generic_digest}" not in requested_paths
    del generic_manifest


async def test_arm64_v8_falls_back_to_descriptor_without_variant() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest(architecture="arm64")
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, platform=Platform("linux", "arm64", "v8"))
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.variant is None
    assert verified.manifest_digest == manifest_digest
    assert f"/v2/demo/app/manifests/{manifest_digest}" in [request.url.path for request in requests]


async def test_variant_none_does_not_select_v8_manifest() -> None:
    _, _, v8_manifest, v8_digest, v8_descriptor = _image_manifest(
        architecture="arm64", variant="v8"
    )
    index_body = _index_body([v8_descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(index_body, OCI_INDEX)

    resolver = _resolver(handler, platform=Platform("linux", "arm64"))
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_PLATFORM_UNAVAILABLE
    assert f"/v2/demo/app/manifests/{v8_digest}" not in [request.url.path for request in requests]
    del v8_manifest


async def test_variant_none_selects_no_variant_descriptor() -> None:
    _, _, generic_manifest, generic_digest, generic_descriptor = _image_manifest(
        architecture="arm64"
    )
    _, _, v8_manifest, v8_digest, v8_descriptor = _image_manifest(
        architecture="arm64", variant="v8"
    )
    index_body = _index_body([v8_descriptor, generic_descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{generic_digest}":
            return _response(generic_manifest, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, platform=Platform("linux", "arm64"))
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.variant is None
    assert verified.manifest_digest == generic_digest
    requested_paths = [request.url.path for request in requests]
    assert f"/v2/demo/app/manifests/{generic_digest}" in requested_paths
    assert f"/v2/demo/app/manifests/{v8_digest}" not in requested_paths
    del v8_manifest


async def test_multiple_fallback_candidates_fail_closed() -> None:
    _, _, _, digest_a, descriptor_a = _image_manifest(architecture="arm64")
    _, _, manifest_b, _, descriptor_b = _image_manifest(architecture="arm64")
    manifest_b_document = json.loads(manifest_b)
    manifest_b_document["layers"] = [
        {
            "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
            "digest": DIGEST_A,
            "size": 1,
        }
    ]
    manifest_b = _json_bytes(manifest_b_document)
    digest_b = _digest(manifest_b)
    descriptor_b["digest"] = digest_b
    descriptor_b["size"] = len(manifest_b)
    index_body = _index_body([descriptor_a, descriptor_b])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(index_body, OCI_INDEX)

    resolver = _resolver(handler, platform=Platform("linux", "arm64", "v8"))
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    assert len(requests) == 1
    assert digest_a != digest_b


# ---------------------------------------------------------------------------
# Direct manifests and config platform discovery
# ---------------------------------------------------------------------------


def _manifest_with_config(config_body: bytes) -> tuple[bytes, str, str]:
    config_digest = _digest(config_body)
    manifest = {
        "schemaVersion": 2,
        "mediaType": OCI_MANIFEST,
        "config": {
            "mediaType": OCI_CONFIG,
            "digest": config_digest,
            "size": len(config_body),
        },
        "layers": [],
    }
    manifest_body = _json_bytes(manifest)
    return manifest_body, _digest(manifest_body), config_digest


def _direct_manifest_routes(
    requests: list[httpx.Request],
    manifest_body: bytes,
    manifest_digest: str,
    config_body: bytes,
    config_digest: str,
    *,
    tag: str | None = None,
    config_digest_header: bool | str = True,
) -> callable:
    reference = tag or manifest_digest
    manifest_path = f"/v2/demo/app/manifests/{reference}"
    config_path = f"/v2/demo/app/blobs/{config_digest}"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == manifest_path:
            _assert_manifest_accept(request)
            return _response(manifest_body, OCI_MANIFEST)
        if request.url.path == config_path:
            assert request.headers["accept"] == "application/octet-stream"
            return _response(
                config_body,
                "application/octet-stream",
                digest_header=config_digest_header,
            )
        return httpx.Response(404)

    return handler


async def test_direct_digest_manifest_reads_config_platform() -> None:
    config = {"os": "linux", "architecture": "arm64", "variant": "v8"}
    config_body = _json_bytes(config)
    config_digest = _digest(config_body)
    manifest = {
        "schemaVersion": 2,
        "mediaType": OCI_MANIFEST,
        "config": {
            "mediaType": OCI_CONFIG,
            "digest": config_digest,
            "size": len(config_body),
        },
        "layers": [],
    }
    manifest_body = _json_bytes(manifest)
    manifest_digest = _digest(manifest_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            config_body,
            config_digest,
        ),
        platform=None,
    )
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{manifest_digest}")

    assert verified.requested_reference == f"{PUBLIC_HOST}/demo/app@{manifest_digest}"
    assert verified.verified_reference == f"{PUBLIC_HOST}/demo/app@{manifest_digest}"
    assert verified.manifest_digest == manifest_digest
    assert verified.index_digest is None
    assert verified.descriptor_media_type == OCI_MANIFEST
    assert (verified.os, verified.architecture, verified.variant) == (
        "linux",
        "arm64",
        "v8",
    )
    assert [request.url.path for request in requests] == [
        f"/v2/demo/app/manifests/{manifest_digest}",
        f"/v2/demo/app/blobs/{config_digest}",
    ]


async def test_direct_tag_manifest_reads_config_platform() -> None:
    _, config_digest, manifest_body, manifest_digest, _ = _image_manifest(architecture="arm64")
    config_body = _json_bytes({"os": "linux", "architecture": "arm64"})
    requests: list[httpx.Request] = []

    # Rebuild the manifest so the config blob served by the fake registry matches.
    manifest = json.loads(manifest_body)
    manifest["config"]["digest"] = config_digest
    manifest["config"]["size"] = len(config_body)
    manifest_body = _json_bytes(manifest)
    manifest_digest = _digest(manifest_body)

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            config_body,
            config_digest,
            tag="1.0",
        ),
        platform=None,
    )
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.requested_reference == f"{PUBLIC_HOST}/demo/app:1.0"
    assert verified.verified_reference == f"{PUBLIC_HOST}/demo/app@{manifest_digest}"
    assert verified.index_digest is None
    assert (verified.os, verified.architecture) == ("linux", "arm64")


async def test_direct_manifest_with_matching_platform_uses_config_identity() -> None:
    config_body = _json_bytes({"os": "linux", "architecture": "arm64", "variant": "v8"})
    manifest_body, manifest_digest, config_digest = _manifest_with_config(config_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            config_body,
            config_digest,
        ),
        platform=Platform("linux", "arm64"),
    )
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{manifest_digest}")

    assert (verified.os, verified.architecture, verified.variant) == (
        "linux",
        "arm64",
        "v8",
    )
    assert [request.url.path for request in requests] == [
        f"/v2/demo/app/manifests/{manifest_digest}",
        f"/v2/demo/app/blobs/{config_digest}",
    ]


async def test_direct_manifest_with_mismatched_platform_fails() -> None:
    config_body = _json_bytes({"os": "linux", "architecture": "arm64"})
    manifest_body, manifest_digest, config_digest = _manifest_with_config(config_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            config_body,
            config_digest,
        ),
        platform=Platform("linux", "amd64"),
    )
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{manifest_digest}")

    assert error.value.code == REGISTRY_PLATFORM_UNAVAILABLE
    assert f"/v2/demo/app/blobs/{config_digest}" in [request.url.path for request in requests]


async def test_direct_manifest_with_mismatched_variant_fails() -> None:
    config_body = _json_bytes({"os": "linux", "architecture": "arm64", "variant": "v8"})
    manifest_body, manifest_digest, config_digest = _manifest_with_config(config_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            config_body,
            config_digest,
        ),
        platform=Platform("linux", "arm64", "v7"),
    )
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{manifest_digest}")

    assert error.value.code == REGISTRY_PLATFORM_UNAVAILABLE
    assert f"/v2/demo/app/blobs/{config_digest}" in [request.url.path for request in requests]


async def test_direct_manifest_with_supplied_platform_still_verifies_config_digest() -> None:
    config_body = _json_bytes({"os": "linux", "architecture": "amd64"})
    wrong_config = _json_bytes({"os": "linux", "architecture": "arm64"})
    manifest_body, manifest_digest, config_digest = _manifest_with_config(config_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            wrong_config,
            config_digest,
        ),
        platform=Platform("linux", "amd64"),
    )
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{manifest_digest}")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH
    assert f"/v2/demo/app/blobs/{config_digest}" in [request.url.path for request in requests]


async def test_direct_manifest_with_supplied_variant_accepts_null_config_variant() -> None:
    config_body = _json_bytes({"os": "linux", "architecture": "arm64"})
    manifest_body, manifest_digest, config_digest = _manifest_with_config(config_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            config_body,
            config_digest,
        ),
        platform=Platform("linux", "arm64", "v8"),
    )
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{manifest_digest}")

    assert (verified.os, verified.architecture, verified.variant) == (
        "linux",
        "arm64",
        None,
    )


async def test_direct_manifest_with_missing_config_platform_fails_with_supplied_platform() -> None:
    config_body = _json_bytes({"os": "linux"})
    manifest_body, manifest_digest, config_digest = _manifest_with_config(config_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            config_body,
            config_digest,
        ),
        platform=Platform("linux", "arm64"),
    )
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{manifest_digest}")

    assert error.value.code == REGISTRY_PLATFORM_UNAVAILABLE
    assert f"/v2/demo/app/blobs/{config_digest}" in [request.url.path for request in requests]


async def test_direct_manifest_without_config_platform_fails_closed() -> None:
    config_body = _json_bytes({"os": "linux"})
    config_digest = _digest(config_body)
    manifest = {
        "schemaVersion": 2,
        "mediaType": OCI_MANIFEST,
        "config": {
            "mediaType": OCI_CONFIG,
            "digest": config_digest,
            "size": len(config_body),
        },
        "layers": [],
    }
    manifest_body = _json_bytes(manifest)
    manifest_digest = _digest(manifest_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            config_body,
            config_digest,
        ),
        platform=None,
    )
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{manifest_digest}")

    assert error.value.code == REGISTRY_PLATFORM_UNAVAILABLE


async def test_direct_manifest_config_digest_mismatch_fails_closed() -> None:
    config_body = _json_bytes({"os": "linux", "architecture": "amd64"})
    config_digest = _digest(config_body)
    wrong_config = _json_bytes({"os": "linux", "architecture": "arm64"})
    manifest = {
        "schemaVersion": 2,
        "mediaType": OCI_MANIFEST,
        "config": {
            "mediaType": OCI_CONFIG,
            "digest": config_digest,
            "size": len(config_body),
        },
        "layers": [],
    }
    manifest_body = _json_bytes(manifest)
    manifest_digest = _digest(manifest_body)
    requests: list[httpx.Request] = []

    resolver = _resolver(
        _direct_manifest_routes(
            requests,
            manifest_body,
            manifest_digest,
            wrong_config,
            config_digest,
        ),
        platform=None,
    )
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app@{manifest_digest}")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH


# ---------------------------------------------------------------------------
# Redirects
# ---------------------------------------------------------------------------


async def test_cross_host_redirect_is_rejected() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "https://198.51.100.5/v2/demo/app/manifests/1.0"},
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE
    assert len(requests) == 1


async def test_scheme_downgrade_redirect_is_rejected() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": f"http://{PUBLIC_HOST}/v2/demo/app/manifests/1.0"},
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE
    assert len(requests) == 1


async def test_redirect_with_credentials_is_rejected() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": (f"https://user:pass@{PUBLIC_HOST}/v2/demo/app/manifests/1.0")},
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE
    assert len(requests) == 1


async def test_redirect_to_another_port_is_rejected() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": (f"https://{PUBLIC_HOST}:8443/v2/demo/app/manifests/1.0")},
        )

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE
    assert len(requests) == 1


async def test_same_host_redirect_is_followed() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return httpx.Response(
                307,
                headers={"Location": "/v2/demo/app/manifests/1.0-final"},
            )
        if request.url.path == "/v2/demo/app/manifests/1.0-final":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler)
    verified = await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert verified.manifest_digest == manifest_digest
    assert [request.url.path for request in requests][:2] == [
        "/v2/demo/app/manifests/1.0",
        "/v2/demo/app/manifests/1.0-final",
    ]


# ---------------------------------------------------------------------------
# Bounds, transport failures, and missing artifacts
# ---------------------------------------------------------------------------


async def test_manifest_response_size_is_capped() -> None:
    oversized = b"x" * (registry_client._MAX_MANIFEST_BYTES + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": OCI_INDEX}, content=oversized)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH


async def test_streamed_manifest_response_size_is_capped() -> None:
    async def chunks():
        yield b"x" * registry_client._MAX_MANIFEST_BYTES
        yield b"x"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": OCI_INDEX}, content=chunks())

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("connection refused"),
        httpx.ConnectTimeout("connection timed out"),
        httpx.ReadTimeout("read timed out"),
    ],
)
async def test_transport_failures_map_to_registry_unreachable(failure: Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE


async def test_server_error_maps_to_registry_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE


async def test_rate_limit_maps_to_registry_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE


async def test_missing_manifest_maps_to_artifact_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISSING


async def test_unsupported_manifest_content_type_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"{}")

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_ARTIFACT_MISMATCH


# ---------------------------------------------------------------------------
# SSRF and host policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "168.63.129.16",
        "100.100.100.200",
        "[::1]",
        "[fd00:ec2::254]",
    ],
)
async def test_private_and_metadata_hosts_are_denied(host: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{host}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE
    assert requests == []


async def test_empty_allowed_hosts_denies_every_host() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    resolver = _resolver(handler, allowed_hosts=frozenset())
    with pytest.raises(RegistryError) as error:
        await resolver.resolve(f"{PUBLIC_HOST}/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE
    assert requests == []


async def test_allowed_hosts_permits_an_explicit_loopback_registry() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, allowed_hosts=frozenset({"127.0.0.1"}))
    verified = await resolver.resolve("127.0.0.1/demo/app:1.0")

    assert verified.verified_reference == f"127.0.0.1/demo/app@{manifest_digest}"
    assert len(requests) == 2


async def test_allowed_hosts_must_match_the_configured_port() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    resolver = _resolver(handler, allowed_hosts=frozenset({"127.0.0.1"}))
    with pytest.raises(RegistryError) as error:
        await resolver.resolve("127.0.0.1:5000/demo/app:1.0")

    assert error.value.code == REGISTRY_UNREACHABLE
    assert requests == []


async def test_allowed_hosts_accepts_an_explicit_port() -> None:
    _, _, manifest_body, manifest_digest, descriptor = _image_manifest()
    index_body = _index_body([descriptor])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/demo/app/manifests/1.0":
            return _response(index_body, OCI_INDEX)
        if request.url.path == f"/v2/demo/app/manifests/{manifest_digest}":
            return _response(manifest_body, OCI_MANIFEST)
        return httpx.Response(404)

    resolver = _resolver(handler, allowed_hosts=frozenset({"127.0.0.1:5000"}))
    verified = await resolver.resolve("127.0.0.1:5000/demo/app:1.0")

    assert verified.verified_reference == f"127.0.0.1:5000/demo/app@{manifest_digest}"


async def test_invalid_reference_does_not_reach_the_transport() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    resolver = _resolver(handler)
    with pytest.raises(RegistryError) as error:
        await resolver.resolve("https://user:secret@registry.example.com/repo:tag")

    assert error.value.code == REGISTRY_REFERENCE_INVALID
    assert "secret" not in str(error.value)
    assert requests == []
