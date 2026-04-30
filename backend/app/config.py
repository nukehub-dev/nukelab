from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Application
    app_name: str = "NukeLab"
    app_env: str = "development"
    app_debug: bool = True
    app_url: str = "http://localhost:8000"
    public_url: str = "http://localhost:8080"  # Traefik/public-facing URL
    
    # Security
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours
    jwt_refresh_expire_days: int = 7
    
    # Auth
    auth_mode: str = "local"  # local | oauth
    local_auth_enabled: bool = True
    local_auth_bcrypt_rounds: int = 12
    
    # Dev Admin
    dev_mode: bool = True
    dev_admin_user: str = "admin"
    dev_admin_password: str = "admin123"
    
    # Database
    database_url: str = "postgresql+asyncpg://nukelab:nukelab123@postgres:5432/nukelab"
    database_pool_size: int = 10
    
    # Redis
    redis_url: str = "redis://redis:6379/0"
    
    # Docker
    docker_socket: str = "/var/run/docker.sock"
    docker_network: str = "nukelab-network"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
