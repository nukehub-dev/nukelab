# Environment Variables Reference

This document groups and explains the environment variables used by NukeLab. The authoritative source is `.env.example`; when in doubt, check that file.

## Quick start

```bash
cp .env.example .env.development   # Local development
cp .env.example .env               # Production
```

Both `.env` and `.env.development` are gitignored. `.env.example` is the only environment file tracked in Git.

## Variable groups

### Application

| Variable | Description |
|---|---|
| `APP_NAME` | Application name |
| `APP_ENV` | `development`, `staging`, or `production` |
| `APP_DEBUG` | Enable debug output; `false` in production |
| `APP_URL` | Public application URL |
| `FRONTEND_URL` | Optional separate frontend URL for Vite dev server |
| `APP_TIMEZONE` | Default timezone |
| `API_DOCS_ENABLED` | Serve `/api/docs`, `/api/redoc`, and `/api/openapi.json`; disabled by default in production |
| `NUKELAB_VERSION` | Version baked into locally built backend images (`APP_VERSION` build arg); defaults to `VERSION` file / git tag. Pinning this switches `nukelabctl` to pull-based deploys |
| `NUKELAB_IMAGE_TAG` | Exact registry image tag to deploy (`ghcr.io/nukehub-dev/nukelab-backend` / `-frontend`); defaults to the pinned `NUKELAB_VERSION` in pull mode, or `latest` in source-build mode |
| `NUKELAB_PULL_DEPLOY` | Set automatically by `nukelabctl`: `true` when `NUKELAB_VERSION` or `NUKELAB_IMAGE_TAG` is pinned, otherwise `false` |

### Security

| Variable | Description |
|---|---|
| `JWT_SECRET` | Encrypts OAuth refresh tokens; must be changed in production |
| `JWT_EXPIRE_MINUTES` | Access token lifetime |
| `JWT_REFRESH_EXPIRE_DAYS` | Refresh token lifetime |
| `USER_AUTH_KEY_ALGORITHM` | `EdDSA` for asymmetric access token signing |
| `USER_AUTH_SECRETS_DIR` | Path to Ed25519 key pair volume |
| `USER_AUTH_DENYLIST_FAIL_CLOSED` | Reject auth if Redis is unavailable |
| `SESSION_SECRET` | Cookie signing secret; must be changed in production |
| `SESSION_MAX_AGE` | Session cookie lifetime in seconds |
| `SESSION_SECURE` | HTTPS-only cookies |
| `SECURITY_HEADERS_ENABLED` | Inject security headers from FastAPI |
| `CSRF_PROTECTION_ENABLED` | Enable double-submit CSRF protection |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `CORS_ALLOW_CREDENTIALS` | Allow cookies across origins |
| `CONTAINER_HARDENING_ENABLED` | Harden spawned server containers (non-root, no capabilities, read-only rootfs, no-new-privileges); defaults on outside dev mode. Pass the same value to `backend` and `celery-worker`, because background-admitted launches use the worker's configuration |

### Rate Limiting

See `.env.example` for per-role RPM limits (`RATE_LIMIT_*_RPM`) and the master
`RATE_LIMIT_ENABLED` switch used by WebSocket message throttling.

### Authentication

| Variable | Description |
|---|---|
| `AUTH_MODE` | `local`, `oauth`, or `both` |
| `LOCAL_AUTH_BCRYPT_ROUNDS` | bcrypt cost factor |
| `DEV_MODE` | Auto-create dev admin account |
| `DEV_ADMIN_USER` / `DEV_ADMIN_PASSWORD` | Dev admin credentials |

### OAuth / OIDC

| Variable | Description |
|---|---|
| `OAUTH_PROVIDER_NAME` | Display name on login screen |
| `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` | Provider credentials |
| `OAUTH_DISCOVERY_URL` | OIDC discovery endpoint |
| `OAUTH_AUTHORIZE_URL` / `OAUTH_TOKEN_URL` / `OAUTH_USERDATA_URL` / `OAUTH_LOGOUT_URL` | Manual endpoints when discovery is unused |
| `OAUTH_CALLBACK_URL` | Redirect URI registered with provider |
| `OAUTH_SCOPE` / `OAUTH_USERNAME_CLAIM` / `OAUTH_EMAIL_CLAIM` / `OAUTH_NAME_CLAIM` / `OAUTH_PICTURE_CLAIM` | Claim mapping |
| `OAUTH_PKCE_ENABLED` | Enable PKCE |

Logout is OIDC RP-initiated: for OAuth-authenticated users, `POST /api/auth/logout`
returns an `oauth_logout_url` (from the discovered `end_session_endpoint` or
`OAUTH_LOGOUT_URL`) and the frontend navigates through it, terminating the SSO
session. Register `<FRONTEND_URL>/login` as an allowed
`post_logout_redirect_uri` with the provider, or the redirect back after logout
will be rejected. If the provider has no end-session endpoint, logout is
local-only.

### Database

| Variable | Description |
|---|---|
| `DATABASE_USER` / `DATABASE_PASSWORD` / `DATABASE_NAME` / `DATABASE_HOST` / `DATABASE_PORT` | PostgreSQL connection |
| `DATABASE_URL` | Optional full asyncpg URL |
| `DATABASE_POOL_SIZE` / `DATABASE_POOL_MAX_OVERFLOW` / `DATABASE_POOL_TIMEOUT` / `DATABASE_POOL_RECYCLE` / `DATABASE_POOL_PRE_PING` | SQLAlchemy pool settings |
| `DATABASE_QUERY_TIMEOUT_SECONDS` | Query abort threshold |
| `DATABASE_ECHO` | Log all SQL |
| `AUTO_CREATE_TABLES` | Create missing tables at startup for local development; set `false` in production and use `db-migrate` |
| `DB_SCHEMA_GUARD` | `auto` (enforce in production, warn elsewhere), `enforce`, or `off` |
| `OBSERVABILITY_SLOW_QUERY_THRESHOLD_MS` | Slow query log threshold |
| `OBSERVABILITY_PG_STAT_STATEMENTS_ENABLED` | Track statements with pg_stat_statements |

### PgBouncer

| Variable | Description |
|---|---|
| `PGBOUNCER_ENABLED` | Enable PgBouncer overlay |
| `PGBOUNCER_POOL_MODE` | Must be `transaction` for asyncpg |
| `PGBOUNCER_MAX_CLIENT_CONN` / `PGBOUNCER_DEFAULT_POOL_SIZE` / `PGBOUNCER_RESERVE_POOL_SIZE` / `PGBOUNCER_MAX_DB_CONNECTIONS` | Pool sizing |
| `PGBOUNCER_*` | Timeouts, TCP keepalive, stats, container resources |

### Redis

| Variable | Description |
|---|---|
| `REDIS_URL` | Redis connection URL |
| `REDIS_PASSWORD` | Optional Redis password |
| `REDIS_DB` | Redis database number |
| `REDIS_MAXMEMORY` | Memory limit |
| `REDIS_MAXMEMORY_POLICY` | Eviction policy, e.g., `allkeys-lru` |

### Frontend / CDN

| Variable | Description |
|---|---|
| `VITE_CDN_URL` | Optional CDN origin for static JS/CSS assets |
| `VITE_ENABLE_PUSH_IN_DEV` | Register the push service worker while running Vite locally |

### Web push

| Variable | Description |
|---|---|
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | VAPID key pair for browser push notifications |
| `VAPID_SUBJECT` | `mailto:` or `https://` contact for the push subscription |

### Docker / Podman

| Variable | Description |
|---|---|
| `DOCKER_SOCKET` | Container engine socket; empty for auto-detection |
| `DOCKER_NETWORK` | Network name for spawned containers |
| `DOCKER_REGISTRY` | Optional image registry |
| `DOCKER_PULL_POLICY` | `always`, `if-not-present`, or `never` |
| `CONTAINER_RUNTIME` | Container runtime driver (`docker` covers Podman; `kubernetes` reserved for the future k3s driver) |
| `COMPOSE_OVERLAYS` | Space-separated extra compose files |
| `VOLUME_STORAGE_PATH` | Host path for volume file operations |
| `XFS_QUOTA_ENABLED` | Enable kernel-enforced XFS project quotas |
| `GPU_ENABLED` | Enable NVIDIA GPU passthrough for user servers (see `docs/operations/GPU-SETUP.md`) |
| `GPU_CDI_DEVICE` | CDI device spec used on Podman when `GPU_DEVICES` is empty (default `nvidia.com/gpu=all`) |
| `GPU_DEVICES` | Comma-separated CDI device pool for exclusive GPU assignment (e.g. `nvidia.com/gpu=0,nvidia.com/gpu=1`); empty = shared mode |
| `RESOURCE_POOL_CPU` | Allocatable CPU units for admitted servers |
| `RESOURCE_POOL_MEMORY_MIB` | Allocatable memory in MiB |
| `RESOURCE_POOL_DISK_MIB` | Allocatable disk in MiB |
| `SERVER_LAUNCH_TIMEOUT_SECONDS` | Deadline for reserved launches and long-running lifecycle/recovery worker operations |
| `QUEUE_DISPATCH_BATCH_SIZE` | Maximum queued requests a worker evaluates per batch |
| `QUEUE_TICK_SECONDS` | Celery Beat interval for queue-dispatch ticks |
| `QUEUE_TIMEOUT_SECONDS` | Maximum age of a waiting request before expiry |
| `QUEUE_MAX_PENDING_PER_OWNER` | Maximum simultaneous pending requests per owner |
| `QUEUE_MAX_PENDING_TOTAL` | Maximum simultaneous pending requests platform-wide |
| `WORKER_HEARTBEAT_INTERVAL_SECONDS` | Worker/executor heartbeat cadence (default 5s) |
| `WORKER_HEARTBEAT_STALE_SECONDS` | Age after which a heartbeat is stale (default 20s; must exceed the interval) |
| `OPERATION_HEARTBEAT_INTERVAL_SECONDS` | Operation heartbeat cadence while a fenced launch/backup/restore row is active (default 10s) |
| `OPERATION_HEARTBEAT_STALE_SECONDS` | Age after which an operation heartbeat is stale (default 90s; must exceed the interval) |
| `RECOVERY_SCAN_INTERVAL_SECONDS` | Recovery reconciliation scan interval (default 30s) |
| `RECOVERY_INITIAL_DELAY_SECONDS` | Delay before the first scan after worker readiness (default 60s) |
| `RECOVERY_PREPARED_GRACE_SECONDS` | Grace before an unclaimed prepared operation may fail (default 60s) |
| `RECOVERY_SCAN_BATCH_SIZE` | Maximum operation rows inspected per scan (default 200) |
| `RECOVERY_STALL_WARNING_SECONDS` | Warning threshold for a live worker with a stale operation heartbeat (default 300s) |
| `RECOVERY_LEGACY_DRAIN_CONFIRMED` | Set true only after a full stop/drain with no pre-2.3 executor; never replaces runtime inspection |
| `UPLOAD_DIR` | Container path for uploads |

Waiting queue requests do not reserve compute from the resource pools. The
values must reflect the actual host capacity available to NukeLab.

### Batch jobs

Single-run batch jobs are disabled for submission by default. Keep these values
consistent on `backend`, `celery-worker`, and `celery-beat`; worker and Beat
values control execution, dispatch cadence, monitoring, recovery and cleanup.
The owner/admin history surfaces remain readable while submission is disabled.

| Variable | Default | Description |
|---|---|---|
| `BATCH_JOBS_SUBMISSION_ENABLED` | `false` | Allow new owner submissions. `false` blocks submission only; existing jobs, history, logs and cancellation continue |
| `BATCH_JOBS_ALLOW_PAID_PLANS` | `false` | Enables paid plans for batch jobs. Requires `CREDITS_ENABLED=true`. When false, nonzero-cost plans are rejected with `paid_plan_unsupported` and capabilities report `zero_cost`. When true, a paid submission creates one credit hold for the maximum runtime; actual usage settles at the frozen rate and the unused authorization is refunded |
| `BATCH_JOBS_ALLOWED_USER_IDS` | empty | Optional comma-separated owner UUID pilot cohort (one UUID is a valid one-entry list). Empty means the `jobs:write_own` grant defines eligibility; a nonempty list narrows it |
| `BATCH_JOBS_MAX_ACTIVE_PER_OWNER` | `1` | Maximum active (`starting`, `running`, `cancelling`, `recovery_required`) jobs per owner |
| `BATCH_JOBS_MAX_QUEUED_PER_OWNER` | `3` | Maximum unexpired queued jobs per owner |
| `BATCH_JOBS_DEFAULT_RUNTIME_SECONDS` | `1800` | Runtime limit when a submission omits `max_runtime_seconds` |
| `BATCH_JOBS_MAX_RUNTIME_SECONDS` | `7200` | Maximum accepted runtime limit |
| `BATCH_JOBS_QUEUE_TTL_SECONDS` | `86400` | Maximum time a job may wait in `queued` before expiry |
| `BATCH_JOBS_MAX_ARGV_ITEMS` | `64` | Maximum argument count |
| `BATCH_JOBS_MAX_INPUT_BYTES` | `16384` | Maximum combined UTF-8 argument bytes |
| `BATCH_JOBS_LOG_TAIL_BYTES` | `262144` | Maximum retained log tail (256 KiB) |
| `BATCH_JOBS_LOG_RETENTION_SECONDS` | `604800` | Read-time log retention (7 days) |
| `BATCH_JOBS_LOG_PURGE_INTERVAL_SECONDS` | `3600` | Celery Beat cadence for the bounded physical log purge |
| `BATCH_JOBS_LOG_PURGE_BATCH_SIZE` | `100` | Maximum expired log payload rows physically removed per purge pass |
| `BATCH_JOBS_REQUIRE_STORAGE_ENFORCEMENT` | `false` | When true, capabilities and submission fail closed with `storage_limits_unenforced` unless the volume storage path has kernel-enforced XFS project quotas; admission keeps queued jobs waiting |
| `BATCH_JOBS_MAX_ACTIVE_FLEET` | `5` | Maximum active job reservations platform-wide; `0` means unlimited |
| `BATCH_JOBS_HEARTBEAT_STALE_SECONDS` | `90` | Heartbeat age that triggers inspection, never takeover |
| `BATCH_JOBS_STOP_TIMEOUT_SECONDS` | `30` | Stop/cleanup timeout and `/work` preparation helper bound |
| `BATCH_JOBS_MONITOR_BATCH_SIZE` | `20` | Maximum active jobs inspected per monitor pass |
| `BATCH_JOBS_DISPATCH_BATCH_SIZE` | `10` | Maximum queued jobs evaluated per dispatch pass |
| `BATCH_JOBS_DISPATCH_INTERVAL_SECONDS` | `5` | Celery Beat dispatch cadence |
| `BATCH_JOBS_MONITOR_INTERVAL_SECONDS` | `10` | Celery Beat monitor cadence |
| `BATCH_JOBS_RECOVERY_INTERVAL_SECONDS` | `30` | Celery Beat stale/recovery and cleanup retry cadence |
| `BATCH_JOBS_RECOVERY_BATCH_SIZE` | `50` | Maximum stale jobs inspected per recovery pass |
| `BATCH_JOBS_PIDS_LIMIT` | `256` | Per-job process limit |
| `BATCH_JOBS_TMPFS_BYTES` | `67108864` | Per-job `/tmp` tmpfs size (64 MiB); `/home` uses a fixed 16 MiB |

The cohort key is `BATCH_JOBS_ALLOWED_USER_IDS` (plural) even for a single owner.
See [BATCH-JOBS.md](../architecture/BATCH-JOBS.md) for admission, runtime and
recovery behavior. Submission stays zero-cost until a settlement contract exists.

Recovery reminders are not configurable through environment variables. While an
`uncertain` launch or `recovery_required` volume row remains unresolved, Celery
Beat runs one bounded reminder sweep daily at 08:00 UTC and deduplicates to at
most one reminder per operation per 24 hours.

### Registry verification

| Variable | Description |
|---|---|
| `REGISTRY_VERIFICATION_POLICY` | `off` (no registry I/O), `prefer` (verify when possible, otherwise record a local-only revision), or `require` (fail closed). Code default `off`; `.env.example` uses `prefer` for new installs |
| `REGISTRY_PULL_POLICY` | `on_demand` allows an exact platform-digest pull when the approved artifact is missing; `preload_only` never pulls during launch or verification |
| `REGISTRY_ALLOWED_HOSTS` | Optional comma-separated registry host allowlist. Empty permits public HTTPS registries that pass SSRF checks; private/loopback hosts and separate token-service hosts must be listed |
| `REGISTRY_CREDENTIALS_FILE` | Docker `config.json`-compatible credentials file used only for verification. Empty means anonymous; compose sets the container path automatically |
| `REGISTRY_CREDENTIALS_FILE_HOST` | Host path mounted read-only into `backend` and `celery-worker` at the credentials path; defaults to `/dev/null`. The file must be readable by uid 65532 and is re-read within 60 seconds, so replace it atomically to rotate credentials |

`credsStore` and `credHelpers` are not supported. Runtime image pulls
use the container engine's own registry login; the verification credentials do
not authenticate a runtime pull. Resolution alone does not create approval, and
a moved tag never becomes a new approval automatically.

### Volume recovery

| Variable | Description |
|---|---|
| `VOLUME_BACKUP_HOST_PATH` | Absolute host path used by the trusted helper for private offline backups; empty disables recovery mutations |
| `VOLUME_BACKUP_STORAGE_PATH` | Path inside API/worker containers that maps to the same bind mount |
| `VOLUME_BACKUP_HELPER_IMAGE` | Trusted helper image; defaults to `nukelab-volume-helper:latest` |
| `VOLUME_BACKUP_RETENTION_DAYS` | Age-based backup retention window |
| `VOLUME_BACKUP_MAX_PER_VOLUME` | Maximum retained backups per volume |
| `VOLUME_BACKUP_MAX_OWNER_BYTES` | Per-owner backup storage budget |
| `VOLUME_BACKUP_MAX_TOTAL_BYTES` | Platform-wide backup storage budget |
| `VOLUME_BACKUP_MAX_LOGICAL_BYTES` | Maximum logical size of one backup archive |
| `VOLUME_BACKUP_MAX_MEMBERS` | Maximum number of archive members |
| `VOLUME_BACKUP_TIMEOUT_SECONDS` | Helper operation timeout |

Recovery requires the helper image and both storage paths to be configured;
otherwise owner history remains readable but backup/restore actions are
disabled. See [BACKUP-RESTORE.md](../operations/BACKUP-RESTORE.md).

### Server container authentication

| Variable | Description |
|---|---|
| `SERVER_AUTH_ENABLED` | Enable short-lived server tokens |
| `SERVER_AUTH_SECRETS_DIR` | Path to RS256 key volume |
| `SERVER_AUTH_TOKEN_TTL` | Server token lifetime in seconds |
| `SERVER_AUTH_KEY_ALGORITHM` | `RS256` or `ES256` |
| `SERVER_AUTH_KEY_ROTATION_DAYS` | Automatic key rotation interval |
| `SERVER_AUTH_MAX_TOKENS_PER_MINUTE` | Rate limit for server token issuance |
| `SERVER_AUTH_AUDIT_LOG` | Record server-token issuance and access decisions in the audit log |

### Credits

| Variable | Description |
|---|---|
| `CREDITS_ENABLED` | Bill server usage with the NUKE credit system |
| `CREDITS_INITIAL_BALANCE` | Balance granted to new users |
| `CREDITS_DAILY_ALLOWANCE` | Default daily allowance for active users |
| `CREDITS_MAX_BALANCE` | Maximum balance; `0` for unlimited |
| `CREDITS_ROLLOVER` | Roll unused daily allowance into the next day |
| `CREDITS_DAILY_ALLOWANCE_LOGIN_WINDOW_HOURS` | Required recent-login window for the daily allowance |

### Maintenance

| Variable | Description |
|---|---|
| `MAINTENANCE_MODE` | Reject normal requests with the maintenance response |
| `MAINTENANCE_MESSAGE` | Message shown while maintenance mode is enabled |

### Monitoring

| Variable | Description |
|---|---|
| `PROMETHEUS_ENABLED` | Expose `/api/metrics` and start the Prometheus overlay |
| `GRAFANA_ENABLED` | Start the Grafana overlay |
| `REQUEST_METRICS_ENABLED` | Enable request-metrics middleware |
| `REQUEST_METRICS_STORE` | `db`, `prometheus`, or `both` |

See `.env.example` for the full list, defaults, and inline documentation.

## Related documents

- [LOCAL-DEV.md](../development/LOCAL-DEV.md) for development setup
- [operations/PRODUCTION-DEPLOYMENT.md](../operations/PRODUCTION-DEPLOYMENT.md) for production-specific guidance
- `.env.example` for the complete template
