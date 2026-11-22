# NukeLab Operations Guide

> **Scope:** Day-to-day database operations, monitoring, and scaling decisions  
> **Audience:** Developers and operators running NukeLab in any environment

---

## 1. Database Health & Profiling

### 1.1 Quick Health Checks

```bash
# Table sizes and approximate row counts
./nukelabctl exec backend python scripts/db_profiler.py table-sizes

# List partitions for a table
./nukelabctl exec backend python scripts/db_profiler.py partitions --table activity_logs

# Partition health (via admin monitoring dashboard API)
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8080/api/admin/health/monitoring | jq '.system.services.partitions'
```

### 1.2 Slow Query Analysis

```bash
# Top slow queries by total execution time
./nukelabctl exec backend python scripts/db_profiler.py slow-queries --limit 10 --min-calls 10

# Check current connections
./nukelabctl exec postgres psql -U nukelab -c "
SELECT count(*) AS active_connections
FROM pg_stat_activity
WHERE state = 'active';
"
```

### 1.3 Partition Management

Partitions are auto-created on startup and via Celery Beat daily, but you can manage them manually:

```bash
# Create partitions for current month + N months ahead
./nukelabctl exec backend python scripts/db_profiler.py ensure-partitions --months-ahead 3

# Drop partitions older than N months (detaches them — data is preserved)
./nukelabctl exec backend python scripts/db_profiler.py drop-old --months-to-keep 12
```

**Operational notes:**

- The baseline migration creates a `DEFAULT` partition + the current month's partition automatically.
- A `DEFAULT` partition acts as a safety net for rows outside explicit partitions.
- Run `ensure-partitions` monthly (via Celery Beat) to create upcoming partitions ahead of time.

---

## 2. Autovacuum Monitoring

### 2.1 When to Act

Run weekly. If `dead_pct` > 20% for any table, tune autovacuum.

```bash
./nukelabctl exec postgres psql -U nukelab -d nukelab -c "
SELECT
    relname AS table_name,
    n_live_tup AS live_rows,
    n_dead_tup AS dead_rows,
    ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_pct
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY dead_pct DESC NULLS LAST;
"
```

### 2.2 Automated Tuning Script

```bash
# Run the metrics-gated tuning script (dry-run by default)
./nukelabctl exec backend python scripts/tune_autovacuum.py --dry-run

# Apply changes if metrics justify them
./nukelabctl exec backend python scripts/tune_autovacuum.py
```

The script only applies tuning when `dead_pct` > 10% for partitioned tables.

### 2.3 Manual Tuning (if needed)

```sql
-- More aggressive autovacuum for high-insert tables
ALTER TABLE server_metrics SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_analyze_scale_factor = 0.02
);

ALTER TABLE activity_logs SET (
    autovacuum_vacuum_scale_factor = 0.05
);
```

**Rationale:** Default `autovacuum_vacuum_scale_factor = 0.2` means vacuum only runs after 20% of the table is dead tuples. On a 100M row table, that's 20M dead tuples — way too late.

---

## 3. Backup & Restore

See [`BACKUP-RESTORE.md`](./BACKUP-RESTORE.md) for full procedures.

Quick reference:

```bash
# Create backup
./nukelabctl backup

# Restore from backup (drops/recreates the DB; asks for confirmation,
# pass --yes to skip the prompt)
./nukelabctl restore backups/nukelab_backup_YYYYMMDD_HHMMSS.sql
```

---

## 4. Connection Scaling (PgBouncer)

### 4.1 When to Enable

**Only when metrics justify it.** Check connection usage:

```bash
./nukelabctl exec postgres psql -U nukelab -c "
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';
"
```

**Enable PgBouncer when:**

- You consistently use >80% of `max_connections` (400+ out of 500)
- You're getting `FATAL: sorry, too many clients already`
- You need to scale beyond what direct Postgres connections allow

**Don't enable it until then.** It adds complexity for no benefit at small scale.

### 4.2 How to Enable

Set `PGBOUNCER_ENABLED=true` in your `.env`. `nukelabctl` auto-detects it and
injects the overlay — no need to set `COMPOSE_OVERLAYS`.

```bash
# 1. Keep database host/port on direct Postgres (used for migrations)
DATABASE_HOST=postgres
DATABASE_PORT=5432

# 2. Enable PgBouncer (DATABASE_PGBOUNCER_URL is optional; a default is used)
PGBOUNCER_ENABLED=true

# 3. Start — overlay is automatic
./nukelabctl start
```

Or one-off:

```bash
./nukelabctl start --overlay compose.pgbouncer.yml
```

### 4.3 What PgBouncer Does

PgBouncer sits between your app and PostgreSQL:

```
App → PgBouncer → PostgreSQL
```

Your app opens thousands of "fake" connections to PgBouncer. PgBouncer keeps a bounded pool of **real** connections open to Postgres and reuses them. Postgres never sees more than `MAX_DB_CONNECTIONS` (default 400) connections, even with 100k users.

When `PGBOUNCER_ENABLED=true`:

- SQLAlchemy client-side pooling is disabled (`NullPool`)
- asyncpg prepared statement caching is disabled
- PgBouncer becomes the single source of truth for connection pooling

This avoids **double-pooling**, which causes connection storms and starvation at scale.

### 4.4 Operational Notes

**Migrations use direct Postgres.** Because `DATABASE_HOST`/`DATABASE_PORT` stay pointed at Postgres, Alembic migrations automatically bypass PgBouncer — no manual URL swapping needed. DDL and long-running migrations should never go through PgBouncer because transaction pooling interferes with session-level features required by schema changes.

**Monitoring PgBouncer.** Connect to the admin console:

```bash
./nukelabctl exec pgbouncer psql -p 6432 pgbouncer -U nukelab -c "SHOW POOLS;"
./nukelabctl exec pgbouncer psql -p 6432 pgbouncer -U nukelab -c "SHOW STATS;"
```

**Sizing for 100k users.** Defaults in `.env.example` are tuned for `max_connections=500`:

- `DEFAULT_POOL_SIZE=100` + `RESERVE_POOL_SIZE=25` = 125 active backend connections
- `MAX_DB_CONNECTIONS=400` hard ceiling per database
- `MAX_CLIENT_CONN=20000` accepts 20k app-side connections
- `QUERY_WAIT_TIMEOUT=15` fails fast when Postgres is saturated

See `.env.example` for all PgBouncer environment variables (`PGBOUNCER_*`).

---

## 5. Read Replicas (Future)

**Not yet implemented.** See [`READ-REPLICAS.md`](./READ-REPLICAS.md) for the architecture reference.

**Trigger:** `pg_stat_statements` shows read queries (SELECT, COUNT) consuming >70% of total execution time.

Only implement when query profiling proves reads are the bottleneck. For most workloads, the optimizations already in place (indexing, partitioning, query batching) will handle scale without replicas.

---

## 6. Configuration Reference

### 6.1 Key Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_POOL_SIZE` | 20 | SQLAlchemy connection pool size |
| `DATABASE_QUERY_TIMEOUT_SECONDS` | 30 | Abort queries running longer than this |
| `OBSERVABILITY_SLOW_QUERY_THRESHOLD_MS` | 100 | Log queries slower than this |
| `OBSERVABILITY_PG_STAT_STATEMENTS_ENABLED` | true | Track query performance in Postgres |
| `COMPOSE_OVERLAYS` | (empty) | Additional compose files (e.g., `compose.pgbouncer.yml`) |
| `PGBOUNCER_MAX_CLIENT_CONN` | 20000 | Max app connections PgBouncer accepts |
| `PGBOUNCER_DEFAULT_POOL_SIZE` | 100 | Real Postgres connections PgBouncer maintains |
| `PGBOUNCER_MIN_POOL_SIZE` | 25 | Warm Postgres connections PgBouncer maintains |

### 6.2 Postgres Settings

| Setting | Value | Location |
|---|---|---|
| `max_connections` | 500 | `compose.yml` |
| `pg_stat_statements` | preloaded | `compose.yml` |

---

## 7. Scaling Decision Tree

```
Slow queries?
  +---> Yes ---> Add indexes? (check EXPLAIN ANALYZE)
      +---> Already indexed? ---> Check dead tuples (autovacuum)
          +---> Still slow? ---> Check if reads dominate (>70%)
              +---> Yes ---> Consider read replicas

Too many connections?
  +---> Yes ---> Enable PgBouncer overlay

Disk filling up?
  +---> Yes ---> Run db_profiler.py drop-old
```

---

## 8. Error Tracking

NukeLab ships with the Sentry SDK integrated on both backend and frontend. By default it is a **no-op** (zero overhead) until you set a DSN.

### 8.1 Self-Hosted GlitchTip (Recommended)

Run [GlitchTip](https://glitchtip.com) on a separate server or VM:

```bash
docker run -d -p 9000:8000 \
  -e DATABASE_URL=postgresql://user:pass@db/glitchtip \
  -e REDIS_URL=redis://redis:6379/0 \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -e PORT=8000 \
  docker.io/glitchtip/glitchtip:latest
```

Then point NukeLab to it:

```bash
# .env
SENTRY_DSN=http://public@glitchtip-host:9000/1
VITE_SENTRY_DSN=http://public@glitchtip-host:9000/1
```

### 8.2 Sentry SaaS

If you prefer Sentry's hosted service, just paste your project DSN:

```bash
SENTRY_DSN=https://xxx@yyy.ingest.sentry.io/zzz
VITE_SENTRY_DSN=https://xxx@yyy.ingest.sentry.io/zzz
```

### 8.3 Disable Error Tracking

Leave both DSNs empty (default). The SDKs initialize as no-ops with zero runtime cost.

## 9. First-run catalog setup

Fresh installs seed the Small/Medium/Large plans as visible to the `user` role;
XLarge remains admin-only and can be published later if desired. Environments
are intentionally not seeded, so an administrator must publish at least one
active public environment before users can deploy.

Use **Administration → Setup** (`/admin/setup`) for the first-run checklist:

1. Publish or activate a public deployment environment.
2. Make at least one active plan available to the `user` role.
3. Create or invite users.
4. Test the launch flow.

The setup page remains available for later catalog reviews. Plan administration
protects the last active plan and the last active plan available to users:
deactivation, deletion or visibility changes that would leave zero usable plans
are rejected with HTTP 409. Other plan fields remain editable at any time.

## 10. Capacity and queue operations

NukeLab admits new servers against configured allocatable budgets, not live
host telemetry. Set `RESOURCE_POOL_CPU`, `RESOURCE_POOL_MEMORY_MIB` and
`RESOURCE_POOL_DISK_MIB` to the capacity actually reserved for user servers.
`GPU_DEVICES` defines the exclusive GPU pool when used.

- Waiting requests consume no CPU, memory, disk or credits.
- Requests expire after `QUEUE_TIMEOUT_SECONDS`.
- `QUEUE_MAX_PENDING_PER_OWNER` and `QUEUE_MAX_PENDING_TOTAL` return 429 when
  reached.
- `celery-worker` dispatches bounded batches (`QUEUE_DISPATCH_BATCH_SIZE`) on
  the Celery Beat interval (`QUEUE_TICK_SECONDS`). Keep Beat and the worker
  running together; queue position is ordering, not a promised start time.
- `SERVER_LAUNCH_TIMEOUT_SECONDS` is the deadline for reserved launches and
  long-running lifecycle/recovery work.
- Owners may cancel only `pending` requests. `starting` rows are resolved from
  the linked launch operation, not by an admin action. An orphaned `starting` row
  is cancelled only after runtime absence is proved from its recorded container
  ID, managed server label, or deterministic launch name; otherwise it remains
  `starting` with `recovery_required`.
- **Administration → Queue** (`/admin/queue`) is a read-only cross-owner view. It
  requires `servers:read_all` plus `ADMIN_ACCESS` and a JWT session. There is no
  admin cancel, retry, or requeue action.

Monitor queue depth, expired requests and worker/Beat health. See
[SERVER-LIFECYCLE.md](../architecture/SERVER-LIFECYCLE.md) for admission and
fencing behavior.

## 11. Recovery operations and upgrades

### 11.1 Upgrading to 2.3.0

2.3.0 adds the `worker_heartbeats` registry, nullable `executor_id` and
`heartbeat_at` columns on launch/backup/restore journal rows, and
`environment_revisions.portable_fingerprint` with active-only uniqueness. The
migration chain must have exactly one Alembic head; branched or mixed heads are
unsupported.

Drain external traffic and stop the old API, Celery worker and Beat before
running the migration. Mixed old/new runtime writers are unsupported: an old
worker does not honor the new heartbeat, claim, mount-guard or cancellation
contract. Do not start launch, backup or restore work against the old schema.

```bash
# Pin the target release first (or set NUKELAB_IMAGE_TAG)
# NUKELAB_VERSION=2.3.0

./nukelabctl stop
./nukelabctl update
./nukelabctl start backend
./nukelabctl db-migrate
./nukelabctl restart
```

`./nukelabctl stop` stops the platform stack; user server containers keep running
unless you also pass `--include-servers`. Run `db-migrate` immediately after the
backend starts: the recovery scanner refuses an incompatible journal schema, and
a background task that cannot run leaves its durable row for the next tick.

`./nukelabctl db-migrate` automatically writes
`backups/pre-migrate-<version>-<current-revision>-<timestamp>.dump` before
`alembic upgrade head`. If the snapshot fails, the migration aborts. If the
migration fails, the command prints the exact restore command. Do not use
`--no-backup` unless you have already taken an equivalent snapshot.

Check the revision graph before deploying:

```bash
./nukelabctl exec backend alembic heads
```

Exactly one head must be returned. Migration preflight also refuses duplicate
owner/server names, conflicting active queue names and unidentified legacy
in-flight queue entries; resolve those with runtime evidence instead of deleting
user servers. Pending legacy requests without a normalized payload are cancelled
with a resubmit reason. Incomplete historic launches become protected uncertain
operations; only matching owner/server/revision/generation evidence permits a
completed journal backfill.

The 2.3.0 portable-fingerprint migration has a downgrade preflight. A downgrade
refuses duplicate `(template_id, fingerprint)` groups, which can exist after a
revoke and re-verification, before any DDL and without deleting or merging rows.
Use the pre-migration snapshot instead of an in-place downgrade.

### 11.2 Rollback

The startup schema guard (`DB_SCHEMA_GUARD=auto`) refuses an old backend image
against a newer database in production and warns in other environments;
`enforce` always refuses and `off` disables the guard. Roll back with a pinned
image and the matching pre-migration snapshot, not by leaving mixed versions
running. Stop Celery workers/Beat and drain requests before the restore so no
writes race the database replacement; maintenance mode can keep user traffic away
while you do this.

```bash
# Pin the previous release first
# NUKELAB_VERSION=<previous-version>

./nukelabctl update
./nukelabctl restore --stamp <previous-revision> \
  backups/pre-migrate-<snapshot-version>-<previous-revision>-<timestamp>.dump
./nukelabctl restart
```

`restore` drops and recreates the database and asks for confirmation unless
`--yes` is supplied. The version in the snapshot filename is the version that
created the snapshot; `--stamp` must use the previous Alembic revision recorded in
that filename. It needs Postgres and a backend container for the Alembic stamp.
Keep the current (newer) backend container running through the restore; if the
stack is stopped, start the newer release first, restore, then restart into the
pinned image. Never start the previous image against the newer schema and expect
the guard to repair it.

### 11.3 Investigating uncertain work

For `recovery_required` volume work or an `uncertain` launch, first establish
that the original executor terminated. Heartbeat age, an HTTP deadline, Celery
inspection and Redis are not termination proof.

1. Open **Administration → Recovery Operations** (`/admin/operations`) and filter
   by kind or recovery state. For an active row, the detail view reruns the
   read-only inspector and shows bounded liveness, runtime and proof diagnostics.
2. Run `./nukelabctl doctor`. Its recovery preflight is read-only and reports
   journal schema, heartbeat configuration, registry verification and credential
   state without pulling images or mutating the stack.
3. Inspect the UUID-based runtime name, managed owner/server labels, actual image
   identity and platform, mount attachments and GPU assignments. A database row
   with no container ID does not prove that no container exists. For volume work,
   inspect the operation-labelled helper and artifact completion/termination.
4. Keep reservations, guards and artifacts until the outcome is proved. Do not
   clear an uncertain journal row, delete operation rows, reuse helper names,
   manually expire reservations on a timer, or blindly retry runtime mutations.
5. Use the reconcile action only when the inspector can support a terminal
   outcome. A 409 response means proof is ambiguous and nothing changed. Record
   the evidence and use a reviewed repair procedure or restore the verified
   pre-migration snapshot with its matching image version.

Reconciliation requires `operations:manage_all` plus `ADMIN_ACCESS`, a JWT
session and a bounded reason. It reruns the same evidence inspection and lets the
fenced finalizer apply only a proof-backed success or failure. There is no force
or override path. Volume completion still requires the recovery service's
artifact and helper-termination checks, which the background reconciler supplies;
the console never activates a destination or marks a backup complete on its own.
Every call is audited.

Applied transitions notify the owner. Attention notices are deduplicated per
operation and terminal state; one completion notice per operation is sent only
after an attention event. A bounded reminder runs daily at 08:00 UTC while work
remains unresolved, with at most one reminder per operation per 24 hours.
Notification failure never changes recovery state or releases reservations.

The operations console requires `operations:read_all` plus `ADMIN_ACCESS` and a
JWT session. The read-only queue console separately requires `servers:read_all`
plus `ADMIN_ACCESS` and a JWT session. Owner queue cancellation remains
pending-only; there is no admin cancel, retry or requeue action.

### 11.4 Recovery monitoring

When `PROMETHEUS_ENABLED=true`, the backend scrape at `/api/metrics` republishes
recovery gauges from durable rows. The reconciler runs in the Celery process, so
it also persists scan freshness in the `system_settings` key
`recovery_scan_state`; the backend scrape loads that bounded state and publishes
it in the API process. The row contains timestamps, duration and counters only.

| Metric | Meaning |
|---|---|
| `nukelab_workers_registered` | Process-lifetime executor rows in the heartbeat registry |
| `nukelab_worker_heartbeats{state}` | Heartbeat rows classified `fresh`, `stale`, or `stopped` |
| `nukelab_worker_heartbeat_age_seconds` | Age of the most recent worker heartbeat |
| `nukelab_worker_last_heartbeat_timestamp_seconds` | Unix timestamp of the most recent worker heartbeat |
| `nukelab_operations_active{kind}` | Active `launch`, `backup`, or `restore` journal rows |
| `nukelab_operations_recovery_required{kind}` | Active rows needing operator recovery |
| `nukelab_operations_stalled{kind}` | Active rows whose operation heartbeat exceeded the stale threshold |
| `nukelab_recovery_scan_last_success_timestamp_seconds` | Last error-free scan pass |
| `nukelab_recovery_scan_duration_seconds` | Duration of the most recent scan |
| `nukelab_recovery_scan_last_report{result}` | `scanned`, `finalized`, `deferred`, or `errors` counters |
| `nukelab_registry_verification_policy{policy}` | `1` for the active `off`, `prefer`, or `require` policy |
| `nukelab_registry_local_only_revisions` | Non-revoked revisions without a portable registry identity |
| `nukelab_registry_templates_without_verified_revision` | Active templates with no non-revoked verified revision |

Labels are fixed to worker state, operation kind, registry policy and scan result.
User, server, operation, image and executor identifiers are never metric labels.

The `nukelab-recovery` alert group covers the operational failures:

| Alert | Condition |
|---|---|
| `NukeLabRecoveryNoFreshWorkers` | Registered executors exist but none are fresh for 2 minutes |
| `NukeLabRecoveryWorkerHeartbeatsStale` | At least one stale heartbeat for 5 minutes |
| `NukeLabRecoveryScanStale` | After a successful scan, none for more than 60 seconds (two default intervals) |
| `NukeLabOperationsRecoveryRequired` | Recovery-required rows remain for 15 minutes |
| `NukeLabOperationsStalled` | An active operation heartbeat is stale for 10 minutes |
| `NukeLabRegistryVerificationGaps` | Local-only revisions under `require`, or unverified active templates under `off` |

Heartbeat and stalled-operation alerts are inspection triggers, not automatic
cleanup. Follow the investigation flow above and do not release protection from
the alert alone.

## 12. Registry verification and environment revisions

Registry verification proves that an approved artifact is the exact platform
artifact expected, independently of mutable tags. Resolution alone never creates
approval.

| Policy | Behavior |
|---|---|
| `off` | No registry I/O; launches use local identities |
| `prefer` | Verify when possible; record a truthful local-only fallback when resolution is unavailable |
| `require` | Fail closed when the approved reference cannot be verified |

A verified revision stores the canonical repository, platform manifest digest,
OS/architecture/variant and index digest. Local proof requires the same canonical
repository and platform digest in the local image's repository digests plus a
matching platform; a tag-pulled multi-architecture index digest is not proof.
`REGISTRY_PULL_POLICY=on_demand` allows pulling exactly
`<repository>@sha256:<platform-digest>` when the approved artifact is absent,
serialized by a PostgreSQL advisory lock on a direct connection and re-proved
after the pull. `preload_only` never pulls during launch or verification and fails
closed when the artifact is missing or platform-mismatched.

Tag movement requires an explicit admin verify. Ordinary launch and recreation
reuse the captured revision and never re-resolve a moved tag into a new approval.
**Administration → Environments** → **Revisions** lists immutable history,
including revoked rows. Verify requires `environment:update` plus `ADMIN_ACCESS`
and a reason; it rejects local image IDs, resolves the current runtime and
toolchain references under `require`, checks the exact local platform digest
(pulling by digest under `on_demand`), captures or reuses the active revision, and
audits the result. Revoke is idempotent, has no un-revoke, and requires explicit
confirmation before removing the last selectable revision. Reads require
`environment:read` plus `ADMIN_ACCESS`.

Portable fingerprints are computed only for registry-verified configurations. A
cross-install portable manifest matches active revisions by that fingerprint
alone; template labels, slugs and origin revision/local IDs are display metadata.
Multiple matching templates return `revision_ambiguous`. Local-only manifests keep
strict local revision matching. Revoked revisions never satisfy either match.

Registry credentials are optional and used only for verification. Set
`REGISTRY_CREDENTIALS_FILE_HOST` to a Docker `config.json`-compatible file; Compose
mounts it read-only into `backend` and `celery-worker` and points
`REGISTRY_CREDENTIALS_FILE` at the container path. The file must be readable by
UID 65532. Replace the host file atomically to rotate credentials; it is re-read
within 60 seconds. Runtime image pulls still use the container engine's own
registry login, and `credsStore`/`credHelpers` are not supported. Private or
loopback registry hosts, including a separate token-service host, must be listed
in `REGISTRY_ALLOWED_HOSTS`.

## 13. Supply-chain checks

**Base-image pinning.** External Dockerfile `FROM` references must be pinned by
digest. The required `Base Image Pinning` job runs
`./nukelabctl security --check-base-images` and is part of the blocking Security
Gate. Local source builds and pull-based deploys share the same pinned images.

**Drift review.** A weekly scheduled `Base Image Digest Review` runs
`scripts/security/check-base-image-drift.sh` against the tracked Dockerfiles. It
resolves each `image:tag` manifest without pulling layers and compares the pinned
digest with both the current index digest and the selected platform manifest
digest. Drift opens or updates one `[supply-chain] Base image digest drift` issue;
a clean review closes it. The workflow never opens a pull request and is not a
pull-request gate; updating a digest remains a reviewed change.

**Release SBOMs and attestations.** Tagged `v*.*.*` releases run the release-only
path. CI generates a deterministic CycloneDX JSON SBOM for each published image
using a pinned Syft image, based on the exact digest-qualified reference. The
generator excludes file catalogers, derives the serial number from the image
digest, removes the run timestamp and sorts serialization so the same image digest
and generator produce the same bytes. It fails on empty, non-CycloneDX, oversized
or component-free output. CI then attests build provenance and the SBOM, and the
Release workflow resolves each published tag to its manifest digest and verifies
both attestations with `gh attestation verify` for backend, frontend,
auth-sidecar, volume-helper and the environment base image. Normal branch CI does
not run the release-only SBOM or attestation steps.

This is build provenance and artifact inventory, not a claim of SLSA compliance.
For an ad-hoc local inventory, `./nukelabctl security --sbom` writes CycloneDX
SBOMs under `backend/reports/security/sbom/`; that path is separate from the
deterministic release artifacts.

## Retaining captured environment artifacts

Environment exports describe approved artifacts and logical data mounts; they do
not contain image bytes, variable values or user-volume data. Local-only
recreation requires the exact images to remain on the original engine and a
matching approved revision on this installation. Pruning those images can make a
recorded launch unavailable for recreation even though its history/export remains
readable.

Registry-verified revisions can use the exact approved platform digest and, under
`on_demand`, pull that digest if it is absent locally. `preload_only` deliberately
refuses that pull. Retain required local-only images and immutable toolchain
caches; inspect overall storage usage before cleanup. Automatic cache garbage
collection is not implemented.

Recreation fails explicitly for unavailable artifacts rather than substituting a
newer tag. Revoking a revision or disabling its approved environment prevents new
recreation while preserving recorded history. An earlier preview is advisory;
current approval, access, quota, credits, capacity and explicit volume selections
are checked again when work is submitted. A manifest does not restore data: use
only supported verified recovery procedures, and never treat an export as a data
backup.
