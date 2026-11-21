# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import base64
import json
import os

import pytest

from app.services.registry_config import (
    CREDENTIAL_HELPERS_UNSUPPORTED,
    CREDENTIALS_FILE_MALFORMED,
    RegistryCredentialProvider,
    parse_allowed_hosts,
)


def _auth(username: str, password: str) -> str:
    return base64.b64encode(f"{username}:{password}".encode()).decode()


def _write(path, document) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


class TestAllowedHosts:
    def test_empty_values_mean_no_allowlist(self):
        assert parse_allowed_hosts("") is None
        assert parse_allowed_hosts("   ") is None
        assert parse_allowed_hosts(" , ") is None

    def test_entries_are_trimmed_lowercased_and_deduplicated(self):
        assert parse_allowed_hosts(" GHCR.IO , Registry.Example.com:5000 ,ghcr.io ") == frozenset(
            {"ghcr.io", "registry.example.com:5000"}
        )

    def test_default_https_port_is_removed(self):
        assert parse_allowed_hosts("ghcr.io:443") == frozenset({"ghcr.io"})

    def test_docker_hub_aliases_normalize_to_one_host(self):
        assert parse_allowed_hosts("docker.io,index.docker.io,registry-1.docker.io") == frozenset(
            {"registry-1.docker.io"}
        )

    @pytest.mark.parametrize(
        "value",
        [
            "https://ghcr.io",
            "ghcr.io/v1/",
            "ghcr.io:99999",
            "bad host",
            "-bad.example.com",
        ],
    )
    def test_malformed_entries_raise_a_clear_error(self, value):
        with pytest.raises(ValueError, match="REGISTRY_ALLOWED_HOSTS"):
            parse_allowed_hosts(value)


class TestCredentialProvider:
    def test_empty_path_is_anonymous(self):
        provider = RegistryCredentialProvider("")

        assert provider.credentials_for("ghcr.io") is None
        assert provider.status().file_configured is False
        assert provider.status().limitations == ()

    def test_missing_file_is_anonymous(self, tmp_path):
        provider = RegistryCredentialProvider(str(tmp_path / "missing.json"))

        assert provider.credentials_for("ghcr.io") is None
        status = provider.status()
        assert status.file_configured is True
        assert status.file_present is False
        assert status.limitations == ()

    def test_empty_file_is_anonymous(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("", encoding="utf-8")
        provider = RegistryCredentialProvider(str(path))

        assert provider.credentials_for("ghcr.io") is None
        status = provider.status()
        assert status.file_present is True
        assert status.credential_count == 0
        assert status.limitations == ()

    def test_auth_map_with_base64_credentials(self, tmp_path):
        path = tmp_path / "config.json"
        _write(
            path,
            {
                "auths": {
                    "ghcr.io": {"auth": _auth("alice", "correct-horse")},
                    "registry.example.com": {"auth": _auth("bob", "battery-staple")},
                }
            },
        )
        provider = RegistryCredentialProvider(str(path))

        ghcr = provider.credentials_for("ghcr.io")
        assert ghcr is not None
        assert ghcr.username == "alice"
        assert ghcr.password == "correct-horse"

        example = provider.credentials_for("registry.example.com")
        assert example is not None
        assert example.username == "bob"

        status = provider.status()
        assert status.credential_count == 2
        assert status.limitations == ()

    def test_credentials_do_not_cross_registries(self, tmp_path):
        path = tmp_path / "config.json"
        _write(path, {"auths": {"ghcr.io": {"auth": _auth("alice", "secret")}}})
        provider = RegistryCredentialProvider(str(path))

        assert provider.credentials_for("registry.example.com") is None
        assert provider.credentials_for("docker.io") is None

    def test_username_and_password_fields(self, tmp_path):
        path = tmp_path / "config.json"
        _write(
            path,
            {
                "auths": {
                    "registry.example.com:5000": {
                        "username": "carol",
                        "password": "hunter2",
                    }
                }
            },
        )
        provider = RegistryCredentialProvider(str(path))

        credentials = provider.credentials_for("registry.example.com:5000")
        assert credentials is not None
        assert credentials.username == "carol"
        assert credentials.password == "hunter2"

    def test_base64_without_padding_is_accepted(self, tmp_path):
        path = tmp_path / "config.json"
        value = _auth("dave", "pass").rstrip("=")
        _write(path, {"auths": {"ghcr.io": {"auth": value}}})
        provider = RegistryCredentialProvider(str(path))

        credentials = provider.credentials_for("ghcr.io")
        assert credentials is not None
        assert credentials.username == "dave"
        assert credentials.password == "pass"

    @pytest.mark.parametrize(
        "key",
        [
            "https://index.docker.io/v1/",
            "docker.io",
            "index.docker.io",
            "registry-1.docker.io",
            "https://registry-1.docker.io/v2/",
        ],
    )
    def test_docker_hub_alias_keys_normalize(self, tmp_path, key):
        path = tmp_path / "config.json"
        _write(path, {"auths": {key: {"auth": _auth("hub-user", "hub-secret")}}})
        provider = RegistryCredentialProvider(str(path))

        credentials = provider.credentials_for("registry-1.docker.io")
        assert credentials is not None
        assert credentials.username == "hub-user"
        assert credentials.password == "hub-secret"

    def test_host_keys_are_lowercased_and_443_is_removed(self, tmp_path):
        path = tmp_path / "config.json"
        _write(
            path,
            {"auths": {"HTTPS://GHCR.IO:443/v1/": {"username": "eve", "password": "secret"}}},
        )
        provider = RegistryCredentialProvider(str(path))

        credentials = provider.credentials_for("ghcr.io")
        assert credentials is not None
        assert credentials.username == "eve"

    def test_mtime_change_is_reloaded_inside_the_cache_window(self, tmp_path):
        path = tmp_path / "config.json"
        _write(path, {"auths": {"ghcr.io": {"username": "alice", "password": "first"}}})
        provider = RegistryCredentialProvider(str(path), clock=lambda: 1000.0)
        assert provider.credentials_for("ghcr.io").password == "first"

        replacement = tmp_path / "config.next"
        _write(replacement, {"auths": {"ghcr.io": {"username": "bob", "password": "second"}}})
        os.replace(replacement, path)
        current_mtime = path.stat().st_mtime_ns
        os.utime(path, ns=(current_mtime + 1_000_000_000, current_mtime + 1_000_000_000))

        assert provider.credentials_for("ghcr.io").password == "second"

    def test_cache_holds_for_60_seconds_without_reloading(self, tmp_path):
        path = tmp_path / "config.json"
        _write(path, {"auths": {"ghcr.io": {"username": "alice", "password": "first"}}})
        original = path.stat()
        now = [1000.0]
        provider = RegistryCredentialProvider(str(path), clock=lambda: now[0])
        assert provider.credentials_for("ghcr.io").password == "first"

        # Same inode, same size, same mtime: only the cache can explain the
        # value staying stable after the file content changes.
        _write(path, {"auths": {"ghcr.io": {"username": "bobby", "password": "other"}}})
        os.utime(path, ns=(original.st_mtime_ns, original.st_mtime_ns))
        now[0] = 1030.0
        assert provider.credentials_for("ghcr.io").password == "first"

        # The 60-second bound forces a re-read even without a signature change.
        now[0] = 1061.0
        assert provider.credentials_for("ghcr.io").password == "other"

    def test_corrupted_json_is_anonymous_with_a_limitation(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{not valid json", encoding="utf-8")
        provider = RegistryCredentialProvider(str(path))

        assert provider.credentials_for("ghcr.io") is None
        assert provider.status().limitations == (CREDENTIALS_FILE_MALFORMED,)

    def test_corrupted_base64_skips_only_that_entry(self, tmp_path):
        path = tmp_path / "config.json"
        _write(
            path,
            {
                "auths": {
                    "ghcr.io": {"auth": "!!!not-base64!!!"},
                    "registry.example.com": {"auth": _auth("alice", "valid-secret")},
                }
            },
        )
        provider = RegistryCredentialProvider(str(path))

        assert provider.credentials_for("ghcr.io") is None
        credentials = provider.credentials_for("registry.example.com")
        assert credentials is not None
        assert credentials.username == "alice"
        assert CREDENTIALS_FILE_MALFORMED in provider.status().limitations

    def test_non_dict_auths_is_malformed(self, tmp_path):
        path = tmp_path / "config.json"
        _write(path, {"auths": ["ghcr.io"]})
        provider = RegistryCredentialProvider(str(path))

        assert provider.credentials_for("ghcr.io") is None
        assert provider.status().limitations == (CREDENTIALS_FILE_MALFORMED,)

    def test_credential_helpers_are_ignored_but_inline_auths_still_work(self, tmp_path):
        path = tmp_path / "config.json"
        _write(
            path,
            {
                "credsStore": "desktop",
                "credHelpers": {"ghcr.io": "gcloud"},
                "auths": {"ghcr.io": {"auth": _auth("alice", "inline-secret")}},
            },
        )
        provider = RegistryCredentialProvider(str(path))

        credentials = provider.credentials_for("ghcr.io")
        assert credentials is not None
        assert credentials.username == "alice"
        assert provider.status().limitations == (CREDENTIAL_HELPERS_UNSUPPORTED,)

    def test_secrets_are_not_exposed_in_reprs_or_status(self, tmp_path):
        path = tmp_path / "config.json"
        password = "super-secret-password-value"
        _write(path, {"auths": {"ghcr.io": {"auth": _auth("alice", password)}}})
        provider = RegistryCredentialProvider(str(path))

        credentials = provider.credentials_for("ghcr.io")
        assert credentials is not None
        assert password not in repr(credentials)
        assert password not in repr(provider)
        assert password not in repr(provider.status())
        assert password not in str(provider.status().limitations)
