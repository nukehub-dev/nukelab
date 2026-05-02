from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "NukeLab"
    app_env: str = "development"
    app_debug: bool = True
    app_url: str = "http://localhost:8000"
    public_url: str = "http://localhost:8080"
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

    rate_limit_enabled: bool = False
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    auth_mode: str = "local"
    local_auth_enabled: bool = True
    local_auth_bcrypt_rounds: int = 12

    dev_mode: bool = True
    dev_admin_user: str = "admin"
    dev_admin_password: str = "admin123"

    oauth_provider_name: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_discovery_url: str = ""
    oauth_callback_url: str = ""

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

    server_idle_timeout: int = 3600
    server_max_runtime: int = 86400
    server_auto_stop_on_depletion: bool = True
    server_warn_before_stop: int = 600

    class Config:
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
