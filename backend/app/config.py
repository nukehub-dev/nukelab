import os
from pydantic_settings import BaseSettings
from pydantic import model_validator


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

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7

    session_secret: str = "change-me"
    session_max_age: int = 86400
    session_secure: bool = False
    session_httponly: bool = True
    session_samesite: str = "lax"

    cors_origins: str = "http://localhost:3000,http://localhost:8000"
    cors_allow_credentials: bool = True

    # -------------------------------------------------------------------------
    # Rate Limiting — Two-Layer Architecture
    #   Layer 1 (Traefik): DDoS protection only — very high per-IP thresholds
    #   Layer 2 (FastAPI + Redis): Per-user throttling by JWT identity
    # -------------------------------------------------------------------------
    rate_limit_enabled: bool = True

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
    rate_limit_websocket_cpm: int = 30         # Connections per minute
    rate_limit_websocket_msg_rpm: int = 120    # Messages per minute per connection

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

    database_url: str = "postgresql+asyncpg://nukelab:nukelab123@postgres:5432/nukelab"
    database_pool_size: int = 10
    database_pool_max_overflow: int = 10
    database_pool_timeout: int = 30
    database_echo: bool = False

    redis_url: str = "redis://redis:6379/0"
    redis_password: str = ""
    redis_db: int = 0

    docker_socket: str = "/var/run/docker.sock"
    docker_network: str = "nukelab-network"
    docker_registry: str = ""
    docker_pull_policy: str = "if-not-present"
    volume_storage_path: str = ""

    container_default_cpu_limit: float = 2.0
    container_default_memory_limit: str = "4Gi"
    container_default_swap_limit: str = "4Gi"
    container_default_disk_limit: str = "50Gi"

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

    registration_enabled: bool = True
    max_servers_per_user: int = 10

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

    @model_validator(mode='after')
    def set_key_paths(self) -> 'Settings':
        """Derive key paths from secrets_dir if not explicitly set."""
        if not self.server_auth_private_key_path:
            self.server_auth_private_key_path = os.path.join(
                self.server_auth_secrets_dir, 'server-auth-private.pem'
            )
        if not self.server_auth_public_key_path:
            self.server_auth_public_key_path = os.path.join(
                self.server_auth_secrets_dir, 'server-auth-public.pem'
            )
        return self

    class Config:
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
