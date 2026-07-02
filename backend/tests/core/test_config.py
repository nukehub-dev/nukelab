# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for app.config validators."""

import os

import pytest

from app.config import Settings


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
