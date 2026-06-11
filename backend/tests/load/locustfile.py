"""Locust load test scenarios for NukeLab.

Usage (headless):
    locust -f locustfile.py --host http://localhost:8080 -u 50 -r 5 -t 5m --headless

Usage (with Web UI):
    locust -f locustfile.py --host http://localhost:8080

Docker (via compose.loadtest.yml):
    docker compose -f compose.loadtest.yml up locust

Profiles:
    smoke       → 1 user,  60s
    baseline    → 50 users, 5min
    stress      → 500 users, 10min
    spike       → 10→300 users, 5min
    endurance   → 50 users, 30min
    connection  → 1000 users, idle (PgBouncer test)
"""

import itertools
import json
import random
import time
from pathlib import Path
from locust import HttpUser, task, between, events

from common import (
    ENDPOINT_WEIGHTS,
    PATHS,
    DEFAULT_ADMIN,
    TEST_PASSWORD,
)

# Shared counter for deterministic user assignment across all user classes
_user_counter = itertools.count()
TEST_USER_COUNT = 100  # Must match seeded test users (loadtest_0000 .. loadtest_0099)

# JWT expires in 15 min; refresh 1 min before expiry to avoid 401 storms
TOKEN_REFRESH_THRESHOLD_SECONDS = 14 * 60

# Pre-generated token pool (populated by generate_tokens.py)
_TOKEN_POOL: dict[str, str] = {}
_TOKEN_FILE = Path("/mnt/locust/tokens.json")
if _TOKEN_FILE.exists():
    try:
        _TOKEN_POOL = json.loads(_TOKEN_FILE.read_text())
        print(f"Loaded {len(_TOKEN_POOL)} pre-generated tokens")
    except Exception as e:
        print(f"Warning: failed to load tokens.json: {e}")


def _pick_token(username: str) -> str | None:
    """Return a pre-generated token if available."""
    return _TOKEN_POOL.get(username)


# ── Locust Event Hooks ──────────────────────────────────────────────────────


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Log test configuration at startup."""
    host = environment.host or "unknown"
    print(f"\n🚀 Load test starting against {host}")
    print(f"   Users: {getattr(environment.parsed_options, 'users', getattr(environment.parsed_options, 'num_users', 'unknown'))}")
    print(f"   Spawn rate: {environment.parsed_options.spawn_rate}")
    print(f"   Run time: {getattr(environment.parsed_options, 'run_time', 'unlimited')}")
    if _TOKEN_POOL:
        print(f"   Token pool: {len(_TOKEN_POOL)} pre-generated tokens")
    else:
        print("   Token pool: not available (will login per user)")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Log summary at test end."""
    print("\n✅ Load test complete")
    stats = environment.runner.stats
    total = stats.total
    if total.num_requests > 0:
        fail_rate = (total.num_failures / total.num_requests) * 100
        print(f"   Total requests: {total.num_requests}")
        print(f"   Failures: {total.num_failures} ({fail_rate:.1f}%)")
        print(f"   Avg response time: {total.avg_response_time:.0f}ms")
        print(f"   p95: {total.get_response_time_percentile(0.95):.0f}ms")
        print(f"   p99: {total.get_response_time_percentile(0.99):.0f}ms")


# ── Base Mixins ─────────────────────────────────────────────────────────────


class AuthMixin:
    """Handles login/logout for Locust users with auto-refresh."""

    token: str | None = None
    user_id: str | None = None
    username: str | None = None
    token_issued_at: float = 0.0
    auth_failed: bool = False
    _using_pregen_token: bool = False

    def _headers(self) -> dict:
        """Return auth headers, refreshing token if near expiry."""
        if self.auth_failed:
            return {}
        # Only refresh tokens obtained via login (15 min expiry).
        # Pre-generated tokens have a 2-hour expiry — refreshing them
        # causes a mass login that hits the 10/min IP rate limit.
        if self.token and self.username and not self._using_pregen_token:
            elapsed = time.time() - self.token_issued_at
            if elapsed > TOKEN_REFRESH_THRESHOLD_SECONDS:
                self._login(self.username, TEST_PASSWORD)
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def _require_auth(self) -> bool:
        """Skip authenticated tasks if login failed."""
        return not self.auth_failed

    def _login(self, username: str, password: str) -> bool:
        """Authenticate with exponential backoff + jitter on 429 rate-limit."""
        max_attempts = 7  # up to ~64s wait
        for attempt in range(max_attempts):
            with self.client.post(
                PATHS["login"],
                data={"username": username, "password": password},
                catch_response=True,
                name="POST /api/auth/login",
            ) as resp:
                if resp.status_code == 200:
                    data = resp.json()
                    self.token = data.get("access_token")
                    self.user_id = data.get("user_id")
                    self.username = username
                    self.token_issued_at = time.time()
                    self.auth_failed = False
                    resp.success()
                    return True
                elif resp.status_code == 429 and attempt < max_attempts - 1:
                    # Rate-limited — back off and retry without counting as failure
                    resp.success()
                    sleep_time = (2 ** attempt) + random.random() * 3  # jitter
                    time.sleep(sleep_time)
                else:
                    resp.failure(f"Login failed: {resp.status_code}")
                    self.auth_failed = True
                    return False
        self.auth_failed = True
        return False


# ── User Scenarios ──────────────────────────────────────────────────────────


class AnonymousUser(HttpUser):
    """Unauthenticated traffic — health checks, login page."""

    weight = 1
    wait_time = between(1, 5)

    @task(ENDPOINT_WEIGHTS["health"])
    def health_check(self):
        self.client.get(PATHS["health"], name="GET /health")

    @task(ENDPOINT_WEIGHTS["login"])
    def health_check_anon(self):
        self.client.get(PATHS["health"], name="GET /health (anon)")


class RegularUser(HttpUser, AuthMixin):
    """Authenticated user performing typical workflows."""

    weight = 10
    wait_time = between(2, 10)

    def on_start(self):
        user_index = next(_user_counter) % TEST_USER_COUNT
        username = f"loadtest_{user_index:04d}"
        self.created_servers = []

        # Try pre-generated token first (bypasses login rate limits)
        pregen = _pick_token(username)
        if pregen:
            self.token = pregen
            self.username = username
            self.token_issued_at = time.time()
            self.auth_failed = False
            self._using_pregen_token = True
            return

        # Fall back to login (for standalone use without token pool)
        self._using_pregen_token = False
        if not self._login(username, TEST_PASSWORD):
            # Don't abort — Locust respawns dead users, causing a 429 death spiral.
            # Stay alive as an unauthenticated user (only health checks run).
            print(f"⚠️  Login failed for {username}, continuing unauthenticated")

    @task(ENDPOINT_WEIGHTS["list_servers"])
    def list_servers(self):
        if not self._require_auth():
            return
        self.client.get(
            PATHS["servers"],
            headers=self._headers(),
            name="GET /api/servers",
        )

    @task(ENDPOINT_WEIGHTS["list_environments"])
    def list_environments(self):
        if not self._require_auth():
            return
        self.client.get(
            PATHS["environments"],
            headers=self._headers(),
            name="GET /api/environments",
        )

    @task(ENDPOINT_WEIGHTS["credits_balance"])
    def credits_balance(self):
        if not self._require_auth():
            return
        self.client.get(
            PATHS["credits_balance"],
            headers=self._headers(),
            name="GET /api/credits/",
        )

    @task(ENDPOINT_WEIGHTS["user_me"])
    def user_me(self):
        if not self._require_auth():
            return
        self.client.get(
            PATHS["me"],
            headers=self._headers(),
            name="GET /api/auth/me",
        )

    @task(ENDPOINT_WEIGHTS["spawn_server"])
    def spawn_server(self):
        """Expensive: spawns a Docker container."""
        if not self._require_auth():
            return
        with self.client.post(
            PATHS["servers"],
            headers=self._headers(),
            json={
                "name": f"loadtest-server-{random.randint(1, 999999)}",
            },
            catch_response=True,
            name="POST /api/servers (spawn)",
        ) as resp:
            if resp.status_code in (200, 201):
                data = resp.json()
                server_id = data.get("id")
                if server_id:
                    self.created_servers.append(server_id)
                resp.success()
            elif resp.status_code == 422:
                # Validation error (quota/plan limit) — valid under load
                resp.success()
            else:
                resp.failure(f"Spawn failed: {resp.status_code}")

    @task(ENDPOINT_WEIGHTS["stop_server"])
    def stop_server(self):
        """Expensive: stops a Docker container the user created."""
        if not self._require_auth():
            return
        if not self.created_servers:
            return
        server_id = self.created_servers.pop()
        with self.client.post(
            f"{PATHS['servers']}/{server_id}/stop",
            headers=self._headers(),
            catch_response=True,
            name="POST /api/servers/{id}/stop",
        ) as resp:
            if resp.status_code in (200, 202, 404):
                # 404 = already stopped or not found, which is fine
                resp.success()
            else:
                resp.failure(f"Stop failed: {resp.status_code}")


class AdminUser(HttpUser, AuthMixin):
    """Admin performing dashboard operations.

    Disabled by default (weight=0) because all AdminUsers share the same
    login account, which rapidly hits per-IP rate limits and causes 401
    cascades. Run explicitly when you want to test admin endpoints:

        locust -f locustfile.py AdminUser --host http://... -u 5 -r 1
    """

    weight = 0
    wait_time = between(3, 15)

    def on_start(self):
        self._login(DEFAULT_ADMIN["username"], DEFAULT_ADMIN["password"])

    @task(ENDPOINT_WEIGHTS["admin_list_users"])
    def list_users(self):
        if not self._require_auth():
            return
        self.client.get(
            PATHS["users"],
            headers=self._headers(),
            params={"limit": 50, "offset": 0},
            name="GET /api/users",
        )

    @task(ENDPOINT_WEIGHTS["admin_list_servers"])
    def admin_list_servers(self):
        if not self._require_auth():
            return
        self.client.get(
            PATHS["admin_servers"],
            headers=self._headers(),
            params={"limit": 50},
            name="GET /api/admin/servers",
        )

    @task(ENDPOINT_WEIGHTS["admin_audit_logs"])
    def audit_logs(self):
        if not self._require_auth():
            return
        self.client.get(
            PATHS["audit_logs"],
            headers=self._headers(),
            params={"limit": 20},
            name="GET /api/admin/activity",
        )

    @task(ENDPOINT_WEIGHTS["system_stats"])
    def system_stats(self):
        if not self._require_auth():
            return
        self.client.get(
            PATHS["system_stats"],
            headers=self._headers(),
            name="GET /api/system/stats",
        )


class ConnectionFloodUser(HttpUser, AuthMixin):
    """Opens many idle DB connections to stress-test PgBouncer.

    These users log in and then do nothing but hold connections open,
    simulating the worst-case scenario for connection pooling.

    Run explicitly with:
        locust -f locustfile.py ConnectionFloodUser --host http://... -u 1000 -r 100
    """

    weight = 0  # Disabled by default; run explicitly via class name
    wait_time = between(30, 60)

    def on_start(self):
        user_index = next(_user_counter) % TEST_USER_COUNT
        username = f"loadtest_{user_index:04d}"

        pregen = _pick_token(username)
        if pregen:
            self.token = pregen
            self.username = username
            self.token_issued_at = time.time()
            self.auth_failed = False
            self._using_pregen_token = True
            return

        self._using_pregen_token = False
        if not self._login(username, TEST_PASSWORD):
            print(f"⚠️  ConnectionFloodUser login failed for {username}, continuing unauthenticated")

    @task(1)
    def heartbeat(self):
        if not self._require_auth():
            return
        self.client.get(
            PATHS["me"],
            headers=self._headers(),
            name="GET /api/auth/me (heartbeat)",
        )
