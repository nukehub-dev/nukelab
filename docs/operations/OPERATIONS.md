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
| `PGBOUNCER_MAX_CLIENT_CONN` | 1000 | Max app connections PgBouncer accepts |
| `PGBOUNCER_DEFAULT_POOL_SIZE` | 20 | Real Postgres connections PgBouncer maintains |

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
