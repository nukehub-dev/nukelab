# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for app.config validators."""

import os

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.version import __version__


class TestProductionUserAuthKeyValidation:
    def test_production_requires_existing_keys(self, tmp_path):
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        private_path = secrets_dir / "user-auth-private.pem"
        public_path = secrets_dir / "user-auth-public.pem"
        private_path.write_text("private")
        public_path.write_text("public")
        os.chmod(private_path, 0o600)

        # Should not raise.
        Settings(
            app_env="production",
            user_auth_private_key_path=str(private_path),
            user_auth_public_key_path=str(public_path),
            cors_origins="https://example.com",
            jwt_secret="a-strong-random-secret-at-least-32-characters-long",
            session_secret="another-strong-random-secret-for-tests-only",
        )

    def test_production_rejects_missing_private_key(self, tmp_path):
        private_path = tmp_path / "missing-private.pem"
        public_path = tmp_path / "public.pem"
        public_path.write_text("public")

        with pytest.raises(ValueError, match="USER_AUTH_PRIVATE_KEY_PATH"):
            Settings(
                app_env="production",
                user_auth_private_key_path=str(private_path),
                user_auth_public_key_path=str(public_path),
                cors_origins="https://example.com",
            )

    def test_production_rejects_missing_public_key(self, tmp_path):
        private_path = tmp_path / "private.pem"
        public_path = tmp_path / "missing-public.pem"
        private_path.write_text("private")

        with pytest.raises(ValueError, match="USER_AUTH_PUBLIC_KEY_PATH"):
            Settings(
                app_env="production",
                user_auth_private_key_path=str(private_path),
                user_auth_public_key_path=str(public_path),
                cors_origins="https://example.com",
            )

    def test_production_rejects_permissive_private_key(self, tmp_path):
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        private_path = secrets_dir / "user-auth-private.pem"
        public_path = secrets_dir / "user-auth-public.pem"
        private_path.write_text("private")
        public_path.write_text("public")
        os.chmod(private_path, 0o644)

        with pytest.raises(ValueError, match="permissions"):
            Settings(
                app_env="production",
                user_auth_private_key_path=str(private_path),
                user_auth_public_key_path=str(public_path),
                cors_origins="https://example.com",
            )

    def test_development_allows_missing_keys(self, tmp_path):
        # In development the config validator should not block missing key paths;
        # the key manager will auto-generate them when accessed.
        private_path = tmp_path / "missing-private.pem"
        public_path = tmp_path / "missing-public.pem"

        Settings(
            app_env="development",
            user_auth_private_key_path=str(private_path),
            user_auth_public_key_path=str(public_path),
        )


class TestApiDocsDefaults:
    """api_docs_enabled defaults to off in production, on elsewhere."""

    def _production_settings(self, tmp_path, **overrides):
        private_path = tmp_path / "user-auth-private.pem"
        public_path = tmp_path / "user-auth-public.pem"
        private_path.write_text("private")
        public_path.write_text("public")
        os.chmod(private_path, 0o600)
        return Settings(
            app_env="production",
            user_auth_private_key_path=str(private_path),
            user_auth_public_key_path=str(public_path),
            cors_origins="https://example.com",
            jwt_secret="a-strong-random-secret-at-least-32-characters-long",
            session_secret="another-strong-random-secret-for-tests-only",
            **overrides,
        )

    def test_development_defaults_to_enabled(self):
        assert Settings(app_env="development").api_docs_enabled is True

    def test_empty_string_uses_env_aware_default(self):
        """compose.yml passes an empty value when the operator leaves it unset."""
        assert Settings(app_env="development", api_docs_enabled="").api_docs_enabled is True

    def test_production_defaults_to_disabled(self, tmp_path):
        assert self._production_settings(tmp_path).api_docs_enabled is False

    def test_explicit_override_wins_in_production(self, tmp_path):
        assert self._production_settings(tmp_path, api_docs_enabled=True).api_docs_enabled is True

    def test_explicit_disable_in_development(self):
        assert Settings(app_env="development", api_docs_enabled=False).api_docs_enabled is False


class TestAppVersion:
    """APP_VERSION (injected as a Docker build arg in CI) overrides the static
    fallback from app/version.py; empty values fall back."""

    def test_default_is_static_fallback(self, monkeypatch):
        monkeypatch.delenv("APP_VERSION", raising=False)
        assert Settings().app_version == __version__

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("APP_VERSION", "9.9.9-ci")
        assert Settings().app_version == "9.9.9-ci"

    def test_empty_env_falls_back(self, monkeypatch):
        """Local Docker builds set APP_VERSION to an empty string."""
        monkeypatch.setenv("APP_VERSION", "")
        assert Settings().app_version == __version__

    def test_otel_service_version_defaults_to_app_version(self, monkeypatch):
        monkeypatch.setenv("APP_VERSION", "9.9.9-ci")
        monkeypatch.delenv("OTEL_SERVICE_VERSION", raising=False)
        assert Settings().otel_service_version == "9.9.9-ci"

    def test_otel_service_version_explicit_override(self, monkeypatch):
        monkeypatch.setenv("APP_VERSION", "9.9.9-ci")
        monkeypatch.setenv("OTEL_SERVICE_VERSION", "custom")
        assert Settings().otel_service_version == "custom"


class TestRegistrySettings:
    """Registry verification settings keep the upgrade-safe code default."""

    def _clear_registry_env(self, monkeypatch):
        for key in (
            "REGISTRY_VERIFICATION_POLICY",
            "REGISTRY_PULL_POLICY",
            "REGISTRY_ALLOWED_HOSTS",
            "REGISTRY_CREDENTIALS_FILE",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_code_defaults_preserve_existing_launch_behavior(self, monkeypatch):
        self._clear_registry_env(monkeypatch)

        settings = Settings()

        assert settings.registry_verification_policy == "off"
        assert settings.registry_pull_policy == "on_demand"
        assert settings.registry_allowed_hosts == ""
        assert settings.registry_credentials_file == ""

    def test_environment_values_are_parsed_raw(self, monkeypatch):
        monkeypatch.setenv("REGISTRY_VERIFICATION_POLICY", "require")
        monkeypatch.setenv("REGISTRY_PULL_POLICY", "preload_only")
        monkeypatch.setenv("REGISTRY_ALLOWED_HOSTS", " GHCR.IO , example.com:5000 ")
        monkeypatch.setenv("REGISTRY_CREDENTIALS_FILE", "/run/registry-credentials/config.json")

        settings = Settings()

        assert settings.registry_verification_policy == "require"
        assert settings.registry_pull_policy == "preload_only"
        # Normalization belongs to the registry service, not Settings.
        assert settings.registry_allowed_hosts == " GHCR.IO , example.com:5000 "
        assert settings.registry_credentials_file == "/run/registry-credentials/config.json"

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("REGISTRY_VERIFICATION_POLICY", "sometimes"),
            ("REGISTRY_PULL_POLICY", "always"),
        ],
    )
    def test_invalid_policy_values_are_rejected(self, monkeypatch, key, value):
        monkeypatch.setenv(key, value)

        with pytest.raises(ValidationError):
            Settings()


class TestWorkerHeartbeatSettings:
    """Recovery heartbeat timing stays positive and ordered."""

    def _clear_heartbeat_env(self, monkeypatch):
        for key in (
            "WORKER_HEARTBEAT_INTERVAL_SECONDS",
            "WORKER_HEARTBEAT_STALE_SECONDS",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_defaults(self, monkeypatch):
        self._clear_heartbeat_env(monkeypatch)

        settings = Settings()

        assert settings.worker_heartbeat_interval_seconds == 5
        assert settings.worker_heartbeat_stale_seconds == 20

    def test_environment_overrides(self, monkeypatch):
        monkeypatch.setenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "7")
        monkeypatch.setenv("WORKER_HEARTBEAT_STALE_SECONDS", "30")

        settings = Settings()

        assert settings.worker_heartbeat_interval_seconds == 7
        assert settings.worker_heartbeat_stale_seconds == 30

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("WORKER_HEARTBEAT_INTERVAL_SECONDS", "0"),
            ("WORKER_HEARTBEAT_INTERVAL_SECONDS", "-1"),
            ("WORKER_HEARTBEAT_STALE_SECONDS", "0"),
            ("WORKER_HEARTBEAT_STALE_SECONDS", "-1"),
        ],
    )
    def test_non_positive_values_are_rejected(self, monkeypatch, key, value):
        self._clear_heartbeat_env(monkeypatch)
        monkeypatch.setenv(key, value)

        with pytest.raises(ValidationError):
            Settings()

    def test_stale_threshold_must_exceed_the_interval(self):
        with pytest.raises(ValidationError, match="WORKER_HEARTBEAT_STALE_SECONDS"):
            Settings(worker_heartbeat_interval_seconds=20, worker_heartbeat_stale_seconds=20)

        with pytest.raises(ValidationError, match="WORKER_HEARTBEAT_STALE_SECONDS"):
            Settings(worker_heartbeat_interval_seconds=20, worker_heartbeat_stale_seconds=10)
