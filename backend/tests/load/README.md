# Load Testing

This directory contains load testing scenarios for the NukeLab platform.
Two tools are provided: **Locust** (realistic user behavior, Python) and **k6**
(high-RPS stress testing, JavaScript/Go runtime).

## Prerequisites

### Option A: Local Python (development)

```bash
cd backend
pip install -r requirements-loadtest.txt
```

### Option B: Docker (recommended for consistent results)

No local installation needed. All tests run in containers via
`compose.loadtest.yml`.

## Preparing Test Data

Load tests need authenticated users. Run the setup script **once** before
testing to create test accounts directly in the database (bypassing API
rate limits):

```bash
# Via nukelabctl (uses running backend container)
./nukelabctl exec backend python -m tests.load.setup_test_data --users 100

# Or directly
cd backend && python -m tests.load.setup_test_data --users 100
```

This creates 100 users (`loadtest_0000` through `loadtest_0099`) with
password `LoadTest123!`.

## Running Tests

### Quick Start — Via Script

```bash
# Smoke test (1 user, 60s)
./scripts/run-load-tests.sh smoke

# Baseline load (50 concurrent users, 5 minutes)
./scripts/run-load-tests.sh baseline

# Stress test (ramp to 500 users, 10 minutes)
./scripts/run-load-tests.sh stress

# Spike test (sudden jump to 300 users)
./scripts/run-load-tests.sh spike

# Endurance test (50 users, 30 minutes)
./scripts/run-load-tests.sh endurance

# k6 high-RPS stress test
./scripts/run-load-tests.sh k6-stress
```

### Locust with Web UI

```bash
# Local
cd backend
locust -f tests/load/locustfile.py --host http://localhost:8080
# Open http://localhost:8089

# Docker
docker compose -f compose.loadtest.yml up locust
# Open http://localhost:8089
```

### k6 Individual Profiles

```bash
# Smoke
docker compose -f compose.loadtest.yml run --rm \
  -e K6_PROFILE=smoke k6 run /scripts/api-stress.js

# Stress
docker compose -f compose.loadtest.yml run --rm \
  -e K6_PROFILE=stress k6 run /scripts/api-stress.js
```

## Test Scenarios

### Locust Scenarios

| User Type | Weight | Behavior |
|---|---|---|
| `AnonymousUser` | 1 | Health checks, unauthenticated page views |
| `RegularUser` | 10 | Login → list servers → view details → spawn/stop (controlled rate) |
| `AdminUser` | 2 | Login → list users → admin servers → audit logs → system stats |
| `ConnectionFloodUser` | 0* | Login → idle with occasional heartbeat (PgBouncer connection stress) |

*ConnectionFloodUser is disabled by default. Enable by editing `weight` in
`locustfile.py`.

### k6 Scenarios

| Profile | VUs | Duration | Purpose |
|---|---|---|---|
| `smoke` | 10 | 30s | Verify system works under minimal load |
| `baseline` | 100 | 5m | Simulate normal production traffic |
| `stress` | 500 | 10m | Find the breaking point |
| `spike` | 10→500 | 5m | Test sudden traffic surges |
| `endurance` | 100 | 30m | Find memory leaks and connection drift |

## What to Watch During Tests

### 1. PgBouncer Pool Health

```bash
./nukelabctl exec pgbouncer psql -p 6432 pgbouncer -U nukelab -c "SHOW POOLS;"
```

Key columns:

- `cl_active` — clients currently executing
- `cl_waiting` — clients waiting for a backend connection (should be 0)
- `sv_active` — active backend connections to Postgres
- `sv_idle` — idle backend connections ready for reuse

If `cl_waiting` > 0, your backend pool is saturated. Increase
`DEFAULT_POOL_SIZE` or optimize queries.

### 2. Postgres Performance

```bash
# Active connections
./nukelabctl exec postgres psql -U nukelab -c \
  "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;"

# Slow queries (requires pg_stat_statements)
./nukelabctl exec backend python scripts/db_profiler.py slow-queries --limit 10

# Lock waits
./nukelabctl exec postgres psql -U nukelab -c \
  "SELECT * FROM pg_locks WHERE NOT granted;"
```

### 3. Application Metrics

The Locust Web UI shows:

- Requests per second (RPS)
- Response time percentiles (p50, p95, p99)
- Error rate

k6 outputs these natively plus custom trends (`health_p95`, `list_servers_p95`).

### 4. System Resources

```bash
# Host-level
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# Inside containers
./nukelabctl exec backend ps aux --sort=-%mem | head
```

## Interpreting Results

| Metric | Good | Warning | Critical |
|---|---|---|---|
| p95 latency | < 200ms | 200-1000ms | > 1000ms |
| Error rate | < 0.1% | 0.1-5% | > 5% |
| PgBouncer `cl_waiting` | 0 | 1-10 | > 10 |
| Postgres active connections | < 300 | 300-400 | > 450 |
| CPU (backend) | < 50% | 50-80% | > 80% |
| Memory growth (endurance) | Flat | Slow rise | Steep rise |

## Troubleshooting

**"Login failures" in load test**
→ Run `setup_test_data.py` first. If users exist, check API rate limiting.

**"Spawn server 422 errors"**
→ Expected under load — users hit plan limits or resource quotas. Not a bug.

**"PgBouncer connection refused"**
→ Check `MAX_CLIENT_CONN` and host `ulimits`. See `compose.pgbouncer.yml`.

**"Traefik 504 Gateway Timeout"**
→ Backend is overloaded. Check `QUERY_WAIT_TIMEOUT` and query performance.

## Extending the Tests

Add new endpoints:

```python
# In locustfile.py, inside a User class
@task(5)
def my_new_endpoint(self):
    self.client.get("/api/my/endpoint", headers=self._headers())
```

Add new k6 checks:

```javascript
// In k6/api-stress.js
const resp = http.get(`${HOST}/api/my/endpoint`, { headers });
check(resp, { 'my endpoint is 200': (r) => r.status === 200 });
```
