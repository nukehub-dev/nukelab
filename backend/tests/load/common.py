"""Shared utilities for load testing.

Provides authentication helpers, test-data generation, and endpoint
wrappers used by both Locust scenarios and k6 script generation.
"""

import random
import string
from urllib.parse import urljoin

# ── Test Data Constants ─────────────────────────────────────────────────────

TEST_USER_PREFIX = "loadtest_"
TEST_PASSWORD = "LoadTest123!"
DEFAULT_ADMIN = {"username": "admin", "password": "admin123"}

# Realistic weighting for endpoints (higher = more frequent)
ENDPOINT_WEIGHTS = {
    # Read-heavy (hot paths at scale)
    "health": 50,
    "list_servers": 30,
    "get_server": 20,
    "list_environments": 15,
    "credits_balance": 10,
    "user_me": 10,
    # Write-heavy (expensive, rate-limited in test)
    "login": 25,
    "spawn_server": 2,
    "stop_server": 2,
    "delete_server": 1,
    # Admin (smaller user pool)
    "admin_list_users": 5,
    "admin_list_servers": 5,
    "admin_audit_logs": 3,
    "system_stats": 2,
}

# Endpoint paths
PATHS = {
    "health": "/api/system/health",
    "login": "/api/auth/login",
    "register": "/api/auth/register",
    "me": "/api/auth/me",
    "servers": "/api/servers",
    "environments": "/api/environments",
    "credits_balance": "/api/credits/",
    "credits_history": "/api/credits/history",
    "users": "/api/users",
    "admin_servers": "/api/admin/servers",
    "audit_logs": "/api/admin/activity",
    "system_stats": "/api/system/stats",
    "system_config": "/api/system/config",
}


# ── Helpers ─────────────────────────────────────────────────────────────────

def rand_user_id() -> str:
    """Generate a random test username."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{TEST_USER_PREFIX}{suffix}"


def build_url(base: str, path: str) -> str:
    """Safely join base URL with endpoint path."""
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))
