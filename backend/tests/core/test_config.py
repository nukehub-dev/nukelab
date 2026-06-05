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
