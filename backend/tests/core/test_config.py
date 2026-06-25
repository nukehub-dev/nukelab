"""Tests for configuration validation."""

import pytest
from pydantic import ValidationError

from app.config import Settings


class TestProductionSecretValidation:
    """Production environment secret validation tests."""

    def test_production_with_default_jwt_secret_raises(self):
        """Starting in production with default JWT_SECRET must fail."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(app_env="production", jwt_secret="change-me")
        assert "JWT_SECRET" in str(exc_info.value)

    def test_production_with_default_session_secret_raises(self):
        """Starting in production with default SESSION_SECRET must fail."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(app_env="production", session_secret="change-me")
        assert "SESSION_SECRET" in str(exc_info.value)

    def test_production_with_strong_secrets_succeeds(self):
        """Production with strong secrets should initialize fine."""
        settings = Settings(
            app_env="production",
            jwt_secret="a-strong-production-jwt-secret-min-32-characters",
            session_secret="another-strong-production-session-secret-here",
        )
        assert settings.app_env == "production"

    def test_development_with_default_secrets_succeeds(self):
        """Development mode should allow default secrets for convenience."""
        settings = Settings(app_env="development", jwt_secret="change-me")
        assert settings.jwt_secret == "change-me"

    def test_dev_jwt_secret_also_rejected_in_production(self):
        """The compose.yml default JWT secret must also be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                jwt_secret="dev-jwt-secret-change-in-production-min-32-chars",
            )
        assert "JWT_SECRET" in str(exc_info.value)

    def test_dev_session_secret_also_rejected_in_production(self):
        """The compose.yml default session secret must also be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                session_secret="dev-session-secret-change-in-production",
            )
        assert "SESSION_SECRET" in str(exc_info.value)


class TestCorsValidation:
    """CORS configuration validation tests."""

    def test_production_with_wildcard_cors_origin_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                jwt_secret="a-strong-production-jwt-secret-min-32-characters",
                session_secret="another-strong-production-session-secret-here",
                cors_origins="*",
            )
        assert "CORS_ORIGINS" in str(exc_info.value)

    def test_production_with_empty_cors_origin_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                jwt_secret="a-strong-production-jwt-secret-min-32-characters",
                session_secret="another-strong-production-session-secret-here",
                cors_origins="",
            )
        assert "CORS_ORIGINS" in str(exc_info.value)

    def test_production_with_explicit_origins_succeeds(self):
        settings = Settings(
            app_env="production",
            jwt_secret="a-strong-production-jwt-secret-min-32-characters",
            session_secret="another-strong-production-session-secret-here",
            cors_origins="https://app.example.com,https://admin.example.com",
        )
        assert settings.app_env == "production"

    def test_production_with_invalid_origin_url_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                app_env="production",
                jwt_secret="a-strong-production-jwt-secret-min-32-characters",
                session_secret="another-strong-production-session-secret-here",
                cors_origins="not-a-valid-url",
            )
        assert "CORS origin" in str(exc_info.value)

    def test_development_with_wildcard_cors_origin_succeeds(self):
        settings = Settings(app_env="development", cors_origins="*")
        assert settings.cors_origins == "*"


class TestPgBouncerSettings:
    """PgBouncer auto-detection and URL derivation."""

    def test_pgbouncer_disabled_by_default(self):
        settings = Settings()
        assert settings.pgbouncer_enabled is False
        assert settings.database_pgbouncer_url == ""

    def test_pgbouncer_enabled_derives_default_url(self):
        settings = Settings(
            pgbouncer_enabled=True,
            database_url="postgresql+asyncpg://nukelab:secret@postgres:5432/nukelab",
        )
        assert settings.database_pgbouncer_url == (
            "postgresql+asyncpg://nukelab:secret@pgbouncer:6432/nukelab"
        )

    def test_pgbouncer_url_can_be_overridden(self):
        explicit = "postgresql+asyncpg://user:pass@pgbouncer:6432/db"
        settings = Settings(pgbouncer_enabled=True, database_pgbouncer_url=explicit)
        assert settings.database_pgbouncer_url == explicit


class TestDatabasePoolSettings:
    """Database connection pool configuration defaults."""

    def test_pool_settings_exist_and_have_correct_types(self):
        """Pool settings must exist on the settings object with expected types."""
        from app.config import settings

        assert isinstance(settings.database_pool_size, int)
        assert isinstance(settings.database_pool_max_overflow, int)
        assert isinstance(settings.database_pool_timeout, int)
        assert isinstance(settings.database_pool_recycle, int)
        assert isinstance(settings.database_pool_pre_ping, bool)
        assert isinstance(settings.database_query_timeout_seconds, int)
        assert settings.database_pool_recycle > 0
        assert settings.database_query_timeout_seconds > 0

    def test_pool_settings_are_customizable(self):
        settings = Settings(
            database_pool_size=5,
            database_pool_max_overflow=2,
            database_pool_timeout=10,
            database_pool_recycle=1800,
            database_pool_pre_ping=False,
            database_query_timeout_seconds=60,
        )
        assert settings.database_pool_size == 5
        assert settings.database_pool_max_overflow == 2
        assert settings.database_pool_timeout == 10
        assert settings.database_pool_recycle == 1800
        assert settings.database_pool_pre_ping is False
        assert settings.database_query_timeout_seconds == 60
