# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

import os
from typing import Any
from urllib.parse import urlparse, urlunparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "NukeLab"
    app_env: str = "development"
    app_debug: bool = True
    app_url: str = "http://localhost:8000"
    public_url: str = "http://localhost:8080"
    frontend_url: str = ""  # Defaults to public_url if not set
    app_timezone: str = "UTC"

    maintenance_mode: bool = False
    maintenance_message: str = "System under maintenance"

    # Legacy shared secret: now used only by app.core.token_encryption for
    # encrypting OAuth refresh tokens. User access tokens are signed with
    # asymmetric EdDSA keys (see user_auth_* below).
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7

    session_secret: str = "change-me"
    session_max_age: int = 86400
    session_secure: bool = False
    session_httponly: bool = True
    session_samesite: str = "lax"

    csrf_protection_enabled: bool = True

    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"
    cors_allow_credentials: bool = True
    cors_max_age: int = 600  # seconds to cache preflight responses

    # Request size limits (bytes)
    max_request_body_size: int = 10 * 1024 * 1024  # 10 MB default
    max_upload_size: int = 100 * 1024 * 1024  # 100 MB for file uploads

    # -------------------------------------------------------------------------
    # Rate Limiting — Two-Layer Architecture
    #   Layer 1 (Traefik): DDoS protection only — very high per-IP thresholds
    #   Layer 2 (FastAPI + Redis): Per-user throttling by JWT identity
    # -------------------------------------------------------------------------
    rate_limit_enabled: bool = True

    # Request metrics middleware writes every request to the DB for observability.
    # Disable during load tests to avoid DB write pressure skewing results.
    request_metrics_enabled: bool = True

    # Where to store request metrics: "db", "prometheus", or "both".
    # "prometheus" removes DB write pressure; "both" keeps backward compatibility.
    request_metrics_store: str = "both"

    # Prometheus metrics export (used by /api/metrics endpoint)
    prometheus_enabled: bool = False
    prometheus_multiproc_dir: str | None = None

    # Per-user tier limits (requests per minute, per user ID from JWT)
    rate_limit_guest_rpm: int = 30
    rate_limit_user_rpm: int = 120
    rate_limit_support_rpm: int = 300
    rate_limit_moderator_rpm: int = 300
    rate_limit_admin_rpm: int = 600
    rate_limit_super_admin_rpm: int = 3000

    # Auth endpoint limits (IP-based via slowapi — for unauthenticated routes)
    rate_limit_auth_login_rpm: int = 10
    rate_limit_auth_register_rpm: int = 5
    rate_limit_auth_refresh_rpm: int = 10

    # Strict endpoint limits (per-user, half of general tier)
    rate_limit_strict_multiplier: float = 0.5

    # WebSocket rate limits
    rate_limit_websocket_cpm: int = 30  # Connections per minute
    rate_limit_websocket_msg_rpm: int = 120  # Messages per minute per connection

    # Redis window configuration (seconds)
    rate_limit_window_seconds: int = 60
    rate_limit_bucket_ttl_multiplier: int = 2

    auth_mode: str = "local"  # local | oauth | both
    local_auth_bcrypt_rounds: int = 12

    dev_mode: bool = True
    dev_admin_user: str = "admin"
    dev_admin_password: str = "admin123"

    oauth_provider_name: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_discovery_url: str = ""
    oauth_authorize_url: str = ""
    oauth_token_url: str = ""
    oauth_userdata_url: str = ""
    oauth_logout_url: str = ""
    oauth_profile_url: str = ""
    oauth_callback_url: str = ""
    oauth_scope: str = "openid profile email"
    oauth_username_claim: str = "preferred_username"
    oauth_email_claim: str = "email"
    oauth_name_claim: str = "name"
    oauth_picture_claim: str = "picture"
    oauth_pkce_enabled: bool = True

    # Database connection components
    database_user: str = "nukelab"
    database_password: str = "nukelab123"
    database_name: str = "nukelab"
    database_host: str = "postgres"
    database_port: int = 5432
    database_url: str = ""  # Optional override; derived from components if empty

    pgbouncer_enabled: bool = False
    database_pgbouncer_url: str = ""  # Optional override; default derived from database_url
    database_pool_size: int = 10
    database_pool_max_overflow: int = 10
    database_pool_timeout: int = 30
    database_pool_recycle: int = 3600  # Recycle connections after 1 hour (seconds)
    database_pool_pre_ping: bool = True  # Validate connections before checkout
    database_query_timeout_seconds: int = 30  # asyncpg command_timeout (seconds)
    database_echo: bool = False

    # When false, skip SQLAlchemy Base.metadata.create_all() on startup.
    # Recommended for production: run Alembic migrations (./nukelabctl db-migrate)
    # instead of relying on auto-create.
    auto_create_tables: bool = True

    # Observability — Query Performance Monitoring
    observability_slow_query_threshold_ms: int = 100
    observability_pg_stat_statements_enabled: bool = True

    redis_url: str = "redis://redis:6379/0"
    redis_password: str = ""
    redis_db: int = 0

    docker_socket: str = "/var/run/docker.sock"
    docker_network: str = "nukelab-network"
    docker_registry: str = ""
    docker_pull_policy: str = "if-not-present"
    volume_storage_path: str = ""

    # Container runtime hardening (defaults to enabled unless dev_mode is True)
    container_hardening_enabled: bool | None = None
    container_user: str = "nukelab"
    container_uid: int = 65532
    container_gid: int = 65532
    container_drop_all_capabilities: bool = True
    container_readonly_rootfs: bool = True
    container_no_new_privileges: bool = True
    container_readonly_tmpfs_paths: list[str] = [
        "/tmp",  # nosec: B108  # intentional container tmpfs mount, not host temp
        "/var/tmp",  # nosec: B108
        "/var/run",  # nosec: B108
        "/var/log/nginx",  # nosec: B108
        "/var/cache/nginx",  # nosec: B108
    ]

    log_level: str = "INFO"
    log_format: str = "json"
    log_file: str = "logs/nukelab.log"
    log_max_bytes: int = 10485760
    log_backup_count: int = 5

    credits_enabled: bool = True
    credits_daily_allowance: int = 500
    credits_max_balance: int = 5000
    credits_rollover: bool = False

    upload_dir: str = "/data/uploads"
    max_avatar_size_mb: int = 2

    server_idle_timeout: int = 3600
    server_max_runtime: int = 86400
    server_auto_stop_on_depletion: bool = True
    server_warn_before_stop: int = 600
    server_auto_restart_enabled: bool = True
    server_auto_restart_max_attempts: int = 3
    server_auto_restart_window: int = 300  # seconds

    # Container readiness: how long to wait for a spawned/started container's
    # /health endpoint (and the Traefik route) before marking the server as running.
    container_readiness_timeout: int = 60  # seconds
    container_readiness_interval: float = 1.0  # seconds between probes

    registration_enabled: bool = True
    max_servers_per_user: int = 10

    security_headers_enabled: bool = True

    # Error Tracking
    sentry_dsn: str = ""
    sentry_release: str = ""

    # OpenTelemetry Distributed Tracing
    otel_traces_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    otel_exporter_otlp_protocol: str = "grpc"  # grpc | http
    otel_service_name: str = "nukelab-backend"
    otel_service_version: str = "2.0.0"
    otel_log_correlation: bool = True
    otel_sampler_ratio: float = 1.0

    # Volume Quota Enforcement
    volume_quota_check_interval_minutes: int = 5  # How often to check running server volumes

    # XFS Project Quotas — kernel-enforced real-time volume limits (optional)
    xfs_quota_enabled: bool = False
    xfs_project_id_start: int = 10000  # Starting project ID to avoid system conflicts
    xfs_projects_file: str = "/data/xfs/projects.nukelab"

    # SMTP Email Configuration
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    smtp_verify_certs: bool = True
    smtp_from: str = "noreply@nukelab.local"
    smtp_from_name: str = "NukeLab"

    # Server Auth - Asymmetric key signing for container access tokens
    server_auth_enabled: bool = True
    server_auth_token_ttl: int = 300  # 5 minutes
    server_auth_key_algorithm: str = "RS256"
    server_auth_secrets_dir: str = "/run/secrets"
    server_auth_private_key_path: str = ""
    server_auth_public_key_path: str = ""
    server_auth_key_rotation_days: int = 30
    server_auth_max_tokens_per_minute: int = 10
    server_auth_audit_log: bool = True

    # User Auth - Asymmetric key signing for API access tokens
    user_auth_key_algorithm: str = "EdDSA"  # Ed25519 via cryptography
    user_auth_secrets_dir: str = "/run/user-secrets"
    user_auth_private_key_path: str = ""
    user_auth_public_key_path: str = ""
    user_auth_issuer: str = "NukeLab"
    user_auth_audience: str = "nukelab-api"
    user_auth_leeway_seconds: int = 5
    user_auth_denylist_fail_closed: bool = True
    user_auth_key_rotation_grace_seconds: int | None = None

    @field_validator("user_auth_key_rotation_grace_seconds", mode="before")
    @classmethod
    def _empty_rotation_grace_to_none(cls, value: Any) -> Any:
        """Treat an empty env value as "use the default"."""
        if value == "" or value is None:
            return None
        return value

    @model_validator(mode="after")
    def set_key_paths(self) -> "Settings":
        """Derive key paths from secrets_dir if not explicitly set."""
        if not self.server_auth_private_key_path:
            self.server_auth_private_key_path = os.path.join(
                self.server_auth_secrets_dir, "server-auth-private.pem"
            )
        if not self.server_auth_public_key_path:
            self.server_auth_public_key_path = os.path.join(
                self.server_auth_secrets_dir, "server-auth-public.pem"
            )
        if not self.user_auth_private_key_path:
            self.user_auth_private_key_path = os.path.join(
                self.user_auth_secrets_dir, "user-auth-private.pem"
            )
        if not self.user_auth_public_key_path:
            self.user_auth_public_key_path = os.path.join(
                self.user_auth_secrets_dir, "user-auth-public.pem"
            )
        return self

    @model_validator(mode="after")
    def set_user_auth_rotation_grace(self) -> "Settings":
        """Default key rotation grace period to 2× access-token lifetime."""
        if self.user_auth_key_rotation_grace_seconds is None:
            self.user_auth_key_rotation_grace_seconds = self.jwt_expire_minutes * 2 * 60
        return self

    @model_validator(mode="after")
    def validate_user_auth_keys_in_production(self) -> "Settings":
        """Refuse to start in production with missing or weakly-protected keys."""
        if self.app_env == "production":
            private_path = self.user_auth_private_key_path
            public_path = self.user_auth_public_key_path

            if not private_path or not os.path.exists(private_path):
                raise ValueError(f"USER_AUTH_PRIVATE_KEY_PATH does not exist: {private_path}")
            if not public_path or not os.path.exists(public_path):
                raise ValueError(f"USER_AUTH_PUBLIC_KEY_PATH does not exist: {public_path}")

            private_mode = os.stat(private_path).st_mode
            if private_mode & 0o077:
                raise ValueError(
                    f"USER_AUTH_PRIVATE_KEY_PATH permissions are too permissive: "
                    f"{oct(private_mode & 0o777)}. Group/other must have no access."
                )
        return self

    @model_validator(mode="after")
    def reject_default_secrets_in_production(self) -> "Settings":
        """Refuse to start in production with default/dev secrets."""
        if self.app_env == "production":
            weak_secrets = {
                "change-me",
                "dev-jwt-secret-change-in-production-min-32-chars",
                "dev-session-secret-change-in-production",
                "dev-jwt-secret",
            }
            if self.jwt_secret in weak_secrets:
                raise ValueError(
                    "JWT_SECRET is using a default/dev value. "
                    "Set a strong random secret before running in production."
                )
            if self.session_secret in weak_secrets:
                raise ValueError(
                    "SESSION_SECRET is using a default/dev value. "
                    "Set a strong random secret before running in production."
                )
        return self

    @model_validator(mode="after")
    def set_container_hardening_defaults(self) -> "Settings":
        """Default container hardening to enabled except in dev_mode."""
        if self.container_hardening_enabled is None:
            self.container_hardening_enabled = not self.dev_mode
        return self

    @model_validator(mode="after")
    def set_database_url(self) -> "Settings":
        """Derive DATABASE_URL from components when no override is provided."""
        if not self.database_url:
            self.database_url = (
                f"postgresql+asyncpg://{self.database_user}:{self.database_password}"
                f"@{self.database_host}:{self.database_port}/{self.database_name}"
            )
        return self

    @model_validator(mode="after")
    def set_pgbouncer_url(self) -> "Settings":
        """Derive a default PgBouncer URL when pooling is enabled explicitly."""
        if self.pgbouncer_enabled and not self.database_pgbouncer_url:
            parsed = urlparse(self.database_url)
            if parsed.username is not None and parsed.password is not None:
                netloc = f"{parsed.username}:{parsed.password}@pgbouncer:6432"
                self.database_pgbouncer_url = urlunparse(
                    (parsed.scheme, netloc, parsed.path, "", parsed.query, "")
                )
        return self

    @model_validator(mode="after")
    def validate_cors_in_production(self) -> "Settings":
        """Refuse wildcard or empty CORS origins in production."""
        if self.app_env == "production":
            origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
            if not origins or "*" in origins:
                raise ValueError(
                    "CORS_ORIGINS must contain explicit origins in production. "
                    "Wildcards (*) are not allowed."
                )
            # Validate each origin looks like a valid URL (scheme + netloc)
            for origin in origins:
                if not origin.startswith(("http://", "https://")):
                    raise ValueError(f"CORS origin '{origin}' must be a valid HTTP/HTTPS URL.")
        return self

    class Config:
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
