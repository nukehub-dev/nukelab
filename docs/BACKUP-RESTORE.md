# Backup & Restore Guide

> **Scope:** PostgreSQL database backup, restore, and disaster recovery for NukeLab  
> **Tables:** Includes partitioned time-series tables (`activity_logs`, `server_metrics`, `request_metrics`)

---

## Quick Reference

```bash
# Full backup (schema + data + partitions)
./manage.sh backup

# Restore from backup
./manage.sh restore backups/nukelab_backup_YYYYMMDD_HHMMSS.sql

# Verify after restore
./manage.sh exec backend python scripts/db_profiler.py table-sizes
./manage.sh exec backend python scripts/db_profiler.py partitions --table activity_logs
```

---

## 1. Backup Strategies

### 1.1 Full Logical Backup (Recommended for < 100 GB)

Uses `pg_dump` — includes schema, partitions, extensions, and data.

```bash
# Full backup (postgres container must be running)
# Using manage.sh:
./manage.sh backup

# Or directly with your container engine:
docker exec -i nukelab-postgres pg_dump \
  -U nukelab -d nukelab --clean --if-exists --create \
  > nukelab-backup-$(date +%Y%m%d).sql
```

**What `--clean --if-exists` does:** Adds `DROP IF EXISTS` before `CREATE`, so restore is idempotent.

**Verification:**
```bash
# Check file size
ls -lh nukelab-backup-*.sql

# Count tables in backup
grep -c "^CREATE TABLE" nukelab-backup-*.sql
```

### 1.2 Partial Backup (Recent Partitions Only)

For large datasets, back up only recent partitions + full schema.

```bash
BACKUP_FILE="nukelab-recent-$(date +%Y%m%d).sql"

# 1. Schema only (parent tables, extensions, indexes)
docker exec -i nukelab-postgres pg_dump \
  -U nukelab -d nukelab --schema-only > "$BACKUP_FILE"

# 2. Append recent partitions (last 3 months)
THIS_MONTH=$(date +%Y%m)
for m in 0 1 2; do
  ym=$(date -d "+$m month" +%Y%m)
  for table in activity_logs server_metrics request_metrics; do
    part="${table}_y${ym:0:4}m${ym:4:2}"
    echo "-- Backing up partition: $part" >> "$BACKUP_FILE"
    docker exec -i nukelab-postgres pg_dump \
      -U nukelab -d nukelab \
      --data-only --table="$part" >> "$BACKUP_FILE"
  done
done

# 3. Append non-partitioned tables
for tbl in users servers volumes shared_workspaces notifications; do
  docker exec -i nukelab-postgres pg_dump \
    -U nukelab -d nukelab \
    --data-only --table="$tbl" >> "$BACKUP_FILE"
done
```

### 1.3 Continuous Archive (WAL Archiving)

For point-in-time recovery (PITR), enable WAL archiving in `compose.yml`:

```yaml
# In compose.yml, postgres service command:
- -c
- archive_mode=on
- -c
- archive_command='cp %p /backups/wal/%f'
- -c
- wal_level=replica
```

**Storage requirement:** WAL files are ~16 MB each. A busy system generates ~1 GB/hour.

---

## 2. Restore Procedures

### 2.1 Full Restore (Fresh Environment)

```bash
# 1. Stop the backend to prevent writes during restore
./manage.sh stop

# 2. Drop and recreate the database
./manage.sh exec postgres psql -U nukelab -c "DROP DATABASE IF EXISTS nukelab;"
./manage.sh exec postgres psql -U nukelab -c "CREATE DATABASE nukelab;"

# 3. Restore from backup
docker exec -i nukelab-postgres psql -U nukelab -d nukelab < nukelab-backup-YYYYMMDD.sql

# 4. Stamp alembic version so migrations don't try to re-run
./manage.sh exec backend python -m alembic stamp 281a4c5d5529

# 5. Restart services
./manage.sh start

# 6. Verify
./manage.sh exec backend python scripts/db_profiler.py table-sizes
./manage.sh exec backend python scripts/db_profiler.py partitions --table activity_logs
# Verify partition health via admin monitoring endpoint
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8080/api/admin/health/monitoring | jq '.system.services.partitions'
```

### 2.2 Restore to a New Host (Migration)

```bash
# 1. Start fresh postgres container
./manage.sh start

# 2. Wait for postgres to be ready
until ./manage.sh exec postgres pg_isready -U nukelab; do sleep 1; done

# 3. Create database and user
./manage.sh exec postgres psql -U postgres -c "CREATE DATABASE nukelab;"
./manage.sh exec postgres psql -U postgres -d nukelab -c "CREATE USER nukelab WITH PASSWORD 'nukelab123';"
./manage.sh exec postgres psql -U postgres -d nukelab -c "GRANT ALL PRIVILEGES ON DATABASE nukelab TO nukelab;"

# 4. Restore
docker exec -i nukelab-postgres psql -U nukelab -d nukelab < nukelab-backup-YYYYMMDD.sql

# 5. Ensure partitions exist for current month
./manage.sh exec backend python scripts/db_profiler.py ensure-partitions --months-ahead 3

# 6. Stamp alembic
./manage.sh exec backend python -m alembic stamp 281a4c5d5529
```

### 2.3 Partial Restore (Single Table Recovery)

```bash
# Extract a single table from the backup
sed -n '/^CREATE TABLE activity_logs/,/^CREATE TABLE /p' nukelab-backup.sql > activity_logs_schema.sql

# Restore just that table
docker exec -i nukelab-postgres psql -U nukelab -d nukelab < activity_logs_schema.sql
```

---

## 3. Partition-Specific Considerations

### 3.1 Partition Restore Order

PostgreSQL requires the **parent table** to exist before any child partitions can be restored.

`pg_dump --clean --if-exists` handles this automatically — it creates parent tables first, then partitions. But if you're doing manual restores, follow this order:

```sql
-- 1. Parent table (with PARTITION BY)
CREATE TABLE activity_logs (
    id UUID NOT NULL,
    actor_id UUID,
    ...
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- 2. Extensions
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 3. Indexes (inherited by partitions)
CREATE INDEX ix_activity_logs_created_at ON activity_logs (created_at);

-- 4. Partitions
CREATE TABLE activity_logs_y2026m06 PARTITION OF activity_logs
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

-- 5. Data
INSERT INTO activity_logs (...) VALUES (...);
```

### 3.2 Detached Partitions

If you previously ran `db_profiler.py drop-old` and detached partitions, those partition tables are **not** in `pg_dump` output unless you explicitly back them up.

```bash
# List detached partitions (orphaned tables)
# (Piping stdin to a container requires direct docker/podman exec)
docker exec -i nukelab-postgres psql -U nukelab -d nukelab -c "
SELECT relname FROM pg_class WHERE relkind = 'r'
AND relname LIKE 'activity_logs_y%';
"

# Back up detached partitions separately
for part in activity_logs_y2025m01 activity_logs_y2025m02; do
  docker exec -i nukelab-postgres pg_dump \
    -U nukelab -d nukelab --data-only --table="$part" >> detached_partitions.sql
done
```

---

## 4. Automated Backups

### 4.1 Celery Beat Scheduled Task

Add to `app/worker.py` `beat_schedule`:

```python
'daily-backup': {
    'task': 'app.tasks.run_database_backup',
    'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
},
```

And create the task in `app/tasks.py`:

```python
@celery_app.task(bind=True)
def run_database_backup(self):
    import subprocess
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"/backups/nukelab-backup-{timestamp}.sql"
    result = subprocess.run(
        ["pg_dump", "-U", "nukelab", "-d", "nukelab", "--clean", "--if-exists"],
        capture_output=True, text=True,
    )
    with open(filename, "w") as f:
        f.write(result.stdout)
    return f"Backup saved to {filename} ({len(result.stdout)} bytes)"
```

### 4.2 Retention

```bash
# Keep last 30 days of backups
find /backups -name "nukelab-backup-*.sql" -mtime +30 -delete
```

---

## 5. Verification Checklist

After any restore, verify:

- [ ] `./manage.sh exec backend python scripts/db_profiler.py table-sizes` shows expected tables
- [ ] `./manage.sh exec backend python scripts/db_profiler.py partitions --table activity_logs` shows partitions
- [ ] Admin monitoring endpoint shows healthy partitions: `curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:8080/api/admin/health/monitoring | jq '.system.services.partitions.status'`
- [ ] `./manage.sh exec backend alembic current` shows `281a4c5d5529 (head)`
- [ ] Application starts without errors
- [ ] Login works (verifies users table)
- [ ] Server list loads (verifies servers + cache)

---

## 6. Disaster Recovery Scenarios

| Scenario | Recovery Time | Procedure |
|---|---|---|
| Accidental `DELETE` without `WHERE` | Minutes | Restore from last night's backup |
| Corrupted partition | Minutes | Drop partition, restore from backup |
| Full database loss | 10–30 min | Full restore from backup + restart services |
| Host failure | 30–60 min | Restore backup to new host, update DNS |
| Ransomware / encryption | 30–60 min | Restore from off-site backup |

---

## 7. Storage Requirements

| Data Size | Backup File Size | Storage (30 days retention) |
|---|---|---|
| 1 GB | ~200 MB | ~6 GB |
| 10 GB | ~2 GB | ~60 GB |
| 100 GB | ~20 GB | ~600 GB |
| 1 TB | ~200 GB | ~6 TB |

**Tip:** Use `pg_dump --format=custom` + `pg_restore` for large databases. Custom format is compressed and supports parallel restore.

```bash
# Custom format (compressed)
docker exec -i nukelab-postgres pg_dump -U nukelab -d nukelab -Fc > backup.dump

# Parallel restore (4 jobs)
docker exec -i nukelab-postgres pg_restore -U nukelab -d nukelab -j 4 < backup.dump
```
