# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for app.config validators."""

import os

import pytest

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
