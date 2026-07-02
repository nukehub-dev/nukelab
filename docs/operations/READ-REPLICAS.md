# Read Replica Architecture

> **Status:** Reference / Not yet implemented  
> **Trigger:** `pg_stat_statements` shows read queries (SELECT, COUNT) consuming >70% of total execution time  
> **Effort:** High (~1 day initial setup, ongoing operational overhead)

---

## When to Implement

**Do NOT implement until this query shows reads dominate:**

```sql
SELECT
    CASE WHEN query LIKE 'SELECT%' OR query LIKE 'COUNT%' THEN 'read' ELSE 'write' END AS query_type,
    ROUND(SUM(total_exec_time)::numeric, 2) AS total_ms,
    ROUND(100.0 * SUM(total_exec_time) / (SELECT SUM(total_exec_time) FROM pg_stat_statements), 2) AS pct
FROM pg_stat_statements
GROUP BY query_type;
```

**Threshold:** Implement when `read` is >70% and write latency is spiking.

---

## Architecture

```
+-------------------------------------------------------------+
|                        Application                          |
|  +-------------+  +-------------+  +---------------------+  |
|  |  Web API    |  | Celery      |  |  Reporting / Admin  |  |
|  |  (writes)   |  | Workers     |  |  (reads)            |  |
|  +------+------+  +------+------+  +-----------+---------+  |
|         |                |                     |            |
|         +----------------+---------------------+            |
|                          |                                  |
|              +-----------+-----------+                      |
|              |   SQLAlchemy Router   |                      |
|              |  (read/write split)   |                      |
|              +-------+-------+-------+                      |
+----------------------+-------+------------------------------+
                       |       |
              +--------+       +--------+
              |                         |
       +------v------+          +-------v-------+
       |   Primary   |<---------|    Replica    |
       |  PostgreSQL |  WAL     |   PostgreSQL  |
       |   (writes)  |  stream  |    (reads)    |
       +-------------+          +---------------+
```

---

## Implementation Guide

### 1. Primary Configuration

Add to `compose.yml` postgres command:

```yaml
- -c
- wal_level=replica
- -c
- max_wal_senders=3
- -c
- max_replication_slots=3
- -c
- hot_standby=on
```

Create replication user (run via `./nukelabctl db-shell`):

```sql
CREATE USER replicator WITH REPLICATION ENCRYPTED PASSWORD '${REPLICATOR_PASSWORD:-change-me}';
```

### 2. Replica Setup

```yaml
# compose.replica.yml
services:
  postgres-replica:
    image: postgres:17-alpine
    container_name: nukelab-postgres-replica
    environment:
      POSTGRES_USER: nukelab
      POSTGRES_PASSWORD: ${DATABASE_PASSWORD:-nukelab123}
    command:
      - postgres
      - -c
      - hot_standby=on
      - -c
      - primary_conninfo='host=postgres port=5432 user=replicator password=${REPLICATOR_PASSWORD:-change-me}'
    volumes:
      - postgres-replica-data:/var/lib/postgresql/data
    networks:
      - nukelab-network
    restart: unless-stopped

volumes:
  postgres-replica-data:
    name: nukelab-postgres-replica-data
```

Initialize replica from primary backup:

```bash
# Initialize replica from primary (run inside the replica container)
docker exec -i nukelab-postgres-replica pg_basebackup \
  -h postgres -D /var/lib/postgresql/data \
  -U replicator -Fp -Xs -P -R
```

### 3. SQLAlchemy Read/Write Split

```python
# app/db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Primary for writes
primary_engine = create_async_engine(settings.database_url, ...)

# Replica for reads (different host)
replica_url = settings.database_url.replace("@postgres:", "@postgres-replica:")
replica_engine = create_async_engine(replica_url, ...)

AsyncSessionPrimary = sessionmaker(primary_engine, class_=AsyncSession)
AsyncSessionReplica = sessionmaker(replica_engine, class_=AsyncSession)
```

**Router utility:**

```python
# app/db/routing.py
from contextvars import ContextVar

read_replica_enabled: ContextVar[bool] = ContextVar("read_replica_enabled", default=False)

def use_replica():
    read_replica_enabled.set(True)

def get_session():
    if read_replica_enabled.get():
        return AsyncSessionReplica()
    return AsyncSessionPrimary()
```

**Usage in endpoints:**

```python
@router.get("/servers")
async def list_servers(db: AsyncSession = Depends(get_db_replica)):
    ...

@router.post("/servers")
async def create_server(db: AsyncSession = Depends(get_db)):
    ...
```

### 4. Replication Lag Monitoring

```sql
-- On primary: check replication lag
SELECT
    client_addr,
    state,
    EXTRACT(EPOCH FROM (now() - backend_start)) AS conn_age_seconds,
    sent_lsn,
    replay_lsn,
    pg_size_pretty(pg_wal_lsn_diff(sent_lsn, replay_lsn)) AS lag
FROM pg_stat_replication;
```

**Alert if lag > 5 seconds.**

---

## Operational Notes

### Consistency Model

PostgreSQL streaming replication is **asynchronous** by default. This means:

- A write on primary may not be immediately visible on the replica
- **Lag is typically <1 second** on LAN
- If your app requires read-after-write consistency, route those specific reads to the primary

### Failover

If primary fails:

1. Promote replica: `pg_ctl promote`
2. Update `DATABASE_HOST`/`DATABASE_PORT` (or set `DATABASE_URL`) to point to replica
3. Rebuild new primary from promoted replica

**Better:** Use Patroni or repmgr for automated failover.

### When NOT to Use Read Replicas

| Scenario | Better Solution |
|---|---|
| Single slow query | Add index or rewrite query |
| Connection exhaustion | PgBouncer |
| Large reporting queries | Materialized views or daily rollups |
| Cache misses | Redis caching |

---

## Cost Estimate

| Component | CPU | Memory | Storage | Monthly (cloud) |
|---|---|---|---|---|
| Primary | 2 cores | 4 GB | 100 GB | ~$50 |
| Replica | 2 cores | 4 GB | 100 GB | ~$50 |
| **Total** | | | | **~$100/month** |

Implement only when query profiling proves reads are the bottleneck.
